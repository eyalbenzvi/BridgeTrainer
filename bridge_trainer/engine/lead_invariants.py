"""Non-negotiable runtime invariants at the boundary before every DDS
evaluation of an opening-lead layout.

These guard the exact class of defect the audit targets: a sampled layout
whose leader hand is not the displayed hand, a candidate card that is not in
the hand actually placed at the leader's seat, a declarer/leader mismatch, or
a deal that is not a legal 52-card partition. Any of those would make the
double-dummy number meaningless (or based on information the player never had).

Always active in tests; in normal runs active only when the environment
variable ``BT_LEAD_CHECK`` is set (or ``check=True`` is passed explicitly), so
production stays quiet and fast. On failure the message names the problem id,
sample index, deterministic sample seed, the offending card and the compass
seats, so a bad board can be reproduced from the log alone.
"""
from __future__ import annotations

import os

from .lead_cards import (FULL_DECK, SEATS, canonical_hand, physical_cards)


class LeadInvariantError(AssertionError):
    """Raised when a layout fails a pre-DDS invariant. Subclasses
    AssertionError so ``python -O`` semantics feel familiar, but it is raised
    unconditionally (not via ``assert``) so it is never stripped."""


def checks_enabled() -> bool:
    """True when the invariant layer should run in a normal (non-test) run."""
    val = os.environ.get("BT_LEAD_CHECK", "")
    return val not in ("", "0", "false", "False", "no", "NO")


def _ctx(problem_id: str, sample_index: int, sample_seed) -> str:
    return (f"[problem={problem_id or '?'} sample={sample_index} "
            f"sample_seed={sample_seed}]")


def check_layout(hands_abs, contract, leader_i: int,
                 displayed_leader_hand: str, candidates,
                 *, sample_index: int = -1, problem_id: str = "",
                 sample_seed=None) -> None:
    """Validate one sampled layout + the candidate lead set before DDS.

    Parameters use the project's real structures:
      hands_abs               tuple of 4 PBN hands indexed by absolute seat NESW
      contract                engine.lead_evaluate.Contract (has declarer_i)
      leader_i                absolute seat index of the opening leader
      displayed_leader_hand   the PBN hand shown to the player
      candidates              the physical candidate cards (== displayed hand)
    """
    ctx = _ctx(problem_id, sample_index, sample_seed)

    # -- four hands, each exactly 13 cards, all 52 unique = the full deck ----
    if len(hands_abs) != 4:
        raise LeadInvariantError(
            f"{ctx} expected 4 hands, got {len(hands_abs)}")
    all_cards: list[str] = []
    for si, hand in enumerate(hands_abs):
        try:
            cs = physical_cards(hand)
        except ValueError as e:
            raise LeadInvariantError(
                f"{ctx} seat {SEATS[si]} malformed hand {hand!r}: {e}")
        if len(cs) != 13:
            raise LeadInvariantError(
                f"{ctx} seat {SEATS[si]} has {len(cs)} cards, not 13: {hand!r}")
        all_cards.extend(cs)
    if len(all_cards) != 52:
        raise LeadInvariantError(f"{ctx} layout has {len(all_cards)} cards")
    if len(set(all_cards)) != 52:
        dupes = sorted({c for c in all_cards if all_cards.count(c) > 1})
        raise LeadInvariantError(f"{ctx} duplicate cards across hands: {dupes}")
    if set(all_cards) != FULL_DECK:
        missing = sorted(FULL_DECK - set(all_cards))
        raise LeadInvariantError(f"{ctx} layout is not the full 52-card deck; "
                                 f"missing {missing}")

    # -- declarer / leader consistency (public contract only) ----------------
    if not 0 <= leader_i < 4:
        raise LeadInvariantError(f"{ctx} leader seat out of range: {leader_i}")
    expected_leader = (contract.declarer_i + 1) % 4
    if leader_i != expected_leader:
        raise LeadInvariantError(
            f"{ctx} leader {SEATS[leader_i]} is not declarer's LHO; declarer "
            f"{SEATS[contract.declarer_i]} => leader must be "
            f"{SEATS[expected_leader]}")

    # -- the leader's sampled hand IS the displayed hand ---------------------
    got = canonical_hand(hands_abs[leader_i])
    want = canonical_hand(displayed_leader_hand)
    if got != want:
        raise LeadInvariantError(
            f"{ctx} sampled hand at leader seat {SEATS[leader_i]} is {got!r} "
            f"but the displayed leader hand is {want!r}")

    # -- candidates are exactly the 13 physical cards of the displayed hand --
    disp = physical_cards(displayed_leader_hand)
    if sorted(candidates) != sorted(disp):
        raise LeadInvariantError(
            f"{ctx} candidate set {sorted(candidates)} != displayed hand "
            f"cards {sorted(disp)}")
    if len(candidates) != len(set(candidates)):
        raise LeadInvariantError(f"{ctx} duplicate candidate cards: "
                                 f"{sorted(candidates)}")

    # -- every candidate is physically present at the leader seat (i.e. not
    #    already removed from the DDS position) ------------------------------
    leader_holding = set(physical_cards(hands_abs[leader_i]))
    for card in candidates:
        if card not in leader_holding:
            raise LeadInvariantError(
                f"{ctx} candidate {card} is not in the leader's DDS hand "
                f"{sorted(leader_holding)} at seat {SEATS[leader_i]}")


def check_dds_result(per_card: dict, candidates, *, sample_index: int = -1,
                     problem_id: str = "", sample_seed=None) -> None:
    """After the DDS solve, the returned per-card map must cover exactly the
    candidate cards, once each — proving DDS evaluated every displayed physical
    card and no extra/collapsed one."""
    ctx = _ctx(problem_id, sample_index, sample_seed)
    keys = set(per_card)
    want = set(candidates)
    if keys != want:
        raise LeadInvariantError(
            f"{ctx} DDS returned cards {sorted(keys)} but candidates are "
            f"{sorted(want)} (missing {sorted(want - keys)}, "
            f"extra {sorted(keys - want)})")
