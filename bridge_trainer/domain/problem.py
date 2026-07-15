from __future__ import annotations

from dataclasses import dataclass, field

from .auction import Auction, Seat

VULS = ("None", "NS", "EW", "Both")


@dataclass(frozen=True)
class SystemProfile:
    """A bidding style: which semantics ruleset governs a side's calls."""

    name: str
    description: str
    ruleset: str  # path (relative to problem file or package rules dir)


@dataclass
class CandidateAction:
    """One action the user can choose, with its projection decision tree."""

    call: str  # e.g. "P", "3S", "X"
    label: str
    projection: list[dict]  # ordered rule nodes, see projection.tree


@dataclass
class BiddingProblem:
    id: str
    title: str
    description: str
    dealer: Seat
    vul: str  # one of VULS
    my_seat: Seat
    my_hand: str  # PBN suit-dot form, e.g. "K93.752.A854.T62"
    auction: Auction
    our_system: SystemProfile
    opps_system: SystemProfile
    candidates: list[CandidateAction]
    n_deals: int = 800
    breakdowns: list[dict] = field(default_factory=list)  # [{feature, label}]
    category: str = ""
    # Optional "next deal" support: a class of hands my seat can be dealt
    # ({"hcp": [lo, hi], "suits": {"S": [lo, hi], ...}}) and how many seeded
    # variants to publish. Variant 0 always uses the authored my_hand.
    my_hand_class: dict | None = None
    variants: int = 1

    def vul_for_side(self, side: str) -> bool:
        return self.vul == "Both" or self.vul == side
