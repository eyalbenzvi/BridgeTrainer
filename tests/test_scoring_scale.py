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

from bridge_trainer.app.webapp import (_CSS, _SCORE_JS, _SHARED_JS,
                                       _DASHBOARD_JS, _HISTORY_JS,
                                       _dashboard_html, _history_html,
                                       _index_html,
                                       _lead_html, _problem_html)

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


# A tie group modeled on the reported bug (problem lead1i-19f92dec280, IMP
# mode): two spades tied at +0.27 IMP and five hearts tied at -0.41 IMP, all
# below the accepted club set, but with the per-card BEN softmax that used to
# split them (86 vs 83; 61/61/62/62/62).
LEAD_TIES = {
    "kind": "lead",
    "verdict": {
        "accepted": ["C4", "C2", "CT", "C9"],
        "by_mode": {
            "MP": {"accepted": ["C4", "C2", "CT", "C9", "S8", "S7"]},
            "IMP": {"accepted": ["C4", "C2", "CT", "C9"]},
        },
        "table": [
            {"card": "C4", "avg_def_tricks": 2.229, "vs_best": 0.0,
             "exp_imps": 0.79, "ben_softmax": 0.092},
            {"card": "C2", "avg_def_tricks": 2.229, "vs_best": 0.0,
             "exp_imps": 0.79, "ben_softmax": 0.092},
            {"card": "CT", "avg_def_tricks": 2.225, "vs_best": -0.004,
             "exp_imps": 0.77, "ben_softmax": 0.339},
            {"card": "C9", "avg_def_tricks": 2.225, "vs_best": -0.004,
             "exp_imps": 0.77, "ben_softmax": 0.0},
            {"card": "S8", "avg_def_tricks": 2.195, "vs_best": -0.033,
             "exp_imps": 0.27, "ben_softmax": 0.461},
            {"card": "S7", "avg_def_tricks": 2.195, "vs_best": -0.033,
             "exp_imps": 0.27, "ben_softmax": 0.037},
            {"card": "H9", "avg_def_tricks": 1.908, "vs_best": -0.32,
             "exp_imps": -0.41, "ben_softmax": 0.0},
            {"card": "H7", "avg_def_tricks": 1.908, "vs_best": -0.32,
             "exp_imps": -0.41, "ben_softmax": 0.051},
            {"card": "H2", "avg_def_tricks": 1.908, "vs_best": -0.32,
             "exp_imps": -0.41, "ben_softmax": 0.051},
        ],
    },
}


@needs_node
def test_lead_tied_cards_score_identically():
    """Regression: cards the mode ranks identically must get the SAME score,
    in either mode — the per-card softmax must not split a tie group."""
    script = (_SCORE_JS +
              f"\nconst T = {json.dumps(LEAD_TIES)};" +
              "\nconst pick = (cards, mode) => cards.map("
              "c => btScoreLead(T, c, mode).score);" +
              "\nconsole.log(JSON.stringify({"
              "s_imp: pick(['S8','S7'], 'IMP'),"
              "h_imp: pick(['H9','H7','H2'], 'IMP'),"
              "s_mp: pick(['S8','S7'], 'MP'),"
              "h_mp: pick(['H9','H7','H2'], 'MP')}));\n")
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        os.write(fd, script.encode("utf-8"))
        os.close(fd)
        res = subprocess.run(["node", path], capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout.strip().splitlines()[-1])
    finally:
        os.unlink(path)
    # every tie group collapses to a single score, in both modes
    for key in ("s_imp", "h_imp", "s_mp", "h_mp"):
        assert len(set(out[key])) == 1, (key, out[key])
    # and the two distinct groups still differ (the fix collapses ties, it
    # does not flatten everything)
    assert out["s_imp"][0] != out["h_imp"][0]


