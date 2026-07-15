"""Random problem generation (spec M5, bot-driven).

Pipeline per seed:
  1. Deal a uniformly random board; pick random dealer + vulnerability.
  2. SimpleBidder bids for all four seats, recording each call's constraint
     signature. Every turn is scored for "decision-ness" (how many distinct
     plausible calls the seat had); one qualifying turn becomes the problem.
  3. The auction up to that turn is the stem; that seat is the hero. The
     concealed seats' signatures are inverted into a ConstraintProfile and
     layouts are simulated with the existing rejection dealer (INV2/INV3).
  4. Each candidate call is projected to a final contract PER LAYOUT by
     letting the bot bid out the auction (hero's later calls use the hero's
     real hand). DD + paired IMP comparison as usual (INV1..INV8).
  5. The problem is kept only if it is genuinely close (difficulty filter)
     and statistically sound; otherwise the seed is rejected.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
from endplay.types import Player

from .. import __version__ as trainer_version
from ..bot.bidder import BOT_VERSION, HandView, Signature, SimpleBidder
from ..bot.walker import AuctionWalker
from ..dd.correction import load_default_correction
from ..dealing.features import hand_to_pbn
from ..dealing.rejection import RejectionDealSource
from ..domain.auction import SEATS
from ..domain.constraints import Band, ConstraintProfile, SeatConstraints
from ..domain.interfaces import GenerationBudget
from ..pool.store import SCHEMA_VERSION
from ..scoring.comparison import compare_candidates
from ..scoring.evaluate import ScoreEvaluator, needed_denoms
from ..semantics.predicates import quality_floor

VULS = ("None", "NS", "EW", "Both")

MAX_DIFFICULTY_GAP = 3.0   # IMPs: top action must not win by more than this
MIN_ESS = 100.0
MAX_SHORTFALL_FRAC = 0.4
MAX_PUSH_RATE = 0.90       # all-candidates-transpose problems are boring


def signature_to_constraints(sigs: list[Signature]) -> SeatConstraints:
    """Invert a seat's accumulated call signatures into soft bands."""
    lo, hi = 0, 40
    suit_min: dict[str, int] = {}
    suit_max: dict[str, int] = {}
    quality: dict[str, int] = {}
    for sig in sigs:
        lo, hi = max(lo, sig.hcp[0]), min(hi, sig.hcp[1])
        for s, n in sig.suit_min.items():
            suit_min[s] = max(suit_min.get(s, 0), n)
        for s, n in sig.suit_max.items():
            suit_max[s] = min(suit_max.get(s, 13), n)
        for s, n in sig.quality.items():
            quality[s] = max(quality.get(s, 0), n)
    hi = max(lo, hi)
    hcp_bands = None
    if (lo, hi) != (0, 40):
        # Core band plus 1-HCP soft margins: bot thresholds are judgment,
        # not laws (INV2 importance weights carry the fuzz).
        hcp_bands = [Band(lo, hi, 1.0)]
        if lo > 0:
            hcp_bands.append(Band(lo - 1, lo - 1, 0.4))
        if hi < 40:
            hcp_bands.append(Band(hi + 1, min(hi + 1, 40), 0.4))
    suits = {}
    for s in ("S", "H", "D", "C"):
        mn, mx = suit_min.get(s, 0), suit_max.get(s, 13)
        if (mn, mx) != (0, 13):
            bands = [Band(mn, mx, 1.0)]
            if mn > 0:
                bands.append(Band(mn - 1, mn - 1, 0.3))
            suits[s] = bands
    exclusions = [quality_floor(s, n) for s, n in sorted(quality.items())]
    return SeatConstraints.from_bands(hcp=hcp_bands, suits=suits,
                                      exclusions=exclusions)


def _plausible_candidates(bidder: SimpleBidder, hand: HandView, view,
                          chosen: str) -> list[str]:
    """Distinct calls this seat could defensibly consider right now."""
    cands = [chosen]

    def add(tok):
        if tok not in cands:
            cands.append(tok)

    add("P")
    # Double: legal (their bid stands undoubled) and we hold real values.
    if view.level > 0 and view.last_bidder_side == "them" \
            and not view.doubled and hand.hcp >= 8:
        add("X")
    # Raise partner's suit one level.
    ps = view.partner_last_bid
    if ps and ps != "NT" and hand.length.get(ps, 0) >= 2:
        lvl = view.cheapest_level(ps)
        if lvl <= 4 and view.outbids(lvl, ps) \
                and hand.support_points(ps) >= 5:
            add(f"{lvl}{ps}")
    # Bid/rebid my longest suit.
    longest = hand.longest()
    if hand.length[longest] >= 5 and hand.hcp >= 6:
        lvl = view.cheapest_level(longest)
        if lvl <= 3 and view.outbids(lvl, longest):
            add(f"{lvl}{longest}")
    return cands[:4]


def _turn_interest(view, n_candidates: int, turn_index: int) -> int:
    if n_candidates < 2:
        return 0
    score = n_candidates
    if view.level >= 1 and view.last_bidder_side == "them":
        score += 2           # live competitive decision
    if view.level >= 2:
        score += 1
    if turn_index >= 4:
        score += 1           # later decisions tend to be richer
    return score


