"""Frozen boundary interfaces (milestone 0). Do not widen casually.

Implementations may accept richer constructor arguments, but these call
signatures are the contract between layers.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from .constraints import ConstraintProfile
from .contracts import FinalContract
from .deals import GenerationDiagnostics, WeightedDeal


@runtime_checkable
class DealSource(Protocol):
    def generate(
        self,
        my_hand: str,
        constraints: ConstraintProfile,
        n: int,
        seed: int,
        budget: "GenerationBudget",
    ) -> tuple[list[WeightedDeal], GenerationDiagnostics]:
        """Produce up to n weighted deals consistent with the constraints."""
        ...


class GenerationBudget:
    """Try/time budget for generation with graceful degradation."""

    def __init__(self, max_attempts: int = 5_000_000, max_seconds: float = 15.0):
        self.max_attempts = max_attempts
        self.max_seconds = max_seconds


@runtime_checkable
class ContractProjector(Protocol):
    def project(self, deal: WeightedDeal, candidate_action: str) -> FinalContract:
        """Decide where the auction ends on this deal for this action."""
        ...


@runtime_checkable
class Evaluator(Protocol):
    def evaluate(
        self,
        weighted_deals: list[WeightedDeal],
        contracts: list[FinalContract],
    ) -> tuple[np.ndarray, np.ndarray]:
        """Per-deal scores from my side's perspective: (raw, corrected)."""
        ...
