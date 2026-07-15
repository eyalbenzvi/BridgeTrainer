"""Conditional-tree ContractProjector.

Each candidate action carries an ordered list of rule nodes:

    - when: "opps_combined_hearts >= 10 and west_hcp >= 16"
      contract: "4HW"
    - else: {contract: "3SN", terminal: true}

The tree is evaluated PER DEAL against features of the concealed hands (and
mine). Doubles are handled the same way: partner's sit/pull is decided per
deal by predicates on partner's hand — never a global sit/pull weight. The
final node must be an `else`; `terminal: true` marks a consciously truncated
auction (defaults to true — truncation is always explicit in the report).
"""
from __future__ import annotations

import ast

from endplay.types import Player

from ..dealing.features import HCP_BY_RANK, parse_hand_pbn
from ..domain.auction import SEATS, Seat, next_seat, partner_of
from ..domain.contracts import FinalContract
from ..domain.deals import WeightedDeal

_ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not,
    ast.USub, ast.Compare, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq,
    ast.NotEq, ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Name, ast.Load,
    ast.Constant,
)

SEAT_WORDS = {"N": "north", "E": "east", "S": "south", "W": "west"}
SUIT_WORDS = {"S": "spades", "H": "hearts", "D": "diamonds", "C": "clubs"}


def compile_predicate(expr: str, allowed_names: set[str]):
    """Compile a boolean expression over deal features, safely."""
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError(
                f"disallowed syntax {type(node).__name__!r} in predicate {expr!r}")
        if isinstance(node, ast.Name) and node.id not in allowed_names:
            raise ValueError(f"unknown feature {node.id!r} in predicate {expr!r}")
        if isinstance(node, ast.Constant) and not isinstance(
                node.value, (int, float, bool)):
            raise ValueError(f"non-numeric constant in predicate {expr!r}")
    code = compile(tree, "<predicate>", "eval")
    return lambda features: bool(eval(code, {"__builtins__": {}}, features))


def feature_names(my_seat: Seat) -> set[str]:
    names: set[str] = set()
    for word in SEAT_WORDS.values():
        names.add(f"{word}_hcp")
        names.update(f"{word}_{s}" for s in SUIT_WORDS.values())
    for role in ("partner", "lho", "rho"):
        names.add(f"{role}_hcp")
        names.update(f"{role}_{s}" for s in SUIT_WORDS.values())
    names.add("opps_combined_hcp")
    names.update(f"opps_combined_{s}" for s in SUIT_WORDS.values())
    return names


def deal_features(deal, my_seat: Seat) -> dict[str, int]:
    """Scalar features of one concrete deal, keyed for predicate expressions."""
    per_seat: dict[str, dict[str, int]] = {}
    for seat in SEATS:
        hand = str(deal[Player.find(seat)])
        cards = parse_hand_pbn(hand)
        feats = {"hcp": int(sum(HCP_BY_RANK[c % 13] for c in cards))}
        for suit_char, word in SUIT_WORDS.items():
            si = "SHDC".index(suit_char)
            feats[word] = sum(1 for c in cards if c // 13 == si)
        per_seat[seat] = feats

    out: dict[str, int] = {}
    for seat, feats in per_seat.items():
        for k, v in feats.items():
            out[f"{SEAT_WORDS[seat]}_{k}"] = v
    roles = {
        "partner": partner_of(my_seat),
        "lho": next_seat(my_seat),
        "rho": next_seat(partner_of(my_seat)),
    }
    for role, seat in roles.items():
        for k, v in per_seat[seat].items():
            out[f"{role}_{k}"] = v
    opp1, opp2 = roles["lho"], roles["rho"]
    for k in per_seat[opp1]:
        out[f"opps_combined_{k}"] = per_seat[opp1][k] + per_seat[opp2][k]
    return out


class ConditionalTreeProjector:
    """ContractProjector over authored YAML decision trees."""

    def __init__(self, trees: dict[str, list[dict]], my_seat: Seat):
        """trees: candidate call -> ordered rule nodes."""
        self.my_seat = my_seat
        names = feature_names(my_seat)
        self._compiled: dict[str, list[tuple]] = {}
        for action, nodes in trees.items():
            if not nodes:
                raise ValueError(f"empty projection tree for {action!r}")
            compiled = []
            for i, node in enumerate(nodes):
                is_last = i == len(nodes) - 1
                if "else" in node:
                    if not is_last:
                        raise ValueError(
                            f"{action!r}: 'else' must be the final node")
                    spec = node["else"]
                    compiled.append((None, self._parse_leaf(spec)))
                else:
                    if is_last:
                        raise ValueError(
                            f"{action!r}: final node must be an 'else'")
                    pred = compile_predicate(node["when"], names)
                    compiled.append((pred, self._parse_leaf(node)))
            self._compiled[action] = compiled

    @staticmethod
    def _parse_leaf(spec: dict) -> FinalContract:
        return FinalContract.parse(
            spec["contract"], terminal=bool(spec.get("terminal", True)))

    def project(self, deal: WeightedDeal, candidate_action: str) -> FinalContract:
        features = deal_features(deal.deal, self.my_seat)
        return self.project_features(features, candidate_action)

    def project_features(self, features: dict[str, int],
                         candidate_action: str) -> FinalContract:
        """Same as project() but on precomputed deal features."""
        try:
            nodes = self._compiled[candidate_action]
        except KeyError:
            raise KeyError(f"no projection tree for action {candidate_action!r}")
        for pred, leaf in nodes:
            if pred is None or pred(features):
                return leaf
        raise AssertionError("unreachable: trees end with else")
