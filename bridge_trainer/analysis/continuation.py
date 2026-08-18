"""Continuation-policy ensemble: candidate call -> final contract per deal.

The authored projection trees (projection/tree.py) require a human author
per problem; user-entered auctions have none. Instead, the rest of the
auction is replayed as a mini-auction over the REAL deal: each seat in
rotation runs a small agent until three passes, on top of the legality
state machine reused from validate/auction_state.py (declarer = the side's
first namer of the denomination, doubling legality, pass-out — all free).

Two agent families (spec 3.4):

* Heuristic agents (policies "conservative"/"realistic"): decide from the
  seat's own hand — raise with fit + support points, respond to partner's
  takeout double (including converting it for penalties with a trump
  stack), compete with a combined fit, and double 4+-level enemy contracts
  holding a trump stack (the scenario the spec mandates in every policy).
  Every numeric threshold comes from analysis/policies.yaml — nothing here
  is hardcoded.

* DD-optimal agent (policy "omniscient"): an explicit upper bound — each
  side, seeing all the cards, picks the resting spot that double-dummy
  scores best for it, and failing contracts are always doubled. This is a
  bound, not a prediction, and the report labels it as such.

Modeling notes (documented simplifications, v1):
  - the compete decision uses the defending side's COMBINED assets — a
    proxy for a real pair finding its combined potential through bidding;
  - penalty doubles use the doubler's own hand only (more sensitive);
  - heuristic agents never introduce NT contracts except the advancer's
    NT response to a takeout double.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from ..dealing.features import HCP_BY_RANK, parse_hand_pbn
from ..domain.auction import Seat, partner_of, side_of
from ..domain.contracts import FinalContract
from ..scoring.tables import contract_score
from ..validate.auction_state import AuctionState, replay

DENOM_ORDER = ("C", "D", "H", "S", "NT")
GAME_LEVEL = {"C": 5, "D": 5, "H": 4, "S": 4, "NT": 3}
POLICIES_FILE = Path(__file__).parent / "policies.yaml"
_MAX_CONTINUATION_CALLS = 16   # hard loop bound; agents cap themselves first


@lru_cache(maxsize=1)
def load_policies() -> dict:
    with open(POLICIES_FILE) as f:
        data = yaml.safe_load(f)
    if data.get("schema_version") != 1:
        raise ValueError("unsupported policies schema_version")
    return data["policies"]


# ---------------------------------------------------------------------------
@dataclass
class SeatView:
    """Scalar features of one seat's actual 13 cards."""
    hcp: int
    length: dict[str, int]
    shcp: dict[str, int]   # honor points held per suit

    def support_pts(self, trump: str) -> int:
        """HCP + shortness points, counted only with a real fit elsewhere."""
        pts = self.hcp
        for s in "SHDC":
            if s != trump and self.length[s] <= 2:
                pts += (3 - self.length[s])
        return pts

    def best_suit(self) -> str:
        return max("SHDC", key=lambda s: (self.length[s], self.shcp[s]))


