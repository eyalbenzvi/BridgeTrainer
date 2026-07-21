"""Verdict gate on Ben's paired candidate evaluation (docs/
ben_execution_plan.md §3.2 + v2 amendments 3, 5, 7, 10).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from ..scoring.tables import imps

GAP_MAX = 2.5           # accept band (IMPs)
MIN_WINNER_GAP = 0.3    # IMPs the EV-best call must clear the runner-up by;
                        # below this the deal has no clear resolution and is
                        # rejected. The EV gap is the sole arbiter — win rate
                        # never overrules it.
CI_MAX = 1.5            # evidence cap: wider than this = insufficient evidence
N_MIN = 100             # minimum samples
STAKES_MIN = 0.5        # E|top-2 per-sample IMP swing|
TOSS_UP_IMPS = 0.5
EQUIV_TV = 0.15         # contract-distribution total-variation floor
EQUIV_GAP = 0.5
DOUBLED_SHARE_MAX = 0.40
DEAD_SHARE = 0.005

# Selectivity layer (expert review, docs/panel/selectivity_r1.md):
# the honesty gates above answer "is the evidence sound?"; the interest
# score answers "is this worth a serious player's minute?"
Q_MIN = 0.40            # consequence floor: P(choice changes the result)
THETA = 80.0            # calibrated 2026-07-17: 12/100 fresh boards
TRAP_GAP_MIN = 0.8      # policy-argmax loses by at least this => trap
UNSTABLE_DELTA = 15.0   # split-half interest drift => DD-noise harvest

# Prescreen cascade (speedup review): decisive-rejection margins on a
# 32-sample slice of the screen pool. Only REJECTIONS may be decided
# here; anything non-decisive escalates to the unchanged 128-sample
# judge, so precision is untouched and only recall is at stake.
PRE_MIN_N = 16          # below this the slice can't be decisive at all
PRE_MIN_NONZERO = 5     # sigma-based margins need dispersion: an all-push
                        # slice has std=0 and a CLT bound is meaningless
PRE_Z = 2.04            # t(31) instead of 1.96: n=32 tails
PRE_TV_ALLOW = 0.15     # optimistic TV allowance (TV is biased UP at
                        # small n, so +allowance is doubly conservative)


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


class _EvalView:
    """A sample-slice view of an Evaluation (for split-half checks)."""

    def __init__(self, ev, sl: slice):
        self.bids = ev.bids
        self.ev = {b: ev.ev[b][sl] for b in ev.bids}
        self.contracts = {b: ev.contracts[b][sl] for b in ev.bids}


def _tv_distance(ca: list, cb: list) -> float:
    fa, fb = Counter(ca), Counter(cb)
    keys = set(fa) | set(fb)
    na, nb = len(ca), len(cb)
    return 0.5 * sum(abs(fa[k] / na - fb[k] / nb) for k in keys)


def _contract_side(contract: str, hero_i: int):
    """0 = hero's side declares, 1 = theirs, None = passed out."""
    if contract.upper() == "PASS":
        return None
    return ("NESW".index(contract[-1]) - hero_i) % 2


def _contract_class(contract: str) -> str:
    if contract.upper() == "PASS":
        return "pass"
    level, strain = int(contract[0]), contract[1]
    if level >= 6:
        return "slam"
    if (strain == "N" and level >= 3) or (strain in "HS" and level >= 4) \
            or (strain in "CD" and level >= 5):
        return "game"
    return "partscore"


def _interest_ref(bids, best, policy_map, fallback):
    """The interest REFERENCE: the call the student is most likely to pick
    instead of the EV-winner — the highest-policy alternative — rather than
    the 2nd-best by EV.

    Anchoring interest to policy (what a player would actually be tempted by)
    instead of to EV rank decouples the score from the SIZE of the candidate
    set: lowering the option threshold surfaces more low-policy calls, but
    none of them can displace the reference, so a genuinely instructive
    board keeps the same interest score whether it shows 2 options or 6.
    Falls back to the EV runner-up when no policy is available (unit tests,
    legacy callers)."""
    if policy_map:
        alts = [b for b in bids if b != best]
        if alts:
            return max(alts, key=lambda b: policy_map.get(b, 0.0))
    return fallback


