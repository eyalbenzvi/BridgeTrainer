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

DD solving — ~98% of the wall clock — is adaptive: deals are solved in
prefix increments (DD_CHECKPOINTS, then the full set) and after each
increment the corrected comparison decides whether to stop. A seed whose
top action already beats the difficulty gap by more than its CI is rejected
without solving the rest; a verdict that is safely inside every gate with a
tight CI is accepted on the prefix (the record's n_deals says how many were
used). All candidates always share the identical prefix (INV1). The solver
additionally routes strains that only rare contracts reach to per-board
solving instead of paying for them in every table (see dd/solver.py).
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
from endplay.types import Player

from .. import __version__ as trainer_version
from ..bot.bidder import (BOT_VERSION, CANDIDATE_SLACK, STRICT, TIGHT,
                          HandView, Signature, SimpleBidder)
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
MIN_INTEREST = 5           # expert_review_v2 §3.3 threshold

# Adaptive DD (see module docstring). Interim decisions at these prefix
# sizes; gates there are CI-guarded so a borderline seed keeps sampling.
DD_CHECKPOINTS = (200, 300)
EARLY_ACCEPT_CI = 0.8      # IMPs: CI tight enough to publish on a prefix
EARLY_PUSH_MARGIN = 0.05   # buffer on MAX_PUSH_RATE for interim decisions


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


def _max_fit(hand: HandView, view) -> int:
    return max(hand.length[s] + view.partner_suit_min.get(s, 0)
               for s in ("S", "H", "D", "C"))


