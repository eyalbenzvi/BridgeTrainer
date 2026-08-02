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

Honest labelling, same contract as ConstraintSampler: this is a modelled
prior (per-seat bands + soft stop weights + silence denials), NOT a
calibrated posterior. Known limitation: disjunctive negative inferences
("responder chose 2D, so he lacks stops in ALL THREE side suits or is
unbalanced") are not representable as per-suit bands and are not encoded;
the chosen calls' own stop annotations carry most of that information.
"""
from __future__ import annotations

import re

from ..domain.constraints import (
    MAX_SUIT_HCP, Band, ConstraintProfile, Denial, SeatConstraints)

SUITS = ("S", "H", "D", "C")
HONOR_HCP = {"A": 4, "K": 3, "Q": 2, "J": 1}

# GIB writes "stop in !D", "partial stop in !S", "likely stop in !H".
_STOP = re.compile(r"(partial\s+|likely\s+)?stop in !([SHDC])", re.I)

# Modelled-prior weights: how much mass stays on "announced a stop but does
# not actually hold the key honor(s)" — nonzero on purpose (players do bid
# 3NT on 'just a balanced hand' when no alternative call exists).
FULL_STOP_MISS_WEIGHT = 0.15
PARTIAL_STOP_MISS_WEIGHT = 0.35
# Silence denial: a concealed seat that only ever passed after an enemy
# opening rarely holds a sound overcall (decent 5-card suit + values).
SILENCE_DENIAL = dict(hcp_lo=9, hcp_hi=16, min_len=5, weight=0.2)
# Bidders stretch: HCP core bands get a +-1 margin at this weight.
HCP_MARGIN_WEIGHT = 0.3


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
    miss_w = (PARTIAL_STOP_MISS_WEIGHT if partial
              else FULL_STOP_MISS_WEIGHT) * miss_scale
    bands = [Band(thr, MAX_SUIT_HCP)]
    if thr >= 1 and miss_w > 0:
        bands.append(Band(0, thr - 1, min(miss_w, 1.0)))
    return bands


def stops_in_card(card: dict) -> list[tuple[str, bool]]:
    """[(suit, is_partial)] stop announcements in one GIB card's raw string."""
    raw = (card or {}).get("gib_raw") or ""
    return [(m.group(2).upper(), bool(m.group(1)))
            for m in _STOP.finditer(raw)]


def _card_is_empty(card: dict) -> bool:
    return not card or (card.get("hcp") is None and card.get("pts") is None
                        and not card.get("minlen") and not card.get("maxlen")
                        and not stops_in_card(card))


def seat_constraints_from_card(card: dict, leader_hand: str,
                               miss_scale: float = 1.0) -> SeatConstraints:
    """One call's GIB card -> SeatConstraints (bands only, no denials).

    * ``hcp (lo, hi)`` -> core band with a +-1 stretch margin;
    * ``pts (lo, hi)`` (total points) -> only the UPPER bound binds HCP
      (distribution points inflate the total, never deflate it);
    * ``minlen``/``maxlen`` -> hard per-suit length bands (GIB length
      promises are definitional: '3- !S' in an inverted raise IS the call);
    * ``stop in !X`` / ``partial stop in !X`` -> suit-HCP bands relative to
      the leader's own holding in X (see ``stop_bands``).
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

    suit_hcp = {}
    leader_suits = leader_hand.split(".")
    for suit, partial in stops_in_card(card):
        bands = stop_bands(leader_suits[SUITS.index(suit)], partial,
                           miss_scale=miss_scale)
        if bands:
            suit_hcp[suit] = bands

    return SeatConstraints.from_bands(
        hcp=hcp_bands, suits=suits or None, suit_hcp=suit_hcp or None)


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
        sc = seat_constraints_from_card(card, leader_hand,
                                        miss_scale=stop_miss_scale)
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
