"""BUG-9 (magic-number constants), BUG-10 (dead code + duplicate CSS), and
BUG-8 (dead guest mechanism)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from bridge_trainer.app.webapp import (_CSS, _DASHBOARD_JS, _SCORE_JS,
                                       _SHARED_JS, _index_html, _lead_html)
from test_scoring_scale import needs_node, run_js

_FB = (Path(__file__).resolve().parent.parent / "bridge_trainer" / "web"
       / "bt-firebase.js").read_text(encoding="utf-8")


# ---- BUG-9: score thresholds / session size come from named constants -------
def test_score_constants_defined_once():
    for c in ("REVIEW_MIN = 85", "NEAR_MIN = 65", "ERROR_MIN = 40",
              "SCORE_MAX_NONBEST = 94", "SESSION_SIZE = 10"):
        assert c in _SCORE_JS, c


@needs_node
def test_btBandOf_uses_the_constant_thresholds():
    got = run_js(["btBandOf(100)", "btBandOf(85)", "btBandOf(84)",
                  "btBandOf(65)", "btBandOf(64)", "btBandOf(40)",
                  "btBandOf(1)", "btBandOf(0)"])
    assert got == ["best", "near", "minor", "minor", "error",
                   "error", "blunder", "dead"]


def test_no_inline_threshold_literals_in_pages():
    pages = _index_html() + _lead_html() + _DASHBOARD_JS
    assert "sp.score >= 65" not in pages       # -> NEAR_MIN
    assert "sp.score >= NEAR_MIN" in pages
    # the non-best clamp ceiling is the named constant, not a bare 94
    assert ", 1, 94)" not in _SCORE_JS
    assert "SCORE_MAX_NONBEST" in _SCORE_JS
    # session size + review threshold are derived in the dashboard/home text
    assert "size: SESSION_SIZE" in _index_html()
    assert "תרגל ${SESSION_SIZE} כאלה" in _DASHBOARD_JS


def test_reset_batch_limit_named():
    assert "RESET_BATCH_LIMIT = 400" in _FB
    assert "n >= RESET_BATCH_LIMIT" in _FB
    assert "n >= 400" not in _FB


# ---- BUG-10: dead code + duplicated CSS removed -----------------------------
def test_dead_code_removed():
    assert "saveStore" not in _SHARED_JS    # no-op with no callers
    assert "it.correct" not in _index_html()  # field bumpSession never writes


def test_headline_font_size_defined_once():
    # was declared 3x (18/22/24px); now a single 24px rule
    sizes = re.findall(r"\.headline\s*\{[^}]*font-size:\s*(\d+)px", _CSS)
    assert sizes == ["24"], sizes


# ---- BUG-8: dead guest mechanism gone ---------------------------------------
def test_guest_mechanism_removed():
    assert "isGuest" not in _FB              # removed from the BT API
    assert "isGuest" not in _SHARED_JS       # refreshAcct no longer calls it
    assert "window.BT.user()" in _SHARED_JS  # refreshAcct keys off the user now
    # the standalone "אורח" label (HE.guest) is gone; guestNote copy stays
    assert "guest:" not in _SHARED_JS
    assert "guestNote:" in _SHARED_JS
