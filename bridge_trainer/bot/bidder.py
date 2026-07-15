"""SimpleBidder v1: a deterministic rule-of-thumb 2/1-ish bidder.

Two jobs (spec M5):
  1. Stem generation — bid random deals until a seat faces a genuine
     decision, which becomes a training problem.
  2. Continuation projection — during simulation, bid out the rest of the
     auction on every layout so each reaches a final contract.

Every call carries a constraint SIGNATURE: coarse, sound bounds (HCP range,
per-suit min/max, optional suit-quality floor in honor points) satisfied by
any hand that makes that call. Signatures are inverted to constrain the
concealed hands during simulation — including passes (INV8).

Known simplifications (disclosed in the app/docs): no Stayman/transfers or
2C (22+ hands open their longest suit at the one level with a wide
signature), crude NT raises, no redoubles, no slam conventions. The aim is
"simplistic but sane", never absurd; level discipline guarantees the auction
terminates.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..dealing.features import HCP_BY_RANK, parse_hand_pbn

BOT_VERSION = 1

SUITS_DESC = ("S", "H", "D", "C")          # rank order high->low
DENOM_ORDER = ("C", "D", "H", "S", "NT")   # bidding order low->high


def denom_rank(d: str) -> int:
    return DENOM_ORDER.index(d)


@dataclass(frozen=True)
class HandView:
    """What the bot sees of its own 13 cards."""

    hcp: int
    length: dict          # suit -> count
    shcp: dict            # suit -> honor points in suit
    balanced: bool

    @classmethod
    def from_pbn(cls, hand: str) -> "HandView":
        cards = parse_hand_pbn(hand)
        length, shcp = {}, {}
        for i, s in enumerate(SUITS_DESC):
            in_suit = [c for c in cards if c // 13 == i]
            length[s] = len(in_suit)
            shcp[s] = int(sum(HCP_BY_RANK[c % 13] for c in in_suit))
        hcp = sum(shcp.values())
        lens = sorted(length.values())
        balanced = lens[0] >= 2 and lens.count(2) <= 1
        return cls(hcp=hcp, length=length, shcp=shcp, balanced=balanced)

    def longest(self, among=SUITS_DESC) -> str:
        return max(among, key=lambda s: (self.length[s], denom_rank(s)))

    def support_points(self, trump: str) -> int:
        """HCP + shortness when holding 4+ trumps, +1 with 3."""
        if self.length[trump] < 3:
            return self.hcp
        bonus = 0
        scale = {0: 5, 1: 3, 2: 1} if self.length[trump] >= 4 else {0: 3, 1: 2}
        for s in SUITS_DESC:
            if s != trump and self.length[s] in scale:
                bonus += scale[self.length[s]]
        return self.hcp + bonus


@dataclass(frozen=True)
class Signature:
    """Sound coarse bounds on a hand that makes a given call."""

    hcp: tuple = (0, 40)
    suit_min: dict = field(default_factory=dict)
    suit_max: dict = field(default_factory=dict)
    quality: dict = field(default_factory=dict)  # suit -> min honor points

    @property
    def informative(self) -> bool:
        return (self.hcp != (0, 40) or bool(self.suit_min)
                or bool(self.suit_max) or bool(self.quality))

    def mid_hcp(self) -> float:
        return (self.hcp[0] + min(self.hcp[1], 24)) / 2


@dataclass
class BotCall:
    token: str            # "P", "X", or e.g. "3H"
    rule: str
    signature: Signature


# ---------------------------------------------------------------------------
# Auction view: what the bidder is allowed to know at its turn.
# Built and maintained by AuctionWalker.
# ---------------------------------------------------------------------------
@dataclass
class TableView:
    seat: str
    vul_us: bool
    vul_them: bool
    # Current contract state
    level: int            # 0 if no bid yet
    denom: str            # "" if no bid yet
    last_bidder_side: str  # "us"/"them"/"" relative to seat
    doubled: bool
    # What partner / we have shown (from signature history)
    partner_min_hcp: float
    partner_max_hcp: float
    partner_suit_min: dict
    my_bids: list         # denoms I have bid
    partner_last_bid: str  # denom of partner's most recent bid, "" if none
    our_first_denom: str   # first denom our side bid, "" if none
    partner_opened: bool
    i_opened: bool
    they_opened: bool
    partner_doubled_takeout: bool
    my_call_count: int     # how many calls I have made (incl. passes)
    partner_passed_only: bool
    opening_denom_them: str  # their opening denom if they opened
    opening_level_them: int
    my_opening_token: str    # e.g. "1S" if I opened, "" otherwise

    def partner_mid(self) -> float:
        return (self.partner_min_hcp + min(self.partner_max_hcp, 24)) / 2

    def outbids(self, level: int, denom: str) -> bool:
        """Would (level, denom) be a legal raise over the current contract?"""
        if self.level == 0:
            return True
        return (level, denom_rank(denom)) > (self.level, denom_rank(self.denom))

    def cheapest_level(self, denom: str) -> int:
        if self.level == 0:
            return 1
        if denom_rank(denom) > denom_rank(self.denom):
            return self.level
        return self.level + 1


def _sig(hcp=(0, 40), mins=None, maxs=None, quality=None) -> Signature:
    return Signature(hcp=tuple(hcp), suit_min=mins or {}, suit_max=maxs or {},
                     quality=quality or {})


BAL_MINS = {s: 2 for s in SUITS_DESC}
BAL_MAXS = {s: 5 for s in SUITS_DESC}


class SimpleBidder:
    """Deterministic priority-rule bidder. See module docstring."""

    def bid(self, hand: HandView, view: TableView) -> BotCall:
        for fn in (self._hard_cap, self._opening, self._respond_to_partner,
                   self._my_rebid, self._responder_rebid, self._direct_seat,
                   self._advance_overcall, self._advance_double,
                   self._competitive):
            call = fn(hand, view)
            if call is not None:
                return call
        return BotCall("P", "no_action", self._pass_signature(view))

    # ------------------------------------------------------------- contexts
    def _hard_cap(self, hand, view):
        """Level discipline: at the 5-level+ only clear actions below fire;
        at the 6-level nobody bids on."""
        if view.level >= 6:
            return BotCall("P", "cap_6level", Signature())
        return None

    def _opening(self, hand, view):
        if view.level != 0 or view.partner_opened or view.they_opened \
                or view.i_opened or view.my_call_count > 0:
            return None
        h = hand
        if h.balanced and 15 <= h.hcp <= 17:
            return BotCall("1NT", "open_1nt",
                           _sig((15, 17), BAL_MINS, BAL_MAXS))
        if h.balanced and 20 <= h.hcp <= 21:
            return BotCall("2NT", "open_2nt",
                           _sig((20, 21), BAL_MINS, BAL_MAXS))
        if h.hcp >= 22:
            suit = h.longest()
            return BotCall(f"1{suit}", "open_big",
                           _sig((22, 40), {suit: 4}))
        # Weak two / preempt before sound openings are ruled out below 11.
        rule_of_20 = h.hcp + sorted(h.length.values())[-1] \
            + sorted(h.length.values())[-2] >= 20
        if h.hcp >= 11 or (h.hcp == 10 and rule_of_20):
            suit = self._opening_suit(h)
            return BotCall(f"1{suit}", f"open_1{suit.lower()}",
                           _sig((10, 21), {suit: 5 if suit in "SH" else 3}))
        if 5 <= h.hcp <= 10:
            for s in ("S", "H", "D"):
                if h.length[s] == 6 and h.shcp[s] >= 3 \
                        and h.length["S" if s != "S" else "H"] < 4:
                    return BotCall(f"2{s}", f"weak_two_{s.lower()}",
                                   _sig((4, 11), {s: 6}, {s: 6},
                                        quality={s: 3}))
            for s in SUITS_DESC:
                if h.length[s] >= 7 and h.shcp[s] >= 3 and h.hcp <= 9:
                    return BotCall(f"3{s}", f"preempt_3{s.lower()}",
                                   _sig((4, 9), {s: 7}, quality={s: 3}))
        return BotCall("P", "open_pass", _sig((0, 11)))

    @staticmethod
    def _opening_suit(h: HandView) -> str:
        if h.length["S"] >= 5 or h.length["H"] >= 5:
            if h.length["S"] >= h.length["H"] and h.length["S"] >= 5:
                return "S"
            if h.length["H"] >= 5:
                return "H"
        if h.length["D"] >= h.length["C"]:
            return "D" if h.length["D"] >= 4 or h.length["D"] > h.length["C"] \
                else "C"
        return "C"

    def _respond_to_partner(self, hand, view):
        """Partner opened and I have not BID yet (earlier passes allowed —
        a passed hand still responds)."""
        if not view.partner_opened or view.i_opened or view.my_bids:
            return None
        h = hand
        popen = view.our_first_denom
        # Responding to 1NT / 2NT (crude, no conventions).
        if popen == "NT":
            if view.level == 1:
                for m in ("S", "H"):
                    if h.length[m] >= 6 and h.hcp >= 8:
                        return BotCall(f"4{m}", "resp_1nt_major_game",
                                       _sig((8, 15), {m: 6}))
                if h.hcp >= 10:
                    return BotCall("3NT", "resp_1nt_raise_game", _sig((10, 15)))
                if 8 <= h.hcp <= 9:
                    return BotCall("2NT", "resp_1nt_invite", _sig((8, 9)))
                return BotCall("P", "resp_1nt_pass", _sig((0, 7)))
            if view.level == 2 and view.outbids(3, "NT"):
                if h.hcp >= 5:
                    return BotCall("3NT", "resp_2nt_raise", _sig((5, 15)))
                return BotCall("P", "resp_2nt_pass", _sig((0, 4)))
        # Responding to a suit opening.
        if popen in ("S", "H", "D", "C") and view.level <= 2:
            if h.hcp <= 5:
                return BotCall("P", "resp_pass", _sig((0, 5)))
            trump = popen
            if popen in ("S", "H") and h.length[trump] >= 3:
                sp = h.support_points(trump)
                if h.length[trump] >= 5 and h.hcp <= 9:
                    if view.outbids(4, trump):
                        return BotCall(f"4{trump}", "resp_preemptive_game",
                                       _sig((3, 9), {trump: 5}))
                if sp >= 13 and view.outbids(4, trump):
                    return BotCall(f"4{trump}", "resp_game_raise",
                                   _sig((8, 40), {trump: 3}))
                if 10 <= sp <= 12 and view.outbids(3, trump):
                    return BotCall(f"3{trump}", "resp_limit_raise",
                                   _sig((5, 12), {trump: 3}))
                if view.outbids(2, trump):
                    return BotCall(f"2{trump}", "resp_simple_raise",
                                   _sig((6, 9), {trump: 3}))
            # New suit at the one level (up the line, majors first by length).
            for s in ("S", "H"):
                if s != popen and h.length[s] >= 4 \
                        and view.outbids(1, s) and view.cheapest_level(s) == 1:
                    return BotCall(f"1{s}", "resp_new_suit_1",
                                   _sig((6, 30), {s: 4}))
            # Two-level new suit needs opening-ish values and a real suit.
            if h.hcp >= 12:
                for s in ("C", "D", "H"):
                    if s != popen and h.length[s] >= 5 \
                            and view.cheapest_level(s) == 2 and view.outbids(2, s):
                        return BotCall(f"2{s}", "resp_two_over_one",
                                       _sig((12, 26), {s: 5}))
            # Minor raise with real support.
            if popen in ("D", "C") and h.length[popen] >= 4:
                sp = h.support_points(popen)
                if 6 <= sp <= 9 and view.outbids(2, popen):
                    return BotCall(f"2{popen}", "resp_minor_raise",
                                   _sig((2, 9), {popen: 4}))
                if sp >= 10 and view.outbids(3, popen):
                    return BotCall(f"3{popen}", "resp_minor_limit",
                                   _sig((5, 16), {popen: 4}))
            if h.balanced and h.hcp >= 13 and view.outbids(3, "NT") \
                    and view.level <= 2:
                return BotCall("3NT", "resp_3nt", _sig((13, 16), BAL_MINS))
            if 6 <= h.hcp <= 10 and view.cheapest_level("NT") == 1:
                return BotCall("1NT", "resp_1nt", _sig((6, 10), maxs={
                    "S": 5, "H": 5, "D": 6, "C": 6}))
            if 6 <= h.hcp <= 10 and view.level >= 2:
                return BotCall("P", "resp_pass_competition", _sig((0, 10)))
        return None

    def _my_rebid(self, hand, view):
        """I opened at the ONE level; partner responded; my second call.
        Preempt/weak-two openers have said their piece: they fall through to
        the uninformative pass (their earlier signature must not be
        tightened by a constructive-sounding rebid pass)."""
        if not view.i_opened or view.my_call_count != 1 \
                or not view.my_opening_token.startswith("1"):
            return None
        h = hand
        mine = view.our_first_denom
        pbid = view.partner_last_bid
        combined = h.hcp + view.partner_mid()
        # Partner raised my suit.
        if pbid == mine and mine:
            game_level = 4 if mine in ("S", "H") else 5
            if view.level >= game_level:
                # Partner already put us in game: no slam machinery in v1.
                return BotCall("P", "rebid_pass_game_reached", _sig((10, 40)))
            if combined >= 24.5 and mine in ("S", "H") and view.outbids(4, mine):
                return BotCall(f"4{mine}", "rebid_accept_game",
                               _sig((13, 40), {mine: 4}))
            if combined >= 24.5 and mine in ("D", "C") \
                    and h.balanced is False and view.outbids(5, mine):
                return BotCall(f"5{mine}", "rebid_minor_game",
                               _sig((13, 40), {mine: 3}))
            if combined >= 25 and mine in ("D", "C") and view.outbids(3, "NT"):
                return BotCall("3NT", "rebid_minor_3nt", _sig((13, 40)))
            return BotCall("P", "rebid_pass_partscore", _sig((10, 17)))
        # Partner bid a new suit: raise with 4-card support.
        if pbid and pbid != "NT" and h.length.get(pbid, 0) >= 4:
            sp = h.support_points(pbid)
            if sp + view.partner_mid() >= 25 and pbid in ("S", "H") \
                    and view.outbids(4, pbid):
                return BotCall(f"4{pbid}", "rebid_raise_game",
                               _sig((9, 40), {pbid: 4}))
            lvl = view.cheapest_level(pbid)
            if lvl <= 3 and view.outbids(lvl, pbid):
                return BotCall(f"{lvl}{pbid}", "rebid_raise",
                               _sig((10, 16), {pbid: 4}))
        # Rebid a 6-card suit cheaply.
        if mine and mine != "NT" and h.length.get(mine, 0) >= 6:
            lvl = view.cheapest_level(mine)
            if lvl <= 3 and view.outbids(lvl, mine):
                return BotCall(f"{lvl}{mine}", "rebid_six_card",
                               _sig((10, 40), {mine: 6}))
        # NT rebids by range.
        if h.balanced and 18 <= h.hcp <= 19 and view.outbids(2, "NT"):
            return BotCall("2NT", "rebid_2nt_1819", _sig((18, 19), BAL_MINS))
        if h.balanced and view.cheapest_level("NT") == 1:
            return BotCall("1NT", "rebid_1nt_1214", _sig((11, 14), BAL_MINS))
        if combined >= 25 and h.balanced and view.outbids(3, "NT"):
            return BotCall("3NT", "rebid_3nt", _sig((9, 40), BAL_MINS))
        # Strong hand with no fitting rebid: force with NT rather than sell.
        if h.hcp >= 17 and view.level <= 2:
            lvl = view.cheapest_level("NT")
            if lvl <= 3 and view.outbids(lvl, "NT"):
                return BotCall(f"{lvl}NT", "rebid_nt_strong", _sig((17, 40)))
        return BotCall("P", "rebid_pass",
                       _sig((10, 16)) if view.level <= 2 else _sig((10, 40)))

    def _responder_rebid(self, hand, view):
        """I responded to partner's opening; partner rebid. Drive to game
        with the values, invite on the fringe, otherwise stop."""
        if not view.partner_opened or view.i_opened or not view.my_bids \
                or view.my_call_count < 2 or view.level == 0:
            return None
        combined = hand.hcp + view.partner_mid()
        if combined >= 25:
            for m in ("S", "H"):
                if hand.length[m] >= 4 and view.partner_suit_min.get(m, 0) >= 4 \
                        and view.outbids(4, m):
                    return BotCall(f"4{m}", "resp_rebid_game_major",
                                   _sig((6, 30), {m: 4}))
            if view.level <= 3 and view.outbids(3, "NT") \
                    and hand.length["S"] <= 5 and hand.length["H"] <= 5:
                return BotCall("3NT", "resp_rebid_3nt", _sig((6, 30)))
        if 23 <= combined < 25 and view.partner_last_bid == "NT" \
                and view.cheapest_level("NT") == 2 and view.outbids(2, "NT"):
            return BotCall("2NT", "resp_rebid_invite", _sig((10, 12)))
        if view.last_bidder_side == "us":
            return BotCall("P", "resp_rebid_stop", _sig((0, 13)))
        return None  # they intervened: fall through to competitive logic

    def _direct_seat(self, hand, view):
        """They opened; partner has not acted yet; my first call."""
        if not view.they_opened or view.partner_opened or view.i_opened \
                or view.my_call_count > 0 or view.partner_min_hcp > 0:
            return None
        if view.last_bidder_side != "them":
            return None
        h = hand
        their = view.opening_denom_them
        if their == "NT":
            return BotCall("P", "pass_over_1nt", _sig((0, 14)))
        # Takeout double: opening values, support for unbid suits, short there.
        unbid = [s for s in SUITS_DESC if s != their]
        if h.hcp >= 12 and h.length[their] <= 2 \
                and all(h.length[s] >= 3 for s in unbid) and view.level <= 3:
            return BotCall("X", "takeout_double",
                           _sig((12, 40), {s: 3 for s in unbid},
                                {their: 2}))
        # Strong balanced: 1NT overcall with a stopper-ish holding.
        if h.balanced and 15 <= h.hcp <= 18 and h.shcp[their] >= 3 \
                and view.level == 1:
            return BotCall("1NT", "overcall_1nt",
                           _sig((15, 18), BAL_MINS, quality={their: 3}))
        # Suit overcalls (quality matters when light).
        for s in SUITS_DESC:
            if s == their or h.length[s] < 5:
                continue
            lvl = view.cheapest_level(s)
            if lvl == 1 and 8 <= h.hcp <= 17 \
                    and (h.hcp >= 10 or h.shcp[s] >= 4):
                return BotCall(f"1{s}", "overcall_1level",
                               _sig((7, 17), {s: 5}, quality={s: 3}))
            if lvl == 2 and 11 <= h.hcp <= 17 and h.shcp[s] >= 4 \
                    and view.level <= 2:
                return BotCall(f"2{s}", "overcall_2level",
                               _sig((11, 17), {s: 5}, quality={s: 4}))
            if lvl == 2 and 5 <= h.hcp <= 10 and h.length[s] >= 6 \
                    and h.shcp[s] >= 3:
                return BotCall(f"2{s}", "weak_jump_overcall",
                               _sig((4, 10), {s: 6}, quality={s: 3}))
        # Too strong to sell out quietly, wrong shape for anything else.
        if h.hcp >= 16 and view.level <= 3:
            return BotCall("X", "power_double", _sig((16, 40)))
        return BotCall("P", "direct_pass", _sig((0, 15)))

    def _advance_overcall(self, hand, view):
        """Partner overcalled (they opened first); my first call."""
        if view.partner_min_hcp <= 0 or not view.they_opened \
                or view.partner_opened or view.i_opened \
                or view.my_call_count > 0 or not view.partner_last_bid:
            return None
        if view.partner_doubled_takeout:
            return None
        h = hand
        suit = view.partner_last_bid
        if suit == "NT":
            return BotCall("P", "advance_nt_pass", _sig((0, 8)))
        if h.length.get(suit, 0) >= 3:
            sp = h.support_points(suit)
            trumps = h.length[suit]
            if sp >= 13 and suit in ("S", "H") and view.outbids(4, suit):
                return BotCall(f"4{suit}", "advance_game_raise",
                               _sig((8, 30), {suit: 3}))
            # LAW-ish: with 4+ support jump to the level of the fit.
            if trumps >= 4 and view.outbids(3, suit) and sp >= 5:
                return BotCall(f"3{suit}", "advance_law_raise",
                               _sig((3, 18), {suit: 4}))
            if 7 <= sp <= 11:
                lvl = view.cheapest_level(suit)
                if lvl <= 2 and view.outbids(lvl, suit):
                    return BotCall(f"{lvl}{suit}", "advance_simple_raise",
                                   _sig((3, 11), {suit: 3}))
        return BotCall("P", "advance_pass", _sig((0, 9)))

    def _advance_double(self, hand, view):
        """Partner made a takeout double; I must act (or pass with length)."""
        if not view.partner_doubled_takeout or view.my_call_count > 0:
            return None
        h = hand
        their = view.opening_denom_them or view.denom
        # Penalty pass: real trump stack.
        if h.length.get(their, 0) >= 5 and h.shcp.get(their, 0) >= 5:
            return BotCall("P", "advance_x_penalty_pass",
                           _sig((3, 40), {their: 5}, quality={their: 5}))
        best = max((s for s in SUITS_DESC if s != their),
                   key=lambda s: (h.length[s], denom_rank(s)))
        lvl = view.cheapest_level(best)
        if h.hcp >= 12 and best in ("S", "H") and view.outbids(4, best):
            return BotCall(f"4{best}", "advance_x_game",
                           _sig((11, 30), {best: 4}))
        if 9 <= h.hcp <= 11 and lvl + 1 <= 3 and view.outbids(lvl + 1, best):
            return BotCall(f"{lvl + 1}{best}", "advance_x_jump",
                           _sig((8, 11), {best: 4}))
        if lvl <= 3 and view.outbids(lvl, best):
            return BotCall(f"{lvl}{best}", "advance_x_min",
                           _sig((0, 11), {best: 3}))
        return BotCall("P", "advance_x_stuck", _sig((0, 11)))

    def _competitive(self, hand, view):
        """Later rounds: compete on fits, double them on power, sacrifice."""
        if view.level == 0:
            return None
        h = hand
        # Our known fit (partner's shown length + mine).
        fit_suit, fit_count = "", 0
        for s in SUITS_DESC:
            shown = view.partner_suit_min.get(s, 0)
            if shown >= 3 or s == view.our_first_denom and shown >= 0:
                total = h.length[s] + max(shown, 2 if s == view.our_first_denom else 0)
                if total > fit_count:
                    fit_suit, fit_count = s, total
        combined = h.hcp + view.partner_mid()
        their_turn = view.last_bidder_side == "them"

        if their_turn and view.denom:
            # Penalty double of their high contract: trump stack + values.
            if view.level >= 3 and h.length.get(view.denom, 0) >= 4 \
                    and h.shcp.get(view.denom, 0) >= 4 and h.hcp >= 10 \
                    and not view.doubled:
                return BotCall("X", "penalty_double",
                               _sig((10, 40), {view.denom: 4},
                                    quality={view.denom: 4}))
            # Compete / push on the fit, LAW-ish: to the level of the fit.
            if fit_suit and fit_count >= 8:
                law_level = fit_count - 6
                lvl = view.cheapest_level(fit_suit)
                game_level = 4 if fit_suit in ("S", "H") else 5
                if lvl <= law_level and view.outbids(lvl, fit_suit) \
                        and lvl < game_level:
                    return BotCall(f"{lvl}{fit_suit}", "compete_law",
                                   _sig((2, 17), {fit_suit: 3}))
                if combined >= 24 and lvl <= game_level \
                        and view.outbids(game_level, fit_suit):
                    return BotCall(f"{game_level}{fit_suit}", "compete_game",
                                   _sig((5, 40), {fit_suit: 3}))
                # Sacrifice: favorable only, huge fit, nothing in defence.
                if not view.vul_us and view.vul_them and fit_count >= 10 \
                        and h.hcp <= 7 and view.level >= 4 and lvl <= 5 \
                        and view.outbids(lvl, fit_suit):
                    return BotCall(f"{lvl}{fit_suit}", "sacrifice",
                                   _sig((0, 7), {fit_suit: 4}))
        return None

    @staticmethod
    def _pass_signature(view: TableView) -> Signature:
        """A later-round pass: 'no clear action'. Kept generous (sound)."""
        if view.level == 0:
            return _sig((0, 11))
        return Signature()