def _interest(diff, doubled, ev, best, ref, hero_i, policy_top, gap):
    """The 0-120 interest score (selectivity review, stage 2).

    ``diff``/``doubled``/``gap``/``ref`` are all taken relative to the
    interest reference (``_interest_ref``), not the EV runner-up."""
    from collections import Counter as _C
    q = float((diff != 0).mean())
    w4 = ((np.abs(diff) >= 4).astype(float) * np.where(doubled, 0.5, 1.0))
    p4 = float(w4.mean())
    tv = _tv_distance(ev.contracts[best], ev.contracts[ref])
    if hero_i is not None:
        flips = [
            (_contract_side(a, hero_i) != _contract_side(b, hero_i))
            for a, b in zip(ev.contracts[best], ev.contracts[ref])]
        flip = float(np.mean(flips))
    else:
        flip = 0.0
    modal_b = _C(ev.contracts[best]).most_common(1)[0][0]
    modal_s = _C(ev.contracts[ref]).most_common(1)[0][0]
    span = _contract_class(modal_b) != _contract_class(modal_s)
    trap = (policy_top is not None and policy_top != best
            and gap >= TRAP_GAP_MIN)
    damage = max(float(ev.ev[b].mean()) for b in ev.bids) < 0

    score = (30 * min(q / 0.80, 1) + 25 * min(p4 / 0.35, 1)
             + 15 * min(tv / 0.60, 1) + 10 * (flip >= 0.25)  # span=10 keeps
             # the pure thin-game archetype (30+25+15+10=80) exactly at THETA
             + 10 * span + 20 * trap + 12 * damage)
    return score, {"q": round(q, 3), "p4": round(p4, 3), "tv": round(tv, 3),
                   "flip": round(flip, 3), "span": bool(span),
                   "trap": bool(trap), "damage": bool(damage),
                   "interest": round(score, 1)}


def judge(ev, policy_top: str | None = None,
          hero_i: int | None = None,
          policy_map: dict | None = None) -> Verdict:
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
            # the winner's row compares to the NEXT-best option, never to
            # itself (owner r5 #2)
            "ev_imp_vs_top": round(float(d.mean()), 2),
            "vs": second if b == best else best,
            "ci": round(float(1.96 * d.std() / np.sqrt(max(n, 1))), 2),
            "p_gain": round(float((d > 0).mean()), 3),
            "p_loss": round(float((d < 0).mean()), 3),
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

    # ---- selectivity layer (stage 1 + 2): consequence + interest -------
    # The interest layer is measured against the REFERENCE call — the
    # highest-policy alternative to the winner (what the student is most
    # tempted to bid) — not the EV runner-up. This makes the score
    # invariant to the candidate-set size: extra low-policy options (from a
    # lower option threshold) never become the reference and so never shift
    # which board qualifies. The honesty/unique-winner gates above stay on
    # the EV pair (best vs second), which is what they are about.
    ref = _interest_ref(bids, best, policy_map, second)
    idiff = _imp_diff(ev.ev[best], ev.ev[ref])
    igap = float(idiff.mean())
    idoubled = np.array([("X" in ca[1:-1]) or ("X" in cb[1:-1])
                         for ca, cb in zip(ev.contracts[best],
                                           ev.contracts[ref])])
    measured["interest_vs"] = ref
    score, interest = _interest(idiff, idoubled, ev, best, ref,
                                hero_i, policy_top, igap)
    measured.update(interest)
    if interest["q"] < Q_MIN:
        return reject("inconsequential")
    if score < THETA:
        return reject("uninteresting")
    # split-half stability: an interest score that flips between sample
    # halves is harvesting DD variance, not bridge
    half = len(idiff) // 2
    s1, _ = _interest(idiff[:half], idoubled[:half],
                      _EvalView(ev, slice(0, half)), best, ref,
                      hero_i, policy_top, igap)
    s2, _ = _interest(idiff[half:], idoubled[half:],
                      _EvalView(ev, slice(half, None)), best, ref,
                      hero_i, policy_top, igap)
    if abs(s1 - s2) > UNSTABLE_DELTA and min(s1, s2) < THETA:
        return reject("unstable_interest")

    # ---- single-winner rule (owner r3 #2): every published deal has ----
    # exactly one winner; near-identical options reject the deal.
    if doubled_share > DOUBLED_SHARE_MAX:
        return reject("doubled_heavy")   # no toss-up downgrade anymore
    pg = float((diff > 0).mean())        # top beats second, per layout
    pl = float((diff < 0).mean())
    measured["p_top_wins"] = round(pg, 3)
    measured["p_second_wins"] = round(pl, 3)
    # The EV gap is the sole arbiter of the winner: the EV-best call must
    # clear the runner-up by at least MIN_WINNER_GAP IMPs. A thinner edge
    # has no clear resolution, so the deal is rejected — win rate never
    # promotes the runner-up over the EV edge anymore.
    if gap < MIN_WINNER_GAP:
        return reject("no_clear_winner")
    winner = best
    measured["winner_by"] = f"EV gap >= {MIN_WINNER_GAP} IMPs"
    # A winner the engine itself would almost never choose is suspect —
    # likely a rollout artifact, and bad teaching (owner r5 #1).
    if policy_map is not None and policy_map.get(winner, 0.0) < 0.15:
        return reject("implausible_winner")

    # split-half evidence snapshots: difficulty.py stabilizes level labels
    # near bucket cut points with these (median-of-three rule)
    measured["half_stats"] = [
        {"gap_imps": round(float(d.mean()), 2),
         "p_top_wins": round(float((d > 0).mean()), 3),
         "p_second_wins": round(float((d < 0).mean()), 3)}
        for d in (diff[:half], diff[half:])]

    flags = []
    return Verdict(True, "accepted", best=winner, toss_up=False,
                   toss_up_with=[], flags=flags,
                   measured=measured, table=table, dead=dead)


