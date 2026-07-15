"""Soft constraints on a concealed hand, expressed as weighted bands.

A Band is an inclusive integer range with an acceptance weight. A feature
(HCP, or the length of one suit) is described by a list of bands: the core
range at weight 1.0 plus optional margin bands at reduced weight. Values
outside every band have weight 0 (rejected). Weights become importance
weights on the sampled deals (INV2).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

SUITS = ("S", "H", "D", "C")
MAX_HCP = 40
MAX_LEN = 13


@dataclass(frozen=True)
class Band:
    lo: int
    hi: int
    weight: float = 1.0

    def __post_init__(self) -> None:
        if self.lo > self.hi:
            raise ValueError(f"band lo {self.lo} > hi {self.hi}")
        if not (0.0 < self.weight <= 1.0):
            raise ValueError(f"band weight must be in (0, 1]: {self.weight}")


def bands_to_weights(bands: list[Band], size: int) -> np.ndarray:
    """Dense weight lookup table indexed by feature value; 0 outside bands.

    Overlapping bands take the maximum weight.
    """
    w = np.zeros(size, dtype=np.float64)
    for b in bands:
        hi = min(b.hi, size - 1)
        w[b.lo:hi + 1] = np.maximum(w[b.lo:hi + 1], b.weight)
    return w


def _unconstrained(size: int) -> np.ndarray:
    return np.ones(size, dtype=np.float64)


@dataclass
class SeatConstraints:
    """Weight tables for one concealed seat plus named exclusion predicates."""

    hcp_weights: np.ndarray = field(
        default_factory=lambda: _unconstrained(MAX_HCP + 1))
    suit_weights: dict[str, np.ndarray] = field(
        default_factory=lambda: {s: _unconstrained(MAX_LEN + 1) for s in SUITS})
    exclusions: list[str] = field(default_factory=list)

    @classmethod
    def from_bands(
        cls,
        hcp: list[Band] | None = None,
        suits: dict[str, list[Band]] | None = None,
        exclusions: list[str] | None = None,
    ) -> "SeatConstraints":
        sc = cls()
        if hcp:
            sc.hcp_weights = bands_to_weights(hcp, MAX_HCP + 1)
        for suit, bands in (suits or {}).items():
            sc.suit_weights[suit] = bands_to_weights(bands, MAX_LEN + 1)
        sc.exclusions = list(exclusions or [])
        return sc

    def merge(self, other: "SeatConstraints") -> "SeatConstraints":
        """Conjunction of two calls' constraints: weights multiply."""
        merged = SeatConstraints(
            hcp_weights=self.hcp_weights * other.hcp_weights,
            suit_weights={s: self.suit_weights[s] * other.suit_weights[s]
                          for s in SUITS},
            exclusions=sorted(set(self.exclusions) | set(other.exclusions)),
        )
        return merged

    def fingerprint(self) -> dict:
        """JSON-serializable canonical form, used for cache keys (INV4)."""
        return {
            "hcp": self.hcp_weights.round(6).tolist(),
            "suits": {s: self.suit_weights[s].round(6).tolist() for s in SUITS},
            "exclusions": list(self.exclusions),
        }


@dataclass
class ConstraintProfile:
    """Constraints for every concealed seat, plus semantics diagnostics."""

    seats: dict[str, SeatConstraints] = field(default_factory=dict)
    unrecognized_calls: list[str] = field(default_factory=list)

    def fingerprint(self) -> dict:
        return {seat: sc.fingerprint() for seat, sc in sorted(self.seats.items())}
