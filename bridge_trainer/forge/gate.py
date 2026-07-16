"""The instance gate (combined plan §2.2, v2 after dual review).

G1 hero-stem sanity (check_hero_stem; structurally vacuous where hero
   has no non-pass stem call — the hand class is the real guarantee),
G2 family audit predicates,
G3 dilemma test on the corrected comparison (top-2 EV gap or toss-up),
G4 stakes floor (AND rule: push_max alone never rejects),
G5 anti-lottery — stub at v0 (all P0 menus are 3 candidates).

Plus honesty layers: shortfall-manufactured toss-ups are rejected,
doubled-heavy gaps publish as flagged toss-ups (b1 #12 at the gate),
fog instances publish as toss-ups only (INV5).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..app.runner import RunResult
from ..validate.trees import check_hero_stem
from .family import FamilySpec, hero_features

DEFAULT_DELTA_IMPS = 3.0     # per-family override / calibration refines
SHORTFALL_CI_WIDEN_MAX = 1.25
DOUBLED_SHARE_MAX = 0.6
DEAD_OPTION_SHARE = 0.005    # strictly-best on <0.5% of layouts


@dataclass
class GateDecision:
    accepted: bool
    reason: str                    # "accepted" or rejection tag
    verdict: str                   # best call, "" when toss-up
    toss_up: bool = False
    toss_up_with: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    measured: dict = field(default_factory=dict)
    dead_options: list[dict] = field(default_factory=list)


def check_hand(family: FamilySpec, hand: str) -> str | None:
    """G1+G2, no simulation. Returns rejection tag or None."""
    warnings = check_hero_stem(
        family.problem.dealer, family.stem_tokens(),
        family.problem.my_seat, hero_features(hand))
    if warnings:
        return f"hero_stem: {warnings[0]}"
    reason = family.audit_hand(hand)
    if reason is not None:
        return f"audit: {reason}"
    return None


def _stakes_and_push(result: RunResult, a: str, b: str) -> tuple[float, float]:
    """E|per-deal top-2 IMP swing| and weighted push probability."""
    diff = result.corrected.imp_matrix[(a, b)]
    w = np.array([wd.weight for wd in result.deals], dtype=float)
    w = w / w.sum()
    stakes = float(np.abs(diff) @ w)
    push = float((diff == 0) @ w)
    return stakes, push


def _doubled_share(result: RunResult, a: str, b: str) -> float:
    """Share of the top-2 gap carried by doubled-terminal layouts."""
    diff = np.abs(result.corrected.imp_matrix[(a, b)]).astype(float)
    w = np.array([wd.weight for wd in result.deals], dtype=float)
    contribution = diff * w
    total = float(contribution.sum())
    if total <= 0:
        return 0.0
    doubled = np.array(
        [ca.doubled or cb.doubled
         for ca, cb in zip(result.contracts_by_candidate[a],
                           result.contracts_by_candidate[b])])
    return float(contribution[doubled].sum() / total)


def _dead_options(result: RunResult) -> list[dict]:
    """Options strictly best on ~no layout (post-answer annotation only —
    the menu is never silently shrunk; combined plan §2.4)."""
    scores = result.corrected_scores
    actions = list(scores)
    stacked = np.stack([scores[a] for a in actions])   # (A, n)
    w = np.array([wd.weight for wd in result.deals], dtype=float)
    w = w / w.sum()
    best = stacked.max(axis=0)
    out = []
    for i, a in enumerate(actions):
        strictly = (stacked[i] >= best) & (
            (stacked > stacked[i] - 1e-9).sum(axis=0) == 1)
        share = float(strictly @ w)
        if share < DEAD_OPTION_SHARE:
            out.append({"call": a, "best_share": round(share, 4)})
    return out


def evaluate_gate(result: RunResult, family: FamilySpec) -> GateDecision:
    """G3-G5 + honesty layers, on a finished full-sim RunResult."""
    comp = result.corrected
    top = comp.candidates[0]
    best, second = top.action, top.best_alternative
    gap = float(top.ev_vs_best_alt)
    delta = family.delta_imps if family.delta_imps is not None else DEFAULT_DELTA_IMPS
    stakes, push = _stakes_and_push(result, best, second)
    doubled_share = _doubled_share(result, best, second)
    shortfall_bad = result.diagnostics.shortfall and result.ci_widen > SHORTFALL_CI_WIDEN_MAX

    measured = {
        "gap_imps": round(gap, 3),
        "ci_half_width": round(float(top.ci_half_width), 3),
        "delta_imps": delta,
        "stakes": round(stakes, 3),
        "push": round(push, 3),
        "doubled_share": round(doubled_share, 3),
        "ci_widen": round(float(result.ci_widen), 3),
        "shortfall": bool(result.diagnostics.shortfall),
        "in_dd_fog": bool(result.in_dd_fog),
        "top2": [best, second],
    }

    def reject(reason: str) -> GateDecision:
        return GateDecision(accepted=False, reason=reason, verdict="",
                            measured=measured)

    # G4 stakes floor (AND rule: push alone never rejects).
    if stakes < family.stakes_min:
        return reject("stakeless")

    toss_up = comp.toss_up or result.in_dd_fog
    toss_up_with = list(comp.toss_up_with)
    if result.in_dd_fog and second not in toss_up_with and toss_up:
        toss_up_with = toss_up_with or [second]

    # G3 dilemma test.
    if not toss_up and gap > delta:
        return reject("one_sided")
    # Shortfall-manufactured toss-ups (widened CIs) are not dilemmas.
    if toss_up and not comp.verdict and shortfall_bad:
        return reject("shortfall_tossup")

    flags = []
    if push > family.push_max:
        flags.append("high_push")
    if result.in_dd_fog:
        flags.append("dd_fog")
    if result.diagnostics.shortfall:
        flags.append("shortfall")

    # Doubled-heavy gaps: publish as flagged toss-up, never a single winner.
    if doubled_share > DOUBLED_SHARE_MAX and not toss_up:
        toss_up, toss_up_with = True, [second]
        flags.append("doubled_heavy")
    elif doubled_share > DOUBLED_SHARE_MAX:
        flags.append("doubled_heavy")

    verdict = "" if toss_up else best
    # never_verdict (e.g. a forcing-pass violation is never crowned).
    if verdict and verdict in family.never_verdict:
        return reject("never_verdict")

    return GateDecision(
        accepted=True, reason="accepted",
        verdict=verdict, toss_up=toss_up, toss_up_with=toss_up_with,
        flags=flags, measured=measured, dead_options=_dead_options(result))
