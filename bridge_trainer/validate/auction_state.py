"""The hard shell, part V1: mechanical auction-state legality.

No author — human, LLM, or engine — is trusted with pass-counting or call
legality. This module replays the auction stem into a state machine and
enforces, for every finalized option and continuation tree:

  L1  the option is a LEGAL call at the hero's turn (bids must outrank the
      standing contract; X only against an undoubled enemy contract; XX
      only against their X; P always legal);
  L2  if the option is a pass that ENDS the auction (two trailing passes
      already, a contract standing), its continuation tree must be exactly
      one else-node naming the standing contract — nobody gets another turn
      (the f50022-21 failure class);
  L3  every contract a continuation tree can reach must be REACHABLE from
      the state after the hero's option: it must outrank the standing
      contract, or BE the standing contract with the true declarer (the
      first namer of that denomination for the declaring side), and only
      doubled if a double is still possible;
  L4  a passed-out stem cannot be a problem at all.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.auction import SEATS, next_seat, side_of
from ..domain.contracts import FinalContract

DENOM_ORDER = ("C", "D", "H", "S", "NT")


def _rank(level: int, denom: str) -> tuple:
    return (level, DENOM_ORDER.index(denom))


class AuctionStateError(ValueError):
    pass


@dataclass
class AuctionState:
    dealer: str
    level: int = 0
    denom: str = ""
    last_bid_seat: str = ""
    doubled: int = 0          # 0 / 1 (X) / 2 (XX)
    trailing_passes: int = 0
    n_calls: int = 0
    first_namer: dict = field(default_factory=dict)  # (side, denom) -> seat

    @property
    def turn(self) -> str:
        seat = self.dealer
        for _ in range(self.n_calls % 4):
            seat = next_seat(seat)
        return seat

    @property
    def finished(self) -> bool:
        if self.n_calls >= 4 and self.level == 0 and self.trailing_passes >= 4:
            return True
        return self.level > 0 and self.trailing_passes >= 3

    def standing_contract(self) -> FinalContract | None:
        if self.level == 0:
            return None
        side = side_of(self.last_bid_seat)
        return FinalContract(
            level=self.level, denom=self.denom,
            declarer=self.first_namer[(side, self.denom)],
            doubled=self.doubled > 0, terminal=False)

    def is_legal(self, token: str) -> bool:
        if self.finished:
            return False
        if token == "P":
            return True
        if token == "X":
            return (self.level > 0 and self.doubled == 0
                    and side_of(self.last_bid_seat) != side_of(self.turn))
        if token == "XX":
            return (self.level > 0 and self.doubled == 1
                    and side_of(self.last_bid_seat) == side_of(self.turn))
        level, denom = int(token[0]), token[1:]
        if self.level == 0:
            return True
        return _rank(level, denom) > _rank(self.level, self.denom)

    def apply(self, token: str) -> "AuctionState":
        if not self.is_legal(token):
            raise AuctionStateError(
                f"illegal call {token!r} at call #{self.n_calls} "
                f"({self.turn} to speak, contract "
                f"{self.level}{self.denom or '-'}{'x' * self.doubled}, "
                f"{self.trailing_passes} trailing passes)")
        seat = self.turn
        new = AuctionState(
            dealer=self.dealer, level=self.level, denom=self.denom,
            last_bid_seat=self.last_bid_seat, doubled=self.doubled,
            trailing_passes=self.trailing_passes, n_calls=self.n_calls + 1,
            first_namer=dict(self.first_namer))
        if token == "P":
            new.trailing_passes += 1
        elif token == "X":
            new.doubled = 1
            new.trailing_passes = 0
        elif token == "XX":
            new.doubled = 2
            new.trailing_passes = 0
        else:
            new.level, new.denom = int(token[0]), token[1:]
            new.doubled = 0
            new.trailing_passes = 0
            new.last_bid_seat = seat
            new.first_namer.setdefault((side_of(seat), new.denom), seat)
        return new


def replay(dealer: str, tokens: list) -> AuctionState:
    state = AuctionState(dealer=dealer)
    for tok in tokens:
        state = state.apply(tok)
    return state


def _tree_contracts(tree: list) -> list[str]:
    out = []
    for node in tree:
        spec = node.get("else", node)
        if "contract" in spec:
            out.append(spec["contract"])
    return out


def validate_options_against_state(
    dealer: str, stem: list, hero: str,
    options: list, projections: dict,
) -> None:
    """Raise AuctionStateError on any V1 violation. See module docstring."""
    state = replay(dealer, stem)
    if state.finished:
        raise AuctionStateError("stem auction is already over (L4)")
    if state.turn != hero:
        raise AuctionStateError(
            f"hero {hero} is not on turn ({state.turn} is)")

    for opt in options:
        if not state.is_legal(opt):
            raise AuctionStateError(f"option {opt!r} is illegal here (L1)")
        after = state.apply(opt)
        leaves = [FinalContract.parse(c)
                  for c in _tree_contracts(projections[opt])]

        if after.finished:
            # L2: this option ENDS the auction. One outcome only.
            standing = after.standing_contract()
            if len(projections[opt]) != 1 or len(leaves) != 1:
                raise AuctionStateError(
                    f"option {opt!r} ends the auction; its continuation "
                    f"must be a single else-node (L2)")
            leaf = leaves[0]
            if standing is None:
                if not leaf.passed_out:
                    raise AuctionStateError(
                        f"option {opt!r} passes the board out; leaf must "
                        f"be a pass-out (L2)")
                continue
            if (leaf.level, leaf.denom, leaf.declarer, leaf.doubled) != \
                    (standing.level, standing.denom, standing.declarer,
                     standing.doubled):
                raise AuctionStateError(
                    f"option {opt!r} ends the auction at {standing}; "
                    f"tree says {leaf} (L2)")
            continue

        # L3: every reachable leaf must be reachable from `after`.
        standing = after.standing_contract()
        for leaf in leaves:
            if leaf.passed_out:
                if standing is not None:
                    raise AuctionStateError(
                        f"option {opt!r}: pass-out leaf while a contract "
                        f"stands (L3)")
                continue
            if standing is None:
                continue  # any contract can still be reached
            same = (leaf.level, leaf.denom) == (standing.level, standing.denom)
            if same:
                if leaf.declarer != standing.declarer:
                    raise AuctionStateError(
                        f"option {opt!r}: leaf {leaf} names the wrong "
                        f"declarer; first namer is {standing.declarer} (L3)")
                if leaf.doubled and after.doubled == 2:
                    raise AuctionStateError(
                        f"option {opt!r}: leaf {leaf} doubled but the "
                        f"contract is redoubled (L3)")
            else:
                if _rank(leaf.level, leaf.denom) <= _rank(standing.level,
                                                          standing.denom):
                    raise AuctionStateError(
                        f"option {opt!r}: leaf {leaf} does not outrank the "
                        f"standing {standing} (L3)")
                declaring_side = side_of(leaf.declarer)
                prior = state.first_namer.get((declaring_side, leaf.denom))
                if prior is not None and prior != leaf.declarer:
                    raise AuctionStateError(
                        f"option {opt!r}: leaf {leaf} declarer should be "
                        f"{prior}, the side's first namer of {leaf.denom} "
                        f"(L3)")