# The reported false tie (problem lead1-19fa8ed5599, MP mode, 3NT-E): the ♥K
# averages 3.480 defensive tricks against a spade spot's 3.482 — inside the
# 0.05 tie epsilon — yet beats the contract on 28% of the layouts instead of
# 37%, which is 0.90 IMP on the same evidence. Graded on the trick average
# alone it scored 100.
LEAD_FALSE_TIE = {
    "kind": "lead",
    "training": {"target_mode": "MP"},
    "verdict": {
        "accepted": ["S7", "S6", "S2", "HK", "HQ", "HJ"],
        "by_mode": {
            "MP": {"recommended": "S7",
                   "accepted": ["S7", "S6", "S2", "HK", "HQ", "HJ"]},
            "IMP": {"recommended": "S7", "accepted": ["S7", "S6", "S2"]},
        },
        "table": [
            {"card": "S7", "avg_def_tricks": 3.482, "vs_best": 0.0,
             "exp_imps": 0.88, "set_prob": 0.367, "ben_softmax": 0.397},
            {"card": "S6", "avg_def_tricks": 3.482, "vs_best": 0.0,
             "exp_imps": 0.88, "set_prob": 0.367, "ben_softmax": 0.397},
            {"card": "S2", "avg_def_tricks": 3.482, "vs_best": 0.0,
             "exp_imps": 0.88, "set_prob": 0.367, "ben_softmax": 0.397},
            {"card": "HK", "avg_def_tricks": 3.480, "vs_best": -0.002,
             "exp_imps": -0.02, "set_prob": 0.283, "ben_softmax": 0.428},
            {"card": "HQ", "avg_def_tricks": 3.480, "vs_best": -0.002,
             "exp_imps": -0.02, "set_prob": 0.283, "ben_softmax": 0.003},
            {"card": "HJ", "avg_def_tricks": 3.480, "vs_best": -0.002,
             "exp_imps": -0.02, "set_prob": 0.283, "ben_softmax": 0.001},
            {"card": "D7", "avg_def_tricks": 3.130, "vs_best": -0.353,
             "exp_imps": -0.58, "set_prob": 0.253, "ben_softmax": 0.067},
            {"card": "H5", "avg_def_tricks": 2.853, "vs_best": -0.63,
             "exp_imps": -1.25, "set_prob": 0.208, "ben_softmax": 0.015},
        ],
    },
}


@needs_node
def test_mp_tie_must_hold_in_the_score_domain():
    """An average-trick tie that costs real result is not a tie: the lead
    leaves the accepted set and is graded on what it actually costs."""
    script = (_SCORE_JS +
              f"\nconst T = {json.dumps(LEAD_FALSE_TIE)};" +
              "\nconst s = c => btScoreLead(T, c, 'MP');" +
              "\nconsole.log(JSON.stringify({"
              "acc_mp: btLeadAccepted(T, 'MP'),"
              "acc_imp: btLeadAccepted(T, 'IMP'),"
              "hk: s('HK'), hq: s('HQ'), s7: s('S7'), d7: s('D7'),"
              "line: btScoreExplain(s('HK'))}));\n")
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        os.write(fd, script.encode("utf-8"))
        os.close(fd)
        res = subprocess.run(["node", path], capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout.strip().splitlines()[-1])
    finally:
        os.unlink(path)
    # the hearts are out of the accepted set; the recommendation and the
    # spades that really do tie it are not
    assert out["acc_mp"] == ["S7", "S6", "S2"]
    assert out["acc_imp"] == ["S7", "S6", "S2"]   # score-domain mode: as stored
    assert out["s7"]["score"] == 100
    # a real deviation, not a rounding nudge off 100, and not a blunder either
    assert 60 <= out["hk"]["score"] <= 85
    # ...and still worse than the honest tie, better than the clear error
    assert out["s7"]["score"] > out["hk"]["score"] > out["d7"]["score"]
    # the tie invariant survives: ♥K/♥Q/♥J are one idea and one score
    assert out["hk"]["score"] == out["hq"]["score"]
    # the charged gap is the score-domain one (the trick gap is ~0), and the
    # breakdown line says so rather than claiming a 0.00-trick deviation
    assert out["hk"]["costSource"] == "score"
    assert out["hk"]["cost"] > 0.25 and out["hk"]["trickCost"] == 0.0
    assert "0.90 IMP" in out["line"]
    # field leniency comes from the ♥ group alone (0.43), never the spades'
    assert out["hk"]["policy"] < 0.5


