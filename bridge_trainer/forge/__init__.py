"""Forge: the family compiler + empirical instance gate.

Combined plan (docs/combined_plan.md): families (expert-reviewed problem
recipes with hand classes) are the chassis; every compiled instance is
accepted or rejected by measurement on its own full simulation. The
field oracle (R2-3) is a deferred prior: records carry `oracle: none`.
"""
from .family import FamilySpec, load_family, load_families
from .gate import GateDecision, evaluate_gate
from .maker import forge_batch

__all__ = [
    "FamilySpec", "load_family", "load_families",
    "GateDecision", "evaluate_gate", "forge_batch",
]