def deal_views(deal) -> dict[Seat, SeatView]:
    from endplay.types import Player
    out: dict[Seat, SeatView] = {}
    for seat in "NESW":
        cards = parse_hand_pbn(str(deal[Player.find(seat)]))
        length = {s: 0 for s in "SHDC"}
        shcp = {s: 0 for s in "SHDC"}
        hcp = 0
        for c in cards:
            suit = "SHDC"[c // 13]
            length[suit] += 1
            p = int(HCP_BY_RANK[c % 13])
            shcp[suit] += p
            hcp += p
        out[seat] = SeatView(hcp=hcp, length=length, shcp=shcp)
    return out


def _min_level(state: AuctionState, denom: str) -> int:
    """Cheapest legal level for `denom` over the standing contract."""
    if state.level == 0:
        return 1
    if DENOM_ORDER.index(denom) > DENOM_ORDER.index(state.denom):
        return state.level
    return state.level + 1


def _side_fit(views, side_seats, denom: str) -> int:
    return sum(views[s].length[denom] for s in side_seats)


# ---------------------------------------------------------------------------
class ContinuationEngine:
    def __init__(self, dealer: Seat, stem_tokens: list[str], hero: Seat,
                 vul: str, policies: dict | None = None):
        self.dealer = dealer
        self.stem_tokens = list(stem_tokens)
        self.hero = hero
        self.vul = vul
        self.policies = policies or load_policies()

    # -- public API ------------------------------------------------------
    def project(self, deal, candidate: str, policy: str,
                tricks: dict | None = None) -> FinalContract:
        """Final contract for this deal if hero makes `candidate`.

        `tricks`: {(denom, declarer): dd_tricks} for THIS deal; required
        for the omniscient policy, ignored by heuristic policies.
        """
        return self.project_with_calls(deal, candidate, policy, tricks)[0]

    def project_with_calls(
            self, deal, candidate: str, policy: str,
            tricks: dict | None = None) -> tuple[FinalContract, list[str]]:
        """Like project(), also returning the continuation call tokens
        (used for the report's partner-response frequency table)."""
        views = deal_views(deal)
        params = self.policies[policy]["params"]
        state = replay(self.dealer, self.stem_tokens).apply(candidate)
        dd_mode = params.get("mode") == "dd_optimal"
        if dd_mode and tricks is None:
            raise ValueError("omniscient policy needs DD tricks")

        actions = {s: 0 for s in "NESW"}
        last_side_action: dict[str, str] = {}   # side -> last non-pass token
        # seed with the stem so agents know e.g. that partner's X exists
        st_walk = AuctionState(dealer=self.dealer)
        for t in self.stem_tokens + [candidate]:
            if t != "P":
                last_side_action[side_of(st_walk.turn)] = t
            st_walk = st_walk.apply(t)

        n = 0
        calls: list[str] = []
        while not state.finished and n < _MAX_CONTINUATION_CALLS:
            seat = state.turn
            cap = int(params.get("max_actions_per_seat", 2))
            if actions[seat] >= cap:
                tok = "P"
            elif dd_mode:
                tok = self._dd_agent(seat, state, views, tricks)
            else:
                tok = self._heuristic_agent(seat, state, views, params,
                                            last_side_action)
            if tok != "P":
                actions[seat] += 1
                last_side_action[side_of(seat)] = tok
            state = state.apply(tok)
            calls.append(tok)
            n += 1

        standing = state.standing_contract()
        if standing is None:
            return FinalContract(level=0, denom="", declarer=None), calls
        return FinalContract(level=standing.level, denom=standing.denom,
                             declarer=standing.declarer,
                             doubled=standing.doubled,
                             terminal=True), calls

    def denoms_possible(self, deal, candidates: list[str]) -> set[str]:
        """Denominations any policy could reach on this deal (for DD)."""
        views = deal_views(deal)
        out: set[str] = set()
        stem_state = replay(self.dealer, self.stem_tokens)
        if stem_state.level:
            out.add(stem_state.denom)
        for c in candidates:
            if c not in ("P", "X", "XX"):
                out.add(c[1:])
        for side_seats in ("NS", "EW"):
            for d in "SHDC":
                if _side_fit(views, side_seats, d) >= 8:
                    out.add(d)
            for s in side_seats:
                out.add(views[s].best_suit())
        out.add("NT")   # advancer NT responses / NT candidates
        return out

    # -- heuristic agents --------------------------------------------------
    def _heuristic_agent(self, seat, state, views, p,
                         last_side_action) -> str:
        v = views[seat]
        my_side = side_of(seat)
        standing = state.standing_contract()
        if standing is None:
            return "P"
        ours = side_of(standing.declarer) == my_side

        if ours:
            return self._raise_or_pass(seat, state, v, views, p,
                                       last_side_action)

        # ---- defending side ------------------------------------------
        # partner made a takeout-ish double that I must act on
        if state.doubled == 1 and last_side_action.get(my_side) == "X":
            return self._respond_to_double(seat, state, v, p)

        # penalty double of a high contract (mandated scenario 3.4)
        if (not state.doubled
                and standing.level >= int(p["dbl_min_level"])
                and standing.denom != "NT"
                and v.length[standing.denom] >= int(p["dbl_stack_len"])
                and v.shcp[standing.denom] >= int(p["dbl_stack_hcp"])
                and v.hcp >= int(p["dbl_own_pts"])
                and state.is_legal("X")):
            return "X"

        # compete: combined fit + combined strength, level-capped
        pard = partner_of(seat)
        my_seats = (seat, pard)
        best_d, best_fit = "", 0
        for d in "SHDC":
            fit = views[seat].length[d] + views[pard].length[d]
            if fit > best_fit or (fit == best_fit and best_d and
                                  DENOM_ORDER.index(d)
                                  > DENOM_ORDER.index(best_d)):
                best_d, best_fit = d, fit
        combined_pts = views[seat].hcp + views[pard].hcp
        need_pts = float(p["compete_pts"])
        if self._is_vul(my_side):
            need_pts += float(p["vul_compete_penalty"])
        if best_fit >= int(p["compete_min_fit"]) and combined_pts >= need_pts:
            lvl = _min_level(state, best_d)
            if lvl <= int(p["compete_max_level"]):
                tok = f"{lvl}{best_d}"
                if state.is_legal(tok):
                    return tok
        return "P"

    def _raise_or_pass(self, seat, state, v, views, p,
                       last_side_action) -> str:
        """Our side holds the contract: raise toward game or pass."""
        standing = state.standing_contract()
        d = standing.denom
        if d == "NT":
            return "P"    # no NT raising in v1 (no slam exploration)
        game = GAME_LEVEL[d]
        if standing.level >= game:
            return "P"
        # only support PARTNER's bid — a seat never raises its own call
        # without partner having acted (that would invent values twice)
        if state.last_bid_seat != partner_of(seat):
            return "P"
        if v.length[d] < int(p["min_fit_to_raise"]):
            return "P"
        support = v.support_pts(d)
        # partner's invite standing below game: accept on values
        pard = partner_of(seat)
        invited = (standing.declarer is not None
                   and state.last_bid_seat == pard
                   and standing.level >= 2)
        if support >= int(p["raise_game_pts"]) or (
                invited and standing.level == game - 1
                and v.hcp >= int(p["invite_accept_pts"])):
            tok = f"{game}{d}"
            return tok if state.is_legal(tok) else "P"
        if support >= int(p["raise_invite_pts"]) \
                and standing.level + 1 < game:
            tok = f"{standing.level + 1}{d}"
            return tok if state.is_legal(tok) else "P"
        return "P"

    def _respond_to_double(self, seat, state, v, p) -> str:
        """Advancer facing partner's (takeout-ish) double."""
        standing = state.standing_contract()
        enemy = standing.denom
        if standing.level >= 4:
            # high-level X is penalty-oriented: pull only with a freak hand
            if (v.hcp <= int(p["pull_high_double_max_hcp"])):
                best = v.best_suit()
                if v.length[best] >= int(p["pull_high_double_suit_len"]):
                    lvl = _min_level(state, best)
                    tok = f"{lvl}{best}"
                    if lvl <= 5 and state.is_legal(tok):
                        return tok
            return "P"
        # penalty pass: trump stack behind the bidder
        if enemy != "NT" \
                and v.length[enemy] >= int(p["penalty_pass_trumps"]) \
                and v.shcp[enemy] >= int(p["penalty_pass_trump_hcp"]):
            return "P"
        # NT with a stopper and values
        if v.hcp >= int(p["nt_bid_pts"]) and enemy != "NT" \
                and v.length[enemy] >= 2 and v.shcp[enemy] >= 3:
            lvl = _min_level(state, "NT")
            tok = f"{lvl}NT"
            if lvl <= 3 and state.is_legal(tok):
                return tok
        # cheapest decent suit (never the enemy suit)
        candidates = [s for s in "SHDC" if s != enemy]
        best = max(candidates, key=lambda s: (v.length[s], v.shcp[s]))
        lvl = _min_level(state, best)
        jump = v.hcp >= int(p["advancer_jump_pts"])
        if jump and lvl + 1 <= GAME_LEVEL[best]:
            lvl += 1
        tok = f"{lvl}{best}"
        return tok if state.is_legal(tok) and lvl <= GAME_LEVEL[best] else "P"

    # -- DD-optimal agent --------------------------------------------------
    def _dd_agent(self, seat, state, views, tricks) -> str:
        """Upper-bound agent: pick the immediately best resting spot for my
        side by DD; failing contracts are assumed doubled by the enemy."""
        my_side = side_of(seat)
        pard = partner_of(seat)

        def side_score(level, denom, declarer, doubled) -> float:
            t = tricks.get((denom, declarer))
            if t is None:
                return float("-inf")
            vul = self._is_vul(side_of(declarer))
            sc = contract_score(level, denom, 1 if doubled else 0, vul,
                                int(t))
            return sc if side_of(declarer) == my_side else -sc

        def resting_score(st: AuctionState) -> float:
            standing = st.standing_contract()
            if standing is None:
                return 0.0
            need = standing.level + 6
            t = tricks.get((standing.denom, standing.declarer))
            if t is None:
                return float("-inf")
            doubled = standing.doubled
            if not doubled and int(t) < need \
                    and side_of(standing.declarer) == my_side:
                doubled = True   # omniscient enemies double our failures
            return side_score(standing.level, standing.denom,
                              standing.declarer, doubled)

        options: list[tuple[float, str]] = [(resting_score(state), "P")]
        if state.is_legal("X"):
            after = state.apply("X")
            standing = after.standing_contract()
            options.append((side_score(standing.level, standing.denom,
                                       standing.declarer, True), "X"))
        # candidate bids: my side's 8+ fits and my own best suit, plus NT,
        # at the cheapest legal level and at game level.
        denoms = {d for d in "SHDC"
                  if views[seat].length[d] + views[pard].length[d] >= 8}
        denoms.add(views[seat].best_suit())
        denoms.add("NT")
        for d in denoms:
            for lvl in {_min_level(state, d), GAME_LEVEL[d]}:
                if lvl < _min_level(state, d) or lvl > 5:
                    continue
                tok = f"{lvl}{d}"
                if not state.is_legal(tok):
                    continue
                declarer = state.first_namer.get((my_side, d), seat)
                t = tricks.get((d, declarer))
                if t is None:
                    continue
                fails = int(t) < lvl + 6
                options.append((side_score(lvl, d, declarer, fails), tok))
        best_score, best_tok = max(options, key=lambda x: (x[0], x[1] == "P"))
        pass_score = options[0][0]
        # bid/double only on strict improvement — guarantees termination
        return best_tok if best_score > pass_score else "P"

    def _is_vul(self, side: str) -> bool:
        return self.vul == "Both" or self.vul == side
