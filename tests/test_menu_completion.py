"""Menu completion + policy-evidence divergence (ben1-19f95ad149d).

The published board: hero W, Q8.K9.A82.AQT752, after 1NT-P-2C-P-2D-P-2NT-P.
Ben's raw softmax gave 4C 57.3% / 3C 30.4% / P 9.6% and rated the humanly
normal 3NT at 2.35% — under the option floor, so it was never offered and
never evaluated. Meanwhile the winner 3C's own rollout ended in 3NT by the
hero on 92% of layouts, and the 57%-policy 4C lost its own rollout by 2.86
IMPs (partner passed it out on every layout). Three mechanisms now catch
this class:

* ``menu_completion_calls`` reads the missing direct call off the rollout's
  own contract distribution (forge: engine/maker.py; purge:
  pool/firestore_store.menu_offenders);
* ``judge`` rejects a board whose policy-top loses its own rollout by more
  than the accept band (``policy_rollout_divergence``);
* the option floor dropped to 2% (scanner.P_OPTION).
"""
from __future__ import annotations

import numpy as np

from bridge_trainer.engine.ben import Evaluation, merge_evaluations
from bridge_trainer.engine.explain_check import (contract_call,
                                                 menu_completion_calls)
from bridge_trainer.engine.verdict import judge
from bridge_trainer.pool.firestore_store import menu_offenders

# the real board's decision point: dealer W (index 3), hero W
STEM = ["1NT", "P", "2C", "P", "2D", "P", "2NT", "P"]


# ---- menu_completion_calls -------------------------------------------------

def test_completion_finds_the_missing_3nt():
    dists = {"3C": {"3NW": 473, "3CE": 37, "3CXE": 1},
             "P": {"2NW": 512},
             "4C": {"4CE": 512}}
    got = menu_completion_calls(dists, 512, STEM, 3, 3, ["4C", "3C", "P"])
    # 3NW (92% of 3C's rollout, hero side, legal) -> 3NT is missing;
    # 2NW's direct 2NT is illegal (does not outrank the standing 2NT);
    # 4CE's direct call 4C is already offered; 3CE is under COMPLETE_SHARE
    assert got == ["3NT"]


def test_completion_accepts_wrapped_firestore_rows():
    dists = {"3C": [{"items": ["3NW", 473]}, {"items": ["3CE", 37]}],
             "4C": [{"items": ["4CE", 512]}]}
    assert menu_completion_calls(
        dists, 512, STEM, 3, 3, ["4C", "3C", "P"]) == ["3NT"]


def test_completion_ignores_their_contracts_and_low_shares():
    # 3NS is declared by the opponents (hero W): bidding 3NT ourselves is
    # not what that rollout shows, so it never nominates a call
    assert menu_completion_calls(
        {"X": {"3NS": 512}}, 512, STEM, 3, 3, ["X"]) == []
    # under the share floor: not a destination, just a stray continuation
    assert menu_completion_calls(
        {"3C": {"3NW": 100}}, 512, STEM, 3, 3, ["3C"]) == []


def test_completion_ignores_pass_doubled_and_offered():
    dists = {"P": {"PASS": 512},                 # pass-out: nothing to bid
             "X": {"3CXE": 512},                 # doubled: no direct call
             "3C": {"3CE": 512}}                 # already offered
    assert menu_completion_calls(dists, 512, STEM, 3, 3, ["P", "X", "3C"]) \
        == []


def test_completion_no_samples_is_silent():
    assert menu_completion_calls({"3C": {"3NW": 473}}, 0, STEM, 3, 3,
                                 ["3C"]) == []


def test_contract_call_shapes():
    assert contract_call("3NW") == "3NT"
    assert contract_call("6CS") == "6C"
    assert contract_call("PASS") is None
    assert contract_call("5DXW") is None


# ---- merge_evaluations ------------------------------------------------------

def _ev(cols: dict, contracts: dict) -> Evaluation:
    bids = list(cols)
    n = len(next(iter(cols.values())))
    return Evaluation(
        bids=bids,
        ev={b: np.asarray(cols[b], float) for b in bids},
        contracts={b: list(contracts[b]) for b in bids},
        auctions={b: [""] * n for b in bids},
        n_samples=n, quality=1.0)


def test_merge_keeps_pairing_and_originals():
    a = _ev({"3C": [100.0, 0.0]}, {"3C": ["3NW", "3CE"]})
    b = _ev({"3NT": [100.0, -50.0]}, {"3NT": ["3NW", "3NW"]})
    m = merge_evaluations(a, b)
    assert m.bids == ["3C", "3NT"]
    assert m.n_samples == 2
    assert list(m.ev["3NT"]) == [100.0, -50.0]
    assert m.contracts["3C"] == ["3NW", "3CE"]


def test_merge_refuses_different_sample_sets():
    a = _ev({"3C": [0.0, 0.0]}, {"3C": ["3NW", "3NW"]})
    b = _ev({"3NT": [0.0]}, {"3NT": ["3NW"]})
    try:
        merge_evaluations(a, b)
    except ValueError:
        return
    raise AssertionError("merging unequal sample sets must fail")


