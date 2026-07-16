"""The hard shell, part V5: ground-truth admissibility.

A finalization document's meanings claim to describe what the auction
showed. When the problem comes from a REAL deal, the actual concealed
hands are the one sample we know occurred — if a real hand has zero
weight under the bands assigned to its own calls, the meanings mis-read
the auction (the batch-b1 failure class: conventional 2m overcalls of
1NT encoded as natural suit bids, while the real overcaller held 2-3
cards in the "shown" suit).

Also home to the harvest-side heuristic that flags suspect "natural"
labels before an author ever sees the spot.
"""
from __future__ import annotations

import numpy as np

from ..dealing.features import SeatFeatures, parse_hand_pbn
from ..domain.constraints import ConstraintProfile, SeatConstraints
from ..semantics.predicates import PREDICATES


def hand_weight(hand: str, sc: SeatConstraints) -> float:
    """The exact sampling weight the real hand would receive."""
    f = SeatFeatures(cards=np.array([parse_hand_pbn(hand)], dtype=np.int8))
    w = float(sc.hcp_weights[f.hcp[0]])
    for suit in "SHDC":
        w *= float(sc.suit_weights[suit][f.suit_lengths[suit][0]])
        w *= float(sc.suit_hcp_weights[suit][f.suit_hcp[suit][0]])
    for d in sc.denials:
        if (d.hcp_lo <= f.hcp[0] <= d.hcp_hi
                and f.suit_lengths[d.suit][0] >= d.min_len):
            w *= d.weight
    for name in sc.exclusions:
        if bool(PREDICATES[name](f)[0]):
            return 0.0
    return w


def check_deal_admissible(
    hands: dict, hero: str, profile: ConstraintProfile,
) -> list[str]:
    """V5: every real concealed hand must be possible under its meanings.

    Returns violation messages (empty = admissible). A weight of exactly
    zero is a mis-read auction; a positive weight, however small, only
    means the real hand was atypical, which is fine.
    """
    violations = []
    for seat, sc in profile.seats.items():
        if seat == hero:
            continue
        hand = hands.get(seat)
        if hand is None:
            continue
        if hand_weight(hand, sc) == 0.0:
            f = SeatFeatures(
                cards=np.array([parse_hand_pbn(hand)], dtype=np.int8))
            shape = "=".join(str(int(f.suit_lengths[s][0])) for s in "SHDC")
            violations.append(
                f"{seat}'s actual hand ({int(f.hcp[0])} HCP, {shape}) has "
                f"zero weight under its meanings — the auction was "
                f"mis-read (V5)")
    return violations


def suspect_natural_calls(
    dealer: str, calls: list, hands: dict, hero: str, min_len: int = 4,
) -> list[str]:
    """Harvest-side heuristic: suit bids whose bidder's REAL hand is short
    in the named suit are probably conventional (transfers, Landy, cue
    bids...). Returns warnings like 'call #4 2D by W: only 2 diamonds'.

    Advisory — the authoritative check is check_deal_admissible against
    the authored meanings.
    """
    from ..domain.auction import SEATS

    out = []
    seat = dealer
    for i, call in enumerate(calls):
        if call not in ("P", "X", "XX") and call[1:] != "NT" and seat != hero:
            suit = call[1]
            hand = hands.get(seat)
            if hand is not None:
                length = int(SeatFeatures(cards=np.array(
                    [parse_hand_pbn(hand)],
                    dtype=np.int8)).suit_lengths[suit][0])
                if length < min_len:
                    out.append(
                        f"call #{i} {call} by {seat}: only {length} "
                        f"{suit} in the real hand — likely conventional")
        seat = SEATS[(SEATS.index(seat) + 1) % 4]
    return out
