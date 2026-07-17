"""Verdict gate on Ben's paired candidate evaluation (docs/
ben_execution_plan.md §3.2 + v2 amendments 3, 5, 7, 10).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from ..scoring.tables import imps

GAP_MAX = 2.5           # accept band (IMPs)
CI_MAX = 1.5            # evidence cap: wider than this = insufficient evidence
N_MIN = 100             # minimum samples
STAKES_MIN = 0.5        # E|top-2 per-sample IMP swing|
TOSS_UP_IMPS = 0.5
EQUIV_TV = 0.15         # contract-distribution total-variation floor
EQUIV_GAP = 0.5
DOUBLED_SHARE_MAX = 0.40
DEAD_SHARE = 0.005


@dataclass
class Verdict:
    accepted: bool
    reason: str
    best: str = ""
    toss_up: bool = False
    toss_up_with: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    measured: dict = field(default_factory=dict)
    table: list = field(default_factory=list)   # per-candidate evidence rows
    dead: list = field(default_factory=list)


def _imp_diff(ev_a: np.ndarray, ev_b: np.ndarray) -> np.ndarray:
    return np.array([imps(float(d)) for d in (ev_a - ev_b)])


def _tv_distance(ca: list, cb: list) -> float:
    fa, fb = Counter(ca), Counter(cb)
    keys = set(fa) | set(fb)
    na, nb = len(ca), len(cb)
    return 0.5 * sum(abs(fa[k] / na - fb[k] / nb) for k in keys)


def judge(ev) -> Verdict:
    """ev: engine.ben.Evaluation for the scanner's candidate list."""
    bids = sorted(ev.bids, key=lambda b: -float(ev.ev[b].mean()))
    n = ev.n_samples
    best, second = bids[0], bids[1]
    diff = _imp_diff(ev.ev[best], ev.ev[second])
    gap = float(diff.mean())
    ci = float(1.96 * diff.std() / np.sqrt(max(n, 1)))
    stakes = float(np.abs(diff).mean())

    doubled = np.array([("X" in ca[1:-1]) or ("X" in cb[1:-1])
                        for ca, cb in zip(ev.contracts[best],
                                          ev.contracts[second])])
    weight = np.abs(diff)
    doubled_share = float(weight[doubled].sum() / weight.sum()) \
        if weight.sum() > 0 else 0.0

    # per-candidate evidence table + dead options + winner shares
    stacked = np.stack([ev.ev[b] for b in bids])
    best_per_sample = stacked.max(axis=0)
    table, dead, winner_share = [], [], {}
    for i, b in enumerate(bids):
        d = _imp_diff(ev.ev[b], ev.ev[best if b != best else second])
        strictly = (stacked[i] >= best_per_sample) & (
            (stacked > stacked[i] - 1e-9).sum(axis=0) == 1)
        share = float(strictly.mean())
        winner_share[b] = share
        row = {
            "bid": b,
            "ev_imp_vs_top": round(float(d.mean()), 2) if b != best else 0.0,
            "ci": round(float(1.96 * d.std() / np.sqrt(max(n, 1))), 2),
            "p_gain": round(float((d > 0).mean()), 3),
            "p_push": round(float((d == 0).mean()), 3),
            "best_share": round(share, 3),
            "top_contracts": Counter(ev.contracts[b]).most_common(3),
        }
        table.append(row)
        if share < DEAD_SHARE:
            dead.append({"bid": b, "best_share": round(share, 4)})

    measured = {
        "n_samples": n, "quality": round(ev.quality, 2),
        "gap_imps": round(gap, 2), "ci": round(ci, 2),
        "stakes": round(stakes, 2), "doubled_share": round(doubled_share, 2),
        "top2": [best, second],
    }

    def reject(reason):
        return Verdict(False, reason, measured=measured, table=table)

    # evidence floors (rec 3) — thin evidence is never a toss-up
    if n < N_MIN:
        return reject("insufficient_samples")
    # clear rejections need no precision: a huge gap is one-sided even
    # with a wide CI; the CI cap guards only would-be acceptances
    if gap > GAP_MAX and gap - ci > GAP_MAX:
        return reject("one_sided")
    if stakes < STAKES_MIN:
        return reject("stakeless")
    if ci > CI_MAX:
        return reject("insufficient_evidence")
    # equivalence discard (rec 5)
    if gap < EQUIV_GAP and _tv_distance(ev.contracts[best],
                                        ev.contracts[second]) < EQUIV_TV:
        return reject("equivalent_options")
    # anti-lottery (rec 5 generalized)
    if len(bids) >= 4:
        pair_close = all(
            abs(float(_imp_diff(ev.ev[a], ev.ev[b]).mean())) <= TOSS_UP_IMPS
            for i, a in enumerate(bids) for b in bids[i + 1:])
        shares = sorted(winner_share.values(), reverse=True)
        if pair_close and shares[0] < 0.4:
            return reject("pure_guess")
    if gap > GAP_MAX:
        return reject("one_sided")

    toss_up = gap <= max(ci, TOSS_UP_IMPS)
    toss_up_with = []
    if toss_up:
        for b in bids[1:]:
            d = float(_imp_diff(ev.ev[best], ev.ev[b]).mean())
            dci = float(1.96 * _imp_diff(ev.ev[best], ev.ev[b]).std()
                        / np.sqrt(n))
            if d <= max(dci, TOSS_UP_IMPS):
                toss_up_with.append(b)

    flags = []
    if doubled_share > DOUBLED_SHARE_MAX:
        flags.append("doubled_heavy")
        if not toss_up:
            toss_up, toss_up_with = True, [second]  # INV5-style containment
    return Verdict(True, "accepted", best=best, toss_up=toss_up,
                   toss_up_with=toss_up_with, flags=flags,
                   measured=measured, table=table, dead=dead)