def test_mp_score_domain_tie_agrees_with_the_forge():
    """btLeadAccepted (client) and mp_score_domain_tie (forge + migration)
    are one policy: they must narrow the same set the same way."""
    from bridge_trainer.pool.firestore_store import mp_score_tie_update
    from bridge_trainer.scoring.lead_metrics import mp_score_domain_tie

    v = LEAD_FALSE_TIE["verdict"]
    imps = {r["card"]: r["exp_imps"] for r in v["table"]}
    assert mp_score_domain_tie(v["by_mode"]["MP"]["accepted"], "S7", imps) \
        == ["S7", "S6", "S2"]
    # a lead BETTER than the recommendation in the score domain is not demoted
    assert mp_score_domain_tie(["S7", "HK"], "S7", {"S7": 0.1, "HK": 0.9}) \
        == ["S7", "HK"]
    # ...nor is one the record carries no score-domain evidence for
    assert mp_score_domain_tie(["S7", "HK"], "S7", {"S7": 0.9}) == ["S7", "HK"]
    # the migration payload moves every "accepted in MP" field together
    up = mp_score_tie_update({"id": "x", **LEAD_FALSE_TIE})
    assert up["verdict"]["by_mode"]["MP"]["accepted"] == ["S7", "S6", "S2"]
    assert up["verdict"]["accepted"] == ["S7", "S6", "S2"]   # MP-forged board
    flags = {r["card"]: r["recommended_mp"] for r in up["verdict"]["table"]}
    assert flags == {"S7": True, "S6": True, "S2": True, "HK": False,
                     "HQ": False, "HJ": False, "D7": False, "H5": False}
    # idempotent: the migrated record is already compliant
    migrated = {"id": "x", **LEAD_FALSE_TIE,
                "verdict": {**v, **up["verdict"]}}
    assert mp_score_tie_update(migrated) is None


# The reported inversion (problem lead1-19fb5723ed9, MP mode, 3NT-W), as
# published: ♥3 averages 3.208 defensive tricks — SECOND best on the board and
# ahead of ♦A (3.185) and ♥J (3.180) — yet the score-domain veto dropped it
# from the accepted set for trailing the ♥5 anchor by 0.07 IMP, while those two
# stayed in. ♥3 scored 94, ♥J 100: in MP, a lead graded below one it BEATS on
# the mode's own objective. Two more of the same on the same board: ♠3 (3.067)
# scored 66 against ♣J's 63 at 3.095, and ♦Q (2.967) 56 against ♣7's 53 at
# 3.038. `accepted` here is the already-migrated set, so the fixture also
# covers the repair path.
LEAD_MP_INVERSION = {
    "kind": "lead",
    "training": {"target_mode": "MP"},
    "verdict": {
        "accepted": ["HJ", "H9", "H5", "DA"],
        "by_mode": {
            "MP": {"recommended": "H5", "accepted": ["H5", "H9", "DA", "HJ"]},
            "IMP": {"recommended": "DA", "accepted": ["DA"]},
        },
        "table": [
            {"card": "H5", "avg_def_tricks": 3.212, "vs_best": 0.0,
             "exp_imps": 0.57, "ben_softmax": 0.477},
            {"card": "H3", "avg_def_tricks": 3.208, "vs_best": -0.005,
             "exp_imps": 0.50, "ben_softmax": 0.477},
            {"card": "H9", "avg_def_tricks": 3.197, "vs_best": -0.015,
             "exp_imps": 0.54, "ben_softmax": 0.023},
            {"card": "DA", "avg_def_tricks": 3.185, "vs_best": -0.027,
             "exp_imps": 0.66, "ben_softmax": 0.120},
            {"card": "HJ", "avg_def_tricks": 3.180, "vs_best": -0.032,
             "exp_imps": 0.56, "ben_softmax": 0.024},
            {"card": "CJ", "avg_def_tricks": 3.095, "vs_best": -0.117,
             "exp_imps": -0.29, "ben_softmax": 0.052},
            {"card": "S3", "avg_def_tricks": 3.067, "vs_best": -0.145,
             "exp_imps": -0.06, "ben_softmax": 0.215},
            {"card": "S9", "avg_def_tricks": 3.040, "vs_best": -0.172,
             "exp_imps": -0.13, "ben_softmax": 0.003},
            {"card": "C7", "avg_def_tricks": 3.038, "vs_best": -0.175,
             "exp_imps": -0.32, "ben_softmax": 0.012},
            {"card": "DQ", "avg_def_tricks": 2.967, "vs_best": -0.245,
             "exp_imps": -0.02, "ben_softmax": 0.019},
            {"card": "D4", "avg_def_tricks": 2.812, "vs_best": -0.400,
             "exp_imps": -1.27, "ben_softmax": 0.051},
            {"card": "SK", "avg_def_tricks": 2.465, "vs_best": -0.748,
             "exp_imps": -1.43, "ben_softmax": 0.001},
        ],
    },
}


