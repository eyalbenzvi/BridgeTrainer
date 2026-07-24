"""External asset emission (task T2 / ARCH-1, PERF-F-4).

write_app now emits the shared CSS/JS as app.css / bt-shared.js instead of
inlining ~73 KB into every page, so the browser caches them once and each
page's HTML shrinks dramatically. The Python constants stay the source of
truth; these tests pin that the emitted files equal the constants, every page
links them (and no longer inlines them), and the bundle parses.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import tempfile

import pytest

from bridge_trainer.app.webapp import _CSS, _SHARED_JS, write_app

PAGES = ("index.html", "p.html", "lead.html", "dashboard.html")


@pytest.fixture(scope="module")
def site():
    d = tempfile.mkdtemp()
    write_app(d)
    return pathlib.Path(d)


def test_shared_assets_are_emitted_and_equal_the_constants(site):
    assert (site / "app.css").read_text(encoding="utf-8") == _CSS
    assert (site / "bt-shared.js").read_text(encoding="utf-8") == _SHARED_JS


@pytest.mark.parametrize("page", PAGES)
def test_pages_link_and_do_not_inline_shared_assets(site, page):
    html = (site / page).read_text(encoding="utf-8")
    assert 'href="app.css"' in html          # links the stylesheet
    assert 'src="bt-shared.js"' in html       # links the shared script
    # and no longer inlines the big blobs
    assert _CSS not in html
    assert _SHARED_JS not in html


@pytest.mark.parametrize("page", PAGES)
def test_pages_are_small(site, page):
    kb = len((site / page).read_bytes()) / 1024
    assert kb < 40, f"{page} is {kb:.0f} KB — shared assets may have leaked back"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_shared_bundle_parses(site):
    res = subprocess.run(["node", "--check", str(site / "bt-shared.js")],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
