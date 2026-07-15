"""AuctionWalker: runs SimpleBidder around the table.

Maintains the public auction state (contract, doubles, who showed what via
call signatures) and produces the final contract. Used both to generate
problem stems from real deals and to project candidate actions to final
contracts on simulated layouts.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.auction import SEATS, next_seat, partner_of, side_of
from ..domain.contracts import FinalContract
from .bidder import (BotCall, HandView, Signature, SimpleBidder, TableView,
                     denom_rank)

MAX_CALLS = 40  # hard safety valve; discipline rules end auctions well before


@dataclass
class SeatShown:
    min_hcp: float = 0.0
    max_hcp: float = 40.0
    suit_min: dict = field(default_factory=dict)
    opened: bool = False
    doubled_takeout: bool = False
    bids: list = field(default_factory=list)  # denoms bid, in order

    def absorb(self, call: BotCall) -> None:
        sig = call.signature
        if sig.informative:
            self.min_hcp = max(self.min_hcp, sig.hcp[0])
            self.max_hcp = min(self.max_hcp, sig.hcp[1])
            for s, n in sig.suit_min.items():
                self.suit_min[s] = max(self.suit_min.get(s, 0), n)


class AuctionWalker:
    def __init__(self, dealer: str, vul: str,
                 hands: dict[str, HandView] | None = None,
                 bidder: SimpleBidder | None = None):
        self.dealer = dealer
        self.vul = vul
        self.hands = hands or {}
        self.bidder = bidder or SimpleBidder()
        self.calls: list[tuple[str, BotCall]] = []  # (seat, call)
        self.shown: dict[str, SeatShown] = {s: SeatShown() for s in SEATS}
        self.level = 0
        self.denom = ""
        self.last_bid_seat = ""
        self.doubled = False
        self.opener = ""
        self.opening_token = ""
        self.first_namer: dict[tuple[str, str], str] = {}  # (side, denom) -> seat

    # -------------------------------------------------------------- state
    @property
    def next_to_call(self) -> str:
        seat = self.dealer
        for _ in range(len(self.calls) % 4):
            seat = next_seat(seat)
        return seat

    @property
    def finished(self) -> bool:
        n = len(self.calls)
        if n >= 4 and all(c.token == "P" for _, c in self.calls[:4]) and n == 4:
            return True
        if n < 4:
            return False
        return all(c.token == "P" for _, c in self.calls[-3:]) \
            and any(c.token != "P" for _, c in self.calls)

    def tokens(self) -> list[str]:
        return [c.token for _, c in self.calls]

    def view_for(self, seat: str) -> TableView:
        me = self.shown[seat]
        pd = self.shown[partner_of(seat)]
        my_side = side_of(seat)
        vul_us = self.vul in ("Both", my_side)
        vul_them = self.vul in ("Both", "NS" if my_side == "EW" else "EW")
        last_side = ""
        if self.last_bid_seat:
            last_side = "us" if side_of(self.last_bid_seat) == my_side else "them"
        our_first = ""
        for s, call in self.calls:
            if side_of(s) == my_side and call.token not in ("P", "X", "XX"):
                our_first = call.token[1:]
                break
        opening_denom_them, opening_level_them = "", 0
        if self.opener and side_of(self.opener) != my_side:
            for s, call in self.calls:
                if s == self.opener and call.token not in ("P", "X"):
                    opening_denom_them = call.token[1:]
                    opening_level_them = int(call.token[0])
                    break
        partner_last_bid = ""
        for s, call in reversed(self.calls):
            if s == partner_of(seat) and call.token not in ("P", "X", "XX"):
                partner_last_bid = call.token[1:]
                break
        return TableView(
            seat=seat,
            vul_us=vul_us,
            vul_them=vul_them,
            level=self.level,
            denom=self.denom,
            last_bidder_side=last_side,
            doubled=self.doubled,
            partner_min_hcp=pd.min_hcp,
            partner_max_hcp=pd.max_hcp,
            partner_suit_min=dict(pd.suit_min),
            my_bids=list(me.bids),
            partner_last_bid=partner_last_bid,
            our_first_denom=our_first,
            partner_opened=pd.opened,
            i_opened=me.opened,
            they_opened=bool(self.opener) and side_of(self.opener) != my_side,
            partner_doubled_takeout=pd.doubled_takeout,
            my_call_count=sum(1 for s, _ in self.calls if s == seat),
            partner_passed_only=not pd.bids and not pd.doubled_takeout
                                and pd.min_hcp == 0,
            opening_denom_them=opening_denom_them,
            opening_level_them=opening_level_them,
            my_opening_token=self.opening_token if self.opener == seat else "",
        )

    # ------------------------------------------------------------- actions
    def record(self, seat: str, call: BotCall) -> None:
        if call.token == "X":
            self.doubled = True
            self.shown[seat].doubled_takeout = (
                self.level <= 3 and not self.shown[seat].bids
                and side_of(self.last_bid_seat) != side_of(seat))
        elif call.token != "P":
            level, denom = int(call.token[0]), call.token[1:]
            self.level, self.denom = level, denom
            self.doubled = False
            self.last_bid_seat = seat
            side = side_of(seat)
            self.first_namer.setdefault((side, denom), seat)
            self.shown[seat].bids.append(denom)
            if not self.opener:
                self.opener = seat
                self.opening_token = call.token
                self.shown[seat].opened = True
        self.shown[seat].absorb(call)
        self.calls.append((seat, call))

    def step(self) -> tuple[str, BotCall]:
        """Let the bot make the next call."""
        seat = self.next_to_call
        if len(self.calls) >= MAX_CALLS:
            call = BotCall("P", "safety_valve", Signature())
        else:
            call = self.bidder.bid(self.hands[seat], self.view_for(seat))
        self.record(seat, call)
        return seat, call

    def force(self, token: str, rule: str = "forced") -> tuple[str, BotCall]:
        """Record a specific call (the hero's candidate) without asking the bot."""
        seat = self.next_to_call
        call = BotCall(token, rule, Signature())
        self.record(seat, call)
        return seat, call

    def run_to_end(self) -> FinalContract:
        while not self.finished:
            self.step()
        return self.final_contract()

    def final_contract(self) -> FinalContract:
        if self.level == 0:
            return FinalContract(level=0, denom="", declarer=None,
                                 terminal=False)
        side = side_of(self.last_bid_seat)
        declarer = self.first_namer[(side, self.denom)]
        return FinalContract(level=self.level, denom=self.denom,
                             declarer=declarer, doubled=self.doubled,
                             terminal=False)

    def clone_stem(self) -> "AuctionWalker":
        """Fresh walker replaying this walker's calls (used per simulation)."""
        w = AuctionWalker(self.dealer, self.vul, hands={}, bidder=self.bidder)
        for seat, call in self.calls:
            w.record(seat, call)
        return w