def evaluate_turn(bidder: SimpleBidder, hand: HandView, view,
                  turn_index: int):
    """Candidate generation + problem-selection per expert_review_v2.md.

    Returns (chosen: BotCall, candidates: list[str], qualifies: bool,
    score: int). Candidates are bridge-legitimate options only: doubles come
    from the bidder's strict double rules (never a bare HCP test), bids from
    slack-fired rules passing level/fit floors, NT bids need stoppers, and
    Pass is included only when declining to act is coherent.
    """
    chosen = bidder.bid(hand, view)

    fired = bidder.enumerate_calls(hand, view, CANDIDATE_SLACK)
    strict_tokens = {c.token for c in bidder.enumerate_calls(hand, view,
                                                             STRICT)}

    picked: list[str] = []
    by_suit_level: dict[str, int] = {}
    for call in fired:
        tok = call.token
        if tok in ("P", chosen.token) or tok in picked:
            continue
        if tok == "X":
            # Doubles are strict rules (penalty/takeout/power/negative):
            # legitimate iff the rule itself fires (no slack inside).
            picked.append(tok)
            continue
        level, denom = int(tok[0]), tok[1:]
        if level >= 6:
            continue
        if denom == "NT":
            if not bidder._enemy_stopped(hand, view):
                continue
        else:
            fit = hand.length[denom] + view.partner_suit_min.get(denom, 0)
            if level == 4 and not (hand.length[denom] >= 5 or fit >= 8):
                continue
            if level == 5:
                if not (fit >= 9 or hand.length[denom] >= 7):
                    continue
                if hand.hcp <= 7 and not (not view.vul_us and view.vul_them):
                    continue  # sacrifice-flavoured: favorable only
            # Per suit keep the cheapest level unless the higher bid fired
            # strictly (a real game bid vs a courtesy raise).
            prev = by_suit_level.get(denom)
            if prev is not None and level > prev and tok not in strict_tokens:
                continue
        if denom != "NT":
            by_suit_level.setdefault(denom, level)
        picked.append(tok)

    # Pass legitimacy: (a) live competitive decision, or (b) the chosen rule
    # sits at its own threshold — tightening by 1 makes the bot pass.
    if chosen.token != "P":
        pass_ok = (view.last_bidder_side == "them"
                   or bidder.bid(hand, view, TIGHT).token == "P")
    else:
        pass_ok = False

    candidates = [chosen.token] + picked[:3]
    if chosen.token != "P" and pass_ok and "P" not in candidates:
        candidates.append("P")
    candidates = candidates[:4]

    alts = [c for c in candidates if c not in ("P", chosen.token)]

    # Qualification gate.
    if chosen.token != "P":
        qualifies = bool(alts) or pass_ok
    else:
        qualifies = bool(alts)

    # Exclusions.
    if qualifies and chosen.token == "P" and set(alts) == {"X"} \
            and view.our_first_denom == "" and view.partner_min_hcp == 0 \
            and view.denom and view.denom != "NT" \
            and view.level >= {"S": 4, "H": 4, "D": 5, "C": 5}[view.denom]:
        qualifies = False  # E1: lone X of their unopposed game
    if qualifies and view.level == 0 and view.passes_since_last_bid == 3:
        qualifies = False  # E2: 4th-seat pass-out turns

    score = 0
    if qualifies:
        score = 2
        if len(alts) + (1 if pass_ok and chosen.token != "P" else 0) >= 2:
            score += 2
        if view.our_first_denom != "" and (
                view.they_opened or view.last_bidder_side == "them"):
            score += 2
        if view.level >= 3:
            score += 1
        if view.level >= 4 and _max_fit(hand, view) >= 8:
            score += 1
        if chosen.token != "P" and bidder.at_edge(hand, view, chosen.token):
            score += 1
        if view.passes_since_last_bid == 2 and view.level > 0:
            score += 1
    return chosen, candidates, qualifies and score >= MIN_INTEREST, score


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
    turns = []  # (score, turn_index, seat, candidates, stem_tokens)
    while not walker.finished and len(walker.calls) < 24:
        seat = walker.next_to_call
        view = walker.view_for(seat)
        chosen, cands, qualifies, score = evaluate_turn(
            bidder, hands[seat], view, len(walker.calls))
        if qualifies:
            turns.append((score, len(walker.calls), seat,
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
    weights_all = np.array([wd.weight for wd in deals])
    ci_widen = float(np.sqrt(n_deals / len(deals))) if diag.shortfall else 1.0

    # 5. Adaptive DD + interestingness filter: solve prefix increments and
    # stop as soon as the accept/reject decision is resolved.
    denoms = needed_denoms(contracts_by_candidate)
    needed_pairs = [
        {(contracts[i].denom, contracts[i].declarer)
         for contracts in contracts_by_candidate.values()
         if not contracts[i].passed_out}
        for i in range(len(deals))
    ]
    n_avail = len(deals)
    checkpoints = sorted({min(c, n_avail) for c in DD_CHECKPOINTS}
                         | {n_avail})
    tricks: dict[tuple[str, str], np.ndarray] = {}
    solved = 0
    for k in checkpoints:
        new = evaluator.solver.solve(deals[solved:k], denoms,
                                     needed=needed_pairs[solved:k])
        for key, arr in new.items():
            tricks[key] = (np.concatenate([tricks[key], arr])
                           if key in tricks else arr)
        solved = k
        evaluator.set_tricks(tricks, k)
        weights = weights_all[:k]
        raw_scores, corr_scores = {}, {}
        for cand, contracts in contracts_by_candidate.items():
            raw_scores[cand], corr_scores[cand] = evaluator.evaluate(
                deals[:k], contracts[:k])
        raw_cmp = compare_candidates(raw_scores, weights, ci_widen=ci_widen)
        corr_cmp = compare_candidates(corr_scores, weights, ci_widen=ci_widen)
        top = corr_cmp.candidates[0]

        if k == n_avail:  # full set: the original point-estimate gates
            if top.ev_vs_best_alt > MAX_DIFFICULTY_GAP:
                return None, f"too one-sided ({top.ev_vs_best_alt:+.1f} IMPs)"
            if top.p_push > MAX_PUSH_RATE:
                return None, "candidates transpose (all push)"
            break
        # Interim: reject only when the gate is cleared by more than the CI.
        if top.ev_vs_best_alt - top.ci_half_width > MAX_DIFFICULTY_GAP:
            return None, (f"too one-sided ({top.ev_vs_best_alt:+.1f} IMPs, "
                          f"n={k})")
        if top.p_push > MAX_PUSH_RATE + EARLY_PUSH_MARGIN:
            return None, f"candidates transpose (all push, n={k})"
        # Accept early only when every gate is safely resolved AND the
        # stats are publication-tight.
        if (top.ev_vs_best_alt + top.ci_half_width <= MAX_DIFFICULTY_GAP
                and top.ci_half_width <= EARLY_ACCEPT_CI
                and top.p_push <= MAX_PUSH_RATE - EARLY_PUSH_MARGIN):
            break
    n_used = solved

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
        "id": f"b{BOT_VERSION}-{seed:08x}",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": {
            "bot_version": BOT_VERSION,
            "seed": seed,
            "n_deals": n_used,
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
            "ess": round(float(weights.sum() ** 2 / (weights ** 2).sum()), 1),
            "acceptance": round(diag.acceptance_rate, 6),
            "shortfall": diag.shortfall,
            "interest": interest,
        },
        "full_deal": {s: hands_pbn[s] for s in SEATS},
        "bot_auction_complete": walker.tokens(),
    }
    return record, None
