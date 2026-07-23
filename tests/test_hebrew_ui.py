"""Localization guardrail: the web app's user-visible chrome is Hebrew.

Renders the four generated pages, strips code (``<script>``/``<style>``) and
markup, and asserts the remaining visible text carries no English word
outside a small allowlist of universal bridge/scoring jargon. This locks the
Hebrew makeover so a future edit can't silently reintroduce English copy.

Scope note: dynamic strings built inside ``<script>`` are covered by the
specific copy assertions in ``test_lead_modes.py`` /
``test_webapp_classification.py``; this test guards the static markup.
"""
from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import tempfile

import pytest

from bridge_trainer.app.webapp import (_dashboard_html, _index_html,
                                        _lead_html, _problem_html)

# Universal terms that stay Latin by design (see the makeover plan §7):
# scoring jargon, the technical DD term, contract denomination, seat letters,
# doubling markers. Card ranks are single letters and filtered by length.
ALLOWED = {
    "IMP", "MP", "NT", "double-dummy", "single-dummy", "Google",
    "N", "E", "S", "W", "X", "XX",
}


def _visible_text(page: str) -> str:
    page = re.sub(r"<script[^>]*>.*?</script>", " ", page, flags=re.S)
    page = re.sub(r"<style[^>]*>.*?</style>", " ", page, flags=re.S)
    page = re.sub(r"<[^>]+>", " ", page)
    return html.unescape(page)


def _english_words(page: str) -> set[str]:
    text = _visible_text(page)
    found = set(re.findall(r"[A-Za-z][A-Za-z-]*", text))
    return {w for w in found if w not in ALLOWED}


def test_no_english_in_visible_chrome():
    pages = {
        "index": _index_html(), "problem": _problem_html(),
        "lead": _lead_html(), "dashboard": _dashboard_html(),
    }
    for name, page in pages.items():
        leaked = _english_words(page)
        assert not leaked, f"{name}: unexpected English words {sorted(leaked)}"


def test_pages_declare_hebrew_rtl():
    for page in (_index_html(), _problem_html(), _lead_html(),
                 _dashboard_html()):
        assert 'lang="he"' in page
        assert 'dir="rtl"' in page


def test_brand_is_hebrew():
    assert "מאמן הברידג'" in _index_html()


def test_call_labels_are_hebrew():
    # פאס / כפל / כפל כפליים, not Pass / Dbl / Rdbl
    js = _index_html()
    assert '"פאס"' in js and '"כפל"' in js and '"כפל כפליים"' in js
    assert "Pass" not in _visible_text(_index_html())


def test_glossary_uses_lakichot_not_trikim():
    # standard Israeli terminology: לקיחות, never טריקים
    for page in (_lead_html(), _dashboard_html()):
        assert "טריק" not in _visible_text(page)


def test_convention_name_glossary_present():
    js = _index_html()
    for name in ("סטיימן", "העברה (טרנספר)", "בלאקווד RKC", "כפל מוציא"):
        assert name in js


# --------------------------------------------------------------------------
# smoke: the inline page scripts must parse as valid JS. Guards against a
# broken f-string brace ({{ }}) or template literal — the likeliest way an
# edit to these string-built pages silently ships a page that errors on load.
# Skips when node is unavailable so the suite still runs without it.
# --------------------------------------------------------------------------

@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
@pytest.mark.parametrize("render", [
    _index_html, _problem_html, _lead_html, _dashboard_html])
def test_inline_scripts_parse(render):
    scripts = re.findall(r"<script>(.*?)</script>", render(), flags=re.S)
    assert scripts, "page has no inline script"
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        os.write(fd, "\n".join(scripts).encode("utf-8"))
        os.close(fd)
        res = subprocess.run(["node", "--check", path],
                             capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
    finally:
        os.unlink(path)
