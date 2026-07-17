"""Prescreen cascade + DD-memo unit tests (no Ben engine needed for the
prejudge half; the memo tests import Ben's bidding table and self-skip
when the checkout isn't on sys.path).

The cascade's contract: prejudge() may return a rejection reason ONLY
when the full 128-sample judge's outcome is statistically settled;
anything borderline must return None (escalate). Precision is protected
by construction — these tests pin the margin behavior the expert review
flagged as dangerous (zero-variance slices, Wald degeneracy at k=0,
observed-vs-optimistic interest binaries).
"""
from __future__ import annotations

import numpy as np
import pytest

from bridge_trainer.engine.ben import Evaluation, _tricks_dd_memo
from bridge_trainer.engine.verdict import (
    Q_MIN, _wilson_upper, prejudge,
)


def make_ev(scores_a, scores_b, contracts_a=None, contracts_b=None,
            bids=("A", "B")) -> Evaluation:
    a, b = np.asarray(scores_a, float), np.asarray(scores_b, float)
    n = len(a)
    return Evaluation(
        bids=list(bids),
        ev={bids[0]: a, bids[1]: b},
        contracts={bids[0]: contracts_a or ["3HS"] * n,
                   bids[1]: contracts_b or ["2SN"] * n},
        auctions={bid: [""] * n for bid in bids},
        n_samples=n, quality=1.0)


# ---------------------------------------------------------------- prejudge

def test_all_push_slice_never_stakeless():
    """Zero-variance trap: 32 pushes have std=0, so a CLT 'upper bound'
    of 0 < STAKES_MIN must never fire. (The q-Wilson bound MAY still
    reject as inconsequential — that one is decisive even at k=0:
    P(all-push | true q >= 0.4) = 0.6^32 ~ 1e-7.)"""
    ev = make_ev(np.zeros(32), np.zeros(32))
    assert prejudge(ev) != "stakeless"
    assert prejudge(ev) == "inconsequential"
    assert _wilson_upper(0, 32) < Q_MIN     # the bound that justifies it


def test_identical_nonzero_diffs_never_one_sided():
    """32 identical nonzero diffs: std=0, ci=0 — a gap barely above
    GAP_MAX must not be 'decisive' on a zero-width interval."""
    a = np.full(32, 110.0)                  # ~3 IMPs on every layout,
    ev = make_ev(a, np.zeros(32))           # all diffs identical
    assert prejudge(ev) != "one_sided"


def test_few_nonzero_diffs_never_one_sided():
    """4 giant swings out of 32 (< PRE_MIN_NONZERO): sigma margins are
    untrusted. The q bound may reject instead — that's decisive and
    fine; it just must not claim one_sided."""
    a = np.zeros(32)
    a[:4] = 5000.0
    ev = make_ev(a, np.zeros(32))
    assert prejudge(ev) != "one_sided"


def test_decisive_one_sided_rejects():
    """A large, consistent, dispersed advantage: gap - ci > GAP_MAX."""
    rng = np.random.default_rng(7)
    a = 600 + rng.normal(0, 50, 32)         # ~12 IMPs up on every layout
    ev = make_ev(a, np.zeros(32))
    assert prejudge(ev) == "one_sided"


def test_borderline_gap_escalates():
    """Gap around GAP_MAX but with real spread (wide ci) and plenty of
    consequence: nothing is decisive, must escalate."""
    a = np.concatenate([np.full(13, 300.0),     # +7 IMPs on 13 layouts
                        np.full(6, -100.0),     # -3 IMPs on 6
                        np.zeros(13)])
    ev = make_ev(a, np.zeros(32))
    assert prejudge(ev) is None


def test_uninteresting_bound_grants_trap_when_order_unsettled():
    """policy_top == best but the gap is NOT decisively positive: the
    trap term (20 pts) must stay granted in the optimistic bound, which
    keeps the score above THETA -> escalate rather than reject."""
    a = np.concatenate([np.full(9, 30.0),       # 1 IMP either way,
                        np.full(8, -30.0),      # near-coin-flip
                        np.zeros(15)])
    ev = make_ev(a, np.zeros(32))
    assert prejudge(ev, policy_top="A") is None


def test_wilson_upper_beats_wald():
    assert _wilson_upper(0, 32) > 0.0           # Wald gives exactly 0
    assert _wilson_upper(32, 32) == pytest.approx(1.0, abs=0.005)
    assert 0.5 < _wilson_upper(16, 32) < 0.75


# ---------------------------------------------------------------- DD memo

class FakeSolver:
    def __init__(self):
        self.calls = 0
        self.deals_solved = 0

    def solve(self, strain, leader, current_trick, hands_pbn, solutions):
        assert current_trick == [] and solutions == 1
        self.calls += 1
        self.deals_solved += len(hands_pbn)
        # deterministic tricks from content so equivalence is checkable
        return {"max": [(hash((p, strain, leader)) % 13) + 1
                        for p in hands_pbn]}


class FakeBot:
    def __init__(self, seat, solver):
        self.seat = seat
        self.ddsolver = solver


def _mk_auctions(tokens_per_row):
    """Encode rows of ben bid tokens into the padded id matrix."""
    from bidding import bidding as bb
    n = len(tokens_per_row)
    out = np.ones((n, 8), dtype=np.int32)   # 1 = PAD_END
    for i, toks in enumerate(tokens_per_row):
        for j, t in enumerate(toks):
            out[i, j] = bb.BID2ID[t]
    return out


def test_dd_memo_dedups_across_candidates():
    pytest.importorskip(
        "bidding.bidding", reason="requires the Ben checkout on sys.path")
    solver = FakeSolver()
    bot = FakeBot(seat=2, solver=solver)
    pbns = [f"deal-{i}" for i in range(6)]
    row_4h = ["1H", "PASS", "4H", "PASS", "PASS", "PASS"]
    row_4s = ["1S", "PASS", "4S", "PASS", "PASS", "PASS"]
    auc_a = _mk_auctions([row_4h] * 6)
    auc_b = _mk_auctions([row_4h] * 4 + [row_4s] * 2)

    memo = {}
    cts_a, soft_a = _tricks_dd_memo(bot, pbns, auc_a, memo)
    solved_after_a = solver.deals_solved
    cts_b, soft_b = _tricks_dd_memo(bot, pbns, auc_b, memo)

    # candidate B re-solves ONLY its two spade rows; the four rows that
    # converged to candidate A's contract come from the memo
    assert solver.deals_solved == solved_after_a + 2
    assert cts_b[:4] == cts_a[:4]

    # equivalence: a memo-less run must be bit-identical
    solver2 = FakeSolver()
    bot2 = FakeBot(seat=2, solver=solver2)
    cts_b2, soft_b2 = _tricks_dd_memo(bot2, pbns, auc_b, None)
    assert cts_b2 == cts_b
    assert np.array_equal(soft_b2, soft_b)


def test_dd_memo_pass_rows_skip_solver():
    pytest.importorskip(
        "bidding.bidding", reason="requires the Ben checkout on sys.path")
    solver = FakeSolver()
    bot = FakeBot(seat=0, solver=solver)
    auc = _mk_auctions([["PASS", "PASS", "PASS", "PASS"]])
    cts, soft = _tricks_dd_memo(bot, ["deal-0"], auc, {})
    assert cts == ["PASS"]
    assert solver.calls == 0
    assert soft.sum() == 0
