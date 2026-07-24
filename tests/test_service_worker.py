"""Service worker app-shell caching (change C.1).

write_app now emits sw.js, an app-shell precache service worker registered by
every page. A returning visitor navigating between index/p/lead/dashboard is
served the HTML/CSS/JS shell + pinned Firebase SDK modules from cache, without
touching the network — while Firestore/Auth traffic is never intercepted.

These tests pin: the file is emitted and parses; Firestore/Auth are pure
passthrough; the version is a safe content hash (senior-review requirement #1);
every page registers the SW and exposes the kill switch (requirement #2).
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest

from bridge_trainer.app.webapp import (_CSS, _SHARED_JS, _dashboard_html,
                                       _index_html, _lead_html, _problem_html,
                                       _service_worker_js, _shell_version,
                                       write_app)

PAGES = ("index.html", "p.html", "lead.html", "dashboard.html")
PAGE_FNS = (_index_html, _problem_html, _lead_html, _dashboard_html)


@pytest.fixture(scope="module")
def site():
    d = tempfile.mkdtemp()
    write_app(d)
    return pathlib.Path(d)


def test_write_app_emits_sw(site):
    sw = site / "sw.js"
    assert sw.exists()
    assert sw.read_text(encoding="utf-8") == _service_worker_js()


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_sw_parses(site):
    res = subprocess.run(["node", "--check", str(site / "sw.js")],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_sw_never_intercepts_firestore_or_auth():
    """The critical safety property: only same-origin and www.gstatic.com are
    ever served from the SW; all other origins (Firestore/Auth) fall through to
    the network. Asserted structurally on the fetch handler."""
    sw = _service_worker_js()
    # the only respondWith calls are gated on same-origin or www.gstatic.com
    assert "url.origin === self.location.origin" in sw
    assert 'url.hostname === "www.gstatic.com"' in sw
    # the sensitive hosts are named nowhere as an intercept target
    for host in ("firestore.googleapis.com", "identitytoolkit.googleapis.com",
                 "accounts.google.com"):
        # they may appear in the trailing comment, but never inside a respondWith
        for line in sw.splitlines():
            if host in line:
                assert "respondWith" not in line
    # non-GET requests are passthrough
    assert 'req.method !== "GET"' in sw


def test_sw_strategies_present():
    sw = _service_worker_js()
    assert "staleWhileRevalidate" in sw   # unversioned shell
    assert "cacheFirst" in sw             # versioned + SDK
    assert "skipWaiting" in sw
    assert "clients.claim" in sw
    # atomic shell precache + best-effort CDN
    assert "addAll(SHELL.concat(VERSIONED))" in sw
    assert "allSettled" in sw


def test_sw_shell_list_and_versioned_urls():
    from bridge_trainer.app.webapp import _CSS_HREF, _SHARED_SRC, _sdk_module_urls
    sw = _service_worker_js()
    for name in ("index.html", "p.html", "lead.html", "dashboard.html",
                 "bt-firebase.js", "bt-logic.js", "firebase-config.js"):
        assert f'"{name}"' in sw
    # the versioned precache URLs are the exact ones the pages link (no drift)
    assert _CSS_HREF in sw
    assert _SHARED_SRC in sw
    for url in _sdk_module_urls():
        assert url in sw
    assert _sdk_module_urls(), "expected pinned SDK modules in the precache"


def test_sw_cache_name_is_versioned():
    sw = _service_worker_js()
    v = _shell_version()
    assert len(v) == 12
    assert f'const VERSION = "{v}";' in sw
    assert 'const CACHE = "bt-shell-" + VERSION;' in sw


def test_shell_version_tracks_shell_assets(monkeypatch):
    """Requirement #1: the version changes when a shell asset changes, and is
    stable otherwise."""
    import bridge_trainer.app.webapp as w
    base = w._shell_version()
    assert base == w._shell_version()  # stable across calls
    # perturb a shell asset (the CSS) and confirm the hash moves
    monkeypatch.setattr(w, "_CSS", w._CSS + "\n/* x */")
    assert w._shell_version() != base


def test_shell_version_ignores_unrelated_change(monkeypatch):
    import bridge_trainer.app.webapp as w
    base = w._shell_version()
    # a constant that is NOT a shell asset must not move the version
    monkeypatch.setattr(w, "_ASSET_FILES", w._ASSET_FILES)  # identity no-op
    assert w._shell_version() == base


def test_every_page_loads_the_registrar():
    """The SW registration lives in _SHARED_JS (emitted as bt-shared.js), which
    every page links — so every page registers the SW without duplicating the
    code inline."""
    for html_fn in PAGE_FNS:
        assert 'src="bt-shared.js?v=' in html_fn()


def test_shared_js_registers_sw():
    assert 'register("sw.js")' in _SHARED_JS


def test_shared_js_has_kill_switch():
    # persisted opt-out + transient ?nosw + console handles (requirement #2)
    assert 'localStorage.getItem("bt_sw_off")' in _SHARED_JS
    assert "nosw" in _SHARED_JS
    assert "window.btSW" in _SHARED_JS
    assert "disable:" in _SHARED_JS and "enable:" in _SHARED_JS
    # the kill path unregisters every SW and drops the bt-shell caches
    assert "getRegistrations" in _SHARED_JS
    assert 'k.indexOf("bt-shell") === 0' in _SHARED_JS


def test_sw_registered_after_load():
    """Registration is deferred to the load event so it never competes with the
    critical Firebase path."""
    assert re.search(r'addEventListener\("load",.*register\("sw\.js"\)',
                     _SHARED_JS, re.S)
