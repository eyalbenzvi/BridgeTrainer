"""The hard shell, part V6: projection-tree realism lints.

The b1 audit found three ways a continuation tree can quietly decide
the verdict instead of discovering it:

  T1  concealed hands bidding on suit length alone — a when-branch that
      puts a concealed hand into a fresh 2+ level contract must carry a
      strength term (some *_hcp feature), else 3-counts bid freely;
  T2  a flagged-deviation bid never getting doubled — the deviation's
      canonical downside must exist in its own tree;
  T3  the same concealed action gated at different strengths in
      different options' trees (no floor over 1D, 14+ over 2C, 16+ over
      1S manufactured one verdict outright) — cross-option floors for
      the same (declarer, denomination) may not diverge by more than 2.

T1/T2 are errors; T3 divergence is an error above the tolerance and the
extracted floors are always returned for the record's quality block.
"""
from __future__ import annotations

import re

from ..domain.contracts import FinalContract
from .auction_state import replay

_HCP_TERM = re.compile(r"\b\w+_hcp\b")
_FLOOR = re.compile(r"\b(\w+_hcp)\s*>=\s*(\d+)")

FLOOR_TOLERANCE = 2


def _when_nodes(tree: list) -> list[tuple[str, FinalContract]]:
    out = []
    for node in tree:
        if "else" not in node and "contract" in node:
            out.append((node["when"], FinalContract.parse(node["contract"])))
    return out


def lint_projection_trees(
    dealer: str, stem: list, hero: str,
    options: list, projections: dict, deviations: dict,
) -> tuple[list[str], list[str]]:
    """Returns (errors, warnings). Errors block the problem."""
    errors: list[str] = []
    warnings: list[str] = []
    state = replay(dealer, stem)

    # floors[(declarer, denom, level)] -> {option: min hcp floor or None}
    floors: dict[tuple, dict] = {}

    for opt in options:
        after = state.apply(opt)
        standing = after.standing_contract()
        nodes = _when_nodes(projections[opt])

        for when, leaf in nodes:
            is_standing = (standing is not None
                           and (leaf.level, leaf.denom, leaf.declarer)
                           == (standing.level, standing.denom,
                               standing.declarer))
            fresh_by_concealed = (leaf.declarer != hero
                                  and not leaf.passed_out
                                  and not is_standing)
            if fresh_by_concealed and leaf.level >= 2 \
                    and not _HCP_TERM.search(when):
                errors.append(
                    f"option {opt!r}: branch to {leaf} is gated on "
                    f"{when!r} with no strength term — concealed hands "
                    f"may not bid on length alone (T1)")
            if fresh_by_concealed:
                found = [int(v) for _, v in _FLOOR.findall(when)]
                key = (leaf.declarer, leaf.denom, leaf.level)
                floors.setdefault(key, {})[opt] = min(found) if found else None

        if opt in deviations and opt not in ("P", "X", "XX") \
                and int(opt[0]) >= 2:
            leaves = [leaf for _, leaf in nodes]
            for node in projections[opt]:
                if "else" in node and "contract" in node["else"]:
                    leaves.append(FinalContract.parse(
                        node["else"]["contract"]))
            if not any(leaf.doubled for leaf in leaves):
                errors.append(
                    f"option {opt!r} is a flagged deviation but its tree "
                    f"never gets doubled — the deviation's downside is "
                    f"missing (T2)")

    for key, by_opt in floors.items():
        vals = [v for v in by_opt.values() if v is not None]
        if len(by_opt) >= 2 and vals and max(vals) - min(vals) \
                > FLOOR_TOLERANCE:
            declarer, denom, level = key
            errors.append(
                f"{declarer}'s {level}{denom} is gated at HCP floors "
                f"{sorted(by_opt.items())} across options — divergent "
                f"opponent aggression manufactures verdicts (T3)")

    return errors, warnings


_OPENING_MIN_HCP = 10
_NT_OPENING = (14, 18)


def check_hero_stem(dealer: str, stem: list, hero: str,
                    hero_hand_features: dict) -> list[str]:
    """Item A5: gross hero-hand vs stem-call inconsistencies (warnings).

    hero_hand_features: {'hcp': int, 'S': len, 'H':..., 'D':..., 'C':...}.
    Conservative rules only — stem lies are legal but must be surfaced so
    they don't silently corrupt what partner's later calls mean.
    """
    from ..domain.auction import SEATS

    warnings = []
    seat, opened = dealer, False
    for i, call in enumerate(stem):
        if seat == hero and call not in ("P", "X", "XX"):
            level, denom = int(call[0]), call[1:]
            if denom == "NT" and not opened and level == 1:
                lo, hi = _NT_OPENING
                if not lo <= hero_hand_features["hcp"] <= hi:
                    warnings.append(
                        f"stem call {call}: {hero_hand_features['hcp']} "
                        f"HCP outside a normal 1NT opening")
            elif denom != "NT":
                length = hero_hand_features[denom]
                if length < 4:
                    warnings.append(
                        f"stem call {call}: only {length} cards in "
                        f"{denom} — a stem lie partner will misread")
                if not opened and level == 1 \
                        and hero_hand_features["hcp"] < _OPENING_MIN_HCP:
                    warnings.append(
                        f"stem call {call}: opened with "
                        f"{hero_hand_features['hcp']} HCP")
        if call not in ("P", "X", "XX"):
            opened = True
        seat = SEATS[(SEATS.index(seat) + 1) % 4]
    return warnings
