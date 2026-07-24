"""SEC-A-2: free-text document fields are HTML-escaped before innerHTML.

esc() lives in _SCORE_JS (DOM-free) and is exercised under node. The render
paths are checked at the string level: the genuinely free-text, externally
sourced fields — P.source.teams/event/board (parsed from external LIN files),
the engine note, and P.meanings[].seat/meaning — must be wrapped in esc();
helpers that intentionally emit markup (terse/callHtml) must NOT be.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile

import pytest

from bridge_trainer.app.webapp import _SCORE_JS, _problem_html

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available")


def run_score(exprs: list[str]):
    script = (_SCORE_JS +
              "\nconsole.log(JSON.stringify([" + ",".join(exprs) + "]));\n")
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        os.write(fd, script.encode("utf-8"))
        os.close(fd)
        res = subprocess.run(["node", path], capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
        return json.loads(res.stdout.strip().splitlines()[-1])
    finally:
        os.unlink(path)


@needs_node
def test_esc_neutralizes_injection():
    img, quotes, amp, empty, none = run_score([
        "esc('<img src=x onerror=alert(1)>')",
        "esc(`\"'`)",
        "esc('a & b')",
        "esc('')",
        "esc(null)",
    ])
    # the tag can no longer be parsed as HTML
    assert img == "&lt;img src=x onerror=alert(1)&gt;"
    assert "<" not in img and ">" not in img
    assert quotes == "&quot;&#39;"
    assert amp == "a &amp; b"
    assert empty == ""
    assert none == ""          # null/undefined -> "" (no "null" text)


def test_free_text_fields_are_escaped():
    html = _problem_html()
    # external source line (from LIN vugraph files)
    assert "esc(s.teams)" in html
    assert "esc(s.event)" in html
    assert "esc(s.board)" in html
    # engine note prose
    assert "esc(note[0].toUpperCase() + note.slice(1))" in html
    # auction meanings
    assert "esc(m.seat)" in html and "esc(m.meaning)" in html
    # raw, unescaped interpolations of these fields are gone
    assert "${s.teams}" not in html
    assert "${m.meaning}" not in html


def test_intentional_markup_helpers_not_escaped():
    """C2 guard: terse() output (row.shows / NOTES) and glyph helpers emit
    markup by design and must NOT be wrapped in esc(), or their suit glyphs
    would show as literal &lt;span&gt;."""
    html = _problem_html()
    assert "esc(NOTES[" not in html
    assert "esc(row.shows)" not in html
    assert "esc(callHtml" not in html
