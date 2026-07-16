"""Family loading: a family is an ordinary problem YAML (with a
`my_hand_class`) plus an optional `family:` block carrying the lesson
text, publishability, gate overrides and audit predicates.

Audit predicates are compiled with the projection language's
AST-whitelisted compiler over hero features (`me_*`), so no new
predicate language exists (engineering review, combined_round1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..bank.schema import load_problem
from ..dealing.features import HCP_BY_RANK, SUIT_NAMES, parse_hand_pbn
from ..domain.problem import BiddingProblem
from ..projection.tree import SUIT_WORDS, compile_predicate
from ..validate.trees import lint_projection_trees

HERO_FEATURES = (
    {"me_hcp"}
    | {f"me_{w}" for w in SUIT_WORDS.values()}
    | {f"me_{w}_hcp" for w in SUIT_WORDS.values()}
)


def hero_features(hand: str) -> dict:
    """me_* features of the hero hand, plus plain keys for check_hero_stem."""
    cards = parse_hand_pbn(hand)
    feats: dict = {}
    hcp = sum(int(HCP_BY_RANK[c % 13]) for c in cards)
    feats["me_hcp"] = feats["hcp"] = hcp
    for i, s in enumerate(SUIT_NAMES):
        in_suit = [c for c in cards if c // 13 == i]
        word = SUIT_WORDS[s]
        feats[f"me_{word}"] = feats[s] = len(in_suit)
        feats[f"me_{word}_hcp"] = sum(int(HCP_BY_RANK[c % 13]) for c in in_suit)
    return feats


@dataclass
class AuditRule:
    expr: str
    reason: str
    fn: object  # compiled predicate


@dataclass
class FamilySpec:
    path: Path
    problem: BiddingProblem
    principle: str = ""
    publish: bool = True
    never_verdict: list[str] = field(default_factory=list)
    delta_imps: float | None = None    # None -> global default / calibration
    stakes_min: float = 0.5
    push_max: float = 0.85
    audits: list[AuditRule] = field(default_factory=list)
    lint_warnings: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.problem.id

    def stem_tokens(self) -> list[str]:
        return [c.token for c in self.problem.auction.calls]

    def audit_hand(self, hand: str) -> str | None:
        """Returns the rejection reason if any audit predicate fires."""
        feats = hero_features(hand)
        for rule in self.audits:
            if rule.fn(feats):
                return rule.reason
        return None


class FamilyError(ValueError):
    pass


def _lint(problem: BiddingProblem) -> tuple[list[str], list[str]]:
    """Cross-option realism lint (V6/T1-T3) at family load."""
    options = [c.call for c in problem.candidates]
    projections = {c.call: c.projection for c in problem.candidates}
    return lint_projection_trees(
        dealer=problem.dealer,
        stem=[c.token for c in problem.auction.calls],
        hero=problem.my_seat,
        options=options,
        projections=projections,
        deviations={},
    )


def load_family(path: str | Path) -> FamilySpec:
    path = Path(path)
    problem = load_problem(path)
    if problem.my_hand_class is None:
        raise FamilyError(f"{path.name}: a family needs my_hand_class")

    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    block = raw.get("family", {}) or {}
    gate = block.get("gate", {}) or {}

    audits = []
    for entry in block.get("audit", []) or []:
        expr, reason = str(entry["when"]), str(entry.get("reason", entry["when"]))
        fn = compile_predicate(expr, HERO_FEATURES)
        audits.append(AuditRule(expr=expr, reason=reason, fn=fn))

    errors, warnings = _lint(problem)
    if errors:
        raise FamilyError(f"{path.name}: projection lint errors: {errors}")

    return FamilySpec(
        path=path,
        problem=problem,
        principle=str(block.get("principle", "")).strip(),
        publish=bool(block.get("publish", True)),
        never_verdict=[str(x) for x in block.get("never_verdict", []) or []],
        delta_imps=gate.get("delta_imps"),
        stakes_min=float(gate.get("stakes_min", 0.5)),
        push_max=float(gate.get("push_max", 0.85)),
        audits=audits,
        lint_warnings=warnings,
    )


def load_families(directory: str | Path) -> list[FamilySpec]:
    """All families in a directory, sorted by filename (the sort order is
    the family index used in seeding — stable, not process-salted)."""
    paths = sorted(Path(directory).glob("*.yaml"))
    if not paths:
        raise FileNotFoundError(f"no family files in {directory}")
    return [load_family(p) for p in paths]
