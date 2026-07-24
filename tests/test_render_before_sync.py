"""Render before the attempts sync (task T4 / PERF-F-2, PERF-D-3).

start() used to `await preloadAttempts(uid)` before handing control to the
page, so the first problem waited on a full auth->sync->read round trip. Now it
loads the local cache synchronously, hands off immediately, and runs the
authoritative sync in the background (requestIdleCallback), announcing
completion via `bt-attempts-synced` so pages can refresh. These tests pin that
ordering in the source and confirm every page listens for the event.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from importlib import resources

import pytest

from bridge_trainer.app.webapp import (_dashboard_html, _index_html,
                                       _lead_html, _problem_html)

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available")


def _src() -> str:
    return (resources.files("bridge_trainer") / "web"
            / "bt-firebase.js").read_text(encoding="utf-8")


def test_cache_load_and_sync_are_split():
    src = _src()
    assert "function loadCacheState(" in src        # synchronous cache load
    assert "async function syncAttempts(" in src     # background network sync
    # the old blocking entry point is gone
    assert "preloadAttempts" not in src
    # loadCacheState must not await (it has to be synchronous)
    body = src[src.index("function loadCacheState("):
               src.index("async function syncAttempts(")]
    assert "await" not in body


def test_start_hands_off_before_the_background_sync():
    src = _src()
    start = src[src.index("start(ready)"):src.index("window.BT = BT;")]
    # render immediately from cache, then hand off, then schedule the sync
    i_cache = start.index("loadCacheState(")
    i_ready = start.index("ready(u)")
    i_sync = start.index("syncAttempts(")
    assert i_cache < i_ready < i_sync
    # the sync is NOT awaited before handoff, and is deferred to idle time
    assert "await syncAttempts" not in start
    assert "requestIdleCallback" in start
    # completion is announced so pages can refresh
    assert 'new Event("bt-attempts-synced")' in start


@pytest.mark.parametrize("html_fn", [_index_html, _problem_html, _lead_html,
                                     _dashboard_html])
def test_every_page_listens_for_sync(html_fn):
    assert 'addEventListener("bt-attempts-synced"' in html_fn()


@needs_node
def test_bt_firebase_still_valid_module():
    src = _src()
    res = subprocess.run(["node", "--check", "--input-type=module"],
                         input=src, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
