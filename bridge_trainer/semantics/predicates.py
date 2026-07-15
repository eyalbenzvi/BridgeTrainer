"""Reusable named hand predicates for rule `exclusions`.

Each predicate takes SeatFeatures for a batch of layouts and returns a bool
mask where True means the hand is EXCLUDED: it fits the rule's ranges but
would have chosen a different call, so it gets weight 0.
"""
from __future__ import annotations

from typing import Callable

import numpy as np

from ..dealing.features import SUIT_NAMES, SeatFeatures

Predicate = Callable[[SeatFeatures], np.ndarray]

PREDICATES: dict[str, Predicate] = {}


def predicate(name: str):
    def deco(fn: Predicate) -> Predicate:
        PREDICATES[name] = fn
        return fn
    return deco


@predicate("balanced_15_17")
def balanced_15_17(f: SeatFeatures) -> np.ndarray:
    """Would have opened 1NT instead."""
    return f.is_balanced & (f.hcp >= 15) & (f.hcp <= 17)


@predicate("balanced_12_14")
def balanced_12_14(f: SeatFeatures) -> np.ndarray:
    """Would have opened a weak 1NT instead (for weak-NT profiles)."""
    return f.is_balanced & (f.hcp >= 12) & (f.hcp <= 14)


@predicate("takeout_double_shape_over_hearts")
def takeout_double_shape_over_hearts(f: SeatFeatures) -> np.ndarray:
    """Opening values, short hearts, support for the other three suits:
    would have made a takeout double rather than a simple overcall."""
    lens = f.suit_lengths
    return (
        (f.hcp >= 12)
        & (lens["H"] <= 2)
        & (lens["S"] >= 3) & (lens["D"] >= 3) & (lens["C"] >= 3)
    )


@predicate("strong_jump_shift_values")
def strong_jump_shift_values(f: SeatFeatures) -> np.ndarray:
    """Too strong for the assumed simple action (18+)."""
    return f.hcp >= 18


@predicate("game_forcing_raise_values")
def game_forcing_raise_values(f: SeatFeatures) -> np.ndarray:
    """Would have made a forcing raise, not a preemptive one (10+ with fit)."""
    return f.hcp >= 10


@predicate("seven_card_suit")
def seven_card_suit(f: SeatFeatures) -> np.ndarray:
    """Any 7+ card suit: would have preempted at a higher level instead."""
    lens = f.suit_lengths
    stacked = np.stack([lens[s] for s in SUIT_NAMES], axis=1)
    return stacked.max(axis=1) >= 7
