"""Seats, calls and auctions as pure data."""
from __future__ import annotations

from dataclasses import dataclass, field

SEATS = ("N", "E", "S", "W")
Seat = str  # one of SEATS

VALID_DENOMS = ("C", "D", "H", "S", "NT")


def next_seat(seat: Seat) -> Seat:
    return SEATS[(SEATS.index(seat) + 1) % 4]


def partner_of(seat: Seat) -> Seat:
    return SEATS[(SEATS.index(seat) + 2) % 4]


def side_of(seat: Seat) -> str:
    """'NS' or 'EW'."""
    return "NS" if seat in ("N", "S") else "EW"


@dataclass(frozen=True)
class Call:
    """A single call: 'P', 'X', 'XX', or level+denom like '1H', '3NT'."""

    token: str

    def __post_init__(self) -> None:
        t = self.token
        if t in ("P", "X", "XX"):
            return
        if len(t) >= 2 and t[0] in "1234567" and t[1:] in VALID_DENOMS:
            return
        raise ValueError(f"invalid call token: {t!r}")

    @property
    def is_pass(self) -> bool:
        return self.token == "P"

    @property
    def is_bid(self) -> bool:
        return self.token not in ("P", "X", "XX")

    @property
    def level(self) -> int:
        if not self.is_bid:
            raise ValueError(f"{self.token} has no level")
        return int(self.token[0])

    @property
    def denom(self) -> str:
        if not self.is_bid:
            raise ValueError(f"{self.token} has no denomination")
        return self.token[1:]

    def __str__(self) -> str:
        return self.token


@dataclass(frozen=True)
class Auction:
    """Calls in order starting from the dealer."""

    dealer: Seat
    calls: tuple[Call, ...] = field(default_factory=tuple)

    @classmethod
    def from_tokens(cls, dealer: Seat, tokens: list[str]) -> "Auction":
        return cls(dealer=dealer, calls=tuple(Call(t) for t in tokens))

    def seat_of(self, index: int) -> Seat:
        seat = self.dealer
        for _ in range(index % 4):
            seat = next_seat(seat)
        return seat

    def calls_with_seats(self) -> list[tuple[Seat, Call]]:
        return [(self.seat_of(i), c) for i, c in enumerate(self.calls)]

    def __str__(self) -> str:
        return " ".join(c.token for c in self.calls)
