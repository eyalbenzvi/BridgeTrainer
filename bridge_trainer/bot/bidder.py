"""SimpleBidder v2: a deterministic rule-of-thumb 2/1-ish bidder.

v2 applies the expert review in docs/expert_review_v2.md: stopper checks on
every NT bid, negative doubles, sound penalty/takeout/power doubles, correct
suit-choice ordering, balancing-seat relaxation, and a slack mechanism so
the problem generator can enumerate near-miss rules as candidate actions.

Rule methods are GENERATORS yielding BotCall in priority order: `bid()`
takes the first (deterministic table behavior); `enumerate_calls()` collects
every rule that fires under a Slack setting (candidate generation). Doubles,
sacrifices and other STRICT families never receive slack.

Every call carries a sound constraint SIGNATURE (HCP range, per-suit
min/max, suit-quality floor) satisfied by any hand that makes that call —
passes included (INV8). Signature soundness is enforced by tests.

Known simplifications (disclosed): no Stayman/transfers or 2C (22+ hands
open their longest suit at the one level with a wide signature), crude NT
raises, no redoubles, no slam machinery. Level discipline guarantees
termination.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..dealing.features import HCP_BY_RANK, parse_hand_pbn

BOT_VERSION = 2

SUITS_DESC = ("S", "H", "D", "C")          # rank order high->low
DENOM_ORDER = ("C", "D", "H", "S", "NT")   # bidding order low->high

GAME_LEVEL = {"S": 4, "H": 4, "D": 5, "C": 5, "NT": 3}


def denom_rank(d: str) -> int:
    return DENOM_ORDER.index(d)


@dataclass(frozen=True)
class Slack:
    """Threshold relaxation for candidate enumeration (0 = strict play).

    hcp: relax hcp lower bounds down / upper bounds up by this much.
    sp: same for support-point bounds (and the LAW level, by 1 if > 0).
    q: relax suit-quality (shcp) floors.
    len6: relax suit-length minimums that are >= 6 (weak twos, preempts,
          six-card rebids) — structural lengths (3-card raises, 5-card
          overcalls) NEVER relax.
    Negative values tighten instead (used for edge detection).
    """

    hcp: int = 0
    sp: int = 0
    q: int = 0
    len6: int = 0


STRICT = Slack()
CANDIDATE_SLACK = Slack(hcp=2, sp=2, q=1, len6=1)
TIGHT = Slack(hcp=-1, sp=-1)


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

    def stop(self, suit: str) -> bool:
        """Stopper approximation: A alone; Kx/QJx-with-length stop."""
        return self.shcp[suit] >= 4 or (
            self.shcp[suit] >= 3 and self.length[suit] >= 2)


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


@dataclass
class BotCall:
    token: str            # "P", "X", or e.g. "3H"
    rule: str
    signature: Signature


@dataclass
class TableView:
    seat: str
    vul_us: bool
    vul_them: bool
    level: int            # 0 if no bid yet
    denom: str            # "" if no bid yet
    last_bidder_side: str  # "us"/"them"/"" relative to seat
    doubled: bool
    partner_min_hcp: float
    partner_max_hcp: float
    partner_suit_min: dict
    my_bids: list         # denoms I have bid
    partner_last_bid: str
    our_first_denom: str
    partner_opened: bool
    i_opened: bool
    they_opened: bool
    partner_doubled_takeout: bool
    my_call_count: int
    partner_passed_only: bool
    opening_denom_them: str
    opening_level_them: int
    my_opening_token: str
    passes_since_last_bid: int = 0

    def partner_mid(self) -> float:
        return (self.partner_min_hcp + min(self.partner_max_hcp, 24)) / 2

    def outbids(self, level: int, denom: str) -> bool:
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

    def __init__(self):
        self._k = STRICT

    # ------------------------------------------------------------- helpers
    def _enemy_suits(self, view: TableView) -> set:
        suits = set()
        if view.opening_denom_them and view.opening_denom_them != "NT":
            suits.add(view.opening_denom_them)
        if view.last_bidder_side == "them" and view.denom \
                and view.denom != "NT":
            suits.add(view.denom)
        return suits

    def _enemy_stopped(self, h: HandView, view: TableView) -> bool:
        return all(h.stop(s) for s in self._enemy_suits(view))

    # ------------------------------------------------------------- chain
    def _rules(self, hand: HandView, view: TableView):
        yield from self._hard_cap(hand, view)
        yield from self._opening(hand, view)
        yield from self._respond_to_partner(hand, view)
        yield from self._my_rebid(hand, view)
        yield from self._responder_rebid(hand, view)
        yield from self._direct_seat(hand, view)
        yield from self._advance_overcall(hand, view)
        yield from self._advance_double(hand, view)
        yield from self._competitive(hand, view)
        yield BotCall("P", "no_action", self._pass_signature(view))

    def bid(self, hand: HandView, view: TableView,
            slack: Slack = STRICT) -> BotCall:
        self._k = slack
        try:
            return next(self._rules(hand, view))
        finally:
            self._k = STRICT

    def enumerate_calls(self, hand: HandView, view: TableView,
                        slack: Slack = CANDIDATE_SLACK) -> list[BotCall]:
        """Every rule that fires under `slack`, deduped by token, in
        priority order. Strict families ignore the slack internally."""
        self._k = slack
        try:
            out, seen = [], set()
            for call in self._rules(hand, view):
                if call.token not in seen:
                    seen.add(call.token)
                    out.append(call)
            return out
        finally:
            self._k = STRICT

    def at_edge(self, hand: HandView, view: TableView,
                chosen_token: str) -> bool:
        """True if tightening slacked thresholds by 1 changes the call —
        the hero sits within 1 unit of a rule boundary."""
        return self.bid(hand, view, TIGHT).token != chosen_token

    # ------------------------------------------------------------ contexts
    def _hard_cap(self, hand, view):
        if view.level >= 6:
            yield BotCall("P", "cap_6level", Signature())

    def _opening(self, hand, view):
        if view.level != 0 or view.partner_opened or view.they_opened \
                or view.i_opened or view.my_call_count > 0:
            return
        h, k = hand, self._k
        if h.balanced and 15 - k.hcp <= h.hcp <= 17 + k.hcp:
            yield BotCall("1NT", "open_1nt", _sig((15, 17), BAL_MINS, BAL_MAXS))
        if h.balanced and 20 - k.hcp <= h.hcp <= 21 + k.hcp:
            yield BotCall("2NT", "open_2nt", _sig((20, 21), BAL_MINS, BAL_MAXS))
        if h.hcp >= 22 - k.hcp:
            suit = h.longest()
            yield BotCall(f"1{suit}", "open_big", _sig((22, 40), {suit: 4}))
            return
        rule_of_20 = h.hcp + sorted(h.length.values())[-1] \
            + sorted(h.length.values())[-2] >= 20
        if h.hcp >= 12 - k.hcp or (h.hcp in (10, 11) and rule_of_20):
            suit = self._opening_suit(h)
            yield BotCall(f"1{suit}", f"open_1{suit.lower()}",
                          _sig((10, 21), {suit: 5 if suit in "SH" else 3}))
            return
        if 5 - k.hcp <= h.hcp <= 10 + k.hcp:
            for s in ("S", "H", "D"):
                if h.length[s] >= 6 - k.len6 and h.shcp[s] >= 3 - k.q \
                        and all(h.length[m] < 4 for m in ("S", "H") if m != s):
                    yield BotCall(f"2{s}", f"weak_two_{s.lower()}",
                                  _sig((4, 11), {s: 5}, {s: 7},
                                       quality={s: 2}))
                    break
            for s in SUITS_DESC:
                if h.length[s] >= 7 - k.len6 and h.shcp[s] >= 3 - k.q \
                        and h.hcp <= 9 + k.hcp:
                    yield BotCall(f"3{s}", f"preempt_3{s.lower()}",
                                  _sig((4, 9), {s: 6}, quality={s: 2}))
                    break
        yield BotCall("P", "open_pass", _sig((0, 11)))

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
        """Partner opened and I have not BID yet (earlier passes allowed)."""
        if not view.partner_opened or view.i_opened or view.my_bids:
            return
        h, k = hand, self._k
        popen = view.our_first_denom
        if popen == "NT":
            if view.level == 1:
                for m in ("S", "H"):
                    if h.length[m] >= 6 - k.len6 and h.hcp >= 8 - k.hcp:
                        yield BotCall(f"4{m}", "resp_1nt_major_game",
                                      _sig((6, 15), {m: 5}))
                if h.hcp >= 10 - k.hcp:
                    yield BotCall("3NT", "resp_1nt_raise_game", _sig((8, 15)))
                if 8 - k.hcp <= h.hcp <= 9 + k.hcp:
                    yield BotCall("2NT", "resp_1nt_invite", _sig((6, 11)))
                yield BotCall("P", "resp_1nt_pass", _sig((0, 7)))
                return
            if view.level == 2 and view.outbids(3, "NT"):
                if h.hcp >= 5 - k.hcp:
                    yield BotCall("3NT", "resp_2nt_raise", _sig((3, 15)))
                yield BotCall("P", "resp_2nt_pass", _sig((0, 4)))
                return
        if popen in ("S", "H", "D", "C") and view.level <= 2:
            if h.hcp <= 5:
                yield BotCall("P", "resp_pass", _sig((0, 5)))
                return
            trump = popen
            if popen in ("S", "H") and h.length[trump] >= 3:
                sp = h.support_points(trump)
                # STRICT family: preemptive game raise.
                if h.length[trump] >= 5 and h.hcp <= 9 \
                        and view.outbids(4, trump):
                    yield BotCall(f"4{trump}", "resp_preemptive_game",
                                  _sig((3, 9), {trump: 5}))
                if sp >= 13 - k.sp and view.outbids(4, trump):
                    yield BotCall(f"4{trump}", "resp_game_raise",
                                  _sig((8, 40), {trump: 3}))
                if 10 - k.sp <= sp <= 12 + k.sp and view.outbids(3, trump):
                    yield BotCall(f"3{trump}", "resp_limit_raise",
                                  _sig((5, 12), {trump: 3}))
                if sp <= 9 + k.sp and view.outbids(2, trump):
                    yield BotCall(f"2{trump}", "resp_simple_raise",
                                  _sig((5, 10), {trump: 3}))
            # New suit at the one level: longest major first, H on ties.
            for s in sorted(("S", "H"),
                            key=lambda m: (-h.length[m], m != "H")):
                if s != popen and h.length[s] >= 4 \
                        and view.outbids(1, s) and view.cheapest_level(s) == 1:
                    yield BotCall(f"1{s}", "resp_new_suit_1",
                                  _sig((6, 30), {s: 4}))
                    break
            if h.hcp >= 12 - k.hcp:
                for s in ("C", "D", "H"):
                    if s != popen and h.length[s] >= 5 \
                            and view.cheapest_level(s) == 2 \
                            and view.outbids(2, s):
                        yield BotCall(f"2{s}", "resp_two_over_one",
                                      _sig((10, 26), {s: 5}))
                        break
            # Negative double (STRICT): interference, short there, other
            # major(s) held.
            if view.last_bidder_side == "them" and view.denom in SUITS_DESC \
                    and view.level <= 2 and not view.doubled \
                    and h.length[view.denom] <= 3:
                majors = [m for m in ("S", "H")
                          if m != popen and m != view.denom]
                if majors and all(h.length[m] >= 4 for m in majors) \
                        and h.hcp >= (6 if view.level == 1 else 8):
                    lo, hi = ((6, 11) if h.hcp <= 11 else (12, 40))
                    yield BotCall("X", "neg_double",
                                  _sig((lo, hi), {m: 4 for m in majors},
                                       {view.denom: 3}))
            if popen in ("D", "C") and h.length[popen] >= 4:
                sp = h.support_points(popen)
                if 6 - k.sp <= sp <= 9 + k.sp and view.outbids(2, popen):
                    yield BotCall(f"2{popen}", "resp_minor_raise",
                                  _sig((2, 9), {popen: 4}))
                if sp >= 10 - k.sp and view.outbids(3, popen):
                    yield BotCall(f"3{popen}", "resp_minor_limit",
                                  _sig((5, 16), {popen: 4}))
            if h.balanced and h.hcp >= 13 - k.hcp and view.outbids(3, "NT") \
                    and view.level <= 2 and self._enemy_stopped(h, view):
                yield BotCall("3NT", "resp_3nt", _sig((11, 16), BAL_MINS))
            if 6 - k.hcp <= h.hcp <= 10 + k.hcp \
                    and view.cheapest_level("NT") == 1 \
                    and self._enemy_stopped(h, view) \
                    and h.length["S"] <= 5 and h.length["H"] <= 5 \
                    and h.length["D"] <= 6 and h.length["C"] <= 6:
                yield BotCall("1NT", "resp_1nt", _sig(
                    (6, 10), maxs={"S": 5, "H": 5, "D": 6, "C": 6}))
            if 6 <= h.hcp <= 10 and view.level >= 2:
                yield BotCall("P", "resp_pass_competition", _sig((0, 10)))

    def _my_rebid(self, hand, view):
        """I opened at the ONE level; partner responded; my second call."""
        if not view.i_opened or view.my_call_count != 1 \
                or not view.my_opening_token.startswith("1") \
                or view.my_opening_token.endswith("NT"):
            return
        h, k = hand, self._k
        mine = view.our_first_denom
        pbid = view.partner_last_bid
        combined = h.hcp + view.partner_mid()
        # Partner made a negative double: show a major.
        if view.partner_doubled_takeout and pbid == "" and mine:
            their = view.denom
            for m in sorted(("S", "H"), key=lambda x: -h.length[x]):
                if m == their or m == mine or h.length[m] < 4:
                    continue
                lvl = view.cheapest_level(m)
                if lvl <= 2 and view.outbids(lvl, m):
                    yield BotCall(f"{lvl}{m}", "rebid_negx_major",
                                  _sig((10, 17), {m: 4}))
                    break
                if lvl == 3 and h.hcp >= 15 - k.hcp and view.outbids(3, m):
                    yield BotCall(f"3{m}", "rebid_negx_major_j",
                                  _sig((14, 21), {m: 4}))
                    break
        if pbid == mine and mine:
            game_level = GAME_LEVEL[mine]
            if view.level >= game_level:
                yield BotCall("P", "rebid_pass_game_reached", _sig((10, 40)))
                return
            if combined >= 24.5 - k.hcp and mine in ("S", "H") \
                    and view.outbids(4, mine):
                yield BotCall(f"4{mine}", "rebid_accept_game",
                              _sig((13, 40), {mine: 4}))
            if combined >= 24.5 - k.hcp and mine in ("D", "C") \
                    and h.balanced is False and view.outbids(5, mine):
                yield BotCall(f"5{mine}", "rebid_minor_game",
                              _sig((13, 40), {mine: 3}))
            if combined >= 25 - k.hcp and mine in ("D", "C") \
                    and view.outbids(3, "NT") \
                    and self._enemy_stopped(h, view):
                yield BotCall("3NT", "rebid_minor_3nt", _sig((13, 40)))
            yield BotCall("P", "rebid_pass_partscore", _sig((10, 17)))
            return
        if pbid and pbid != "NT" and h.length.get(pbid, 0) >= 4:
            sp = h.support_points(pbid)
            if sp + view.partner_mid() >= 25 - k.sp and pbid in ("S", "H") \
                    and view.outbids(4, pbid):
                yield BotCall(f"4{pbid}", "rebid_raise_game",
                              _sig((9, 40), {pbid: 4}))
            lvl = view.cheapest_level(pbid)
            if lvl <= 3 and view.outbids(lvl, pbid):
                yield BotCall(f"{lvl}{pbid}", "rebid_raise",
                              _sig((10, 16), {pbid: 4}))
        if mine and mine != "NT" and h.length.get(mine, 0) >= 6 - k.len6:
            lvl = view.cheapest_level(mine)
            if lvl <= 3 and view.outbids(lvl, mine):
                yield BotCall(f"{lvl}{mine}", "rebid_six_card",
                              _sig((10, 40), {mine: 6}))
        stopped = self._enemy_stopped(h, view)
        if h.balanced and 18 - k.hcp <= h.hcp <= 19 + k.hcp \
                and view.outbids(2, "NT") and stopped:
            yield BotCall("2NT", "rebid_2nt_1819", _sig((18, 19), BAL_MINS))
        if h.balanced and 11 - k.hcp <= h.hcp <= 14 + k.hcp \
                and view.cheapest_level("NT") == 1 and stopped:
            yield BotCall("1NT", "rebid_1nt_1214", _sig((11, 14), BAL_MINS))
        if combined >= 25 - k.hcp and h.balanced and view.outbids(3, "NT") \
                and stopped:
            yield BotCall("3NT", "rebid_3nt", _sig((9, 40), BAL_MINS))
        if h.hcp >= 17 - k.hcp and view.level <= 2 and stopped \
                and min(h.length.values()) >= 1 \
                and h.length[h.longest()] <= 5:
            lvl = view.cheapest_level("NT")
            if lvl <= 3 and view.outbids(lvl, "NT"):
                yield BotCall(f"{lvl}NT", "rebid_nt_strong", _sig((17, 40)))
        # Strong hand, no stopper for NT, no fit, no 6-card suit: rebid the
        # opened suit rather than trap-pass with 17+ (crude but sane).
        if h.hcp >= 17 - k.hcp and mine and mine != "NT":
            lvl = view.cheapest_level(mine)
            if lvl <= 3 and view.outbids(lvl, mine):
                yield BotCall(f"{lvl}{mine}", "rebid_suit_strong",
                              _sig((17, 40), {mine: 4}))
        yield BotCall("P", "rebid_pass",
                      _sig((10, 16)) if view.level <= 2 else _sig((10, 40)))

    def _responder_rebid(self, hand, view):
        """I responded to partner's opening (with a bid); partner rebid."""
        if not view.partner_opened or view.i_opened or not view.my_bids \
                or view.level == 0:
            return
        h, k = hand, self._k
        combined = h.hcp + view.partner_mid()
        stopped = self._enemy_stopped(h, view)
        if combined >= 25 - k.hcp:
            for m in ("S", "H"):
                if h.length[m] >= 4 and view.partner_suit_min.get(m, 0) >= 4 \
                        and view.outbids(4, m):
                    yield BotCall(f"4{m}", "resp_rebid_game_major",
                                  _sig((6, 30), {m: 4}))
                    break
            if view.level <= 3 and view.outbids(3, "NT") and stopped \
                    and h.length["S"] <= 5 and h.length["H"] <= 5:
                yield BotCall("3NT", "resp_rebid_3nt", _sig((6, 30)))
        if 23 - k.hcp <= combined < 25 + k.hcp \
                and view.partner_last_bid == "NT" \
                and view.cheapest_level("NT") == 2 and view.outbids(2, "NT") \
                and stopped:
            yield BotCall("2NT", "resp_rebid_invite", _sig((8, 13)))
        if view.last_bidder_side == "us":
            yield BotCall("P", "resp_rebid_stop", _sig((0, 13)))

    def _direct_seat(self, hand, view):
        """They opened; partner has not acted; my first call."""
        if not view.they_opened or view.partner_opened or view.i_opened \
                or view.my_call_count > 0 or view.partner_min_hcp > 0:
            return
        if view.last_bidder_side != "them":
            return
        h, k = hand, self._k
        their = view.opening_denom_them
        if their == "NT":
            yield BotCall("P", "pass_over_1nt", _sig((0, 14)))
            return
        balancing = view.passes_since_last_bid == 2
        relax = 3 if balancing else 0
        # Takeout double (STRICT except balancing relaxation): floor scales
        # with the level of their opening.
        x_floor = 12 + 2 * (view.level - 1) - relax
        unbid = [s for s in SUITS_DESC if s != their]
        if h.hcp >= x_floor and h.length[their] <= 2 \
                and all(h.length[s] >= 3 for s in unbid) and view.level <= 3:
            yield BotCall("X", "takeout_double",
                          _sig((x_floor, 40), {s: 3 for s in unbid},
                               {their: 2}))
        if h.balanced and 15 - k.hcp <= h.hcp <= 18 + k.hcp \
                and h.stop(their) and view.level == 1:
            yield BotCall("1NT", "overcall_1nt",
                          _sig((15, 18), BAL_MINS, quality={their: 3}))
        # Suit overcalls: longest suit first (rank breaks ties).
        for s in sorted((x for x in SUITS_DESC if x != their),
                        key=lambda x: (-h.length[x], -denom_rank(x))):
            if h.length[s] < 5:
                continue
            lvl = view.cheapest_level(s)
            if lvl == 1 and 8 - relax - k.hcp <= h.hcp <= 17 + k.hcp \
                    and (h.hcp >= 10 - relax or h.shcp[s] >= 4 - k.q):
                yield BotCall(f"1{s}", "overcall_1level",
                              _sig((max(4, 7 - relax), 17), {s: 5}))
                break
            if lvl == 2 and 11 - relax - k.hcp <= h.hcp <= 17 + k.hcp \
                    and h.shcp[s] >= 4 - k.q and view.level <= 2:
                yield BotCall(f"2{s}", "overcall_2level",
                              _sig((max(6, 11 - relax), 17), {s: 5},
                                   quality={s: 3}))
                break
            if lvl == 2 and 5 - k.hcp <= h.hcp <= 10 + k.hcp \
                    and h.length[s] >= 6 - k.len6 and h.shcp[s] >= 3 - k.q:
                yield BotCall(f"2{s}", "weak_jump_overcall",
                              _sig((4, 10), {s: 5}, quality={s: 2}))
                break
        # Power double (STRICT): too strong to sell, wrong shape otherwise.
        if h.hcp >= 17 and h.length[their] <= 3 and view.level <= 3:
            yield BotCall("X", "power_double", _sig((17, 40), maxs={their: 3}))
        yield BotCall("P", "direct_pass", _sig((0, 16)))

    def _advance_overcall(self, hand, view):
        """Partner overcalled (they opened first); my first call."""
        if view.partner_min_hcp <= 0 or not view.they_opened \
                or view.partner_opened or view.i_opened \
                or view.my_call_count > 0 or not view.partner_last_bid:
            return
        if view.partner_doubled_takeout:
            return
        h, k = hand, self._k
        suit = view.partner_last_bid
        if suit == "NT":
            yield BotCall("P", "advance_nt_pass", _sig((0, 8)))
            return
        if h.length.get(suit, 0) >= 3:
            sp = h.support_points(suit)
            trumps = h.length[suit]
            if sp >= 13 - k.sp and suit in ("S", "H") and view.outbids(4, suit):
                yield BotCall(f"4{suit}", "advance_game_raise",
                              _sig((8, 30), {suit: 3}))
            if trumps >= 4 and view.outbids(3, suit) and sp >= 5 - k.sp:
                yield BotCall(f"3{suit}", "advance_law_raise",
                              _sig((2, 18), {suit: 4}))
            if 7 - k.sp <= sp <= 11 + k.sp:
                lvl = view.cheapest_level(suit)
                if lvl <= 2 and view.outbids(lvl, suit):
                    yield BotCall(f"{lvl}{suit}", "advance_simple_raise",
                                  _sig((3, 11), {suit: 3}))
        yield BotCall("P", "advance_pass", _sig((0, 11)))

    def _advance_double(self, hand, view):
        """Partner made a takeout double; I must act (or pass for blood)."""
        if not view.partner_doubled_takeout or view.my_call_count > 0:
            return
        h, k = hand, self._k
        their = view.opening_denom_them or view.denom
        if h.length.get(their, 0) >= 5 and h.shcp.get(their, 0) >= 5:
            yield BotCall("P", "advance_x_penalty_pass",
                          _sig((3, 40), {their: 5}, quality={their: 5}))
            return
        best = max((s for s in SUITS_DESC if s != their),
                   key=lambda s: (h.length[s], denom_rank(s)))
        lvl = view.cheapest_level(best)
        if h.hcp >= 12 - k.hcp and best in ("S", "H") and h.length[best] >= 4 \
                and view.outbids(4, best):
            yield BotCall(f"4{best}", "advance_x_game",
                          _sig((11, 30), {best: 4}))
        if 9 - k.hcp <= h.hcp <= 11 + k.hcp and h.length[best] >= 4 \
                and lvl + 1 <= 3 and view.outbids(lvl + 1, best):
            yield BotCall(f"{lvl + 1}{best}", "advance_x_jump",
                          _sig((8, 11), {best: 4}))
        if lvl <= 3 and view.outbids(lvl, best):
            yield BotCall(f"{lvl}{best}", "advance_x_min",
                          _sig((0, 11), {best: 3}))
        yield BotCall("P", "advance_x_stuck", _sig((0, 11)))

    def _competitive(self, hand, view):
        """Later rounds: compete on fits, sound doubles, sacrifices."""
        if view.level == 0:
            return
        h, k = hand, self._k
        fit_suit, fit_count = "", 0
        for s in SUITS_DESC:
            shown = view.partner_suit_min.get(s, 0)
            assumed = 2 if (s == view.our_first_denom and s in view.my_bids) \
                else 0
            if shown >= 3 or assumed:
                total = h.length[s] + max(shown, assumed)
                if total > fit_count:
                    fit_suit, fit_count = s, total
        combined = h.hcp + view.partner_mid()
        their_turn = view.last_bidder_side == "them"

        if their_turn and view.denom and view.denom != "NT":
            them = view.denom
            # Penalty doubles (STRICT).
            if not view.doubled and view.level >= 2:
                if view.our_first_denom == "":
                    if view.level >= GAME_LEVEL[them] \
                            and h.length[them] >= 5 and h.shcp[them] >= 5 \
                            and h.hcp >= 13:
                        yield BotCall("X", "penalty_double_unopposed",
                                      _sig((13, 40), {them: 5},
                                           quality={them: 5}))
                else:
                    if h.length[them] >= 4 and h.shcp[them] >= 4 \
                            and h.hcp >= 11 and combined >= 20:
                        yield BotCall("X", "penalty_double_comp",
                                      _sig((11, 40), {them: 4},
                                           quality={them: 4}))
            if fit_suit and fit_count >= 8:
                law_level = fit_count - 6 + (1 if k.sp > 0 else 0)
                lvl = view.cheapest_level(fit_suit)
                game_level = GAME_LEVEL[fit_suit]
                if lvl <= law_level and view.outbids(lvl, fit_suit) \
                        and lvl < game_level:
                    yield BotCall(f"{lvl}{fit_suit}", "compete_law",
                                  _sig((2, 17), {fit_suit: 3}))
                if combined >= 24 - k.hcp and lvl <= game_level \
                        and view.outbids(game_level, fit_suit):
                    yield BotCall(f"{game_level}{fit_suit}", "compete_game",
                                  _sig((5, 40), {fit_suit: 3}))
                # Sacrifice (STRICT): favorable, huge fit, no defence.
                if not view.vul_us and view.vul_them and fit_count >= 10 \
                        and h.hcp <= 7 and view.level >= 4 and lvl <= 5 \
                        and view.outbids(lvl, fit_suit):
                    yield BotCall(f"{lvl}{fit_suit}", "sacrifice",
                                  _sig((0, 7), {fit_suit: 4}))

    @staticmethod
    def _pass_signature(view: TableView) -> Signature:
        if view.level == 0:
            return _sig((0, 11))
        return Signature()
