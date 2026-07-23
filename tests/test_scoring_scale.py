"""Panel-score unit tests (docs/scoring_scale.md).

The 0-100 scale is implemented in ``_SCORE_JS`` — a DOM-free block shared
by every page — so the numeric behavior is exercised by running that block
under node with fixture problem docs. String-level assertions keep the page
wiring (chips, breakdown line, storage) honest without node.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import tempfile

import pytest

from bridge_trainer.app.webapp import (_SCORE_JS, _dashboard_html,
                                       _index_html, _lead_html,
                                       _problem_html)

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available")

# raw record shape: accepted as a string, verdict.table rows (the page
# normalizes to verdict.corrected, but the scorer must handle both)
BIDDING = {
    "kind": "bidding",
    "quality": {"stakes": 2.5},
    "candidates": [{"call": "4H", "policy": 0.55},
                   {"call": "3H", "policy": 0.30},
                   {"call": "P", "policy": 0.15}],
    "verdict": {
        "accepted": "4H", "toss_up": False,
        "table": [
            {"bid": "4H", "ev_imp_vs_top": 1.2, "ci": 0.6},
            {"bid": "3H", "ev_imp_vs_top": -1.2, "ci": 0.6},
            {"bid": "P", "ev_imp_vs_top": -5.0, "ci": 1.0},
        ],
        "dead_options": [{"bid": "P"}],
    },
}

LEAD = {
    "kind": "lead",
    "verdict": {
        "accepted": ["SK"],
        "by_mode": {"MP": {"accepted": ["SK"]},
                    "IMP": {"accepted": ["HA"]}},
        "table": [
            {"card": "SK", "avg_def_tricks": 4.1, "vs_best": 0.0,
             "ben_softmax": 0.5, "exp_imps": 0.5},
            {"card": "HA", "avg_def_tricks": 3.8, "vs_best": -0.3,
             "ben_softmax": 0.3, "exp_imps": 1.1},
            {"card": "D2", "avg_def_tricks": 3.0, "vs_best": -1.1,
             "ben_softmax": 0.05, "exp_imps": -1.4},
        ],
    },
}


def run_js(exprs: list[str]):
    """Run _SCORE_JS under node and evaluate each expression; returns the
    list of JSON-decoded results (one node process for the whole list)."""
    script = (_SCORE_JS +
              f"\nconst BIDDING = {json.dumps(BIDDING)};" +
              f"\nconst LEAD = {json.dumps(LEAD)};" +
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
def test_bidding_pins_and_bands():
    best, dead, mid = run_js([
        "btScoreBidding(BIDDING, '4H')",
        "btScoreBidding(BIDDING, 'P')",
        "btScoreBidding(BIDDING, '3H')",
    ])
    assert best["score"] == 100                    # accepted set pins to 100
    assert dead["score"] == 0 and dead["dead"]     # dead option pins to 0
    # 1.2 IMP below best, half the 0.6 CI forgiven, +1.8 field leniency:
    # a light deviation, never confusable with best (cap 94)
    assert 65 <= mid["score"] <= 94
    assert mid["cost"] == pytest.approx(1.2)
    assert mid["cEff"] == pytest.approx(0.9)


@needs_node
def test_bidding_ci_haircut_and_leniency_monotonic():
    with_ci, no_ci, no_policy = run_js([
        "btScoreBidding(BIDDING, '3H')",
        "btScoreBidding({...BIDDING, verdict: {...BIDDING.verdict, "
        "table: [{bid: '4H', ev_imp_vs_top: 1.2, ci: 0}, "
        "{bid: '3H', ev_imp_vs_top: -1.2, ci: 0}]}}, '3H')",
        "btScoreBidding({...BIDDING, candidates: []}, '3H')",
    ])
    # an established gap scores lower than the same gap that is partly noise
    assert no_ci["score"] < with_ci["score"]
    # field leniency: the popular error keeps a few points
    assert no_policy["score"] < with_ci["score"]


@needs_node
def test_bidding_stakes_stretch_differentiates_problem_types():
    quiet, neutral, wild = run_js([
        "btScoreBidding({...BIDDING, quality: {stakes: 0.9}}, '3H')",
        "btScoreBidding(BIDDING, '3H')",
        "btScoreBidding({...BIDDING, quality: {stakes: 4.5}}, '3H')",
    ])
    # the same 1.2 IMP miss: harsher on a quiet part-score board, softer on
    # a swingy (slam/game) board
    assert quiet["score"] < neutral["score"] < wild["score"]
    assert wild["score"] <= 94


@needs_node
def test_bidding_toss_up_set_all_score_100():
    legacy = {"verdict": {"toss_up": True, "toss_up_set": ["3S", "P"],
                          "accepted": "", "table": []}}
    a, b = run_js([
        f"btScoreBidding({json.dumps(legacy)}, '3S')",
        f"btScoreBidding({json.dumps(legacy)}, 'P')",
    ])
    assert a["score"] == b["score"] == 100


@needs_node
def test_lead_modes_grade_against_their_own_ranking():
    mp_best, mp_second, mp_worst, imp_best, imp_sk, imp_d2 = run_js([
        "btScoreLead(LEAD, 'SK', 'MP')",
        "btScoreLead(LEAD, 'HA', 'MP')",
        "btScoreLead(LEAD, 'D2', 'MP')",
        "btScoreLead(LEAD, 'HA', 'IMP')",
        "btScoreLead(LEAD, 'SK', 'IMP')",
        "btScoreLead(LEAD, 'D2', 'IMP')",
    ])
    assert mp_best["score"] == 100
    assert imp_best["score"] == 100          # per-mode accepted set
    assert 100 > mp_second["score"] > mp_worst["score"] >= 1
    assert 100 > imp_sk["score"] > imp_d2["score"] >= 1
    # MP blends the matchpoint rank; the second-best of three keeps dignity
    assert mp_second["rank"] == 2 and mp_second["groups"] == 3
    assert mp_second["score"] >= 60


@needs_node
def test_attempt_fallback_matches_semantics():
    rows = run_js([
        "btScoreOfAttempt({score: 73})",
        "btScoreOfAttempt({correct: true})",
        "btScoreOfAttempt({outcomeClass: 'dead'})",
        "btScoreOfAttempt({kind: 'bidding', gradedCost: 2.0})",
        "btScoreOfAttempt({kind: 'lead', trainingMode: 'IMP', gradedCost: 2.0})",
        "btScoreOfAttempt({kind: 'lead', gradedCost: 0.6})",
        "btScoreOfAttempt(null)",
        # legacy MISTAKE with no measured cost (old graders left cost 0 when
        # the chosen option had no table row): the no-data fallback, never a
        # free ride up the curve to 94
        "btScoreOfAttempt({correct: false, outcomeClass: 'suboptimal'})",
        "btScoreOfAttempt({correct: false, gradedCost: 0})",
    ])
    stored, legacy_ok, legacy_dead, bid, lead_imp, lead_mp, none, \
        nocost1, nocost2 = rows
    assert stored == 73                      # stored score wins verbatim
    assert legacy_ok == 100 and legacy_dead == 0
    assert nocost1 == 40 and nocost2 == 40
    # base curve at cost == tau crosses ~47 in every scenario
    assert 40 <= bid <= 55
    assert lead_imp < bid                    # tighter lead-IMP scale
    assert 40 <= lead_mp <= 55               # 0.6 tricks == the MP tau
    assert none is None


@needs_node
def test_band_boundaries():
    bands = run_js(["[100, 92, 70, 50, 20, 0].map(btBandOf)"])[0]
    assert bands == ["best", "near", "minor", "error", "blunder", "dead"]


def test_pages_wire_the_score():
    p, l, d, i = _problem_html(), _lead_html(), _dashboard_html(), _index_html()
    assert "btScoreBidding(P, chosen)" in p and "scoreline" in p
    assert "btScoreLead(P, chosen, MODE)" in l and "scoreline" in l
    for page in (p, l, d, i):
        assert "btScoreOfAttempt" in page    # shared module on every page
        assert ".scorechip" in page          # chip styling shipped
    # the session trail and home stats aggregate scores, not correct counts
    assert "bumpSession(rec.score, P.id)" in p
    assert "bumpSession(rec.score, P.id)" in l
    assert "scoreSum += btScoreOfAttempt(rec)" in i
    # dashboard aggregates: mean-score rows + score-band distribution
    assert "meanCI" in d and "ציון ממוצע" in d


def test_attempt_records_carry_score():
    js = pathlib.Path("bridge_trainer/web/bt-firebase.js") \
        .read_text(encoding="utf-8")
    assert "window.btScoreBidding" in js
    assert "window.btScoreLead" in js
    # grading still works (binary fallback) when the shared block is absent
    assert "(correct ? 100 : 0)" in js


def test_band_labels_are_hebrew():
    for label in ("מיטבי", "כמעט מיטבי", "סטייה קלה", "טעות",
                  "טעות חמורה", "אפשרות מתה"):
        assert label in _SCORE_JS
