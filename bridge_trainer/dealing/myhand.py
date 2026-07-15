"""Seeded sampling of MY hand from an authored hand class.

A hand class keeps a problem's decision coherent across "next deal" variants:
e.g. for a 3-card-raise competitive problem, every dealt hand has exactly
three spades and near-minimum values, so Pass/3S/X stay the sensible
candidates and the authored projection trees remain valid.
"""
from __future__ import annotations

import numpy as np

from .features import HCP_BY_RANK, SUIT_NAMES, hand_to_pbn


def sample_my_hand(hand_class: dict, rng: np.random.Generator,
                   batch: int = 4096, max_batches: int = 200) -> str:
    """Deal a random 13-card hand satisfying the class, PBN dot form."""
    hcp_lo, hcp_hi = hand_class.get("hcp", [0, 40])
    suit_bounds = {s: hand_class.get("suits", {}).get(s, [0, 13])
                   for s in SUIT_NAMES}
    deck = np.arange(52, dtype=np.int8)
    for _ in range(max_batches):
        hands = rng.permuted(np.tile(deck, (batch, 1)), axis=1)[:, :13]
        hcp = HCP_BY_RANK[hands % 13].sum(axis=1)
        ok = (hcp >= hcp_lo) & (hcp <= hcp_hi)
        for i, s in enumerate(SUIT_NAMES):
            lens = (hands // 13 == i).sum(axis=1)
            ok &= (lens >= suit_bounds[s][0]) & (lens <= suit_bounds[s][1])
        idx = np.flatnonzero(ok)
        if len(idx):
            return hand_to_pbn(hands[idx[0]])
    raise RuntimeError(f"hand class looks unsatisfiable: {hand_class}")
