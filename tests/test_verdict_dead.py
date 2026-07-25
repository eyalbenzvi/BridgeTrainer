"""Dead-option determination: "won a layout" includes TIES for the
per-sample best result.

Regression for ben1-19f939859fa: 3S tied Pass's winning result (both end
in the same 3S contract) on every layout where 3S beat the 4S winner, so
under the old strictly-UNIQUE winner share 3S was published as dead
(best_share 0.004) and scored 0 — while Pass, strictly worse by EV, kept
a normal score. An option that reaches the winning result on half the
layouts is not dead, even if it never wins alone.
"""
from __future__ import annotations

import numpy as np

from bridge_trainer.engine.ben import Evaluation
from bridge_trainer.engine.verdict import judge


def _ev(cols: dict, contracts: dict) -> Evaluation:
    bids = list(cols)
    n = len(next(iter(cols.values())))
    return Evaluation(
        bids=bids,
        ev={b: np.asarray(cols[b], float) for b in bids},
        contracts={b: list(contracts[b]) for b in bids},
        auctions={b: [""] * n for b in bids},
        n_samples=n, quality=1.0)


POLICY = {"W": 0.44, "T": 0.45, "D": 0.10, "Z": 0.01}


def _board(n=160):
    """W (winner, bids game) vs T (the tempting partscore raise) vs D (a
    pass-like underbid) vs Z (a hopeless call). T and D score IDENTICALLY
    on every layout W loses — the same final contract — so T is never the
    strictly-unique per-sample winner, exactly the reported shape. D alone
    is unique-best on a few layouts. EV order: W > T > D > Z."""
    W = np.zeros(n)
    W[:60] = 250.0          # game makes on 60 layouts
    W[60:96] = -100.0       # goes down on 36
    T = np.zeros(n)         # the partscore result, everywhere
    D = np.zeros(n)
    D[:60] = -50.0          # underbid misses the game layouts
    D[60:70] = 30.0         # but is alone on top of 10 layouts
    Z = np.full(n, -300.0)  # never ties the best result anywhere
    cW = np.array(["4SS"] * 96 + ["3SS"] * (n - 96))
    perm = np.random.default_rng(20260725).permutation(n)
    cols = {"W": W[perm], "T": T[perm], "D": D[perm], "Z": Z[perm]}
    contracts = {"W": list(cW[perm]), "T": ["3SS"] * n,
                 "D": ["2SS"] * n, "Z": ["2SS"] * n}
    return cols, contracts


def test_tied_winner_is_not_dead():
    cols, contracts = _board()
    v = judge(_ev(cols, contracts), policy_top="T", hero_i=0,
              policy_map=POLICY)
    assert v.accepted and v.best == "W"
    dead = {d["bid"] for d in v.dead}
    # T ties the per-sample best on ~56% of layouts (W's losses + pushes):
    # alive, despite never being the unique winner
    assert "T" not in dead
    assert "D" not in dead
    # a call that never even ties the best result stays dead
    assert dead == {"Z"}
    # the published share counts tied wins, so it matches the flag
    rows = {r["bid"]: r for r in v.table}
    assert rows["T"]["best_share"] > 0.5
    assert rows["Z"]["best_share"] == 0.0
    # and the EV ordering the user sees stays coherent with deadness:
    # T is closer to best than D, and neither is pinned
    assert rows["T"]["ev_imp_vs_top"] > rows["D"]["ev_imp_vs_top"]


def test_forge_and_migration_agree_on_deadness():
    """A call that ties the ACCEPTED call's result — on layouts where some
    THIRD call is better, so it never ties the per-sample best — used to be
    pinned dead by the forge and un-pinned by `trainer pool backfill-dead` on
    the very next migration run. The forge now uses the migration's test
    (p_gain + p_push, the row's own evidence), so stored deadness is stable."""
    from bridge_trainer.pool.firestore_store import vet_dead_options

    cols, contracts = _board()
    n = len(cols["W"])
    # C matches W exactly on the 36 layouts where W's game goes down (both
    # -100) and is worse everywhere else; it is never the per-sample best,
    # since T or D reach 0/30 on those same layouts.
    cols = dict(cols, C=np.full(n, -100.0))
    contracts = dict(contracts, C=["2SS"] * n)
    v = judge(_ev(cols, contracts), policy_top="T", hero_i=0,
              policy_map={**POLICY, "C": 0.01})
    assert v.accepted and v.best == "W"
    rows = {r["bid"]: r for r in v.table}
    assert rows["C"]["best_share"] == 0.0          # never the per-sample best
    assert rows["C"]["p_gain"] + rows["C"]["p_push"] > 0.2   # ... but matches W
    dead = {d["bid"] for d in v.dead}
    assert "C" not in dead and dead == {"Z"}
    # and the migration confirms every flag the forge emits
    kept, stale = vet_dead_options({"accepted": v.best, "table": v.table,
                                    "dead_options": v.dead})
    assert stale == [] and len(kept) == len(v.dead)
