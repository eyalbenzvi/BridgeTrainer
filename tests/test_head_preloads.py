"""Firebase critical-path preload hints (task T3 / PERF-F-1).

Every generated page loads the Firebase SDK as ES modules from gstatic; without
hints the browser discovers them only after fetching+parsing bt-firebase.js
(HTML -> module -> CDN, serial). These tests assert each page carries the
preconnect + modulepreload hints, and — crucially — that the modulepreloaded
SDK URLs are exactly the ones bt-firebase.js imports (so the hints can't drift
from reality).
"""
from __future__ import annotations

import re
from importlib import resources

import pytest

from bridge_trainer.app.webapp import (_dashboard_html, _index_html,
                                       _lead_html, _problem_html, _sdk_module_urls)

PAGES = {
    "index.html": _index_html,
    "p.html": _problem_html,
    "lead.html": _lead_html,
    "dashboard.html": _dashboard_html,
}


def _imports_in_bt_firebase() -> set[str]:
    src = (resources.files("bridge_trainer") / "web"
           / "bt-firebase.js").read_text(encoding="utf-8")
    return set(re.findall(r"https://www\.gstatic\.com/firebasejs/\S+?\.js", src))


def test_sdk_urls_match_bt_firebase_imports():
    """The drift guard: the preload source of truth == the real imports."""
    assert set(_sdk_module_urls()) == _imports_in_bt_firebase()
    assert _sdk_module_urls(), "expected at least one gstatic SDK module URL"


@pytest.mark.parametrize("name", list(PAGES))
def test_every_page_has_preconnect(name):
    html = PAGES[name]()
    assert '<link rel="preconnect" href="https://www.gstatic.com"' in html
    assert ('<link rel="preconnect" href="https://firestore.googleapis.com"'
            in html)


@pytest.mark.parametrize("name", list(PAGES))
def test_every_page_modulepreloads_each_sdk_module(name):
    html = PAGES[name]()
    for url in _sdk_module_urls():
        assert f'<link rel="modulepreload" href="{url}" crossorigin>' in html, \
            f"{name} missing modulepreload for {url}"


@pytest.mark.parametrize("name", list(PAGES))
def test_preloads_precede_the_module_script(name):
    """Hints must sit before the module that triggers the fetch."""
    html = PAGES[name]()
    assert (html.index('rel="modulepreload"')
            < html.index('src="bt-firebase.js"'))
