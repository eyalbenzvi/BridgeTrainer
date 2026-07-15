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


@predicate("balanced_20_21")
def balanced_20_21(f: SeatFeatures) -> np.ndarray:
    """Would have opened 2NT."""
    return f.is_balanced & (f.hcp >= 20) & (f.hcp <= 21)


@predicate("light_overcall_junk_spades")
def light_overcall_junk_spades(f: SeatFeatures) -> np.ndarray:
    """A light 1S overcall requires suit quality; with a near-honorless suit
    and sub-opening values the expert passes."""
    return (f.hcp <= 9) & (f.suit_hcp["S"] <= 2)


@predicate("takeout_double_shape_over_spades")
def takeout_double_shape_over_spades(f: SeatFeatures) -> np.ndarray:
    """Would have doubled spades for takeout instead of passing."""
    lens = f.suit_lengths
    return (
        (f.hcp >= 12)
        & (lens["S"] <= 2)
        & (lens["H"] >= 3) & (lens["D"] >= 3) & (lens["C"] >= 3)
    )


@predicate("sound_two_level_overcall_over_spades")
def sound_two_level_overcall_over_spades(f: SeatFeatures) -> np.ndarray:
    """Would have made a direct two-level overcall over spades instead of
    passing: opening values with a good five-card suit outside spades."""
    lens, shcp = f.suit_lengths, f.suit_hcp
    good_suit = np.zeros(len(f.cards), dtype=bool)
    for s in ("H", "D", "C"):
        good_suit |= (lens[s] >= 5) & (shcp[s] >= 5)
    return (f.hcp >= 12) & good_suit


@predicate("weak_two_suit_junk")
def weak_two_suit_junk(f: SeatFeatures) -> np.ndarray:
    """A vulnerable-style weak two promises a real suit; Q-empty is excluded."""
    return f.suit_hcp["S"] <= 2


def quality_floor(suit: str, min_shcp: int) -> str:
    """Register (idempotently) a dynamic predicate excluding hands whose
    honor points in `suit` fall below `min_shcp`. Used to invert the bot's
    suit-quality signature conditions. Returns the predicate name."""
    name = f"suit_quality_{suit}_{min_shcp}"
    if name not in PREDICATES:
        PREDICATES[name] = lambda f, s=suit, m=min_shcp: f.suit_hcp[s] < m
    return name