def _wilson_upper(k: int, n: int, z: float = PRE_Z) -> float:
    """Wilson score upper bound for a binomial proportion (Wald
    undercovers badly at small n / extreme p-hat; k=0 stays non-zero)."""
    if n <= 0:
        return 1.0
    p = k / n
    z2 = z * z
    center = p + z2 / (2 * n)
    half = z * np.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return float((center + half) / (1 + z2 / n))


def prejudge(ev, policy_top: str | None = None,
             hero_i: int | None = None,
             policy_map: dict | None = None) -> str | None:
    """Decisive-rejection prescreen on a small sample slice.

    Returns a rejection reason only when the full 128-sample judge's
    outcome is already statistically settled; returns None ("escalate")
    otherwise. Two families of bounds, deliberately kept apart:

    - sigma-based margins (one_sided, stakeless) use the sample std and
      are trusted only with PRE_MIN_NONZERO nonzero diffs — IMP diffs
      are spiky (mostly 0, occasionally 10+), and an all-push slice has
      std=0, which would make any CLT "upper bound" vacuous;
    - binomial bounds (q, p4, flip) use the Wilson upper bound, which is
      valid at k=0: 0 nonzero diffs out of 32 genuinely is decisive
      evidence that q < 0.40 (a true-q>=0.40 board shows all-push with
      probability 0.6^32 ~ 1e-7).

    The caller evaluates the FULL candidate list here (not just the top
    two), so ``best``/``second``/``ref`` match the 128-sample judge's own
    pairs and every bound is a genuine upper bound on the same quantity —
    the decisive-rejection guarantee holds under any option threshold.
    The EV pair (best, second) drives one_sided/stakeless; the interest
    bounds use the policy reference ``ref`` exactly as ``judge`` does.
    """
    n = ev.n_samples
    if n < PRE_MIN_N:
        return None
    bids = sorted(ev.bids, key=lambda b: -float(ev.ev[b].mean()))
    best, second = bids[0], bids[1]
    diff = _imp_diff(ev.ev[best], ev.ev[second])
    gap = float(diff.mean())
    ci = float(PRE_Z * diff.std() / np.sqrt(n))
    nonzero = int((diff != 0).sum())
    # sigma margins also need VARIETY: 32 identical nonzero diffs have
    # std=0, and a zero-width CI proves nothing about the 128-sample tail
    distinct = len(set(np.round(diff[diff != 0], 6).tolist()))
    dispersion_ok = nonzero >= PRE_MIN_NONZERO and distinct >= 2

    if dispersion_ok and gap - ci > GAP_MAX:
        return "one_sided"
    if dispersion_ok:
        absd = np.abs(diff)
        stakes_hi = float(absd.mean() + PRE_Z * absd.std() / np.sqrt(n))
        if stakes_hi < STAKES_MIN:
            return "stakeless"

    # interest reference (matches judge): winner vs highest-policy alt
    ref = _interest_ref(bids, best, policy_map, second)
    idiff = _imp_diff(ev.ev[best], ev.ev[ref])
    inonzero = int((idiff != 0).sum())

    q_hi = _wilson_upper(inonzero, n)
    if q_hi < Q_MIN:
        return "inconsequential"

    # optimistic upper bound of the interest score: every term takes its
    # most favorable defensible value; only a bound that STILL cannot
    # reach THETA is decisive. span and damage are granted outright
    # unless excluded with their own margin; trap (20 pts) is denied only
    # when the ordering is decisively settled in policy_top's favor.
    # p4's doubled-discount weights are <= 1, so the plain count bounds
    # the weighted mean from above
    k4 = int((np.abs(idiff) >= 4).sum())
    p4_hi = _wilson_upper(k4, n)
    tv = _tv_distance(ev.contracts[best], ev.contracts[ref])
    tv_hi = min(1.0, tv + PRE_TV_ALLOW)
    if hero_i is not None:
        flips = int(sum(
            _contract_side(a, hero_i) != _contract_side(b, hero_i)
            for a, b in zip(ev.contracts[best], ev.contracts[ref])))
        flip_hi = _wilson_upper(flips, n)
    else:
        flip_hi = 0.0
    trap_denied = (policy_top is not None and policy_top == best
                   and dispersion_ok and gap - ci > 0)
    damage_lo = max(float(ev.ev[b].mean()) -
                    PRE_Z * float(ev.ev[b].std()) / np.sqrt(n)
                    for b in ev.bids)
    damage_denied = damage_lo > 0     # best EV decisively positive
    score_hi = (30 * min(q_hi / 0.80, 1) + 25 * min(p4_hi / 0.35, 1)
                + 15 * min(tv_hi / 0.60, 1) + 10 * (flip_hi >= 0.25)
                + 10                              # span: granted
                + (0 if trap_denied else 20)
                + (0 if damage_denied else 12))
    if score_hi < THETA:
        return "uninteresting"
    return None
