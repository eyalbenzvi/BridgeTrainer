from __future__ import annotations

from dataclasses import dataclass, field

from endplay.types import Deal


@dataclass
class WeightedDeal:
    """A concrete deal with its importance weight (INV2)."""

    deal: Deal
    weight: float = 1.0


@dataclass
class GenerationDiagnostics:
    attempts: int = 0
    acceptance_rate: float = 0.0
    effective_sample_size: float = 0.0
    unrecognized_calls: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    shortfall: int = 0  # deals missing if budget hit before n

    def to_dict(self) -> dict:
        return {
            "attempts": self.attempts,
            "acceptance_rate": self.acceptance_rate,
            "effective_sample_size": self.effective_sample_size,
            "unrecognized_calls": list(self.unrecognized_calls),
            "elapsed_s": self.elapsed_s,
            "shortfall": self.shortfall,
        }
