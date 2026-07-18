"""Verdict gate for opening-lead problems.

Grading is exactly the owner's definition: every candidate lead is scored by
the AVERAGE NUMBER OF DEFENSIVE TRICKS it yields under double-dummy across
layouts consistent with the bidding. The correct answer is every card tied
for the maximum average (touching cards land on identical values and all
count). Two "uninteresting deal" filters, both the owner's:

  C1  BEN's opening-lead policy puts > 70% on any single card  -> too obvious
  C2  the best card beats the best card of a DIFFERENT suit by < 0.25 tricks
      -> the suit choice does not really matter

Everything here is pure (numpy only, no BEN import) so it is unit-tested in
normal CI, which the bidding verdict never was.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# -- the owner's two criteria ------------------------------------------------
P_OBVIOUS = 0.70        # C1: max lead-policy mass above this = no problem
GAP_MIN = 0.25          # C2: best minus best-different-suit, in DD tricks

# -- mechanical guards -------------------------------------------------------
N_MIN = 100             # minimum samples before any accept
TIE_EPS = 0.05          # cards within this of the max are "tied for best"
CLOSE_SUIT = 0.5        # a different suit this near the best is a live option
UNSTABLE_TRICKS = 0.30  # split-half drift in the headline gap => DD noise

SUITS = "SHDC"


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


def _averages(le: LeadEvaluation) -> dict:
    return {c: float(np.mean(le.def_tricks[c])) for c in le.cards}


def _best_different_suit(avg: dict, best: str) -> tuple[str | None, float]:
    """Best card whose suit differs from `best` (for criterion 2)."""
    others = [(c, v) for c, v in avg.items() if _suit(c) != _suit(best)]
    if not others:
        return None, float("-inf")
    c, v = max(others, key=lambda kv: kv[1])
    return c, v


def _difficulty(avg: dict, best_cards: list, softmax: dict,
                gap: float) -> tuple[int, dict]:
    """1-5, built from what makes an opening lead hard for a strong human:
    a seductive-but-wrong natural lead (trap), decisively punished (gap),
    with the engine unsure of the right card and several live suits."""
    best = best_cards[0]
    top_soft = max(softmax, key=lambda c: softmax.get(c, 0.0)) \
        if softmax else best
    trap = top_soft not in best_cards
    ben_conf_best = max((softmax.get(c, 0.0) for c in best_cards), default=0.0)
    close_suits = {_suit(c) for c, v in avg.items()
                   if v >= avg[best] - CLOSE_SUIT}
    n_close = len(close_suits)

    if trap and gap >= 0.5:
        level = 5 if (softmax.get(top_soft, 0.0) >= 0.40) else 4
    elif trap:
        level = 4
    elif n_close >= 3 or ben_conf_best < 0.20:
        level = 3
    elif gap < 0.5 or n_close == 2:
        level = 2
    else:
        level = 1
    sub = {"trap": bool(trap), "gap": round(gap, 3),
           "ben_conf_in_best": round(ben_conf_best, 3),
           "n_close_suits": n_close,
           "top_softmax_card": top_soft,
           "top_softmax": round(softmax.get(top_soft, 0.0), 3)}
    return level, sub


def _table(avg: dict, best_avg: float, softmax: dict) -> list:
    rows = []
    for c in sorted(avg, key=lambda c: -avg[c]):
        rows.append({
            "card": c,
            "avg_def_tricks": round(avg[c], 3),
            "vs_best": round(avg[c] - best_avg, 3),
            "ben_softmax": round(softmax.get(c, 0.0), 3),
        })
    return rows


def prejudge_lead(le: LeadEvaluation) -> str | None:
    """Decisive early rule-out for the screening cascade (32 → 64 → full).

    Returns a rejection reason ONLY when we are statistically confident the
    board is uninteresting; None means "keep sampling". Conservative by
    design so it never drops a board that might still qualify:
      * obvious (C1) and doubled don't depend on the sample count.
      * suit_indifferent fires only when the 95% UPPER bound of the
        different-suit gap is still below the 0.25-trick threshold.
    """
    if le.softmax and max(le.softmax.values()) > P_OBVIOUS:
        return "obvious"
    if le.doubled:
        return "doubled_excluded"
    avg = _averages(le)
    winner = max(avg, key=lambda c: avg[c])
    ds_card, _ds_val = _best_different_suit(avg, winner)
    if ds_card is None:
        return None
    diff = np.asarray(le.def_tricks[winner]) - np.asarray(le.def_tricks[ds_card])
    n = diff.shape[0]
    if n < 8:
        return None
    gap = float(diff.mean())
    se = float(diff.std()) / (n ** 0.5)
    if gap + 1.96 * se < GAP_MIN:      # confident the gap can't reach 0.25
        return "suit_indifferent"
    return None


def judge_lead(le: LeadEvaluation) -> LeadVerdict:
    avg = _averages(le)
    best_avg = max(avg.values())
    best_cards = [c for c in le.cards if avg[c] >= best_avg - TIE_EPS]
    # a stable, suit-then-rank order for the accepted set
    best_cards.sort(key=lambda c: (SUITS.index(_suit(c)), le.cards.index(c)))
    winner = max(avg, key=lambda c: avg[c])
    table = _table(avg, best_avg, le.softmax)

    _, ds_val = _best_different_suit(avg, winner)
    gap = best_avg - ds_val
    diff_level, sub = _difficulty(avg, best_cards, le.softmax, gap)
    measured = {
        "n_samples": le.n_samples,
        "quality": round(float(le.quality), 3),
        "best_avg_tricks": round(best_avg, 3),
        "gap": round(gap, 3),
        "doubled": bool(le.doubled),
        **sub,
    }

    def reject(reason: str) -> LeadVerdict:
        return LeadVerdict(False, reason, measured=measured, table=table)

    # ---- mechanical evidence floor -------------------------------------
    if le.n_samples < N_MIN:
        return reject("insufficient_samples")

    # ---- v1 exclusion: doubled contracts (DD defense is unrealistic, and
    # Lightner/lead-directing doubles demand a convention-specific lead the
    # sampler can't infer from the bare X token) -------------------------
    if le.doubled:
        return reject("doubled_excluded")

    # ---- owner criterion 1: BEN too sure => obvious --------------------
    if le.softmax and max(le.softmax.values()) > P_OBVIOUS:
        return reject("obvious")

    # ---- owner criterion 2: suit choice doesn't matter ----------------
    if gap < GAP_MIN:
        return reject("suit_indifferent")

    # ---- split-half stability on the headline gap ---------------------
    half = le.n_samples // 2
    if half >= N_MIN // 2:
        def gap_on(sl: slice) -> float:
            a = {c: float(np.mean(le.def_tricks[c][sl])) for c in le.cards}
            b = max(a, key=lambda c: a[c])
            _, dv = _best_different_suit(a, b)
            return a[b] - dv
        g1, g2 = gap_on(slice(0, half)), gap_on(slice(half, None))
        measured["gap_halves"] = [round(g1, 3), round(g2, 3)]
        if abs(g1 - g2) > UNSTABLE_TRICKS and min(g1, g2) < GAP_MIN:
            return reject("unstable_tricks")

    return LeadVerdict(True, "accepted", best=best_cards,
                       difficulty=diff_level, flags=[],
                       measured=measured, table=table)