def generate_problem(seed: int, n_deals: int = 600,
                     bidder: SimpleBidder | None = None):
    """Returns (record, None) on success or (None, reject_reason)."""
    rng = np.random.default_rng([seed, 20260715])
    bidder = bidder or SimpleBidder()

    # 1. Random board.
    deck = rng.permutation(52).astype(np.int8)
    hands_pbn = {s: hand_to_pbn(deck[i * 13:(i + 1) * 13])
                 for i, s in enumerate(SEATS)}
    dealer = SEATS[int(rng.integers(4))]
    vul = VULS[int(rng.integers(4))]
    hands = {s: HandView.from_pbn(h) for s, h in hands_pbn.items()}

    # 2. Bid it out, scoring every turn for decision-ness.
    walker = AuctionWalker(dealer, vul, hands=hands, bidder=bidder)
    turns = []  # (interest, turn_index, seat, candidates, stem_tokens)
    while not walker.finished and len(walker.calls) < 24:
        seat = walker.next_to_call
        view = walker.view_for(seat)
        chosen = bidder.bid(hands[seat], view)
        cands = _plausible_candidates(bidder, hands[seat], view, chosen.token)
        interest = _turn_interest(view, len(cands), len(walker.calls))
        if interest >= 4:
            turns.append((interest, len(walker.calls), seat,
                          cands, walker.tokens()))
        walker.record(seat, chosen)

    if not turns:
        return None, "no decision point"

    # Prefer the most interesting turn; break ties toward later turns.
    turns.sort(key=lambda t: (t[0], t[1]))
    interest, turn_index, hero, candidates, stem_tokens = turns[-1]

    # 3. Rebuild the stem and invert concealed constraints.
    stem = AuctionWalker(dealer, vul, hands=hands, bidder=bidder)
    sigs: dict[str, list[Signature]] = {s: [] for s in SEATS}
    for _ in range(turn_index):
        seat, call = stem.step()
        if call.signature.informative:
            sigs[seat].append(call.signature)
    assert stem.next_to_call == hero

    profile = ConstraintProfile(seats={
        s: signature_to_constraints(sigs[s])
        for s in SEATS if s != hero
    })

    source = RejectionDealSource(my_seat=hero)
    deals, diag = source.generate(
        hands_pbn[hero], profile, n_deals, seed=seed + 1,
        budget=GenerationBudget(max_attempts=4_000_000, max_seconds=12.0))
    if not deals:
        return None, "constraints infeasible"
    if diag.shortfall > MAX_SHORTFALL_FRAC * n_deals:
        return None, f"generation shortfall {diag.shortfall}/{n_deals}"
    min_ess = min(MIN_ESS, 0.3 * n_deals)  # scaled for small test runs
    if diag.effective_sample_size < min_ess:
        return None, f"ESS too low ({diag.effective_sample_size:.0f})"

    # 4. Project every candidate on the identical deal set (INV1).
    deal_views = [{s: HandView.from_pbn(str(wd.deal[Player.find(s)]))
                   for s in SEATS} for wd in deals]
    contracts_by_candidate = {}
    for cand in candidates:
        contracts = []
        for views in deal_views:
            w = stem.clone_stem()
            w.hands = views
            w.force(cand)
            contracts.append(w.run_to_end())
        contracts_by_candidate[cand] = contracts

    evaluator = ScoreEvaluator(hero, vul, load_default_correction())
    evaluator.prepare(deals, contracts_by_candidate)
    weights = np.array([wd.weight for wd in deals])
    raw_scores, corr_scores = {}, {}
    for cand, contracts in contracts_by_candidate.items():
        raw_scores[cand], corr_scores[cand] = evaluator.evaluate(
            deals, contracts)

    ci_widen = float(np.sqrt(n_deals / len(deals))) if diag.shortfall else 1.0
    raw_cmp = compare_candidates(raw_scores, weights, ci_widen=ci_widen)
    corr_cmp = compare_candidates(corr_scores, weights, ci_widen=ci_widen)

    # 5. Interestingness filter on the verdict itself.
    top = corr_cmp.candidates[0]
    if top.ev_vs_best_alt > MAX_DIFFICULTY_GAP:
        return None, f"too one-sided ({top.ev_vs_best_alt:+.1f} IMPs)"
    if top.p_push > MAX_PUSH_RATE:
        return None, "candidates transpose (all push)"

    def rows(comp):
        return [{
            "action": c.action,
            "ev": round(c.ev_vs_best_alt, 2),
            "ci": round(c.ci_half_width, 2),
            "vs": c.best_alternative,
            "p_gain": round(c.p_gain, 3),
            "p_loss": round(c.p_loss, 3),
            "p_push": round(c.p_push, 3),
        } for c in comp.candidates]

    accepted = [corr_cmp.candidates[0].action]
    if corr_cmp.toss_up:
        accepted += corr_cmp.toss_up_with
    fog = (raw_cmp.toss_up != corr_cmp.toss_up
           or raw_cmp.verdict != corr_cmp.verdict)

    record = {
        "schema": SCHEMA_VERSION,
        "id": f"r{seed:08x}",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": {
            "bot_version": BOT_VERSION,
            "seed": seed,
            "n_deals": len(deals),
            "trainer_version": trainer_version,
        },
        "dealer": dealer,
        "vul": vul,
        "seat": hero,
        "hand": hands_pbn[hero],
        "auction": stem_tokens,
        "candidates": candidates,
        "verdict": {
            "accepted": accepted,
            "toss_up": corr_cmp.toss_up,
            "fog": fog,
            "corrected": rows(corr_cmp),
            "raw": rows(raw_cmp),
        },
        "difficulty": round(float(top.ev_vs_best_alt), 3),
        "quality": {
            "ess": round(diag.effective_sample_size, 1),
            "acceptance": round(diag.acceptance_rate, 6),
            "shortfall": diag.shortfall,
            "interest": interest,
        },
        "full_deal": {s: hands_pbn[s] for s in SEATS},
        "bot_auction_complete": walker.tokens(),
    }
    return record, None
