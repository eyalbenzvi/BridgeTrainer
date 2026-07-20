"""Explanations: given-bidding meaning bands + option explanations.
All computed (samples + auction mechanics + evaluation numbers), never
asserted — docs/ben_execution_plan.md §3.3 + v2 amendments 1, 2, 9, 11.

Display grammar (BBO alert-card style, ux/bridge panel redesign): terse
comma-separated fragments — optional convention name, suit lengths, HCP
band — never prose. "6+♣, 10-12", "3+♦, 11-21", a limited pass is "0-11".
"""
from __future__ import annotations

import re

from .conventions import seat_of

SEATS = "NESW"
SUIT_GLYPH = {"S": "♠", "H": "♥", "D": "♦", "C": "♣", "NT": "NT"}
BAND_N_MIN = 30

# HCP upper bounds at/above this mean "no real upper bound"
_HCP_OPEN_TOP = 25
# GIB's meaning strings are already canonical 2/1 names (Stayman, Blackwood,
# Weak two bid, Forcing two over one, Cappelletti, …); we keep them verbatim.
# These few fragments carry no information a reader wants as a bid's "name"
# (the suit/HCP bands already say it), so they are dropped from the label.
_FILLER_PARTS = {"artificial", "forcing", "bidable suit", "calculated bid"}


def _is_filler(low: str) -> bool:
    return low in _FILLER_PARTS


_SUIT_PART_RE = re.compile(r"^(\d+)\s*\+?\s*!?([SHDC])$")
_HCP_PART_RE = re.compile(r"\d+\s*(\+|-\s*\d+)?\s*HCP", re.I)
_CONTRACT_RE = re.compile(r"^(\d)([CDHSN])([NESW])$")


def _call_name(tok: str) -> str:
    if tok in ("P", "X", "XX"):
        return {"P": "Pass", "X": "Dbl", "XX": "Rdbl"}[tok]
    return tok[0] + SUIT_GLYPH[tok[1:]]


def _glyphify(text: str) -> str:
    """The engine's !S/!H/!D/!C suit markers → suit glyphs."""
    for k, g in SUIT_GLYPH.items():
        text = text.replace(f"!{k}", g)
    return text


def contract_name(tok: str) -> str:
    """'5CE' → '5♣E', '3NW' → '3NT W' (BBO contract notation)."""
    m = _CONTRACT_RE.match(tok)
    if not m:
        return tok
    level, strain, decl = m.groups()
    if strain == "N":
        return f"{level}NT {decl}"
    return f"{level}{SUIT_GLYPH[strain]}{decl}"


def terse_meaning(card: dict, call: str | None = None) -> str:
    """BBO alert-card string from the ENGINE's card state only:
    [name, ] [suit lengths…, ] [hcp band]. Empty string = nothing worth
    saying (e.g. an unlimited pass). No bridge knowledge here — formatting
    only (owner r6/r7)."""
    denom = None
    if call and call not in ("P", "X", "XX"):
        denom = call[1:]
    raw = (card.get("text") or "").replace("--", ";")
    name = None
    text_suits: list[tuple[int, str]] = []
    for part in raw.split(";"):
        p = part.strip(" .")
        if not p:
            continue
        low = p.lower()
        if _is_filler(low):
            continue
        if low == "balanced":
            # implied by a NT call; informative enough elsewhere
            if denom != "NT" and name is None:
                name = "Balanced"
            continue
        if _HCP_PART_RE.search(p):
            continue  # card["hcp"] carries the band; text repeats it
        m = _SUIT_PART_RE.match(p)
        if m:
            text_suits.append((int(m.group(1)), m.group(2)))
            continue
        if name is None and p:
            # keep the whole convention name — a long one (e.g. "Roman Key
            # Card Blackwood", "Lebensohl after double") is EXACTLY what must
            # not be silently dropped; that truncation is what left 4NT and
            # other conventions unexplained.
            name = _glyphify(p)
    by_suit: dict[str, int] = {}
    for st in "SHDC":
        v = (card.get("minlen") or {}).get(st, 0)
        # a 3-card minimum is only alertable on the suit actually bid
        if v >= 4 or (v == 3 and st == denom):
            by_suit[st] = v
    for v, st in text_suits:
        if v > by_suit.get(st, 0):
            by_suit[st] = v
    suits = sorted(by_suit.items(),
                   key=lambda kv: (-kv[1], "SHDC".index(kv[0])))[:2]
    if name:
        # "Transfer to ♥" + a 5+♥ fragment says ♥ twice — keep the name short
        for st, _ in suits:
            if name.endswith(f" to {SUIT_GLYPH[st]}"):
                name = name[:-len(f" to {SUIT_GLYPH[st]}")]
    maxlen = card.get("maxlen") or {}

    def _suit_frag(st: str, v: int) -> str:
        # use the engine's UPPER bound too: "5-6♠", "6♠" (exactly), "5+♠"
        mx = maxlen.get(st, 13)
        if v <= mx < 13:
            return f"{v}{SUIT_GLYPH[st]}" if v == mx \
                else f"{v}-{mx}{SUIT_GLYPH[st]}"
        return f"{v}+{SUIT_GLYPH[st]}"

    frags = ([name] if name else []) + \
        [_suit_frag(st, v) for st, v in suits]
    hcp = card.get("hcp")
    if hcp:
        lo, hi = int(hcp[0]), int(hcp[1])
        if hi >= _HCP_OPEN_TOP:
            if lo > 0:
                frags.append(f"{lo}+")
        else:
            frags.append(f"{lo}-{hi}")
    return ", ".join(frags)


