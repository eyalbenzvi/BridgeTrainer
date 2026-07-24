"""Load-error handling on problem/lead/home pages (task T16 / UX-I-1).

A failed getProblem/fetchIndex used to leave the user on an endless skeleton
(problem/lead pages) or a misleading "pool still building" message (home) with
no retry. Now every load path catches, renders loadErrorHtml (offline-aware),
and wires a retry button back to init(). These tests exercise the pure
loadErrorHtml under node and assert the wiring is present and the generated
scripts still parse.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile

import pytest

from bridge_trainer.app.webapp import (_index_html, _lead_html, _problem_html,
                                       _SHARED_JS)
from tests.test_home_early_click import _extract_function

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available")


def _node_eval(src: str):
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        os.write(fd, src.encode("utf-8"))
        os.close(fd)
        res = subprocess.run(["node", path], capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
        return json.loads(res.stdout.strip().splitlines()[-1])
    finally:
        os.unlink(path)


@needs_node
def test_load_error_html_is_offline_aware():
    fn = _extract_function(_SHARED_JS, "loadErrorHtml")
    online, offline = _node_eval(
        fn
        + """
        // module-scoped `var` shadows node's built-in read-only navigator
        var navigator = { onLine: true };
        const on = loadErrorHtml('retry-load');
        navigator = { onLine: false };
        const off = loadErrorHtml('retry-load');
        console.log(JSON.stringify([on, off]));
        """
    )
    assert "הטעינה נכשלה" in online and "אין חיבור לרשת" not in online
    assert "אין חיבור לרשת" in offline
    # both offer a retry button with the caller's id and a way home,
    # and announce themselves to assistive tech
    for html in (online, offline):
        assert 'id="retry-load"' in html
        assert 'href="index.html"' in html
        assert 'role="alert"' in html


@pytest.mark.parametrize("html_fn", [_problem_html, _lead_html])
def test_problem_pages_catch_getProblem_and_wire_retry(html_fn):
    js = html_fn()
    init = _extract_function(js, "init")
    assert "try {" in init and "getProblem(id)" in init
    assert "loadErrorHtml(" in init
    assert '"#retry-load"' in init and "init()" in init


@pytest.mark.parametrize("html_fn", [_problem_html, _lead_html])
def test_next_handler_shows_error_panel_not_silent_redirect(html_fn):
    """A failed fetchIndex on "next" must surface the retry panel, not bounce
    the user home without explanation."""
    js = html_fn()
    # the old silent fallback is gone
    assert 'location.href = "index.html"; return; }' not in js
    assert 'catch (e) { location.href = "index.html"' not in js


def test_home_catch_uses_load_error_and_retry():
    init = _extract_function(_index_html(), "init")
    assert "loadErrorHtml(" in init
    assert '"#retry-load"' in init and "init()" in init
    # the old misleading always-on "still building" copy is gone from the catch
    assert "המאגר עדיין נבנה" not in init


@needs_node
@pytest.mark.parametrize("html_fn", [_index_html, _problem_html, _lead_html])
def test_generated_inline_script_parses(html_fn):
    html = html_fn()
    start = html.index("<script>") + len("<script>")
    end = html.index("</script>", start)
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        os.write(fd, html[start:end].encode("utf-8"))
        os.close(fd)
        res = subprocess.run(["node", "--check", path],
                             capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
    finally:
        os.unlink(path)
