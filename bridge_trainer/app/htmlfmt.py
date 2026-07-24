"""Shared HTML fragment helpers for the static generators (ARCH-6).

``report.py`` and ``publish.py`` each carried their own copies of the suit
glyphs, the hand renderer and the auction renderer — divergent in quote style
and separators, so a fix or a11y tweak had to be made two (or three) times.
They now share these. The per-consumer look (report renders a hand inline with
spaces; publish stacks the suits with <br>) is preserved via keyword options,
not by forking the function.
"""
from __future__ import annotations

import html

from ..domain.auction import partner_of

# four-colour suit glyphs; red suits carry a class the page CSS colours.
SUIT_GLYPHS = {"S": "&#9824;", "H": '<span class="red">&#9829;</span>',
               "D": '<span class="red">&#9830;</span>', "C": "&#9827;"}


def hand_html(hand: str, *, suit_sep: str = " ", glyph_sep: str = "",
              dash: str = "—") -> str:
    """Render a PBN hand ("AKx.QJ.T98.xxxx") as four suit segments.

    ``suit_sep`` joins the four suits (report: " " inline; publish: "<br>"
    stacked), ``glyph_sep`` sits between a suit's glyph and its cards, and
    ``dash`` marks a void.
    """
    parts = hand.split(".")
    return suit_sep.join(
        f"{SUIT_GLYPHS[s]}{glyph_sep}{html.escape(p) or dash}"
        for s, p in zip("SHDC", parts))


def auction_html(problem) -> str:
    """The stem auction as text: opponents' calls parenthesised, ours plain,
    a trailing " – ?" for the call under test."""
    return " &ndash; ".join(
        f"({c.token})" if seat not in (problem.my_seat,
                                       partner_of(problem.my_seat))
        else c.token
        for seat, c in problem.auction.calls_with_seats()) + " &ndash; ?"