# ---- the divergence gate in judge -------------------------------------------

def _board(top_loss_rows: int) -> Evaluation:
    """B (winner) vs S (close second) vs T (the policy top, 100 raw points
    — 3 IMPs — behind B on *top_loss_rows* layouts, identical elsewhere).
    B-vs-S passes every honesty gate: gap ~1.7 IMPs, plenty of stakes,
    tight CI. T's mean loss is 3 * top_loss_rows / 160 IMPs."""
    n = 160
    B = np.zeros(n)
    B[:60] = 250.0
    B[60:90] = -100.0
    S = np.zeros(n)
    T = B.copy()
    T[:top_loss_rows] -= 100.0
    contracts = {"B": ["4SS"] * 90 + ["3SS"] * (n - 90),
                 "S": ["3SS"] * n, "T": ["5CS"] * n}
    return _ev({"B": B, "S": S, "T": T}, contracts)


POLICY = {"T": 0.57, "B": 0.30, "S": 0.10}


def test_refuted_policy_top_rejects_the_board():
    # 3 IMPs * 150/160 rows = 2.81 IMPs mean loss — past the accept band
    v = judge(_board(150), policy_top="T", hero_i=2, policy_map=POLICY)
    assert not v.accepted
    assert v.reason == "policy_rollout_divergence"
    assert v.measured["policy_top_gap"] > 2.5


def test_trap_band_survives_the_divergence_gate():
    # 3 IMPs * 60/160 rows = 1.13 IMPs — a genuine trap, inside the band
    v = judge(_board(60), policy_top="T", hero_i=2, policy_map=POLICY)
    assert v.reason != "policy_rollout_divergence"


def test_policy_top_that_wins_is_never_divergent():
    v = judge(_board(150), policy_top="B", hero_i=2, policy_map=POLICY)
    assert v.reason != "policy_rollout_divergence"


# ---- menu_offenders (the purge's pure core) ---------------------------------

def _record(candidates, table, accepted, auction=STEM, n=512):
    return {"id": "ben1-test", "kind": "bidding", "dealer": "W", "seat": "W",
            "auction": list(auction),
            "candidates": [{"call": b, "policy": p} for b, p in candidates],
            "quality": {"n_samples": n},
            "verdict": {"accepted": accepted, "table": table}}


def test_offender_menu_missing_3nt():
    rec = _record(
        [("4C", 0.573), ("3C", 0.304), ("P", 0.096)],
        [{"bid": "3C", "ev_imp_vs_top": 1.2,
          "top_contracts": [{"items": ["3NW", 473]},
                            {"items": ["3CE", 37]}]},
         {"bid": "P", "ev_imp_vs_top": -1.2,
          "top_contracts": [{"items": ["2NW", 512]}]},
         {"bid": "4C", "ev_imp_vs_top": -2.86,
          "top_contracts": [{"items": ["4CE", 512]}]}],
        accepted="3C")
    reasons = menu_offenders([rec])
    assert reasons == {"ben1-test": "menu missing 3NT"}


def test_offender_refuted_policy_top():
    # menu complete (winner's rollout stays in an offered call's contract),
    # but the 57%-policy call loses 2.86 IMPs to the accepted one
    rec = _record(
        [("4C", 0.573), ("3C", 0.304)],
        [{"bid": "3C", "ev_imp_vs_top": 1.2,
          "top_contracts": [{"items": ["3CE", 512]}]},
         {"bid": "4C", "ev_imp_vs_top": -2.86,
          "top_contracts": [{"items": ["4CE", 512]}]}],
        accepted="3C")
    reasons = menu_offenders([rec])
    assert list(reasons) == ["ben1-test"]
    assert reasons["ben1-test"].startswith("policy top 4C loses 2.86 IMPs")


def test_clean_record_not_flagged():
    rec = _record(
        [("3C", 0.50), ("P", 0.30), ("3NT", 0.15)],
        [{"bid": "3C", "ev_imp_vs_top": 1.2,
          "top_contracts": [{"items": ["3NW", 473]},
                            {"items": ["3CE", 37]}]},
         {"bid": "P", "ev_imp_vs_top": -1.2,
          "top_contracts": [{"items": ["2NW", 512]}]},
         {"bid": "3NT", "ev_imp_vs_top": -0.2,
          "top_contracts": [{"items": ["3NW", 512]}]}],
        accepted="3C")
    assert menu_offenders([rec]) == {}


def test_lead_records_and_tossups_skipped():
    lead = {"id": "lead1-x", "kind": "lead", "dealer": "W", "seat": "E"}
    tossup = _record(
        [("4C", 0.573), ("3C", 0.304)],
        [{"bid": "3C", "ev_imp_vs_top": 0.1,
          "top_contracts": [{"items": ["3CE", 512]}]},
         {"bid": "4C", "ev_imp_vs_top": -3.0,
          "top_contracts": [{"items": ["4CE", 512]}]}],
        accepted="")           # toss-up: no accepted call to diverge from
    assert menu_offenders([lead, tossup]) == {}
