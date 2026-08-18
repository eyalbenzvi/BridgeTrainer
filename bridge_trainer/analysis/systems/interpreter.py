"""Generic auction interpreter: arbitrary auction -> per-call meanings.

The existing semantics engine (semantics/engine.py) indexes rules by the
EXACT preceding call sequence — right for authored problems, unusable for
free user-entered auctions. Here the mapping is two-stage instead:

  1. classify_calls() (pure code, system-independent): derive each call's
     structural ROLE from the auction state — opening / response / rebid /
     overcall / advance / double type / informative pass — yielding a
     meaning KEY plus suit parameters (own suit, partner's suit, enemy suit).
  2. SystemTable (per-system YAML): meaning key -> HCP/suit bands, denials,
     exclusions and a Hebrew gloss. The band format (core/margin) is the
     same one semantics/rules uses, parsed with the same shape.

Keys missing from a table degrade to a documented level-based fallback and
are surfaced as transparency notes that the report prints verbatim (task
spec 3.1). Pass is a first-class call throughout (INV8).

User overrides (spec 2.3): an override for call index i REPLACES that
call's system interpretation (the user is overriding, not adding), and is
reported as a transparency note.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import numpy as np
import yaml

from ...domain.auction import (Auction, Seat, next_seat, partner_of, side_of)
from ...domain.constraints import (Band, ConstraintProfile, Denial,
                                   SeatConstraints, bands_to_weights,
                                   MAX_HCP, MAX_LEN, SUITS)
from ...semantics.predicates import PREDICATES

DENOM_ORDER = ("C", "D", "H", "S", "NT")
SUIT_HE = {"S": "♠", "H": "♥", "D": "♦", "C": "♣", "NT": "NT"}


def call_he(token: str) -> str:
    """Hebrew-friendly rendering of a call token (suit glyphs, LTR-safe)."""
    if token == "P":
        return "פאס"
    if token == "X":
        return "דאבל"
    if token == "XX":
        return "רידאבל"
    return token[0] + SUIT_HE[token[1:]]


# ---------------------------------------------------------------------------
# Dynamic predicates (registered once, reusing the semantics predicate
# mechanism the way quality_floor does).
def _takeout_shape_over(suit: str) -> str:
    name = f"takeout_shape_over_{suit}"
    if name not in PREDICATES:
        others = [s for s in "SHDC" if s != suit]

        def pred(f, suit=suit, others=tuple(others)):
            lens = f.suit_lengths
            ok = (f.hcp >= 12) & (lens[suit] <= 2)
            for o in others:
                ok = ok & (lens[o] >= 3)
            return ok
        PREDICATES[name] = pred
    return name


def _sound_overcall_outside(suit: str) -> str:
    """Opening values + a good 5-card suit outside `suit` (would overcall)."""
    name = f"sound_overcall_outside_{suit}"
    if name not in PREDICATES:
        others = [s for s in "SHDC" if s != suit]

        def pred(f, others=tuple(others)):
            good = np.zeros(len(f.cards), dtype=bool)
            for o in others:
                good |= (f.suit_lengths[o] >= 5) & (f.suit_hcp[o] >= 5)
            return (f.hcp >= 12) & good
        PREDICATES[name] = pred
    return name


def _balanced_range(lo: int, hi: int) -> str:
    name = f"balanced_{lo}_{hi}"
    if name not in PREDICATES:
        PREDICATES[name] = (
            lambda f, lo=lo, hi=hi: f.is_balanced & (f.hcp >= lo)
            & (f.hcp <= hi))
    return name


def _long_suit(n: int) -> str:
    name = f"any_suit_{n}_plus"
    if name not in PREDICATES:
        def pred(f, n=n):
            lens = np.stack([f.suit_lengths[s] for s in "SHDC"], axis=1)
            return lens.max(axis=1) >= n
        PREDICATES[name] = pred
    return name


# names usable from system YAML `exclusions:` entries, expanded lazily so a
# table can say e.g. "takeout_shape_over_$enemy".
def _resolve_exclusion(name: str, params: dict[str, str]) -> str | None:
    for sym, suit in params.items():
        name = name.replace(f"${sym}", suit)
    if "$" in name:
        return None  # unresolved symbol (e.g. no enemy suit) — skip cleanly
    if name in PREDICATES:
        return name
    if name.startswith("takeout_shape_over_"):
        return _takeout_shape_over(name.rsplit("_", 1)[1])
    if name.startswith("sound_overcall_outside_"):
        return _sound_overcall_outside(name.rsplit("_", 1)[1])
    if name.startswith("balanced_"):
        _, lo, hi = name.rsplit("_", 2)
        return _balanced_range(int(lo), int(hi))
    if name.startswith("any_suit_"):
        return _long_suit(int(name.split("_")[2]))
    if name.startswith("suit_quality_"):
        from ...semantics.predicates import quality_floor
        _, _, suit, m = name.split("_")
        return quality_floor(suit, int(m))
    raise ValueError(f"unknown exclusion predicate {name!r}")


# ---------------------------------------------------------------------------
@dataclass
class CallMeaning:
    index: int
    seat: Seat
    token: str
    key: str                       # meaning key into the system table
    he: str = ""                   # Hebrew gloss (from table / fallback)
    constraints: SeatConstraints | None = None
    is_fallback: bool = False
    is_override: bool = False
    note: str = ""                 # transparency note (Hebrew), if any
    params: dict = field(default_factory=dict)  # suit symbols -> suit letter


class SystemTable:
    """Per-system meaning table loaded from YAML."""

    def __init__(self, data: dict, source: str = "<inline>"):
        if data.get("schema_version") != 1:
            raise ValueError(f"{source}: unsupported analysis-system schema")
        self.source = source
        self.name = data["system"]
        self.he_name = data.get("he_name", self.name)
        self.meanings: dict[str, dict] = data.get("meanings", {})

    def lookup(self, key: str) -> dict | None:
        return self.meanings.get(key)


_SYSTEMS_DIR = Path(__file__).parent
SYSTEM_FILES = {"sayc": "sayc.yaml", "two_over_one": "two_over_one.yaml"}


def load_system(name: str) -> SystemTable:
    try:
        fname = SYSTEM_FILES[name]
    except KeyError:
        raise ValueError(f"unknown system {name!r}; "
                         f"available: {sorted(SYSTEM_FILES)}")
    path = _SYSTEMS_DIR / fname
    with open(path) as f:
        data = yaml.safe_load(f)
    base = data.pop("extends", None)
    if base:
        merged = dict(load_system(base).meanings)
        merged.update(data.get("meanings", {}))
        data["meanings"] = merged
    return SystemTable(data, source=str(path))


# ---------------------------------------------------------------------------
# Stage 1: structural classification (system-independent).

@dataclass
class _SeatTrack:
    bids: list[str] = field(default_factory=list)   # non-pass tokens
    suits: list[str] = field(default_factory=list)  # suits bid (no NT)
    acted: bool = False                             # made any non-pass call


def _rank(token: str) -> tuple[int, int]:
    return (int(token[0]), DENOM_ORDER.index(token[1:]))


def _is_jump(token: str, level: int, denom: str) -> bool:
    """Is `token` a jump over the standing contract (level, denom)?"""
    if level == 0:
        return int(token[0]) >= 2
    lvl, d = int(token[0]), token[1:]
    min_level = level + (1 if DENOM_ORDER.index(d) <= DENOM_ORDER.index(denom)
                         else 0)
    return lvl > min_level


def classify_calls(auction: Auction) -> list[CallMeaning]:
    """Structural meaning key + suit params for every call in the auction."""
    out: list[CallMeaning] = []
    tracks: dict[Seat, _SeatTrack] = {s: _SeatTrack() for s in "NESW"}
    opener: Seat | None = None
    opening_token = ""
    level, denom, last_bid_seat = 0, "", ""
    doubled = 0

    for i, (seat, call) in enumerate(auction.calls_with_seats()):
        tok = call.token
        me, pard = tracks[seat], tracks[partner_of(seat)]
        my_side_opened = opener is not None and side_of(seat) == side_of(opener)
        enemy_suit = ""
        if last_bid_seat and side_of(last_bid_seat) != side_of(seat):
            enemy_suit = denom if denom != "NT" else ""
        params: dict[str, str] = {}
        if enemy_suit:
            params["enemy"] = enemy_suit

        key = ""
        if tok == "P":
            key = _classify_pass(seat, opener, opening_token, my_side_opened,
                                 me, pard, level, last_bid_seat, params)
        elif tok == "X":
            key = _classify_double(seat, opener, my_side_opened, me, pard,
                                   level, denom, last_bid_seat, params)
        elif tok == "XX":
            key = "rdbl.strength" if level and doubled == 1 else "rdbl.other"
        else:  # a bid
            key = _classify_bid(tok, seat, opener, opening_token,
                                my_side_opened, me, pard, level, denom,
                                last_bid_seat, params)

        out.append(CallMeaning(index=i, seat=seat, token=tok, key=key,
                               params=params))

        # advance state
        if tok == "P":
            pass
        else:
            me.acted = True
            if tok not in ("X", "XX"):
                me.bids.append(tok)
                if tok[1:] != "NT":
                    me.suits.append(tok[1:])
                if opener is None:
                    opener, opening_token = seat, tok
                level, denom, last_bid_seat = int(tok[0]), tok[1:], seat
                doubled = 0
            elif tok == "X":
                doubled = 1
            else:
                doubled = 2
    return out


def _classify_pass(seat, opener, opening_token, my_side_opened, me, pard,
                   level, last_bid_seat, params) -> str:
    if opener is None:
        return "open.pass"
    if me.acted:
        return "pass.after_limited"
    if my_side_opened:
        if partner_of(seat) == opener and not me.acted:
            # a pass of partner's PREEMPT is "no game interest", not the
            # 0-5 a pass of a one-level opening shows
            if int(opening_token[0]) >= 2 and opening_token != "2C":
                return "resp.preempt.pass"
            if level and last_bid_seat and \
                    side_of(last_bid_seat) != side_of(seat):
                return "pass.resp_over_interference"
            return "resp.pass"
        return "pass.after_limited"
    # defender who never acted
    if me.acted:
        return "pass.after_limited"
    if level >= 3:
        return "pass.no_action_high"
    return "pass.no_direct_action"


def _classify_double(seat, opener, my_side_opened, me, pard, level, denom,
                     last_bid_seat, params) -> str:
    if level == 0 or not last_bid_seat or \
            side_of(last_bid_seat) == side_of(seat):
        return "dbl.other"
    if level >= 4:
        return "dbl.penalty_high"
    if my_side_opened and partner_of(seat) == opener and not me.acted \
            and denom != "NT" and level <= 2:
        return "dbl.negative"
    if not my_side_opened and not me.acted and not pard.acted \
            and denom != "NT" and level <= 3:
        return "dbl.takeout"
    return "dbl.other"


def _classify_bid(tok, seat, opener, opening_token, my_side_opened, me, pard,
                  level, denom, last_bid_seat, params) -> str:
    lvl, d = int(tok[0]), tok[1:]
    if d != "NT":
        params["own"] = d
    jump = _is_jump(tok, level, denom)

    # ---- openings ----------------------------------------------------
    if opener is None:
        if lvl == 1:
            if d == "NT":
                return "open.1NT"
            return "open.1M" if d in ("H", "S") else "open.1m"
        if tok == "2C":
            return "open.2C"
        if lvl == 2 and d == "NT":
            return "open.2NT"
        if lvl == 2:
            return "open.weak2"
        if lvl == 3 and d == "NT":
            return "open.bid_other"
        if lvl == 3:
            return "open.preempt3"
        if lvl == 4 and d != "NT":
            return "open.preempt4"
        return "open.bid_other"

    pard_suit = pard.suits[0] if pard.suits else ""
    if pard_suit:
        params["partner"] = pard_suit

    # ---- our side opened ----------------------------------------------
    if my_side_opened:
        if seat == opener:
            return _classify_opener_rebid(tok, lvl, d, jump, me, pard, params)
        # responder
        if not me.acted:
            return _classify_response(tok, lvl, d, jump, opening_token,
                                      params, interference=(
                                          side_of(last_bid_seat)
                                          != side_of(seat)))
        return _classify_responder_rebid(tok, lvl, d, me, pard, params)

    # ---- defending side -----------------------------------------------
    if not me.acted and not pard.acted:
        # first positive action of the side: overcall family
        if d == "NT" and lvl == 1:
            return "ovc.nt1"
        if d != "NT" and params.get("enemy") == d:
            return "ovc.cue"
        if jump:
            return "ovc.jump_weak" if lvl <= 3 else "ovc.preempt_high"
        if d == "NT":
            return "ovc.nt_other"
        return "ovc.simple1" if lvl == 1 else "ovc.simple2"
    if not me.acted and pard.acted:
        # advancer's first action; partner overcalled or doubled
        partner_doubled = not pard.bids
        if partner_doubled:
            if d == "NT":
                return "adv.x_nt"
            if params.get("enemy") == d:
                return "adv.x_strong"
            return "adv.x_jump" if jump else "adv.x_min"
        if d == pard_suit:
            return "adv.raise_jump" if jump else "adv.raise"
        if params.get("enemy") == d:
            return "adv.cue"
        if d == "NT":
            return "adv.nt"
        return "adv.new"
    # later defender actions
    if me.suits and d == me.suits[0]:
        return "ovc.rebid_suit"
    if pard_suit and d == pard_suit:
        return "adv.raise"
    return "def.bid_other"


def _classify_opener_rebid(tok, lvl, d, jump, me, pard, params) -> str:
    open_suit = me.suits[0] if me.suits else ""
    if open_suit:
        params["own_first"] = open_suit
    if d == open_suit:
        params["own"] = d
        return "reb.opener.same_jump" if jump else "reb.opener.same_min"
    if pard.suits and d == pard.suits[0]:
        params["partner"] = pard.suits[0]
        return "reb.opener.raise_jump" if jump else "reb.opener.raise"
    if d == "NT":
        return "reb.opener.nt_jump" if jump else "reb.opener.nt_min"
    # new suit
    params["own"] = d
    if jump:
        return "reb.opener.jumpshift"
    if open_suit and lvl >= 2 and \
            DENOM_ORDER.index(d) > DENOM_ORDER.index(open_suit):
        return "reb.opener.reverse"
    return "reb.opener.new"


def _classify_response(tok, lvl, d, jump, opening_token, params,
                       interference: bool) -> str:
    op_lvl, op_d = int(opening_token[0]), opening_token[1:]
    # over 1NT
    if opening_token == "1NT":
        if tok == "2C":
            return "resp.nt.stayman"
        if tok == "2D":
            params["own"] = "H"
            return "resp.nt.transfer"
        if tok == "2H":
            params["own"] = "S"
            return "resp.nt.transfer"
        if tok == "2NT":
            return "resp.nt.inv"
        if tok == "3NT":
            return "resp.nt.game"
        return "resp.nt.other"
    if op_d == "NT":
        return "resp.nt.other"
    params["partner"] = op_d
    # over a weak two / preempt
    if op_lvl >= 2 and opening_token != "2C":
        if d == op_d:
            return "resp.preempt.raise"
        if tok == "2NT" and op_lvl == 2:
            return "resp.preempt.2nt_ask"
        return "resp.preempt.other"
    if opening_token == "2C":
        return "resp.2c.waiting" if tok == "2D" else "resp.2c.positive"
    # over a one-of-a-suit opening
    if d == op_d:
        params["own"] = d
        if lvl == op_lvl + 1:
            return "resp.raise_simple"
        if lvl == op_lvl + 2:
            return "resp.raise_invite"
        return "resp.raise_game" if lvl == 4 or (lvl == 5 and d in "CD") \
            else "resp.raise_other"
    if d == "NT":
        if lvl == 1:
            return "resp.nt1_forcing" if interference is False else "resp.nt1"
        fam = "major" if op_d in ("H", "S") else "minor"
        return {2: f"resp.nt2_{fam}", 3: f"resp.nt3_{fam}"}.get(
            lvl, "resp.nt_other")
    # new suit
    if jump:
        return "resp.jumpshift"
    return "resp.new1" if lvl == 1 else "resp.new2"


def _classify_responder_rebid(tok, lvl, d, me, pard, params) -> str:
    if me.suits and d == me.suits[0]:
        params["own"] = d
        return "reb.responder.same"
    if pard.suits and d == pard.suits[0]:
        params["partner"] = pard.suits[0]
        return "reb.responder.pref"
    if d == "NT":
        return "reb.responder.nt"
    params["own"] = d
    return "reb.responder.new"


# ---------------------------------------------------------------------------
# Stage 2: meaning key -> constraints via the system table.

def _sub_suit(sym: str, params: dict[str, str]) -> str | None:
    """Resolve a YAML suit key ('$own', 'S', ...) to a suit letter."""
    if sym.startswith("$"):
        return params.get(sym[1:])
    return sym if sym in SUITS else None


def _spec_to_constraints(spec: dict, params: dict[str, str],
                         enemy_suits: set[str]) -> SeatConstraints:
    hcp = _parse_bands(spec["hcp"]) if "hcp" in spec else None
    suits: dict[str, list[Band]] = {}
    for sym, bands in (spec.get("suits") or {}).items():
        suit = _sub_suit(sym, params)
        if suit:
            suits[suit] = _parse_bands(bands)
    denials: list[Denial] = []
    for dn in (spec.get("denials") or []):
        suit_sym = dn["suit"]
        if suit_sym == "$each_unbid_by_enemy":
            targets = [s for s in SUITS if s not in enemy_suits]
        else:
            t = _sub_suit(suit_sym, params)
            targets = [t] if t else []
        for t in targets:
            denials.append(Denial(hcp_lo=int(dn["hcp"][0]),
                                  hcp_hi=int(dn["hcp"][1]), suit=t,
                                  min_len=int(dn["min_len"]),
                                  weight=float(dn.get("weight", 0.0))))
    exclusions = [r for x in (spec.get("exclusions") or [])
                  if (r := _resolve_exclusion(x, params)) is not None]
    return SeatConstraints.from_bands(hcp=hcp, suits=suits, denials=denials,
                                      exclusions=exclusions)


def _parse_bands(spec: dict) -> list[Band]:
    bands = [Band(int(spec["core"][0]), int(spec["core"][1]), 1.0)]
    for m in spec.get("margin", []):
        bands.append(Band(int(m["range"][0]), int(m["range"][1]),
                          float(m["weight"])))
    return bands


def _fallback_meaning(token: str) -> tuple[SeatConstraints, str]:
    """Documented default for a call the system table does not cover:
    a suit bid promises 4+ cards (3 at reduced weight) and values scaling
    with the level; NT bids and doubles promise values only. Deliberately
    wide — a fallback must not over-constrain the simulation."""
    if token in ("X", "XX"):
        sc = SeatConstraints.from_bands(hcp=[Band(8, MAX_HCP),
                                             Band(6, 7, 0.4)])
        note = "הנחת ברירת מחדל: {call} מבטא ערכים (8+ נק') — ההכרזה אינה מכוסה בטבלת השיטה."
        return sc, note
    if token == "P":
        return SeatConstraints(), \
            "פאס בהקשר לא מכוסה — לא נגזרו אילוצים נוספים."
    lvl, d = int(token[0]), token[1:]
    hcp_lo = min(6 + 2 * lvl, 16)
    hcp = [Band(hcp_lo, MAX_HCP), Band(max(0, hcp_lo - 3), hcp_lo - 1, 0.35)]
    suits = None
    if d != "NT":
        suits = {d: [Band(4, MAX_LEN), Band(3, 3, 0.3)]}
    sc = SeatConstraints.from_bands(hcp=hcp, suits=suits)
    note = ("הנחת ברירת מחדל: {call} בגובה " + str(lvl) +
            " מתפרש כהכרזה טבעית (4+ קלפים בסדרה, ערכים תואמי-גובה) — "
            "הרצף אינו מכוסה בטבלת השיטה.")
    return sc, note


def _override_to_constraints(ov: dict) -> SeatConstraints:
    hcp = None
    if ov.get("hcp"):
        lo, hi = int(ov["hcp"][0]), int(ov["hcp"][1])
        hcp = [Band(lo, hi)]
    suits = {}
    for s, rng in (ov.get("suits") or {}).items():
        if s in SUITS and rng:
            suits[s] = [Band(int(rng[0]), int(rng[1]))]
    return SeatConstraints.from_bands(hcp=hcp, suits=suits or None)


@dataclass
class InterpretedAuction:
    meanings: list[CallMeaning]
    profile: ConstraintProfile             # concealed seats only
    transparency_notes: list[str] = field(default_factory=list)


def interpret_auction(
    auction: Auction,
    my_seat: Seat,
    our_table: SystemTable,
    opps_table: SystemTable | None = None,
    overrides: dict[int, dict] | None = None,
) -> InterpretedAuction:
    """Meanings for every call + merged constraints for concealed seats.

    overrides: call index -> {"hcp": [lo,hi], "suits": {"S": [lo,hi], ...},
    "note": str}. Structured fields replace the system meaning for that
    call; the free-text note only reaches the report (no LLM in the compute
    layer — spec 1).
    """
    opps_table = opps_table or our_table
    overrides = overrides or {}
    meanings = classify_calls(auction)
    profile = ConstraintProfile()
    notes: list[str] = []
    my_side = side_of(my_seat)

    # enemy suits per side, for $each_unbid_by_enemy expansion
    suits_by_side: dict[str, set[str]] = {"NS": set(), "EW": set()}
    for seat, call in auction.calls_with_seats():
        if call.is_bid and call.denom != "NT":
            suits_by_side[side_of(seat)].add(call.denom)

    for m in meanings:
        table = our_table if side_of(m.seat) == my_side else opps_table
        entry = table.lookup(m.key)
        che = call_he(m.token)
        ov = overrides.get(m.index)

        if ov is not None and (ov.get("hcp") or ov.get("suits")
                               or ov.get("note")):
            m.is_override = True
            if ov.get("hcp") or ov.get("suits"):
                m.constraints = _override_to_constraints(ov)
                m.he = ov.get("note") or "משמעות מותאמת אישית"
                m.note = (f"הכרזה #{m.index + 1} ({che}) פורשה לפי הסכם "
                          f"אישי של המשתמש" +
                          (f": {ov['note']}" if ov.get("note") else "."))
            else:
                # note-only override: keep system constraints, add the note
                if entry is not None:
                    m.he = entry.get("he", "").format(call=che)
                    m.constraints = _spec_to_constraints(
                        entry.get("constraints", {}), m.params,
                        suits_by_side["EW" if side_of(m.seat) == "NS"
                                      else "NS"])
                m.note = f"הערת המשתמש על {che}: {ov['note']}"
            notes.append(m.note)
        elif entry is not None:
            m.he = entry.get("he", "").format(call=che)
            enemy_of_seat = suits_by_side["EW" if side_of(m.seat) == "NS"
                                          else "NS"]
            m.constraints = _spec_to_constraints(
                entry.get("constraints", {}), m.params, enemy_of_seat)
        else:
            sc, note_tpl = _fallback_meaning(m.token)
            m.constraints = sc
            m.is_fallback = True
            m.he = "פרשנות ברירת מחדל"
            m.note = note_tpl.format(call=che)
            if m.seat != my_seat:
                notes.append(f"הכרזה #{m.index + 1} ({che} של {m.seat}): "
                             + m.note)

        if m.seat != my_seat and m.constraints is not None:
            if m.seat in profile.seats:
                profile.seats[m.seat] = profile.seats[m.seat].merge(
                    m.constraints)
            else:
                profile.seats[m.seat] = m.constraints
            if m.is_fallback:
                profile.unrecognized_calls.append(
                    f"{m.seat}:{m.token}@{m.index} [{table.name}]")

    return InterpretedAuction(meanings=meanings, profile=profile,
                              transparency_notes=notes)
