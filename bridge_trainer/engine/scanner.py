"""Random-deal scanner: Ben bids all four seats; qualifying decision
points are turns where the policy genuinely splits (docs/
ben_execution_plan.md §3.1 + v2 amendments 4, 8, 12).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..dealing.features import hand_to_pbn
from .conventions import previous_call_is_asking, seat_of

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


def _gf_pass_artifact(policy, auction, dealer_i) -> bool:
    """A Pass candidate carrying real mass in a game-forcing auction is a
    model artifact (rec 4): 2C opening or an uncontested 2-level new-suit
    response (2/1 GF) present, game not yet reached."""
    if not any(b == "P" and p >= P_OPTION for b, p in policy):
        return False
    from .conventions import classify, _is_bid, _level  # noqa
    gf = False
    for j, tok in enumerate(auction):
        if tok == "2C" and not [t for t in auction[:j] if t != "P"]:
            gf = True
        info_needed = tok not in ("P", "X", "XX") and tok[0] == "2"
        if info_needed and not gf:
            info = classify(auction, dealer_i, j)
            if info.category == "new-suit" and info.jump == 0:
                # 2-level new suit by responder, uncontested = 2/1 GF
                me = seat_of(dealer_i, j)
                interference = any(
                    t != "P" and seat_of(dealer_i, k) not in (me, (me + 2) % 4)
                    for k, t in enumerate(auction[:j]))
                if not interference:
                    gf = True
    if not gf:
        return False
    last_bid = next((t for t in reversed(auction) if t not in ("P", "X", "XX")),
                    None)
    below_game = last_bid is None or (
        int(last_bid[0]) < 4 if last_bid[1:] in ("H", "S") else
        int(last_bid[0]) < 5 if last_bid[1:] in ("C", "D") else
        int(last_bid[0]) < 3)
    return below_game


def _content_exclusion(hand: str, policy, auction, dealer_i, seat_i) -> str:
    """Stage-0 content exclusions (selectivity review): agreement forks
    and engine-temperature splits that are close by the numbers but
    worthless or misleading to a 2/1 student."""
    from ..dealing.features import HCP_BY_RANK, parse_hand_pbn
    cands = [b for b, p in policy if p >= P_OPTION]

    # Bust artifact: engine splits on a near-yarborough with Pass live.
    cards = parse_hand_pbn(hand)
    hcp = sum(int(HCP_BY_RANK[c % 13]) for c in cards)
    maxlen = max(sum(1 for c in cards if c // 13 == s) for s in range(4))
    if hcp <= 4 and maxlen < 5 and "P" in cands:
        return "bust artifact"

    partner_i = (seat_i + 2) % 4
    my_passes = [j for j, t in enumerate(auction)
                 if seat_of(dealer_i, j) == seat_i and t == "P"]
    partner_bids = [t for j, t in enumerate(auction)
                    if seat_of(dealer_i, j) == partner_i
                    and t not in ("P", "X", "XX")]

    # Drury space: passed hand raising partner's major with 2C live.
    if my_passes and partner_bids and partner_bids[-1] in ("1H", "1S"):
        raise_call = "2" + partner_bids[-1][1]
        if "2C" in cands and raise_call in cands:
            return "system fork (Drury space)"

    # Negative-double range fork: responder directly over an overcall
    # with both X and a 2-level new suit among the candidates.
    if partner_bids and "X" in cands and any(
            b[0] == "2" and b not in ("2NT",) and b[1:] != partner_bids[-1][1:]
            for b in cands if b not in ("P", "X", "XX")):
        last = next((t for t in reversed(auction)
                     if t not in ("P", "X", "XX")), None)
        opp_last = last is not None and last != partner_bids[-1]
        if opp_last:
            return "system fork (negative-X range)"
    return ""


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
            nonpass = sum(1 for t in auction if t != "P")
            if nonpass > MAX_NONPASS_STEM:
                qualifies, why = False, "stem too deep"
            elif previous_call_is_asking(auction, dealer_i):
                qualifies, why = False, "response to asking call"
            elif _gf_pass_artifact(policy, auction, dealer_i):
                qualifies, why = False, "gf pass artifact"
            else:
                fork = _content_exclusion(hands[seat_i], policy, auction,
                                          dealer_i, seat_i)
                if fork:
                    qualifies, why = False, fork

        # Searched choice only where search can matter (>1 live candidate);
        # dominant turns commit the policy top directly — same call Ben's
        # own no-search shortcut would make, at NN cost instead of seconds.
        if len(policy) > 1:
            chosen, _resp = engine.choose(bots[seat_i], dealer_i, auction)
        else:
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
