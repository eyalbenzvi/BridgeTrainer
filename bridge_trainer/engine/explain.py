"""Explanations: given-bidding meaning bands + option explanations.
All computed (samples + auction mechanics + evaluation numbers), never
asserted — docs/ben_execution_plan.md §3.3 + v2 amendments 1, 2, 9, 11.

Display grammar (BBO alert-card style, ux/bridge panel redesign): terse
comma-separated fragments — optional convention name, suit lengths, HCP
band — never prose. "6+♣, 10-12", "3+♦, 11-21", a limited pass is "11-"
(an upper bound only, mirroring the "11+" form — never "0-11", which
claims a floor of zero the gloss never stated).

A call's note shows what the SEAT has shown by that point in the auction,
not what GIB says about that one call in isolation — see
``merge_promises``.
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


def _intersect(prev, cur):
    """Intersect two point bands (HCP or total points). ``None`` means "this
    call said nothing", so the other band stands. Where the two cannot both be
    true — GIB glossed the two calls as different systemic hands — the CURRENT
    call wins: it is the one being explained."""
    if prev is None or cur is None:
        return cur if prev is None else tuple(prev)
    lo = max(int(prev[0]), int(cur[0]))
    hi = min(int(prev[1]), int(cur[1]))
    return (lo, hi) if lo <= hi else tuple(cur)


def merge_promises(prev: dict | None, card: dict) -> dict:
    """``card`` with everything the SAME SEAT has already shown folded in.

    GIB glosses each call in isolation, and an upper-bound-only clause
    ("21- HCP" on a reverse, "16- total points" on a pass) parses to (0, 21)
    — a floor of zero the seat's own earlier bidding has usually already
    refuted. On lead1-b8b58ea96 (1♣-P-1♥-P-2♦-P-4♥) North's 2♦ was displayed
    "Opener reverse, 5+♣, 4+♦, 0-21" two calls after its 1♣ opening was
    displayed "11-21", and the final pass repeated the 0.

    A hand does not change during the auction, so a seat's constraints
    INTERSECT: the highest floor and the lowest ceiling it has shown are both
    true of it on every later call. Only hand facts accumulate — the
    convention name, the raw gloss and the ``forcing`` flag describe THIS
    call and come from it alone (a force is discharged by an opponent's bid,
    and ``explain_check`` reads the flag as a live commitment).
    """
    if not prev:
        return dict(card)
    out = dict(card)
    out["hcp"] = _intersect(prev.get("hcp"), card.get("hcp"))
    out["pts"] = _intersect(prev.get("pts"), card.get("pts"))
    minlen = dict(card.get("minlen") or {})
    maxlen = dict(card.get("maxlen") or {})
    for st in "SHDC":
        lo = max(minlen.get(st, 0), (prev.get("minlen") or {}).get(st, 0))
        hi = min(maxlen.get(st, 13), (prev.get("maxlen") or {}).get(st, 13))
        if lo > hi:
            continue          # contradictory glosses — this call's own stands
        if lo:
            minlen[st] = lo
        if hi < 13:
            maxlen[st] = hi
    out["minlen"], out["maxlen"] = minlen, maxlen
    return out


def accumulated_cards(dealer_i: int, cards: list[dict]) -> list[dict]:
    """``cards`` (one per call, in auction order) with each seat's earlier
    promises folded into its later calls — what the trainee is shown."""
    state: dict[int, dict] = {}
    out = []
    for j, card in enumerate(cards):
        seat_i = seat_of(dealer_i, j)
        state[seat_i] = merge_promises(state.get(seat_i), card or {})
        out.append(state[seat_i])
    return out


def seat_promises(dealer_i: int, cards: list[dict],
                  seat_i: int) -> dict | None:
    """Everything ``seat_i`` has shown over ``cards`` — the state a further
    call by that seat (an offered option) is merged into."""
    state = None
    for j, card in enumerate(cards):
        if seat_of(dealer_i, j) == seat_i:
            state = merge_promises(state, card or {})
    return state


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
    pts = card.get("pts")
    hcp_floor = 0
    if hcp:
        lo, hi = int(hcp[0]), int(hcp[1])
        hcp_floor = lo
        if hi >= _HCP_OPEN_TOP:
            if lo > 0:
                frags.append(f"{lo}+")
        else:
            frags.append(_band(lo, hi))
    # the total-points band shows when GIB gave no HCP band at all — without
    # this a limited pass ("No suitable call -- 8- total points") rendered with
    # no range whatsoever, which read as a missing explanation — and ALSO when
    # the HCP band has no floor while the points band does: on lead1-b8b58ea96
    # South's 4♥ is glossed "10- HCP" alone, three calls after its 1♥ promised
    # 6+ total points, and dropping that floor left "10-" reading as a hand
    # that might hold nothing.
    if pts and (not hcp or (hcp_floor <= 0 and int(pts[0]) > 0)):
        lo, hi = int(pts[0]), int(pts[1])
        if hi >= _HCP_OPEN_TOP:
            if lo > 0:
                frags.append(f"{lo}+ pts")
        else:
            frags.append(f"{_band(lo, hi)} pts")
    return ", ".join(frags)


def _band(lo: int, hi: int) -> str:
    """A point band as a trainee should read it: "11-14", but a one-point band
    as the single number it is. GIB emits "9-9"/"24-24"/"0-0" where its rule
    pinned the count exactly, and rendering that as a RANGE claimed a precision
    the source never had — 157 published calls said things like "9-9" over a
    seven-count.

    A band with no floor is an upper bound, and says so: "10-", the mirror of
    the "10+" already used at the other end. GIB's "10- HCP" never claimed the
    hand could be worthless, and "0-10" read as a range that contradicted
    whatever the seat had already promised."""
    if lo == hi:
        return str(lo)
    return f"{hi}-" if lo <= 0 else f"{lo}-{hi}"


def stem_explanations(spot) -> list[dict]:
    """One entry per stem call; the meaning of each call comes from GIB
    (BBO gibrest), which interprets the auction prefix through that call.
    Silent calls get no note.

    ``card`` stays GIB's card for that call alone — the gates check the gloss
    of each call against the hand that made it — while ``text`` is rendered
    from the seat's ACCUMULATED promises (``merge_promises``), which is what a
    trainee reading the auction needs."""
    from . import gib_explain
    cards = [gib_explain.card_for_auction(spot.stem[:j + 1])
             for j in range(len(spot.stem))]
    shown = accumulated_cards(spot.dealer_i, cards)
    out = []
    for j, tok in enumerate(spot.stem):
        seat_i = seat_of(spot.dealer_i, j)
        meaning = terse_meaning(shown[j], call=tok)
        entry = {"idx": j, "seat": SEATS[seat_i], "call": tok,
                 "card": cards[j]}
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
    # an option is one more call by the hero, so it is displayed with the
    # hero's own earlier promises folded in (stem cards are already cached)
    stem_cards = [gib_explain.card_for_auction(spot.stem[:j + 1])
                  for j in range(len(spot.stem))]
    hero_state = seat_promises(spot.dealer_i, stem_cards, spot.hero_i)
    out = []
    for row in verdict.table:
        b = row["bid"]
        contracts = ", ".join(
            f"{contract_name(c)} {cnt / verdict.measured['n_samples']:.0%}"
            for c, cnt in row["top_contracts"])
        meaning = terse_meaning(
            merge_promises(hero_state,
                           cards.get(b, {"text": "", "hcp": None,
                                         "minlen": {}})), call=b)
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
