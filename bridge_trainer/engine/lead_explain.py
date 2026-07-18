"""Explanations for opening-lead problems.

Two computed artifacts, no hand-authored bridge:
  * auction meanings — one entry per call of the COMPLETE auction, from the
    engine's convention card, so the UI can make every bid clickable.
  * card notes — per candidate lead, phrased purely in the owner's currency
    (average defensive tricks and rank).
"""
from __future__ import annotations

from .conventions import SEATS, seat_of
from .explain import terse_meaning


def auction_meanings(engine, hand_pbn, leader_i, dealer_i, vul,
                     full_auction) -> list[dict]:
    """Per-call meaning for the whole auction (idx, seat, call, text)."""
    try:
        bot = engine.bot(hand_pbn, leader_i, dealer_i, vul)
        cards = engine.explain_calls(bot, dealer_i, full_auction)
    except Exception:
        cards = [{"text": "", "hcp": None, "minlen": {}}
                 for _ in full_auction]
    out = []
    for j, tok in enumerate(full_auction):
        seat_i = seat_of(dealer_i, j)
        meaning = terse_meaning(cards[j], call=tok) if j < len(cards) else ""
        out.append({"idx": j, "seat": SEATS[seat_i], "call": tok,
                    "text": meaning})
    return out


def card_notes(verdict) -> list[dict]:
    """One note per candidate lead, in defensive-trick terms only."""
    rows = verdict.table
    best = set(verdict.best)
    n = len(rows)
    out = []
    for rank, row in enumerate(rows, start=1):
        c = row["card"]
        avg = row["avg_def_tricks"]
        if c in best:
            text = (f"Best lead — the defense averages {avg:.2f} tricks, "
                    f"more than any other card.")
        else:
            text = (f"Averages {avg:.2f} defensive tricks "
                    f"({row['vs_best']:+.2f} vs the best lead; "
                    f"rank {rank} of {n}).")
        out.append({"card": c, "text": text})
    return out