@needs_node
def test_mp_score_never_falls_below_a_worse_trick_average():
    """MP ranks by expected defensive tricks, so the panel score must be
    monotone in it: more tricks never scores less. The score domain may still
    split what the trick average cannot, but it may not invert it."""
    script = (_SCORE_JS +
              f"\nconst T = {json.dumps(LEAD_MP_INVERSION)};" +
              "\nconst rows = T.verdict.table.map(r => ({card: r.card,"
              " t: r.avg_def_tricks,"
              " score: btScoreLead(T, r.card, 'MP').score,"
              " capped: !!btScoreLead(T, r.card, 'MP').capped}));"
              "\nconsole.log(JSON.stringify({rows: rows,"
              " acc: btLeadAccepted(T, 'MP'),"
              " acc_imp: btLeadAccepted(T, 'IMP'),"
              " line: btScoreExplain(btScoreLead(T, 'S3', 'MP'))}));\n")
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        os.write(fd, script.encode("utf-8"))
        os.close(fd)
        res = subprocess.run(["node", path], capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout.strip().splitlines()[-1])
    finally:
        os.unlink(path)
    rows = out["rows"]
    by_card = {r["card"]: r for r in rows}
    # THE invariant, over every pair on the board
    for a in rows:
        for b in rows:
            if a["t"] > b["t"]:
                assert a["score"] >= b["score"], (a, b)
    # the reported pair specifically: ♥3 is back in the accepted set (it beats
    # two leads that were never out of it), so both are 100
    assert "H3" in out["acc"]
    assert by_card["H3"]["score"] == 100 == by_card["HJ"]["score"]
    # the IMP mode ranks in the score domain and is untouched
    assert out["acc_imp"] == ["DA"]
    # the other two inversions are gone by the ceiling, which says so in the
    # breakdown line rather than letting the parts fail to add up
    assert by_card["S3"]["capped"] and by_card["DQ"]["capped"]
    assert "תקרה" in out["line"]
    # the ceiling only clamps — it never lifts a lead to the accepted grade
    assert max(r["score"] for r in rows if r["card"] not in out["acc"]) < 100


