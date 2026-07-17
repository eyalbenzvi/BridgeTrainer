"""Mechanical auction facts only — no bridge judgment, no bridge
situation types (owner r8: exclusions come solely from the agreed
statistical rules; meanings come solely from the engine's card).

Seats are absolute indices 0..3 = N,E,S,W; auction tokens run from the
dealer.
"""
from __future__ import annotations

SEATS = "NESW"


def seat_of(dealer_i: int, idx: int) -> int:
    return (dealer_i + idx) % 4


def _is_bid(tok: str) -> bool:
    return tok not in ("P", "X", "XX")


def final_contract(auction: list[str], dealer_i: int) -> dict | None:
    """The contract a completed auction settles in — a mechanical fact.

    Returns {level, denom, declarer_i, doubled} or None when the board is
    passed out. `denom` is C/D/H/S/NT; `doubled` is "", "x" or "xx".
    Declarer is the member of the contract-winning side who FIRST named the
    final denomination (standard bridge rule).
    """
    bids = [(j, t) for j, t in enumerate(auction) if _is_bid(t)]
    if not bids:
        return None
    last_j, last_t = bids[-1]
    level, denom = int(last_t[0]), last_t[1:]
    decl_side = seat_of(dealer_i, last_j) % 2
    declarer_i = seat_of(dealer_i, last_j)
    for j, t in bids:
        if t[1:] == denom and seat_of(dealer_i, j) % 2 == decl_side:
            declarer_i = seat_of(dealer_i, j)
            break
    doubled = ""
    for t in auction[last_j + 1:]:
        if t == "XX":
            doubled = "xx"
        elif t == "X":
            doubled = "x"
    return {"level": level, "denom": denom,
            "declarer_i": declarer_i, "doubled": doubled}


def opening_leader(declarer_i: int) -> int:
    """The player on lead: left-hand opponent of declarer."""
    return (declarer_i + 1) % 4


def contract_str(fc: dict) -> str:
    """{level,denom,declarer_i,doubled} -> '4HE' / '3NTSx'."""
    return f"{fc['level']}{fc['denom']}{SEATS[fc['declarer_i']]}{fc['doubled']}"


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
