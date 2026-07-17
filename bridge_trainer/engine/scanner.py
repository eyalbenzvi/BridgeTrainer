"""Random-deal scanner: Ben bids all four seats; qualifying decision
points are turns where the policy genuinely splits (docs/
ben_execution_plan.md §3.1 + v2 amendments 4, 8, 12).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..dealing.features import hand_to_pbn
from .conventions import seat_of

SEATS = "NESW"
VULS = [(False, False), (True, False), (False, True), (True, True)]
VUL_NAMES = {(False, False): "None", (True, False): "NS",
             (False, True): "EW", (True, True): "Both"}

P_TOP = 0.70
P_SECOND = 0.15
P_TOP_3WAY = 0.60
P_23_SUM = 0.25
P_OPTION = 0.08
STEM_MASS_FLOOR = 0.05
MAX_NONPASS_STEM = 10
MAX_CANDIDATES = 5


@dataclass
class Turn:
    idx: int
    seat_i: int
    policy: list            # [(bid, p)] sorted desc
    chosen: str
    eligible: bool
    why_ineligible: str = ""


@dataclass
class Spot:
    seed: int
    dealer_i: int
    vul: tuple
    hands: list[str]              # pbn per seat N,E,S,W
    stem: list[str]               # auction up to the decision point
    hero_i: int
    candidates: list              # [(bid, p)]
    p_top: float
    full_auction: list[str]       # Ben's complete table auction
    turns: list[Turn] = field(default_factory=list)


def deal_board(seed: int):
    rng = np.random.default_rng([seed, 4242])
    deck = rng.permutation(52)
    hands = [hand_to_pbn(np.sort(deck[i * 13:(i + 1) * 13])) for i in range(4)]
    dealer_i = int(rng.integers(0, 4))
    vul = VULS[int(rng.integers(0, 4))]
    return hands, dealer_i, vul


def bid_out(engine, seed: int):
    """Deal a board and let Ben bid all four seats to conclusion.

    Returns (hands, dealer_i, vul, full_auction). This is the play-out that
    the opening-lead maker needs for EVERY board (the completed auction and
    its final contract), whereas scan_board keeps only boards with a bidding
    dilemma. Kept deliberately parallel to scan_board's committing loop.
    """
    hands, dealer_i, vul = deal_board(seed)
    bots = [engine.bot(hands[i], i, dealer_i, vul) for i in range(4)]
    auction: list[str] = []
    while True:
        n = len(auction)
        if n >= 3 and all(t == "P" for t in auction[-3:]) and \
                any(t != "P" for t in auction):
            break
        if n >= 4 and all(t == "P" for t in auction):
            break  # passed out
        if n > 40:
            break  # runaway guard
        seat_i = seat_of(dealer_i, n)
        policy = engine.policy(bots[seat_i], dealer_i, auction)
        auction.append(policy[0].bid if policy else "P")
    return hands, dealer_i, vul, auction


def scan_board(engine, seed: int, scan_log=None) -> Spot | None:
    hands, dealer_i, vul = deal_board(seed)
    bots = [engine.bot(hands[i], i, dealer_i, vul) for i in range(4)]
    auction: list[str] = []
    turns: list[Turn] = []

    while True:
        n = len(auction)
        if n >= 3 and all(t == "P" for t in auction[-3:]) and \
                any(t != "P" for t in auction):
            break
        if n >= 4 and all(t == "P" for t in auction):
            break  # passed out
        if n > 40:
            break  # runaway guard
        # early stop: too deep for any further eligible turn (owner r3 #1)
        if sum(1 for t in auction if t != "P") > MAX_NONPASS_STEM + 3 \
                and not any(t.eligible for t in turns):
            return None
        seat_i = seat_of(dealer_i, n)
        policy = [(it.bid, it.p) for it in
                  engine.policy(bots[seat_i], dealer_i, auction)]
        p1 = policy[0][1] if policy else 1.0
        p2 = policy[1][1] if len(policy) > 1 else 0.0
        p3 = policy[2][1] if len(policy) > 2 else 0.0

        qualifies = (p1 < P_TOP and p2 >= P_SECOND) or \
                    (p1 < P_TOP_3WAY and p2 + p3 >= P_23_SUM)
        why = ""
        if qualifies:
            # the ONLY eligibility rules are the agreed mechanical ones
            # (owner r8): stem depth; everything else is decided by the
            # statistical gates downstream
            nonpass = sum(1 for t in auction if t != "P")
            if nonpass > MAX_NONPASS_STEM:
                qualifies, why = False, "stem too deep"

        # Speed (owner r3 #1): scan commits the raw policy top at every
        # turn — no internal search. The stem-mass floor still discards
        # engine-weird stems; the verdict stage does the real judging.
        chosen = policy[0][0]
        turns.append(Turn(idx=n, seat_i=seat_i, policy=policy,
                          chosen=chosen, eligible=qualifies,
                          why_ineligible=why))
        if scan_log:
            scan_log(f"  turn {n} {SEATS[seat_i]}: "
                     f"{[(b, round(p, 2)) for b, p in policy[:3]]} -> {chosen}"
                     f"{' [DILEMMA]' if qualifies else ''}")
        auction.append(chosen)

    eligible = [t for t in turns if t.eligible]
    if not eligible:
        return None
    best = min(eligible, key=lambda t: t.policy[0][1])

    # stem-mass floor on every committed call before the decision point
    for t in turns[:best.idx]:
        pmap = dict(t.policy)
        if pmap.get(t.chosen, 0.0) < STEM_MASS_FLOOR:
            return None  # engine-weird stem, discard board

    candidates = [(b, p) for b, p in best.policy if p >= P_OPTION]
    if not any(b == best.policy[0][0] for b, _ in candidates):
        candidates.insert(0, best.policy[0])
    candidates = candidates[:MAX_CANDIDATES]
    if len(candidates) < 2:
        return None

    return Spot(seed=seed, dealer_i=dealer_i, vul=vul, hands=hands,
                stem=auction[:best.idx], hero_i=best.seat_i,
                candidates=candidates, p_top=best.policy[0][1],
                full_auction=auction, turns=turns)
