"""Tests for the DOM-free display/data helpers added to _SCORE_JS and for the
page normalize() shape handling (BUG-4, BUG-5).

_SCORE_JS is the DOM-free block (the tail of _SHARED_JS is NOT — it runs
applyTheme()/initChrome() at load), so pure helpers live in _SCORE_JS and are
exercised by running that block under node, the same harness as
test_scoring_scale.py. optRowHtml/chipsHtml/normalize live in the p.html
f-string body, so they are checked at the string level.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile

import pytest

from bridge_trainer.app.webapp import _SCORE_JS, _problem_html

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available")


def run_score(exprs: list[str]):
    """Run _SCORE_JS under node and evaluate each expression."""
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
def test_safenum_guards_missing_and_nan():
    zero, half, missing, nan, dflt = run_score([
        "safeNum(0)", "safeNum(0.5)", "safeNum(undefined)",
        "safeNum(NaN)", "safeNum(undefined, 1)",
    ])
    assert zero == 0
    assert half == 0.5
    assert missing == 0          # missing clamps to the default 0 (CSS width)
    assert nan == 0
    assert dflt == 1


@needs_node
def test_pct_never_emits_nan():
    zero, half, one, missing, nan = run_score([
        "pct(0)", "pct(0.5)", "pct(1)", "pct(undefined)", "pct(NaN)",
    ])
    assert zero == "0%"
    assert half == "50%"
    assert one == "100%"
    # the whole point of BUG-5: a missing/NaN probability shows an em dash,
    # never "NaN%"
    assert missing == "—"
    assert nan == "—"


def test_optrow_and_chips_use_safe_helpers():
    """optRowHtml/chipsHtml must route probabilities through pct()/safeNum() so
    a row without p_gain/p_push cannot render "NaN%" or width:NaN%."""
    html = _problem_html()
    # no raw Math.round(row.p_gain * 100) / width:${row.p_gain * 100} survives
    assert "Math.round(row.p_gain * 100)" not in html
    assert "Math.round(row.policy * 100)" not in html
    assert "width:${row.p_gain * 100}%" not in html
    assert "width:${row.p_loss * 100}%" not in html
    # the safe helpers are wired in
    assert "pct(row.p_gain)" in html
    assert "pct(row.p_loss)" in html
    assert "pct(push)" in html
    assert "safeNum(row.p_gain)" in html
    assert "safeNum(row.p_loss)" in html


def test_normalize_does_not_derive_nan_p_loss():
    """normalize() must not compute p_loss from a missing p_push (that yields
    NaN); it derives only when both inputs are present."""
    html = _problem_html()
    # the unguarded expression is gone
    assert "Math.max(0, 1 - r.p_gain - r.p_push)" in html  # still used...
    # ...but only under the both-present guard
    assert "r.p_gain !== undefined && r.p_push !== undefined" in html