def test_mp_accepted_set_is_closed_upward_in_tricks():
    """The forge, the migration and the client share one policy: the score
    domain may trim the TAIL of a trick tie, never its middle."""
    from bridge_trainer.pool.firestore_store import mp_score_tie_update
    from bridge_trainer.scoring.lead_metrics import (mp_monotone_close,
                                                     mp_score_domain_tie,
                                                     mp_trick_tie)

    v = LEAD_MP_INVERSION["verdict"]
    imps = {r["card"]: r["exp_imps"] for r in v["table"]}
    tricks = {r["card"]: r["avg_def_tricks"] for r in v["table"]}
    tied = mp_trick_tie(tricks)
    assert tied == ["H5", "H3", "H9", "DA", "HJ"]
    # without the trick evidence the veto still cuts ♥3 out of the middle...
    assert mp_score_domain_tie(tied, "H5", imps) == ["H5", "H9", "DA", "HJ"]
    # ...with it, ♥3 is re-admitted: it beats every lead that stayed
    assert mp_score_domain_tie(tied, "H5", imps, tricks) == tied
    # the closure is what does it, and it only ever re-admits
    assert mp_monotone_close(tied, ["H5", "HJ"], tricks) == tied
    assert mp_monotone_close(tied, ["H5"], tricks) == ["H5"]
    # STRICTLY better, never merely equal: leads on the SAME average are the
    # tie the score domain exists to split, so the veto's own motivating case
    # (equal averages, opposite results) survives the closure
    equal = {"SA": 4.0, "HK": 4.0}
    assert mp_monotone_close(["SA", "HK"], ["SA"], equal) == ["SA"]
    assert mp_score_domain_tie(["SA", "HK"], "SA", {"SA": 0.9, "HK": -0.9},
                               equal) == ["SA"]

    # the same policy on the reference board still demotes: there the hearts
    # ARE the tail of the trick order, so nothing is re-admitted
    fv = LEAD_FALSE_TIE["verdict"]
    f_imps = {r["card"]: r["exp_imps"] for r in fv["table"]}
    f_tricks = {r["card"]: r["avg_def_tricks"] for r in fv["table"]}
    assert mp_score_domain_tie(fv["by_mode"]["MP"]["accepted"], "S7", f_imps,
                               f_tricks) == ["S7", "S6", "S2"]

    # the migration repairs a record the earlier, non-monotone policy already
    # narrowed — it reads the record's own trick tie, not just its stored set
    up = mp_score_tie_update({"id": "x", **LEAD_MP_INVERSION})
    assert set(up["verdict"]["by_mode"]["MP"]["accepted"]) == set(tied)
    assert up["verdict"]["accepted"] == ["HJ", "H9", "H5", "H3", "DA"]
    flags = {r["card"]: r["recommended_mp"] for r in up["verdict"]["table"]}
    assert flags["H3"] is True and flags["CJ"] is False
    # ...and is idempotent once applied
    fixed = {"id": "x", **LEAD_MP_INVERSION,
             "verdict": {**v, **up["verdict"]}}
    assert mp_score_tie_update(fixed) is None


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
    h = _history_html()
    assert "btScoreBidding(P, chosen)" in p and "scoreline" in p
    assert "btScoreLead(P, chosen, MODE)" in l and "scoreline" in l
    for page in (p, l, d, i, h):
        # the shared score module + chip styling now ship as external assets
        # (T2); every page must link them.
        assert 'src="bt-shared.js?v=' in page
        assert 'href="app.css?v=' in page
    assert "btScoreOfAttempt" in _SHARED_JS   # shared score module
    assert ".scorechip" in _CSS               # chip styling
    # the session trail and home stats aggregate scores, not correct counts
    # (the kind arg is the UX-I-6 out-of-scenario guard)
    assert 'bumpSession(rec.score, P.id, "bidding")' in p
    assert 'bumpSession(rec.score, P.id, "lead")' in l
    assert "scoreSum += btScoreOfAttempt(rec)" in i
    # dashboard aggregates: mean-score rows + score-band distribution.
    # The dashboard ships its script as an external asset, so the page
    # links it and the aggregation itself lives in _DASHBOARD_JS.
    assert 'src="dashboard.js?v=' in d
    assert "meanCI" in _DASHBOARD_JS and "ציון ממוצע" in _DASHBOARD_JS
    # the practice log shows the same stored score per row, from the same
    # module, and ships its script the same way
    assert 'src="history.js?v=' in h
    assert "btScoreOfAttempt" in _HISTORY_JS


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
