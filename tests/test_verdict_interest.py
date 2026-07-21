"""Interest-reference tests: the selectivity layer is anchored to the
highest-policy alternative (the call the student is tempted to make),
NOT the 2nd-best by EV. The property this pins down is that lowering the
option threshold — which surfaces extra low-policy candidates — does not
change which board qualifies or its interest score.
"""
from __future__ import annotations

import numpy as np

from bridge_trainer.engine.ben import Evaluation
from bridge_trainer.engine.verdict import _interest_ref, judge


def _ev(cols: dict, contracts: dict) -> Evaluation:
    bids = list(cols)
    n = len(next(iter(cols.values())))
    return Evaluation(
        bids=bids,
        ev={b: np.asarray(cols[b], float) for b in bids},
        contracts={b: list(contracts[b]) for b in bids},
        auctions={b: [""] * n for b in bids},
        n_samples=n, quality=1.0)


def test_interest_ref_picks_highest_policy_alternative():
    bids = ["W", "C", "T"]          # EV order is irrelevant here
    # winner W; alternatives C (4%) and T (45%): the tempting call is T
    ref = _interest_ref(bids, "W", {"W": 0.44, "C": 0.04, "T": 0.45}, "C")
    assert ref == "T"


def test_interest_ref_falls_back_without_policy():
    # no policy map -> the EV runner-up (fallback) is used, unchanged
    assert _interest_ref(["W", "C"], "W", None, "C") == "C"


# ---- the core invariance: adding a low-policy, EV-close candidate ----
# must not change the verdict or the interest score, because the interest
# layer references the high-policy temptation, not the EV runner-up.

def _winner_vs_tempt_columns(n=160):
    """W (winner) vs T (high-policy tempting call): a real dilemma — W
    wins a game swing often, loses a little sometimes. T sits in a
    partscore throughout (span + trap + consequence). Sample types are
    interleaved by a fixed permutation so the two sample halves are
    statistically alike (no spurious split-half instability)."""
    W = np.zeros(n)
    W[:60] = 250.0          # +game swing on 60 layouts
    W[60:96] = -100.0       # a partscore loss on 36
    cW = np.array(["4SS"] * 96 + ["3SS"] * (n - 96))  # modal W = game
    perm = np.random.default_rng(12345).permutation(n)
    W, cW = W[perm], cW[perm]
    T = np.zeros(n)
    cT = ["3SS"] * n                          # T = partscore throughout
    return W, T, list(cW), cT


POLICY = {"W": 0.44, "T": 0.45, "C": 0.05}   # T is policy-top -> trap


def test_board_accepted_without_extra_candidate():
    W, T, cW, cT = _winner_vs_tempt_columns()
    ev = _ev({"W": W, "T": T}, {"W": cW, "T": cT})
    v = judge(ev, policy_top="T", hero_i=0, policy_map=POLICY)
    assert v.accepted and v.best == "W"
    assert v.measured["interest_vs"] == "T"


def test_extra_low_policy_candidate_does_not_change_interest():
    """Append C: a low-policy call whose EV sits just under W, so it
    becomes the 2nd-best by EV (displacing T from that slot). The verdict
    and the interest score must be unchanged — the fix's whole point."""
    W, T, cW, cT = _winner_vs_tempt_columns()
    base = judge(_ev({"W": W, "T": T}, {"W": cW, "T": cT}),
                 policy_top="T", hero_i=0, policy_map=POLICY)

    C = W.copy()
    C[:50] -= 100.0         # slightly worse than W -> EV runner-up, small gap
    cC = list(cW)
    ev2 = _ev({"W": W, "C": C, "T": T}, {"W": cW, "C": cC, "T": cT})
    v2 = judge(ev2, policy_top="T", hero_i=0, policy_map=POLICY)

    # C is the EV runner-up now ...
    assert v2.measured["top2"] == ["W", "C"]
    # ... but interest still references the high-policy temptation T,
    # so acceptance and the interest score are identical to the 2-call board
    assert v2.accepted and v2.best == "W"
    assert v2.measured["interest_vs"] == "T"
    assert v2.measured["interest"] == base.measured["interest"]
    assert v2.measured["q"] == base.measured["q"]
