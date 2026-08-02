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
MAX_SUIT_HCP = 10  # AKQJ of one suit


@dataclass(frozen=True)
class Denial:
    """A conditional negative inference: hands with HCP in [hcp_lo, hcp_hi]
    AND at least min_len cards in `suit` are discounted to `weight` (0 =
    rejected outright). This expresses what a call DENIES relative to the
    actions not taken — e.g. a seat that passed over an enemy opening
    rarely holds a decent 5-card suit with overcalling values."""

    hcp_lo: int
    hcp_hi: int
    suit: str
    min_len: int
    weight: float = 0.0

    def __post_init__(self) -> None:
        if self.suit not in SUITS:
            raise ValueError(f"denial suit must be one of {SUITS}")
        if self.hcp_lo > self.hcp_hi:
            raise ValueError("denial hcp_lo > hcp_hi")
        if not (0.0 <= self.weight < 1.0):
            raise ValueError("denial weight must be in [0, 1)")


@dataclass(frozen=True)
class HonorSpec:
    """Weighted constraint on holding SPECIFIC cards in one suit — the DSL
    primitive behind GIB clauses like ``!CKQ`` (holds the club K and Q),
    ``no !DAK`` (holds neither top diamond) and ``Q+ in !D`` (an honor at
    least as good as the queen). ``mode``: 'all' = holds every rank listed,
    'any' = at least one, 'none' = none of them. Hands FAILING the spec keep
    ``weight`` (0 = rejected outright)."""

    suit: str
    ranks: str                # subset of "AKQJT"
    mode: str = "all"
    weight: float = 0.0

    def __post_init__(self) -> None:
        if self.suit not in SUITS:
            raise ValueError(f"honor-spec suit must be one of {SUITS}")
        if not self.ranks or any(r not in "AKQJT" for r in self.ranks):
            raise ValueError(f"honor-spec ranks must be honors: {self.ranks!r}")
        if self.mode not in ("all", "any", "none"):
            raise ValueError(f"honor-spec mode {self.mode!r}")
        if not (0.0 <= self.weight < 1.0):
            raise ValueError("honor-spec weight must be in [0, 1)")


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
    suit_hcp_weights: dict[str, np.ndarray] = field(
        default_factory=lambda: {s: _unconstrained(MAX_SUIT_HCP + 1)
                                 for s in SUITS})
    denials: list[Denial] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    honor_specs: list[HonorSpec] = field(default_factory=list)
    # Disjunction groups: each group is a list of alternative SeatConstraints
    # ("!SAKQ,no !S" = solid top spades OR a void). A hand's factor for a
    # group is the MAX over its alternatives' weights; groups (and the base
    # constraints) multiply as usual. Alternatives may not nest further
    # groups — one level is what the GIB vocabulary needs.
    alt_groups: list[list["SeatConstraints"]] = field(default_factory=list)

    @classmethod
    def from_bands(
        cls,
        hcp: list[Band] | None = None,
        suits: dict[str, list[Band]] | None = None,
        suit_hcp: dict[str, list[Band]] | None = None,
        denials: list[Denial] | None = None,
        exclusions: list[str] | None = None,
        honor_specs: list[HonorSpec] | None = None,
        alt_groups: list[list["SeatConstraints"]] | None = None,
    ) -> "SeatConstraints":
        sc = cls()
        if hcp:
            sc.hcp_weights = bands_to_weights(hcp, MAX_HCP + 1)
        for suit, bands in (suits or {}).items():
            sc.suit_weights[suit] = bands_to_weights(bands, MAX_LEN + 1)
        for suit, bands in (suit_hcp or {}).items():
            sc.suit_hcp_weights[suit] = bands_to_weights(
                bands, MAX_SUIT_HCP + 1)
        sc.denials = list(denials or [])
        sc.exclusions = list(exclusions or [])
        sc.honor_specs = list(honor_specs or [])
        sc.alt_groups = [list(g) for g in (alt_groups or [])]
        for g in sc.alt_groups:
            if not g:
                raise ValueError("empty alternatives group")
            for alt in g:
                if alt.alt_groups:
                    raise ValueError("alternatives may not nest alt_groups")
        return sc

    def merge(self, other: "SeatConstraints") -> "SeatConstraints":
        """Conjunction of two calls' constraints: weights multiply."""
        merged = SeatConstraints(
            hcp_weights=self.hcp_weights * other.hcp_weights,
            suit_weights={s: self.suit_weights[s] * other.suit_weights[s]
                          for s in SUITS},
            suit_hcp_weights={
                s: self.suit_hcp_weights[s] * other.suit_hcp_weights[s]
                for s in SUITS},
            denials=self.denials + other.denials,
            exclusions=sorted(set(self.exclusions) | set(other.exclusions)),
            honor_specs=self.honor_specs + other.honor_specs,
            alt_groups=self.alt_groups + other.alt_groups,
        )
        return merged

    def fingerprint(self) -> dict:
        """JSON-serializable canonical form, used for cache keys (INV4)."""
        return {
            "hcp": self.hcp_weights.round(6).tolist(),
            "suits": {s: self.suit_weights[s].round(6).tolist() for s in SUITS},
            "suit_hcp": {s: self.suit_hcp_weights[s].round(6).tolist()
                         for s in SUITS},
            "denials": [[d.hcp_lo, d.hcp_hi, d.suit, d.min_len,
                         round(d.weight, 6)] for d in self.denials],
            "exclusions": list(self.exclusions),
            "honor_specs": [[h.suit, h.ranks, h.mode, round(h.weight, 6)]
                            for h in self.honor_specs],
            "alt_groups": [[alt.fingerprint() for alt in g]
                           for g in self.alt_groups],
        }


@dataclass
class ConstraintProfile:
    """Constraints for every concealed seat, plus semantics diagnostics."""

    seats: dict[str, SeatConstraints] = field(default_factory=dict)
    unrecognized_calls: list[str] = field(default_factory=list)

    def fingerprint(self) -> dict:
        return {seat: sc.fingerprint() for seat, sc in sorted(self.seats.items())}
