"""Negative inferences for silent seats (backlog item A3).

A pass is a call: it denies things. The batch-b1 audit found silent
seats modeled with an HCP cap only, so the sampler dealt them hands
that would never have stayed silent (one 'silent' hand held SEVEN
diamonds). This module converts every all-pass seat's silence into
baseline Denial discounts, applied automatically by build_record
unless the author explicitly opts a seat out
(meanings[seat]["no_default_denials"] = true) — overrides must be
explicit, never by omission.

Two inference families, deliberately coarse (weights, not bans):

  PREEMPT SILENCE   any seat that only passed rarely holds a weak hand
                    with a 6/7-card suit (would have preempted);
  OVERCALL SILENCE  a seat that passed while an enemy contract stood at
                    the 1-2 level rarely holds a decent 5-card suit
                    with overcalling values.
"""
from __future__ import annotations

from ..domain.auction import SEATS
from ..domain.constraints import SUITS, Denial

PREEMPT_DENIALS = [
    # (hcp_lo, hcp_hi, min_len, weight): weak hands with long suits act
    (3, 10, 7, 0.10),
    (5, 10, 6, 0.35),
]
OVERCALL_DENIAL = (11, 16, 5, 0.30)


def silent_seats(dealer: str, stem: list, hero: str) -> dict[str, bool]:
    """Concealed seats whose stem calls are all passes -> whether any of
    those passes was over a standing enemy 1-2 level bid (overcall
    silence, judged from that seat's perspective)."""
    seat = dealer
    last_bidder, level = None, 0
    passed_over_enemy: dict[str, bool] = {}
    spoke: set[str] = set()
    for call in stem:
        if call == "P":
            if seat != hero:
                enemy = (last_bidder is not None
                         and (SEATS.index(last_bidder) - SEATS.index(seat))
                         % 2 == 1)
                if enemy and 1 <= level <= 2:
                    passed_over_enemy[seat] = True
                passed_over_enemy.setdefault(seat, False)
        else:
            spoke.add(seat)
            if call not in ("X", "XX"):
                last_bidder, level = seat, int(call[0])
        seat = SEATS[(SEATS.index(seat) + 1) % 4]
    return {s: over for s, over in passed_over_enemy.items()
            if s not in spoke}


def default_silence_denials(dealer: str, stem: list, hero: str,
                            ) -> dict[str, list[Denial]]:
    """Baseline denials per all-pass concealed seat."""
    out: dict[str, list[Denial]] = {}
    for seat, over_enemy in silent_seats(dealer, stem, hero).items():
        denials = [Denial(lo, hi, suit, ln, w)
                   for (lo, hi, ln, w) in PREEMPT_DENIALS for suit in SUITS]
        if over_enemy:
            lo, hi, ln, w = OVERCALL_DENIAL
            denials += [Denial(lo, hi, suit, ln, w) for suit in SUITS]
        out[seat] = denials
    return out
