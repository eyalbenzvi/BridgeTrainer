"""Rule engine: auction -> ConstraintProfile.

Rules live in YAML rulesets (one per SystemProfile) keyed by auction context
(the exact sequence of preceding calls) + the call made. The engine walks
every call in the auction — including passes (INV8) — and for each call by a
concealed seat looks up the matching rule in that side's ruleset and merges
its soft constraints into the seat's profile. Calls with no matching rule
degrade gracefully: known constraints still apply and the gap is surfaced in
ConstraintProfile.unrecognized_calls (and from there in
GenerationDiagnostics).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from ..domain.auction import Auction, Seat, side_of
from ..domain.constraints import Band, ConstraintProfile, SeatConstraints
from .predicates import PREDICATES

SUPPORTED_SCHEMA_VERSIONS = (1,)


class Ruleset:
    def __init__(self, data: dict, source: str = "<inline>"):
        version = data.get("schema_version")
        if version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"{source}: unsupported semantics schema_version {version!r}")
        self.source = source
        self.system = data.get("system", "unnamed")
        self.raw = data
        # index: (context tuple, call) -> rule dict
        self.index: dict[tuple[tuple[str, ...], str], dict] = {}
        for rule in data.get("rules", []):
            key = (tuple(rule.get("context", [])), rule["call"])
            if key in self.index:
                raise ValueError(f"{source}: duplicate rule for {key}")
            for name in rule.get("exclusions", []):
                if name not in PREDICATES:
                    raise ValueError(
                        f"{source}: unknown exclusion predicate {name!r} "
                        f"in rule {rule.get('id', key)}")
            self.index[key] = rule

    def lookup(self, context: tuple[str, ...], call: str) -> dict | None:
        return self.index.get((context, call))

    def fingerprint(self) -> str:
        blob = json.dumps(self.raw, sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:16]


def load_ruleset(path: str | Path) -> Ruleset:
    path = Path(path)
    with open(path) as f:
        return Ruleset(yaml.safe_load(f), source=str(path))


def _parse_bands(spec: dict) -> list[Band]:
    bands = [Band(int(spec["core"][0]), int(spec["core"][1]), 1.0)]
    for m in spec.get("margin", []):
        bands.append(Band(int(m["range"][0]), int(m["range"][1]),
                          float(m["weight"])))
    return bands


def rule_to_constraints(rule: dict) -> SeatConstraints:
    cspec = rule.get("constraints", {})
    hcp = _parse_bands(cspec["hcp"]) if "hcp" in cspec else None
    suits = {suit: _parse_bands(spec)
             for suit, spec in cspec.get("suits", {}).items()}
    return SeatConstraints.from_bands(
        hcp=hcp, suits=suits, exclusions=rule.get("exclusions", []))


class RuleEngine:
    """Extracts a ConstraintProfile for the concealed seats of an auction."""

    def __init__(self, our_ruleset: Ruleset, opps_ruleset: Ruleset,
                 my_seat: Seat):
        self.my_seat = my_seat
        self.my_side = side_of(my_seat)
        other_side = "EW" if self.my_side == "NS" else "NS"
        self.rulesets = {self.my_side: our_ruleset, other_side: opps_ruleset}

    def extract(self, auction: Auction) -> ConstraintProfile:
        profile = ConstraintProfile()
        context: list[str] = []
        for seat, call in auction.calls_with_seats():
            if seat != self.my_seat:  # INV8: every concealed call, incl. passes
                ruleset = self.rulesets[side_of(seat)]
                rule = ruleset.lookup(tuple(context), call.token)
                if rule is None:
                    profile.unrecognized_calls.append(
                        f"{seat}:{call.token} after '{' '.join(context) or '(start)'}'"
                        f" [{ruleset.system}]")
                else:
                    sc = rule_to_constraints(rule)
                    if seat in profile.seats:
                        profile.seats[seat] = profile.seats[seat].merge(sc)
                    else:
                        profile.seats[seat] = sc
            context.append(call.token)
        return profile
