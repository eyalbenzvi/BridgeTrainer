"""Explanations for opening-lead problems.

Two computed artifacts, no hand-authored bridge:
  * auction meanings — one entry per call of the COMPLETE auction, from GIB
    (BBO gibrest), so the UI can make every bid clickable.
  * card notes — per candidate lead, phrased purely in the owner's currency
    (average defensive tricks and rank).
"""
from __future__ import annotations

from .conventions import SEATS, seat_of
from .explain import accumulated_cards, terse_meaning


def auction_meanings(dealer_i, full_auction) -> list[dict]:
    """Per-call meaning for the whole auction (idx, seat, call, text, card).
    Each call's meaning comes from GIB interpreting the auction prefix; the
    meaning depends only on the auction, so no hand/engine is needed.

    ``card`` is GIB's card for that call alone (what the audits check); the
    displayed ``text`` folds in what the seat has already shown, so a
    later upper-bound-only gloss cannot contradict the seat's own opening —
    ``explain.merge_promises``."""
    from . import gib_explain
    cards = [gib_explain.card_for_auction(list(full_auction[:j + 1]))
             for j in range(len(full_auction))]
    shown = accumulated_cards(dealer_i, cards)
    out = []
    for j, tok in enumerate(full_auction):
        seat_i = seat_of(dealer_i, j)
        out.append({"idx": j, "seat": SEATS[seat_i], "call": tok,
                    "text": terse_meaning(shown[j], call=tok),
                    "card": cards[j]})
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
            text = (f"ההובלה המיטבית — ההגנה לוקחת בממוצע {avg:.2f} טריקים, "
                    f"יותר מכל קלף אחר.")
        else:
            text = (f"בממוצע {avg:.2f} טריקים הגנתיים "
                    f"({row['vs_best']:+.2f} מול ההובלה המיטבית · "
                    f"מדורג {rank} מתוך {n}).")
        out.append({"card": c, "text": text})
    return out
