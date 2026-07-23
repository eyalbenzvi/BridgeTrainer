"""Verdict gate for opening-lead problems, one per training mode.

The generator is SPLIT by training mode; each mode grades on its own
objective and the acceptance gates run in that mode's unit:

  MP  (Matchpoints) — the owner's original definition: every candidate lead
      is scored by the AVERAGE NUMBER OF DEFENSIVE TRICKS it yields under
      double-dummy across layouts consistent with the bidding.
  IMP               — every candidate lead is scored by its EXPECTED IMP
      VALUE, derived from the final duplicate score against the centralized
      baseline (scoring.lead_metrics.per_sample_imps).

In both modes the correct answer is every card tied for the maximum average
(touching cards land on identical values and all count), and the two
"uninteresting deal" filters are the owner's, translated to the mode's unit:

  C1  BEN's opening-lead policy on the answer set is > 50%      -> too obvious
  C2  the best card beats the best card of a DIFFERENT suit by < gap_min
      (0.25 tricks in MP; 0.5 IMPs in IMP) -> the suit choice does not matter

Everything here is pure (numpy only, no BEN import) so it is unit-tested in
normal CI, which the bidding verdict never was.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# -- the owner's two criteria (MP unit: double-dummy tricks) ------------------
P_OBVIOUS = 0.50        # C1: BEN policy mass on the answer set above this = no problem
GAP_MIN = 0.25          # C2: best minus best-different-suit, in DD tricks

# -- mechanical guards (MP unit) ----------------------------------------------
N_MIN = 100             # minimum samples before any accept
TIE_EPS = 0.05          # cards within this of the max are "tied for best"
CLOSE_SUIT = 0.5        # a different suit this near the best is a live option
UNSTABLE_TRICKS = 0.30  # split-half drift in the headline gap => DD noise

# -- the IMP-mode analogues (unit: expected IMPs, not tricks) ------------------
# 0.5 IMPs matches the bidding verdict's long-standing "a thinner edge is a
# toss-up" line (engine/verdict.py, scoring/comparison.py); the other two keep
# the MP constants' proportions to GAP_MIN.
GAP_MIN_IMP = 0.5       # C2: best minus best-different-suit, in IMPs
CLOSE_IMP = 1.0         # a different suit this near the best is a live option
UNSTABLE_IMPS = 0.6     # split-half drift in the headline IMP gap => DD noise

SUITS = "SHDC"


@dataclass(frozen=True)
class ModeScale:
    """The per-mode grading unit: which per-sample values to judge on and
    the thresholds, all expressed in that unit."""
    mode: str            # "MP" | "IMP"
    gap_min: float       # C2 cross-suit gap floor
    close: float         # a different suit this near the best is "live"
    unstable: float      # split-half drift above this = DD noise
    decisive: float      # a gap this big decisively punishes a trap


MP_SCALE = ModeScale("MP", GAP_MIN, CLOSE_SUIT, UNSTABLE_TRICKS, 0.5)
IMP_SCALE = ModeScale("IMP", GAP_MIN_IMP, CLOSE_IMP, UNSTABLE_IMPS, 1.0)
SCALES = {"MP": MP_SCALE, "IMP": IMP_SCALE}


@dataclass
class LeadEvaluation:
    """Per-card double-dummy evidence on one shared sample set.

    def_tricks[card] is a per-sample array of the DEFENSE's trick count when
    that card is led; softmax[card] is BEN's opening-lead policy mass.
    """
    cards: list[str]                       # all 13 leader cards, e.g. "SK"
    def_tricks: dict                       # card -> np.ndarray (per sample)
    softmax: dict                          # card -> float
    n_samples: int
    quality: float
    contract: str                          # e.g. "4HE"
    doubled: bool = False
    sample_deals: list[str] = field(default_factory=list)


@dataclass
class LeadVerdict:
    accepted: bool
    reason: str
    best: list = field(default_factory=list)     # cards tied for the max
    difficulty: int = 0
    flags: list = field(default_factory=list)
    measured: dict = field(default_factory=dict)
    table: list = field(default_factory=list)    # per-card rows, best first


def _suit(card: str) -> str:
    return card[0]


def _imp_values(le: LeadEvaluation, vul: str) -> dict:
    """Per-sample IMP arrays for the IMP-mode gates (centralized baseline)."""
    from ..scoring.lead_metrics import per_sample_imps
    return per_sample_imps(le.def_tricks, le.contract, vul)


def _mode_values(le: LeadEvaluation, scale: ModeScale, vul: str | None) -> dict:
    if scale.mode == "MP":
        return le.def_tricks
    if vul is None:
        raise ValueError("IMP judging needs the vulnerability")
    return _imp_values(le, vul)


def _averages(values: dict) -> dict:
    return {c: float(np.mean(values[c])) for c in values}


def _best_different_suit(avg: dict, best: str) -> tuple[str | None, float]:
    """Best card whose suit differs from `best` (for criterion 2)."""
    others = [(c, v) for c, v in avg.items() if _suit(c) != _suit(best)]
    if not others:
        return None, float("-inf")
    c, v = max(others, key=lambda kv: kv[1])
    return c, v


def _difficulty(avg: dict, best_cards: list, softmax: dict, gap: float,
                scale: ModeScale) -> tuple[int, dict]:
    """1-5, built from what makes an opening lead hard for a strong human:
    a seductive-but-wrong natural lead (trap), decisively punished (gap),
    with the engine unsure of the right card and several live suits.
    Thresholds are in the mode's unit (tricks for MP, IMPs for IMP)."""
    best = best_cards[0]
    top_soft = max(softmax, key=lambda c: softmax.get(c, 0.0)) \
        if softmax else best
    trap = top_soft not in best_cards
    ben_conf_best = max((softmax.get(c, 0.0) for c in best_cards), default=0.0)
    close_suits = {_suit(c) for c, v in avg.items()
                   if v >= avg[best] - scale.close}
    n_close = len(close_suits)

    if trap and gap >= scale.decisive:
        level = 5 if (softmax.get(top_soft, 0.0) >= 0.40) else 4
    elif trap:
        level = 4
    elif n_close >= 3 or ben_conf_best < 0.20:
        level = 3
    elif gap < scale.decisive or n_close == 2:
        level = 2
    else:
        level = 1
    sub = {"trap": bool(trap), "gap": round(gap, 3),
           "ben_conf_in_best": round(ben_conf_best, 3),
           "n_close_suits": n_close,
           "top_softmax_card": top_soft,
           "top_softmax": round(softmax.get(top_soft, 0.0), 3)}
    return level, sub


