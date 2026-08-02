"""Card-world grading (engine/lead_card_world): gloss validation, the
LeadEvaluation bridge, stability, and the stored-record regrade path.

Ben-free; the real reference board lead1-19fa5daef4b runs end-to-end with
small sample counts (rejection sampling + endplay DDS, a few seconds).
"""
import numpy as np
import pytest

from bridge_trainer.engine.lead_card_world import (
    card_world_evaluation, gloss_violations, grade_record_card_world,
    stability_check)
from bridge_trainer.engine.lead_posterior import build_problem

LEADER_HAND = "AQJ754.Q.T975.76"
AUCTION = ["1C", "P", "2C", "P", "2D", "P", "3NT", "P", "P", "P"]
FULL_DEAL = {"S": "T63.J74.AJ3.AQJ3", "W": "9.KT9632.842.985",
             "E": LEADER_HAND, "N": "K82.A85.KQ6.KT42"}

ENTRIES = [
    {"idx": 0, "seat": "S", "call": "1C", "card": {
        "gib_raw": "Minor suit opening -- 3+ !C; 11-21 HCP",
        "hcp": (11, 21), "pts": None, "minlen": {"C": 3}, "maxlen": {}}},
    {"idx": 2, "seat": "N", "call": "2C", "card": {
        "gib_raw": "Inverted minor suit raise -- 4+ !C; 3- !H; 3- !S; 10+ HCP",
        "hcp": (10, 37), "pts": None,
        "minlen": {"C": 4}, "maxlen": {"S": 3, "H": 3}}},
    {"idx": 4, "seat": "S", "call": "2D", "card": {
        "gib_raw": "3+ !C; 11-21 HCP; stop in !D",
        "hcp": (11, 21), "pts": None, "minlen": {"C": 3}, "maxlen": {}}},
    {"idx": 6, "seat": "N", "call": "3NT", "card": {
        "gib_raw": "4+ !C; 3- !H; 3- !S; 14-18 HCP; partial stop in !H; "
                   "partial stop in !S",
        "hcp": (14, 18), "pts": None,
        "minlen": {"C": 4}, "maxlen": {"S": 3, "H": 3}}},
]


def _problem():
    return build_problem(LEADER_HAND, AUCTION, "S", "Both", "3NTN")


def _record(full_deal=FULL_DEAL):
    return {"id": "lead1-19fa5daef4b", "kind": "lead", "hand": LEADER_HAND,
            "leader": "E", "dealer": "S", "vul": "Both", "contract": "3NTN",
            "auction": AUCTION, "full_deal": dict(full_deal),
            "training": {"target_mode": "MP"},
            "verdict": {"accepted": ["SA"], "table": [
                {"card": "SA", "ben_softmax": 0.45},
                {"card": "SQ", "ben_softmax": 0.20}]},
            "classification": {"difficulty_level": 4, "type": "lead_3nt"},
            "generator": {"target_mode": "MP"},
            "explanations": {"auction": ENTRIES}}


# ---- gloss validation -------------------------------------------------------

def test_gloss_violations_pass_on_the_true_deal():
    assert gloss_violations(ENTRIES, FULL_DEAL, LEADER_HAND, "E") == []


def test_gloss_violations_catch_a_stopless_3nt():
    fd = dict(FULL_DEAL)
    # swap the spade K away from declarer: 3NT's partial spade stop is a lie
    fd["N"] = "982.A85.KQ6.KT42"
    fd["W"] = "K.KT9632.842.985"
    bad = gloss_violations(ENTRIES, fd, LEADER_HAND, "E")
    assert any("partial stop in !S" in b and b.startswith("N:3NT") for b in bad)
    # hard facts (lengths/HCP) stay with explain_check — not reported here
    assert not any("4+ !C" in b for b in bad)


# ---- the LeadEvaluation bridge ---------------------------------------------

def test_card_world_evaluation_returns_paired_plain_arrays():
    le, diag = card_world_evaluation(_problem(), ENTRIES, {"SA": 0.45},
                                     n_samples=120, seed=3)
    assert le is not None
    assert diag["any_constraint_applied"] and diag["ess"] > 30
    assert le.n_samples >= 60 and le.contract == "3NTN"
    assert set(le.def_tricks) == set(le.cards) and len(le.cards) == 13
    lengths = {arr.shape[0] for arr in le.def_tricks.values()}
    assert lengths == {le.n_samples}            # shared resample, paired
    # deterministic in the seed
    le2, _ = card_world_evaluation(_problem(), ENTRIES, {"SA": 0.45},
                                   n_samples=120, seed=3)
    assert np.array_equal(le.def_tricks["SA"], le2.def_tricks["SA"])


def test_card_world_evaluation_abstains_without_constraints():
    le, diag = card_world_evaluation(_problem(), [], {}, n_samples=50)
    assert le is None
    assert diag["fallback"] == "no_constraints_recognised"


# ---- the stored-record regrade (migration path) -----------------------------

def test_grade_record_deletes_gloss_contradicting_deal():
    rec = _record()
    rec["full_deal"] = dict(FULL_DEAL,
                            N="982.A85.KQ6.KT42", W="K.KT9632.842.985")
    rep = grade_record_card_world(rec, n_samples=80)
    assert rep["status"] == "gloss_unfulfilled"


def test_grade_record_regrades_and_reports_answer_change():
    rep = grade_record_card_world(_record(), seed=2, n_samples=250)
    assert rep["status"] in ("regraded", "honor_sensitive")
    if rep["status"] == "regraded":
        up = rep["update"]
        assert up["verdict"]["accepted"] == rep["new_accepted"]
        assert up["generator"]["grading"]["distribution"] \
            == "gib_cards_calibrated"
        assert len(up["verdict"]["table"]) == 13
        row = up["verdict"]["table"][0]
        for k in ("exp_imps", "set_prob", "rank_mp", "rank_imp"):
            assert k in row
        assert up["explanations"]["cards"]          # notes regenerated
        assert rep["answer_changed"] == (set(rep["new_accepted"])
                                         != {"SA"})


def test_grade_record_keeps_unconstrained_board():
    rec = _record()
    rec["explanations"] = {"auction": []}
    rep = grade_record_card_world(rec, n_samples=50)
    assert rep["status"] == "no_constraints"


# ---- stability --------------------------------------------------------------

def test_stability_check_accepts_overlap_and_flags_flip(monkeypatch):
    from bridge_trainer.engine import lead_card_world as m
    from bridge_trainer.engine.lead_verdict import LeadVerdict

    fake_le = type("L", (), {"n_samples": 200})()
    monkeypatch.setattr(m, "card_world_evaluation",
                        lambda *a, **k: (fake_le, {"ess": 150}))
    monkeypatch.setattr(m, "judge_lead_mode",
                        lambda le, mode, vul=None, force=False:
                        LeadVerdict(True, "accepted", best=["D5", "D7"]),
                        raising=False)
    import bridge_trainer.engine.lead_verdict as lv
    monkeypatch.setattr(lv, "judge_lead_mode",
                        lambda le, mode, vul=None, force=False:
                        LeadVerdict(True, "accepted", best=["D5", "D7"]))
    ok, diag = m.stability_check(_problem(), ENTRIES, ["D5"], {})
    assert ok and diag["overlap"]
    ok, _ = m.stability_check(_problem(), ENTRIES, ["SA"], {})
    assert not ok
