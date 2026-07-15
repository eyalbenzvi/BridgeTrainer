"""Vectorized card model shared by the dealer, predicates and projector.

Card index 0..51 = suit*13 + rank; suit order S,H,D,C; rank 0=A .. 12=2.
A batch of candidate layouts is a (B, 39) int8 array of card ids: the 39
cards not in my hand, permuted, sliced 13/13/13 to the hidden seats.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

import numpy as np

SUIT_NAMES = "SHDC"
RANK_NAMES = "AKQJT98765432"
HCP_BY_RANK = np.array([4, 3, 2, 1] + [0] * 9, dtype=np.int8)


def parse_hand_pbn(s: str) -> list[int]:
    """'K93.752.A854.T62' (spades.hearts.diamonds.clubs) -> card ids."""
    parts = s.strip().split(".")
    if len(parts) != 4:
        raise ValueError(f"hand must have 4 suit groups: {s!r}")
    out = []
    for suit, holding in enumerate(parts):
        for ch in holding.upper():
            out.append(suit * 13 + RANK_NAMES.index(ch))
    if len(out) != 13:
        raise ValueError(f"hand must have 13 cards: {s!r}")
    if len(set(out)) != 13:
        raise ValueError(f"duplicate card in hand: {s!r}")
    return out


def hand_to_pbn(cards) -> str:
    by_suit = ["", "", "", ""]
    for c in sorted(int(c) for c in cards):
        by_suit[c // 13] += RANK_NAMES[c % 13]
    return ".".join(by_suit)


@dataclass
class SeatFeatures:
    """Vectorized features of one seat across a batch of layouts."""

    cards: np.ndarray  # (B, 13) card ids

    @cached_property
    def hcp(self) -> np.ndarray:
        return HCP_BY_RANK[self.cards % 13].sum(axis=1)

    @cached_property
    def suit_lengths(self) -> dict[str, np.ndarray]:
        suits = self.cards // 13
        return {s: (suits == i).sum(axis=1) for i, s in enumerate(SUIT_NAMES)}

    @cached_property
    def suit_hcp(self) -> dict[str, np.ndarray]:
        suits = self.cards // 13
        pts = HCP_BY_RANK[self.cards % 13]
        return {s: np.where(suits == i, pts, 0).sum(axis=1)
                for i, s in enumerate(SUIT_NAMES)}

    @cached_property
    def is_balanced(self) -> np.ndarray:
        """No singleton or void, at most one doubleton (4333/4432/5332)."""
        lens = np.stack([self.suit_lengths[s] for s in SUIT_NAMES], axis=1)
        return (lens.min(axis=1) >= 2) & ((lens == 2).sum(axis=1) <= 1)

    def take(self, mask_or_idx: np.ndarray) -> "SeatFeatures":
        return SeatFeatures(cards=self.cards[mask_or_idx])


@dataclass
class DealFeatures:
    """Per-seat features for the full batch; my fixed hand is broadcast."""

    seats: dict[str, SeatFeatures]  # keyed by seat letter N/E/S/W

    def take(self, mask_or_idx: np.ndarray) -> "DealFeatures":
        return DealFeatures(
            seats={k: v.take(mask_or_idx) for k, v in self.seats.items()})