def _table(le: LeadEvaluation, softmax: dict) -> list:
    """Per-card rows, best-first BY TRICKS. The table's avg_def_tricks /
    vs_best columns are always trick-denominated (they feed the shared
    record shape and legacy readers); mode-specific ranks are added on top
    by the record builder."""
    avg = _averages(le.def_tricks)
    best_avg = max(avg.values())
    rows = []
    for c in sorted(avg, key=lambda c: -avg[c]):
        rows.append({
            "card": c,
            "avg_def_tricks": round(avg[c], 3),
            "vs_best": round(avg[c] - best_avg, 3),
            "ben_softmax": round(softmax.get(c, 0.0), 3),
        })
    return rows


def prejudge_lead_values(le: LeadEvaluation, values: dict,
                         scale: ModeScale) -> str | None:
    """Decisive early rule-out for the screening cascade (32 → 64 → full),
    in the mode's unit.

    Returns a rejection reason ONLY when we are statistically confident the
    board is uninteresting; None means "keep sampling". Conservative by
    design so it never drops a board that might still qualify:
      * obvious (C1) does not depend on the sample count.
      * suit_indifferent fires only when the 95% UPPER bound of the
        different-suit gap is still below the mode's gap_min threshold.
    """
    if le.softmax and max(le.softmax.values()) > P_OBVIOUS:
        return "obvious"
    avg = _averages(values)
    winner = max(avg, key=lambda c: avg[c])
    ds_card, _ds_val = _best_different_suit(avg, winner)
    if ds_card is None:
        return None
    diff = np.asarray(values[winner]) - np.asarray(values[ds_card])
    n = diff.shape[0]
    if n < 8:
        return None
    gap = float(diff.mean())
    se = float(diff.std()) / (n ** 0.5)
    if gap + 1.96 * se < scale.gap_min:  # confident the gap can't reach it
        return "suit_indifferent"
    return None


def prejudge_lead(le: LeadEvaluation) -> str | None:
    """MP prescreen: rule out on the double-dummy trick gap."""
    return prejudge_lead_values(le, le.def_tricks, MP_SCALE)


def prejudge_lead_imp(le: LeadEvaluation, vul: str) -> str | None:
    """IMP prescreen: rule out on the expected-IMP gap."""
    return prejudge_lead_values(le, _imp_values(le, vul), IMP_SCALE)


def prejudge_lead_mode(le: LeadEvaluation, mode: str,
                       vul: str | None = None) -> str | None:
    scale = SCALES[mode]
    return prejudge_lead_values(le, _mode_values(le, scale, vul), scale)


