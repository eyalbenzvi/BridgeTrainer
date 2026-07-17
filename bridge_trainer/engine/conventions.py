"""Mechanical auction facts only — no bridge judgment, no bridge
situation types (owner r8: exclusions come solely from the agreed
statistical rules; meanings come solely from the engine's card).

Seats are absolute indices 0..3 = N,E,S,W; auction tokens run from the
dealer.
"""
from __future__ import annotations


def seat_of(dealer_i: int, idx: int) -> int:
    return (dealer_i + idx) % 4


def _is_bid(tok: str) -> bool:
    return tok not in ("P", "X", "XX")


def hero_role(auction: list[str], dealer_i: int, hero_i: int) -> str:
    """opener / responder / overcaller / advancer / other — a mechanical
    fact of who acted first, used only for batch-diversity metadata."""
    first_bid_j = next((j for j, t in enumerate(auction) if _is_bid(t)), None)
    if first_bid_j is None:
        return "opener-to-be"
    opener = seat_of(dealer_i, first_bid_j)
    if hero_i == opener:
        return "opener"
    if hero_i == (opener + 2) % 4:
        return "responder"
    over_j = next((j for j in range(first_bid_j + 1, len(auction))
                   if _is_bid(auction[j]) or auction[j] == "X"), None)
    if over_j is not None:
        overcaller = seat_of(dealer_i, over_j)
        if hero_i == overcaller:
            return "overcaller"
        if hero_i == (overcaller + 2) % 4:
            return "advancer"
    return "other"
