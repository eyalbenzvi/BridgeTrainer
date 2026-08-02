"""Auction-inference constraints from the GIB explanation cards.

Motivation (board ``lead1-19fa5daef4b``, 3NT-N after 1C-2C; 2D-3NT, East
leads from AQJ754.Q.T975.76): the production verdict (SA, +0.51 over SQ) was
measured on Ben's neural-consistency samples, in which the missing spade K
sat with DUMMY 48% of the time and with DECLARER only 42% — although
declarer's own 3NT explicitly announced a partial spade stop, and 57% of the
samples ignored the 3NT card's 14-18 HCP range. Re-sampling under the
auction's stated constraints moves the answer: at P(SK with declarer)=0.8 the
SA margin more than halves and the runner-up becomes a passive diamond; at
P(SK)=1.0 the ace lead LOSES 0.33 tricks to HQ and ~0.39 to a diamond. The
published single answer is thus an artifact of where the uncalibrated sampler
puts one key honor. See ``docs/lead_auction_inference_gap.md``.

The generalisable fix: every published problem already stores, per call, a
machine-readable GIB card — ``explanations.auction[].card`` with
``hcp``/``pts``/``minlen``/``maxlen`` plus the raw meaning string whose
``stop in !X`` / ``partial stop in !X`` clauses the parser keeps in
``gib_raw``. This module turns those cards into a ``ConstraintProfile`` for
the existing ``ConstraintSampler``, so ANY stored lead problem (and any new
board at forge time) can be graded under a distribution that honours what the
auction explicitly said — with no dependency on the hand-authored YAML
rulesets' coverage.

Coverage: the compiler handles the COMPLETE measured GIB vocabulary — 94
distinct clause patterns over 91,910 instances in the production pool
(fixture: tests/data/gib_vocab_patterns.json) — lengths/HCP/points via the
parsed card fields; stops (full/partial/likely/at-best/two) as leader-
relative suit-quality bands; specific honor holdings (``!CKQ``, ``no
!DAK``, ``Q+ in !D``) as HonorSpec primitives; ``!SAKQ,no !S`` as an
alternatives (disjunction) group; solid/exact/strong suit qualities; and
auction facts as recognised no-ops. Soft miss weights are CALIBRATED
likelihood ratios measured on real deals (semantics/gib_calibration.json,
regenerate with scripts/calibrate_gib_vocab.py), scaled by the reading
strength (``stop_miss_scale=0`` = strict).

Honest labelling, same contract as ConstraintSampler: this is a modelled
prior, NOT a calibrated deal posterior. Known limitation: negative
inferences from calls NOT chosen ("responder chose 2D over 2NT, so he
lacks one of the three side stops or is unbalanced") are not auto-derived —
the DSL can now express them (alt_groups), but nothing compiles them yet;
the chosen calls' own annotations carry most of that information.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from ..domain.constraints import (
    MAX_SUIT_HCP, Band, ConstraintProfile, Denial, HonorSpec, SeatConstraints)

SUITS = ("S", "H", "D", "C")
HONOR_HCP = {"A": 4, "K": 3, "Q": 2, "J": 1}

# GIB writes "stop in !D", "partial stop in !S", "likely stop in !H".
_STOP = re.compile(r"(partial\s+|likely\s+)?stop in !([SHDC])", re.I)

# Modelled-prior weights: how much mass stays on "announced X but does not
# actually hold it" — nonzero on purpose (players do bid 3NT on 'just a
# balanced hand' when no alternative call exists). These are DEFAULTS; the
# calibration file (semantics/gib_calibration.json, written by
# scripts/calibrate_gib_vocab.py) overrides them per clause kind with
# likelihood ratios measured on real deals.
DEFAULT_MISS_WEIGHTS = {
    "stop": 0.15,
    "partial_stop": 0.35,          # 'likely stop' counts as partial
    "at_best_partial": 0.15,       # weight on "actually holds a FULL stop"
    "two_stops": 0.15,
    "honor_all": 0.05,             # '!CKQ' — near-definitional promises
    "honor_any": 0.10,             # 'Q+ in !D'
    "honor_none": 0.05,            # 'no !DAK'
    "solid": 0.05,                 # 'solid 6-card !S'
    "alt_group": 0.05,             # floor when no alternative matches
    "strong_rebiddable": 0.30,     # quality margin for 'strong rebiddable'
}
FULL_STOP_MISS_WEIGHT = DEFAULT_MISS_WEIGHTS["stop"]
PARTIAL_STOP_MISS_WEIGHT = DEFAULT_MISS_WEIGHTS["partial_stop"]
# Silence denial: a concealed seat that only ever passed after an enemy
# opening rarely holds a sound overcall (decent 5-card suit + values).
SILENCE_DENIAL = dict(hcp_lo=9, hcp_hi=16, min_len=5, weight=0.2)
# Bidders stretch: HCP core bands get a +-1 margin at this weight.
HCP_MARGIN_WEIGHT = 0.3

CALIBRATION_PATH = (Path(__file__).resolve().parent.parent / "semantics"
                    / "gib_calibration.json")


@lru_cache(maxsize=1)
def _calibrated_weights() -> dict:
    """DEFAULT_MISS_WEIGHTS overridden by the checked-in calibration file
    (measured likelihood ratios), when present."""
    weights = dict(DEFAULT_MISS_WEIGHTS)
    try:
        data = json.loads(CALIBRATION_PATH.read_text())
    except (OSError, ValueError):
        return weights
    for kind, entry in data.items():
        w = (entry or {}).get("weight")
        if kind in weights and isinstance(w, (int, float)) and 0 <= w < 1:
            weights[kind] = float(w)
    return weights


# Runtime overrides on top of the checked-in calibration — set by the
# backward-migration script after it RE-calibrates on the gloss-validated
# subset of the pool, so regrading uses the post-validation weights without
# touching the repo file in a dry run.
_RUNTIME_OVERRIDES: dict[str, float] = {}


def set_calibration_overrides(weights: dict | None) -> None:
    """Override calibrated miss weights for this process (None/{} clears).
    Values outside [0, 1) are ignored."""
    _RUNTIME_OVERRIDES.clear()
    for kind, w in (weights or {}).items():
        if kind in DEFAULT_MISS_WEIGHTS and isinstance(w, (int, float)) \
                and 0 <= w < 1:
            _RUNTIME_OVERRIDES[kind] = float(w)


def miss_weight(kind: str, miss_scale: float = 1.0) -> float:
    """Calibrated miss weight for a clause kind, scaled by the reading
    strength (miss_scale=0 -> strict: announcements taken literally)."""
    base = _RUNTIME_OVERRIDES.get(kind)
    if base is None:
        base = _calibrated_weights()[kind]
    return base * miss_scale


def stop_threshold(leader_holding: str) -> int:
    """Minimum suit-HCP a concealed seat must hold for its announced stop to
    be a real one, GIVEN the honors the leader can see in his own hand.

    The cheapest missing top honor is what a stop is made of: missing the K
    (leader has AQJ...) => the stop is the K, threshold 3; missing only the
    Q => Qxx, threshold 2; nothing above the T missing => length stops only,
    threshold 0 (no band constraint possible).
    """
    missing = [h for h in "AKQJ" if h not in leader_holding.upper()]
    if not missing:
        return 0
    return min(HONOR_HCP[h] for h in missing)


def stop_bands(leader_holding: str, partial: bool,
               miss_scale: float = 1.0) -> list[Band] | None:
    """suit-HCP bands for an announced (partial) stop, or None when the
    leader's own honors make the announcement untestable by HCP.

    ``miss_scale`` scales the mass left on "announced but doesn't hold it";
    0 is the STRICT reading (the announcement is taken literally). The
    default/strict pair is the interpretation-strength sweep the regrade
    audit uses — a winner that changes between the two readings is
    honor-location-sensitive and must not ship as a single answer."""
    thr = stop_threshold(leader_holding)
    if thr <= 0:
        return None
    miss_w = miss_weight("partial_stop" if partial else "stop", miss_scale)
    bands = [Band(thr, MAX_SUIT_HCP)]
    if thr >= 1 and miss_w > 0:
        bands.append(Band(0, thr - 1, min(miss_w, 1.0)))
    return bands


def two_stop_bands(leader_holding: str,
                   miss_scale: float = 1.0) -> list[Band] | None:
    """'two stops in !X': the seat covers the suit twice — threshold is the
    sum of the two cheapest missing honors (falls back to a single stop when
    only one honor is out)."""
    missing = sorted(HONOR_HCP[h] for h in "AKQJ"
                     if h not in leader_holding.upper())
    if not missing:
        return None
    thr = min(sum(missing[:2]), MAX_SUIT_HCP)
    miss_w = miss_weight("two_stops", miss_scale)
    bands = [Band(thr, MAX_SUIT_HCP)]
    if thr >= 1 and miss_w > 0:
        bands.append(Band(0, thr - 1, min(miss_w, 1.0)))
    return bands


def at_best_partial_bands(leader_holding: str,
                          miss_scale: float = 1.0) -> list[Band] | None:
    """'at best partial stop in !X' — a NEGATIVE promise: the seat does NOT
    hold a full stop. The inverse of stop_bands: core mass below the stop
    threshold, reduced mass on 'actually holds it after all'."""
    thr = stop_threshold(leader_holding)
    if thr <= 0:
        return None
    miss_w = miss_weight("at_best_partial", miss_scale)
    bands = [Band(0, thr - 1)] if thr >= 1 else []
    if miss_w > 0:
        bands.append(Band(thr, MAX_SUIT_HCP, min(miss_w, 1.0)))
    return bands or None


def stops_in_card(card: dict) -> list[tuple[str, bool]]:
    """[(suit, is_partial)] stop announcements in one GIB card's raw string.
    'likely stop' counts as partial; 'at best partial stop' is a different,
    NEGATIVE clause and is deliberately not matched here."""
    raw = (card or {}).get("gib_raw") or ""
    out = []
    for c in _clauses(raw):
        m = _STOP.fullmatch(c)
        if m:
            out.append((m.group(2).upper(), bool(m.group(1))))
    return out


# ---------------------------------------------------------------------------
# the full GIB clause vocabulary (measured over the whole pool: 94 distinct
# patterns; see docs/lead_auction_inference_gap.md). Clauses that
# parse_meaning already folds into the card's hcp/pts/minlen/maxlen fields
# are recognised NO-OPs here, as are pure auction facts ("forcing to 3N").
# ---------------------------------------------------------------------------
_RE_HONORS = re.compile(r"^!([SHDC])([AKQJT]+)$")               # !CKQ
_RE_HONORS_OR_VOID = re.compile(                                # !SAKQ,no !S
    r"^!([SHDC])([AKQJT]+),\s*no !([SHDC])$")
_RE_NO_HONORS = re.compile(r"^no !([SHDC])([AKQJT]+)$")         # no !DAK
_RE_HONOR_PLUS = re.compile(r"^([AKQJT])\+ in !([SHDC])$")      # Q+ in !D
_RE_CARD_EXACT = re.compile(r"^(\d+)-card !([SHDC])$")          # 3-card !D
_RE_SOLID = re.compile(r"^solid (\d+)-card !([SHDC])$")         # solid 6-card
_RE_STRONG_REBID = re.compile(r"^strong rebiddable !([SHDC])$")
_RE_TWO_STOPS = re.compile(r"^two stops in !([SHDC])$")
_RE_AT_BEST = re.compile(r"^at best partial stop in !([SHDC])$")
# recognised, but carrying no hand constraint (auction facts / already in
# the parsed card fields via parse_meaning)
_NOOP_RES = [
    re.compile(r"^forcing( to \d+[NSHDC])?$"),
    re.compile(r"^game force$"),
    re.compile(r"^opponents cannot play undoubled below \d+N$"),
    re.compile(r"^\d+- losers$"),
    re.compile(r"^\d+(-\d+)?\s*[+-]?\s*!([SHDC])$"),            # suit ranges
    re.compile(r"^\d+(-\d+)?\s*[+-]?\s*HCP$", re.I),
    re.compile(r"^\d+(-\d+)?\s*[+-]?\s*total points$", re.I),
    re.compile(r"^(twice rebiddable|rebiddable|biddable) !([SHDC])$"),
]


def _clauses(raw: str) -> list[str]:
    body = raw.split("--", 1)[-1] if "--" in raw else raw
    return [c.strip() for c in body.split(";") if c.strip()]


def _honor_ranks_vs_leader(ranks: str, leader_holding: str):
    """Split promised ranks into (still promisable, contradicted-by-leader).
    A rank the LEADER holds cannot be in the concealed hand: the gloss is
    contradicted there and the spec degrades gracefully (reported, never a
    zero-mass constraint)."""
    held = set(leader_holding.upper())
    promisable = "".join(r for r in ranks if r not in held)
    contradicted = "".join(r for r in ranks if r in held)
    return promisable, contradicted


def compile_clause(clause: str, leader_suits: list[str],
                   miss_scale: float = 1.0) -> dict | None:
    """One raw GIB clause -> a constraint effect, or None when unrecognised.

    The effect dict may carry: ``suits`` / ``suit_hcp`` (suit -> band list),
    ``honor_specs`` (list), ``alt_groups`` (list of groups), and
    ``contradicted`` (clause text whose promise the leader's own hand makes
    impossible — reported upward, constraint skipped). A recognised no-op
    returns an empty dict."""
    for r in _NOOP_RES:
        if r.match(clause):
            return {}

    m = _STOP.fullmatch(clause)
    if m:
        suit = m.group(2).upper()
        bands = stop_bands(leader_suits[SUITS.index(suit)], bool(m.group(1)),
                           miss_scale=miss_scale)
        return {"suit_hcp": {suit: bands}} if bands else {}

    m = _RE_AT_BEST.match(clause)
    if m:
        suit = m.group(1)
        bands = at_best_partial_bands(leader_suits[SUITS.index(suit)],
                                      miss_scale=miss_scale)
        return {"suit_hcp": {suit: bands}} if bands else {}

    m = _RE_TWO_STOPS.match(clause)
    if m:
        suit = m.group(1)
        bands = two_stop_bands(leader_suits[SUITS.index(suit)],
                               miss_scale=miss_scale)
        return {"suit_hcp": {suit: bands}} if bands else {}

    m = _RE_HONORS_OR_VOID.match(clause)
    if m and m.group(1) == m.group(3):
        suit, ranks = m.group(1), m.group(2)
        promisable, contradicted = _honor_ranks_vs_leader(
            ranks, leader_suits[SUITS.index(suit)])
        if not promisable:
            return {"contradicted": clause}
        floor = max(miss_weight("alt_group", miss_scale), 0.0)
        group = [
            SeatConstraints.from_bands(honor_specs=[
                HonorSpec(suit, promisable, "all", 0.0)]),
            SeatConstraints.from_bands(suits={suit: [Band(0, 0)]}),
        ]
        if floor > 0:
            group.append(SeatConstraints.from_bands(
                hcp=[Band(0, 40, min(floor, 1.0))]))
        return {"alt_groups": [group]}

    m = _RE_HONORS.match(clause)
    if m:
        suit, ranks = m.group(1), m.group(2)
        promisable, contradicted = _honor_ranks_vs_leader(
            ranks, leader_suits[SUITS.index(suit)])
        if not promisable:
            return {"contradicted": clause}
        w = miss_weight("honor_all", miss_scale)
        return {"honor_specs": [HonorSpec(suit, promisable, "all", w)]}

    m = _RE_NO_HONORS.match(clause)
    if m:
        suit, ranks = m.group(1), m.group(2)
        promisable, _ = _honor_ranks_vs_leader(
            ranks, leader_suits[SUITS.index(suit)])
        if not promisable:      # leader holds them all: trivially true
            return {}
        w = miss_weight("honor_none", miss_scale)
        return {"honor_specs": [HonorSpec(suit, promisable, "none", w)]}

    m = _RE_HONOR_PLUS.match(clause)
    if m:
        floor_rank, suit = m.group(1), m.group(2)
        order = "AKQJT"
        ranks = order[:order.index(floor_rank) + 1]
        promisable, _ = _honor_ranks_vs_leader(
            ranks, leader_suits[SUITS.index(suit)])
        if not promisable:
            return {"contradicted": clause}
        w = miss_weight("honor_any", miss_scale)
        return {"honor_specs": [HonorSpec(suit, promisable, "any", w)]}

    m = _RE_CARD_EXACT.match(clause)
    if m:
        n, suit = int(m.group(1)), m.group(2)
        return {"suits": {suit: [Band(n, n)]}}

    m = _RE_SOLID.match(clause)
    if m:
        n, suit = int(m.group(1)), m.group(2)
        effect = {"suits": {suit: [Band(n, min(n + 1, 13))]}}
        promisable, contradicted = _honor_ranks_vs_leader(
            "AKQ", leader_suits[SUITS.index(suit)])
        if promisable:
            w = miss_weight("solid", miss_scale)
            effect["honor_specs"] = [HonorSpec(suit, promisable, "all", w)]
        else:
            effect["contradicted"] = clause
        return effect

    m = _RE_STRONG_REBID.match(clause)
    if m:
        suit = m.group(1)
        margin = miss_weight("strong_rebiddable", 1.0)
        bands = [Band(5, MAX_SUIT_HCP)]
        if margin > 0:
            bands.append(Band(3, 4, min(margin, 1.0)))
        return {"suits": {suit: [Band(5, 13)]}, "suit_hcp": {suit: bands}}

    return None


def clause_kind(clause: str) -> str | None:
    """The calibration bucket a clause belongs to, or None for hard /
    no-op clauses (lengths, HCP, auction facts) that need no calibration."""
    if _RE_AT_BEST.match(clause):
        return "at_best_partial"
    if _RE_TWO_STOPS.match(clause):
        return "two_stops"
    m = _STOP.fullmatch(clause)
    if m:
        return "partial_stop" if m.group(1) else "stop"
    if _RE_HONORS_OR_VOID.match(clause):
        return "alt_group"
    if _RE_HONORS.match(clause):
        return "honor_all"
    if _RE_NO_HONORS.match(clause):
        return "honor_none"
    if _RE_HONOR_PLUS.match(clause):
        return "honor_any"
    if _RE_SOLID.match(clause):
        return "solid"
    if _RE_STRONG_REBID.match(clause):
        return "strong_rebiddable"
    return None


def _hand_suit_hcp(hand_pbn: str, suit: str) -> int:
    holding = hand_pbn.split(".")[SUITS.index(suit)]
    return sum(HONOR_HCP.get(c, 0) for c in holding.upper())


def _spec_satisfied(spec: HonorSpec, hand_pbn: str) -> bool:
    holding = set(hand_pbn.split(".")[SUITS.index(spec.suit)].upper())
    held = [r in holding for r in spec.ranks]
    if spec.mode == "all":
        return all(held)
    if spec.mode == "any":
        return any(held)
    return not any(held)


def clause_core_satisfied(clause: str, leader_hand: str,
                          seat_hand: str) -> bool | None:
    """Does *seat_hand* satisfy the CORE (weight-1.0) region of *clause*,
    compiled relative to *leader_hand*? None when the clause compiles to no
    testable constraint. This is the measurement primitive the calibration
    script uses: p = P(core satisfied | clause announced) on real deals."""
    effect = compile_clause(clause, leader_hand.split("."), miss_scale=1.0)
    if not effect or effect.get("contradicted"):
        return None

    def core_ok(bands, value):
        return any(b.lo <= value <= b.hi and b.weight >= 0.999
                   for b in bands)

    checks = []
    for suit, bands in (effect.get("suit_hcp") or {}).items():
        checks.append(core_ok(bands, _hand_suit_hcp(seat_hand, suit)))
    for suit, bands in (effect.get("suits") or {}).items():
        checks.append(core_ok(
            bands, len(seat_hand.split(".")[SUITS.index(suit)])))
    for spec in effect.get("honor_specs") or []:
        checks.append(_spec_satisfied(spec, seat_hand))
    for group in effect.get("alt_groups") or []:
        def alt_ok(alt):
            ok = all(_spec_satisfied(s, seat_hand) for s in alt.honor_specs)
            for suit in SUITS:
                ln = len(seat_hand.split(".")[SUITS.index(suit)])
                ok &= bool(alt.suit_weights[suit][ln] >= 0.999)
            return ok
        # a constant-floor alternative (hcp weight < 1 everywhere) is the
        # soft escape hatch, not a core option — exclude it from "satisfied"
        checks.append(any(alt_ok(alt) for alt in group
                          if alt.hcp_weights.max() >= 0.999))
    if not checks:
        return None
    return all(checks)


def _card_is_empty(card: dict) -> bool:
    return not card or (card.get("hcp") is None and card.get("pts") is None
                        and not card.get("minlen") and not card.get("maxlen")
                        and not (card.get("gib_raw") or "").strip())


def compile_card(card: dict, leader_hand: str,
                 miss_scale: float = 1.0) -> tuple[SeatConstraints, dict]:
    """One call's GIB card -> (SeatConstraints, diagnostics).

    * ``hcp (lo, hi)`` -> core band with a +-1 stretch margin;
    * ``pts (lo, hi)`` (total points) -> only the UPPER bound binds HCP
      (distribution points inflate the total, never deflate it);
    * ``minlen``/``maxlen`` -> hard per-suit length bands (GIB length
      promises are definitional: '3- !S' in an inverted raise IS the call);
    * every other clause of the raw meaning string goes through
      ``compile_clause`` — the full measured GIB vocabulary: stops (full /
      partial / likely / at-best-partial / two), specific honor holdings
      (``!CKQ``, ``no !DAK``, ``Q+ in !D``), honor-or-void alternatives
      (``!SAKQ,no !S``) and exact / solid / strong suit qualities.

    Clause effects are merged MULTIPLICATIVELY (conjunction), so an exact
    '6-card !S' narrows a '4+ !S' from the parsed fields instead of
    widening it. diagnostics: {"unrecognized": [...], "contradicted": [...]}
    — both degrade gracefully (reported upward, never dropped silently).
    """
    hcp_bands = None
    hcp = card.get("hcp")
    pts = card.get("pts")
    if hcp:
        lo, hi = int(hcp[0]), int(hcp[1])
        hcp_bands = [Band(lo, hi)]
        if lo > 0:
            hcp_bands.append(Band(max(lo - 1, 0), lo - 1, HCP_MARGIN_WEIGHT))
        if hi < 37:
            hcp_bands.append(Band(hi + 1, min(hi + 1, 40), HCP_MARGIN_WEIGHT))
    elif pts and int(pts[1]) < 37:
        hcp_bands = [Band(0, int(pts[1]))]

    suits = {}
    minlen = card.get("minlen") or {}
    maxlen = card.get("maxlen") or {}
    for s in SUITS:
        lo = int(minlen.get(s, 0))
        hi = int(maxlen.get(s, 13))
        if (lo, hi) != (0, 13):
            suits[s] = [Band(lo, hi)]

    sc = SeatConstraints.from_bands(hcp=hcp_bands, suits=suits or None)
    diag = {"unrecognized": [], "contradicted": []}
    leader_suits = leader_hand.split(".")
    for clause in _clauses((card or {}).get("gib_raw") or ""):
        effect = compile_clause(clause, leader_suits, miss_scale=miss_scale)
        if effect is None:
            diag["unrecognized"].append(clause)
            continue
        if effect.get("contradicted"):
            diag["contradicted"].append(effect["contradicted"])
        if effect.get("suits") or effect.get("suit_hcp") \
                or effect.get("honor_specs") or effect.get("alt_groups"):
            sc = sc.merge(SeatConstraints.from_bands(
                suits=effect.get("suits"),
                suit_hcp=effect.get("suit_hcp"),
                honor_specs=effect.get("honor_specs"),
                alt_groups=effect.get("alt_groups")))
    return sc, diag


def seat_constraints_from_card(card: dict, leader_hand: str,
                               miss_scale: float = 1.0) -> SeatConstraints:
    """Back-compat wrapper over ``compile_card`` (diagnostics dropped)."""
    return compile_card(card, leader_hand, miss_scale=miss_scale)[0]


def profile_from_explained_auction(entries: list[dict], leader: str,
                                   leader_hand: str,
                                   silence_denials: bool = True,
                                   stop_miss_scale: float = 1.0,
                                   ) -> ConstraintProfile:
    """``explanations.auction`` (idx/seat/call/card per call) -> a
    ConstraintProfile over the three concealed seats.

    Each concealed seat's cards are merged multiplicatively (conjunction),
    exactly like the rule engine's profiles. Calls whose card parsed to
    nothing are reported in ``unrecognized_calls`` — graceful degradation,
    same contract as ``constraint_profile_from_auction``.

    ``silence_denials`` adds the negative inference of silence: a concealed
    seat whose calls were ALL passes, seated after an enemy opening, is
    discounted for sound-overcall hands in every unbid suit (weight
    ``SILENCE_DENIAL['weight']``, never 0 — a trap pass exists).
    """
    seats: dict[str, SeatConstraints] = {}
    unrecognized: list[str] = []
    contradicted: list[str] = []
    opened_suit = None
    opener_side_seats: set[str] = set()
    for e in entries:
        seat, call, card = e.get("seat"), e.get("call"), e.get("card") or {}
        if opened_suit is None and call not in ("P", "X", "XX"):
            opened_suit = call[1:] if call[1:] in SUITS else None
            opener_side_seats = {seat, _partner(seat)}
        if seat == leader:
            continue
        if _card_is_empty(card):
            if call != "P":     # an unexplained PASS constrains nothing anyway
                unrecognized.append(f"{seat}:{call}")
            continue
        sc, diag = compile_card(card, leader_hand,
                                miss_scale=stop_miss_scale)
        unrecognized.extend(f"{seat}:{call}:{c}"
                            for c in diag["unrecognized"])
        contradicted.extend(f"{seat}:{call}:{c}"
                            for c in diag["contradicted"])
        seats[seat] = seats[seat].merge(sc) if seat in seats else sc

    if silence_denials:
        by_seat: dict[str, list[str]] = {}
        for e in entries:
            by_seat.setdefault(e["seat"], []).append(e["call"])
        for seat, calls in by_seat.items():
            if seat == leader or seat in opener_side_seats:
                continue
            if calls and all(c == "P" for c in calls) and opened_suit:
                denials = [Denial(suit=s, **SILENCE_DENIAL)
                           for s in SUITS if s != opened_suit]
                sc = SeatConstraints.from_bands(denials=denials)
                seats[seat] = seats[seat].merge(sc) if seat in seats else sc

    profile = ConstraintProfile(seats=seats)
    profile.unrecognized_calls = unrecognized
    # gloss promises the leader's own hand makes impossible (e.g. a card
    # claiming an honor the leader holds) — reported, constraints skipped
    profile.contradicted_clauses = contradicted
    return profile


def _partner(seat: str) -> str:
    return {"N": "S", "S": "N", "E": "W", "W": "E"}.get(seat, "")


def sampler_from_record(record: dict, stop_miss_scale: float = 1.0, **kw):
    """A ready ConstraintSampler for a STORED lead problem, built from its own
    persisted explanation cards (no network, no Ben, no YAML coverage).

    ``stop_miss_scale=0`` is the strict reading (announced stops taken
    literally); the default keeps soft miss mass. Auditing under BOTH is the
    interpretation sweep that catches honor-location-sensitive verdicts."""
    from .lead_samplers import ConstraintSampler
    entries = ((record.get("explanations") or {}).get("auction")) or []
    profile = profile_from_explained_auction(
        entries, record["leader"], record["hand"],
        stop_miss_scale=stop_miss_scale)
    mode = "gib_cards" if stop_miss_scale else "gib_cards_strict"
    return ConstraintSampler(profile=profile,
                             semantic_constraint_mode=mode,
                             unrecognized_calls=profile.unrecognized_calls,
                             **kw)


# ---------------------------------------------------------------------------
# the inference gate: no lead board ships with an answer the auction refutes
# ---------------------------------------------------------------------------
# Reject when the published best lead trails the reading's winner by more
# than this many DD tricks, even if the bootstrap CI still touches 0 —
# a low-sample tie must not smuggle a refuted answer through.
REFUTE_MARGIN = 0.15
GATE_SAMPLES = 250
GATE_SECONDS = 60.0


def regrade_readings(record: dict, samples: int = GATE_SAMPLES,
                     seed: int = 1, n_boot: int = 600) -> dict:
    """Grade every lead of *record* under BOTH interpretation strengths of
    its own GIB cards: ``soft`` (default miss mass on announced stops) and
    ``strict`` (announcements taken literally). Ben-free; endplay DDS on
    physical cards. Returns {reading: {winner, means, published_delta:
    {delta, ci95, ess}, diagnostics}} — empty dict per reading when the
    constraints produced no layouts (the gate then abstains)."""
    from .lead_posterior import build_problem, delta_report, evaluate_layouts

    problem = build_problem(record["hand"], list(record["auction"]),
                            record["dealer"], record.get("vul", "None"),
                            record["contract"])
    published = (((record.get("verdict") or {}).get("accepted")) or [None])[0]
    out = {}
    for reading, scale in (("soft", 1.0), ("strict", 0.0)):
        sampler = sampler_from_record(record, stop_miss_scale=scale,
                                      max_seconds=GATE_SECONDS)
        ls = sampler.sample(problem, samples, seed)
        diag = getattr(ls, "constraint_diagnostics", {})
        if ls.n == 0 or not diag.get("any_constraint_applied"):
            out[reading] = {"diagnostics": diag}
            continue
        ev = evaluate_layouts(ls)
        means = ev.weighted_mean()
        order = ev.ranking()
        r = {"winner": order[0],
             "means": {c: round(means[c], 3) for c in order},
             "diagnostics": diag}
        if published and published in ev.def_tricks:
            dr = delta_report(ev.def_tricks[published],
                              ev.def_tricks[order[0]],
                              weight=ls.weight, n_boot=n_boot, seed=seed)
            r["published_delta"] = {"delta": dr["mean"],
                                    "ci95": dr["boot_ci95"],
                                    "ess": dr["ess"]}
        out[reading] = r
    return out


def inference_verdict(published: str | None, readings: dict) -> tuple[str, str]:
    """(status, detail) for a published single answer against the two-reading
    regrade. ONE definition, shared by the forge gate and the pool audit
    script, so they cannot drift.

    * ``inference_refuted`` — in some reading the published lead loses to
      that reading's winner decisively: the bootstrap CI excludes 0, OR the
      point loss exceeds REFUTE_MARGIN tricks. The board must not ship /
      must leave the pool: its answer is contradicted by the auction's own
      stated meaning.
    * ``honor_sensitive`` — the two readings crown different winners and at
      least one of them is not the published lead: there is no single
      answer to teach. Must not ship as a single-answer board.
    * ``abstain`` — no published answer, or neither reading produced
      constrained layouts (nothing recognisable in the auction).
    * ``stable`` — the published answer is the winner (or within noise of
      it) under BOTH readings.
    """
    graded = {k: v for k, v in readings.items() if v.get("winner")}
    if not published or not graded:
        return "abstain", "no published answer or no constrained layouts"
    for reading, r in graded.items():
        pd = r.get("published_delta")
        if pd is None:
            continue
        lo, hi = pd["ci95"]
        loses_ci = published != r["winner"] and not (lo <= 0 <= hi)
        loses_margin = pd["delta"] < -REFUTE_MARGIN
        if loses_ci or loses_margin:
            return ("inference_refuted",
                    f"{reading}: {published} loses {-pd['delta']:.2f} DD "
                    f"tricks to {r['winner']} (CI {pd['ci95']})")
    winners = {r["winner"] for r in graded.values()}
    if len(winners) > 1 and winners != {published}:
        return ("honor_sensitive",
                "readings disagree: " + ", ".join(
                    f"{k}->{v['winner']}" for k, v in sorted(graded.items())))
    return "stable", "published answer survives both readings"


def inference_gate(record: dict, samples: int = GATE_SAMPLES, seed: int = 1,
                   n_boot: int = 600) -> tuple[str, str, dict]:
    """Forge-time gate: (status, detail, readings). ``inference_refuted`` and
    ``honor_sensitive`` block publication; ``stable``/``abstain`` pass."""
    readings = regrade_readings(record, samples=samples, seed=seed,
                                n_boot=n_boot)
    published = (((record.get("verdict") or {}).get("accepted")) or [None])[0]
    status, detail = inference_verdict(published, readings)
    return status, detail, readings


def sampler_from_problem(problem, stop_miss_scale: float = 1.0, **kw):
    """Same, for a bare LeadProblem — fetches the GIB cards live (one HTTP
    GET per call, cached; see engine/gib_explain.py). For the audit CLI."""
    from .conventions import SEATS as _SEATS
    from .lead_explain import auction_meanings
    from .lead_samplers import ConstraintSampler
    entries = auction_meanings(_SEATS.index(problem.dealer),
                               list(problem.auction))
    profile = profile_from_explained_auction(
        entries, problem.leader, problem.hand,
        stop_miss_scale=stop_miss_scale)
    mode = "gib_cards" if stop_miss_scale else "gib_cards_strict"
    return ConstraintSampler(profile=profile,
                             semantic_constraint_mode=mode,
                             unrecognized_calls=profile.unrecognized_calls,
                             **kw)