def judge_lead_values(le: LeadEvaluation, values: dict, scale: ModeScale,
                      force: bool = False) -> LeadVerdict:
    """The shared verdict machinery, graded on `values` (card -> per-sample
    array in the mode's unit). judge_lead / judge_lead_imp are the public
    per-mode entry points."""
    avg = _averages(values)
    best_avg = max(avg.values())
    best_cards = [c for c in le.cards if avg[c] >= best_avg - TIE_EPS]
    # a stable, suit-then-rank order for the accepted set
    best_cards.sort(key=lambda c: (SUITS.index(_suit(c)), le.cards.index(c)))
    winner = max(avg, key=lambda c: avg[c])
    table = _table(le, le.softmax)

    _, ds_val = _best_different_suit(avg, winner)
    gap = best_avg - ds_val
    diff_level, sub = _difficulty(avg, best_cards, le.softmax, gap, scale)
    measured = {
        "n_samples": le.n_samples,
        "quality": round(float(le.quality), 3),
        "mode": scale.mode,
        "gap": round(gap, 3),
        "doubled": bool(le.doubled),
        **sub,
    }
    # the best average, named by its unit (best_avg_tricks kept for MP so
    # existing records/readers see the same key as before the split)
    measured["best_avg_tricks" if scale.mode == "MP"
             else "best_avg_imps"] = round(best_avg, 3)

    def reject(reason: str) -> LeadVerdict:
        return LeadVerdict(False, reason, best=best_cards, difficulty=diff_level,
                           measured=measured, table=table)

    # force=True: caller wants this board accepted regardless of the
    # "interesting" gates (used for the lead_doubled category, where the
    # defining feature is the doubled contract, not suit-choice tension —
    # the C1 (P_OBVIOUS) and C2 gap rules deliberately do not apply). The
    # best-card set and difficulty are still the real double-dummy grade.
    if force:
        return LeadVerdict(True, "accepted", best=best_cards,
                           difficulty=diff_level, flags=["accept_forced"],
                           measured=measured, table=table)

    # ---- mechanical evidence floor -------------------------------------
    if le.n_samples < N_MIN:
        return reject("insufficient_samples")

    # NOTE: doubled contracts are no longer excluded — they form the
    # `lead_doubled` category. Their double-dummy defense is still the least
    # realistic (Lightner/lead-directing doubles ask for a specific lead the
    # sampler can't infer from the bare X token), so treat the numbers on
    # doubled boards with more caution than undoubled ones.

    # ---- owner criterion 1: BEN too sure => obvious --------------------
    # Sum BEN's policy over the tied-best ANSWER set (deduped by 32-card lead
    # code), not just the single top card: touching honors split the mass
    # (e.g. HK 61% + HA 28% = 89% on "a top heart") yet are one decision, so a
    # single-card check wrongly passes them. Folded low spots share one code.
    from .lead_classify import answer_policy_mass
    if le.softmax and answer_policy_mass(best_cards, le.softmax) > P_OBVIOUS:
        return reject("obvious")

    # ---- owner criterion 2: suit choice doesn't matter ----------------
    if gap < scale.gap_min:
        return reject("suit_indifferent")

    # ---- split-half stability on the headline gap ---------------------
    half = le.n_samples // 2
    if half >= N_MIN // 2:
        def gap_on(sl: slice) -> float:
            a = {c: float(np.mean(values[c][sl])) for c in le.cards}
            b = max(a, key=lambda c: a[c])
            _, dv = _best_different_suit(a, b)
            return a[b] - dv
        g1, g2 = gap_on(slice(0, half)), gap_on(slice(half, None))
        measured["gap_halves"] = [round(g1, 3), round(g2, 3)]
        if abs(g1 - g2) > scale.unstable and min(g1, g2) < scale.gap_min:
            return reject("unstable_tricks" if scale.mode == "MP"
                          else "unstable_imps")

    return LeadVerdict(True, "accepted", best=best_cards,
                       difficulty=diff_level, flags=[],
                       measured=measured, table=table)


def judge_lead(le: LeadEvaluation, force: bool = False) -> LeadVerdict:
    """MP verdict: grade every lead by average double-dummy defensive
    tricks (the original, pre-split behavior)."""
    return judge_lead_values(le, le.def_tricks, MP_SCALE, force)


def judge_lead_imp(le: LeadEvaluation, vul: str,
                   force: bool = False) -> LeadVerdict:
    """IMP verdict: grade every lead by its expected IMP value from the
    final duplicate score (needs the board's vulnerability name). The trick
    average never determines the accepted set here."""
    return judge_lead_values(le, _imp_values(le, vul), IMP_SCALE, force)


def judge_lead_mode(le: LeadEvaluation, mode: str, vul: str | None = None,
                    force: bool = False) -> LeadVerdict:
    """Dispatch to the mode's verdict gate ('MP' or 'IMP')."""
    scale = SCALES[mode]
    return judge_lead_values(le, _mode_values(le, scale, vul), scale, force)
