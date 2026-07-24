"""WCAG AA contrast guardrail for the CSS color tokens (task T20).

UX-A-1/UX-A-4 found selected-state text (white on --accent/--win) dropping to
~2.6:1 in dark mode, plus several light-theme pairs below AA. The fix adds
--on-accent/--on-win/--on-loss tokens and darkens a few values. This test
extracts the two explicit theme palettes (html[data-theme="light"|"dark"] body)
and asserts every text/background pair the UI actually paints meets AA (4.5:1).
"""
from __future__ import annotations

import re

from bridge_trainer.app.webapp import _CSS

# (foreground token, background token) pairs the UI renders as text-on-fill.
PAIRS = [
    ("on-accent", "accent"),   # segctl/tabs/pills/tags selected, .tick, modechip
    ("on-win", "win"),         # win bar labels, .tag.best, scorechip tone-win
    ("on-loss", "loss"),       # loss bar labels, scorechip tone-loss
    ("on-felt-muted", "felt"),  # muted text on the green felt (topbar/meta)
    ("on-felt", "felt"),       # primary text on felt
    ("on-nonvul", "nonvul"),   # vulnerability plate (non-vul seat)
    ("di", "card"),            # orange diamond suit glyph on white cards
    ("fg", "push"),            # a.big.off disabled CTA text on the grey fill
]


def _palette(theme: str) -> dict[str, str]:
    """Extract {token: #rrggbb} from an explicit theme block. Skips 8-digit
    (alpha) hex like --accent-tint so only solid colors are compared."""
    m = re.search(r'html\[data-theme="' + theme + r'"\] body \{(.*?)\}',
                  _CSS, re.S)
    assert m, f"{theme} palette block not found"
    return {name: val for name, val in
            re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6})(?![0-9A-Fa-f])",
                       m.group(1))}


def _lin(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _lum(hx: str) -> float:
    hx = hx.lstrip("#")
    r, g, b = (int(hx[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _ratio(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _check(theme: str):
    pal = _palette(theme)
    failures = []
    for fg, bg in PAIRS:
        assert fg in pal, f"{theme}: missing token --{fg}"
        assert bg in pal, f"{theme}: missing token --{bg}"
        r = _ratio(pal[fg], pal[bg])
        if r < 4.5:
            failures.append(f"{theme}: --{fg} on --{bg} = {r:.2f} (< 4.5)")
    assert not failures, "\n".join(failures)


def test_contrast_light_theme_meets_aa():
    _check("light")


def test_contrast_dark_theme_meets_aa():
    _check("dark")