def stem_explanations(spot) -> list[dict]:
    """One entry per stem call; the meaning of each call comes from GIB
    (BBO gibrest), which interprets the auction prefix through that call.
    Silent calls get no note."""
    from . import gib_explain
    out = []
    for j, tok in enumerate(spot.stem):
        seat_i = seat_of(spot.dealer_i, j)
        card = gib_explain.card_for_auction(spot.stem[:j + 1])
        meaning = terse_meaning(card, call=tok)
        entry = {"idx": j, "seat": SEATS[seat_i], "call": tok, "card": card}
        entry["text"] = (f"{_call_name(tok)} ({SEATS[seat_i]}): {meaning}"
                         if meaning else "")
        out.append(entry)
    return out


def option_explanations(spot, verdict, policy_map, ev=None) -> list[dict]:
    """Outcome-first, terse. What each option shows (GIB's meaning of
    stem+option), where it leads and how it scores — no process narration."""
    from . import gib_explain
    cards = {}
    for b in [r["bid"] for r in verdict.table]:
        cards[b] = gib_explain.card_for_auction(spot.stem + [b])
    out = []
    for row in verdict.table:
        b = row["bid"]
        contracts = ", ".join(
            f"{contract_name(c)} {cnt / verdict.measured['n_samples']:.0%}"
            for c, cnt in row["top_contracts"])
        meaning = terse_meaning(
            cards.get(b, {"text": "", "hcp": None, "minlen": {}}), call=b)
        lines = [
            f"{_call_name(b)} — {meaning}." if meaning
            else f"{_call_name(b)}.",
            f"Leads to {contracts}.",
            f"Engine: {policy_map.get(b, 0):.0%}.",
        ]
        if b == verdict.best:
            other = [x for x in verdict.measured['top2'] if x != b]
            vs = _call_name(other[0]) if other else "the alternative"
            lines.append(
                f"Best: {verdict.measured['gap_imps']:+.1f} IMPs vs {vs} "
                f"(±{verdict.measured['ci']:.1f}), wins "
                f"{verdict.measured.get('p_top_wins', 0):.0%} of layouts.")
        else:
            lines.append(
                f"{row['ev_imp_vs_top']:+.1f} IMPs vs the top choice "
                f"(±{row['ci']:.1f}), wins {row['p_gain']:.0%}, "
                f"pushes {row['p_push']:.0%}.")
        if any(d["bid"] == b for d in verdict.dead):
            lines.append("Never the winner on any simulated layout.")
        if b == "X" and "doubled_heavy" in verdict.flags:
            lines.append("Caveat: much of this margin flows through doubled "
                         "contracts, where double-dummy defense is too good — "
                         "treat the exact number with care.")
        out.append({"bid": b, "text": " ".join(lines),
                    "card": cards.get(b)})
    return out
