"""ARCH-6: the shared HTML helpers preserve each consumer's look and escape
their input (report renders a hand inline with spaces; publish stacks it)."""
from __future__ import annotations

from bridge_trainer.app import htmlfmt


def test_report_style_hand_inline_with_char_dash():
    # report.py defaults: space-joined suits, no glyph gap, em-dash void
    out = htmlfmt.hand_html("AK.QJ..T987")
    assert out == (f'{htmlfmt.SUIT_GLYPHS["S"]}AK '
                   f'{htmlfmt.SUIT_GLYPHS["H"]}QJ '
                   f'{htmlfmt.SUIT_GLYPHS["D"]}— '
                   f'{htmlfmt.SUIT_GLYPHS["C"]}T987')


def test_publish_style_hand_stacked_with_entities():
    # publish.py options: <br>-stacked, glyph gap, &mdash; void
    out = htmlfmt.hand_html("AK...", suit_sep="<br>", glyph_sep=" ",
                            dash="&mdash;")
    assert out.startswith(f'{htmlfmt.SUIT_GLYPHS["S"]} AK<br>')
    assert out.count("<br>") == 3
    assert "&mdash;" in out                     # the three voids


def test_hand_html_escapes_cards():
    # a hostile card string can't inject markup
    out = htmlfmt.hand_html("<img>...")
    assert "&lt;img&gt;" in out and "<img>" not in out


def test_glyphs_are_valid_quoted_markup():
    # canonical form uses quoted class attributes (both consumers agree now)
    assert 'class="red"' in htmlfmt.SUIT_GLYPHS["H"]
    assert 'class="red"' in htmlfmt.SUIT_GLYPHS["D"]
