"""Analysis pipeline: request -> constraints -> adaptive simulation -> DD ->
policy-ensemble scoring -> AnalysisResult (all facts, no prose).

Sampling is ADAPTIVE (spec 3.2): deals are generated in blocks and the run
stops as soon as the corrected-IMP gap between the two leading candidates
(realistic policy) is statistically settled — the 95% CI excludes zero, or
is narrow enough to call an honest toss-up — up to a hard cap (default
2000 deals, documented in DECISIONS.md). Every statistic is importance-
weighted with ESS-based CIs (INV2), all candidates score on the identical
deal set (INV1), and the single-dummy correction is applied symmetrically
with both raw and corrected shown (INV5).
"""
from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from ..dd.correction import load_default_correction
from ..dealing.rejection import RejectionDealSource
from ..domain.auction import Auction, partner_of, side_of
from ..domain.contracts import FinalContract
from ..domain.interfaces import GenerationBudget
from ..scoring.comparison import ComparisonResult, compare_candidates
from ..scoring.evaluate import ScoreEvaluator
from ..scoring.stats import weighted_ci
from ..validate.auction_state import AuctionStateError, replay
from .continuation import ContinuationEngine, deal_views, load_policies
from .systems import interpret_auction, load_system

# Adaptive-sampling knobs (see DECISIONS.md §2.4).
DEFAULT_MAX_DEALS = 2000
DEFAULT_BLOCK = 250
TOSS_UP_PRECISION_IMPS = 0.35   # CI half-width at which a tie is called
HERO_POLICIES = ("conservative", "realistic", "omniscient")


@dataclass
class AnalysisRequest:
    dealer: str
    vul: str                    # None/NS/EW/Both
    my_seat: str
    my_hand: str                # PBN suit-dot form
    auction: list[str]          # calls from the dealer, up to the decision
    # index of the analyzed call. The primary mode is decision_index ==
    # len(auction): the auction STOPS at the hero's turn and the question is
    # "what should I bid now?" (the actual choice is unknown). The legacy
    # mode (< len(auction)) analyzes a call inside a full recorded auction.
    decision_index: int
    system: str = "two_over_one"
    scoring: str = "IMP"        # or "MP"
    candidates: list[str] | None = None   # None -> auto-suggest
    overrides: dict[int, dict] = field(default_factory=dict)
    seed: int = 1
    max_deals: int = DEFAULT_MAX_DEALS
    block: int = DEFAULT_BLOCK
    narration: str = "template"           # or "llm"


@dataclass
class RepresentativeDeal:
    kind: str                   # typical / failure / disaster / best
    hands: dict[str, str]       # seat -> PBN
    imp_swing: float            # recommended vs best alternative
    contract_top: str
    contract_alt: str
    score_top: float
    score_alt: float
    weight: float
    # the projected continuation (realistic policy) after each action, as
    # (seat, call) pairs — the report shows HOW the auction was assumed to
    # continue, not just where it ended
    cont_top: list = field(default_factory=list)
    cont_alt: list = field(default_factory=list)


@dataclass
class PolicyOutcome:
    policy: str
    he: str
    he_desc: str
    raw: ComparisonResult
    corrected: ComparisonResult
    mp_pct: dict[str, float]            # candidate -> mean matchpoint %
    contract_freqs: dict[str, list]     # candidate -> [(contract, share)]
    partner_response_freqs: dict[str, list]  # candidate -> [(call, share)]
    top_action: str = ""


@dataclass
class AnalysisResult:
    request: AnalysisRequest
    stem: list[str]
    actual_call: str | None     # None in stem-only mode (choice unknown)
    candidates: list[str]
    meanings: list                       # CallMeaning for the full auction
    transparency_notes: list[str]
    policies: dict[str, PolicyOutcome]
    stable: bool
    stability_note: str
    recommended: str                     # by scoring mode, realistic policy
    n_deals: int
    ess: float
    acceptance_rate: float
    shortfall: int
    ci_widen: float
    stopped_early: bool
    top_pair: tuple[str, str]
    top_pair_mean_imp: float
    top_pair_ci: float
    representative: list[RepresentativeDeal]
    elapsed_s: float
    seed: int
    in_dd_fog: bool


# ---------------------------------------------------------------------------
def suggest_candidates(req: AnalysisRequest) -> list[str]:
    """Plausible actions at the decision point: the actual call, pass,
    double (with values), hero's 5+ suits, a raise of partner's suit, and
    NT with a stopper — legal calls only, capped at 6."""
    from ..dealing.features import HCP_BY_RANK, parse_hand_pbn
    state = replay(req.dealer, req.auction[:req.decision_index])
    cards = parse_hand_pbn(req.my_hand)
    length = {s: 0 for s in "SHDC"}
    shcp = {s: 0 for s in "SHDC"}
    hcp = 0
    for c in cards:
        s = "SHDC"[c // 13]
        length[s] += 1
        p = int(HCP_BY_RANK[c % 13])
        shcp[s] += p
        hcp += p

    out = ([req.auction[req.decision_index]]
           if req.decision_index < len(req.auction) else [])
    if state.is_legal("P"):
        out.append("P")
    if state.is_legal("X") and hcp >= 8:
        out.append("X")
    # partner's suit raise
    pard = partner_of(req.my_seat)
    pard_suit = next((c[1:] for s, c in zip(_seats_of(req), req.auction)
                      if s == pard and c not in ("P", "X", "XX")
                      and c[1:] != "NT"), None)
    enemy = state.denom if state.level and \
        side_of(state.last_bid_seat) != side_of(req.my_seat) else ""
    for suit, min_len in ([(pard_suit, 3)] if pard_suit else []) + \
            [(s, 5) for s in "SHDC"]:
        if suit and length.get(suit, 0) >= min_len and suit != enemy:
            lvl = state.level + (0 if state.level and
                                 _denom_gt(suit, state.denom) else 1)
            lvl = max(1, lvl)
            tok = f"{lvl}{suit}"
            if state.is_legal(tok):
                out.append(tok)
    if hcp >= 12 and (not enemy or (length.get(enemy, 0) >= 2
                                    and shcp.get(enemy, 0) >= 3)):
        lvl = state.level + (0 if state.level and
                             _denom_gt("NT", state.denom) else 1)
        lvl = max(1, lvl)
        # prefer 3NT over an awkward 2NT when the hand is strong
        if lvl <= 3:
            tok = f"{max(lvl, 3) if hcp >= 15 else lvl}NT"
            if state.is_legal(tok):
                out.append(tok)
    seen, uniq = set(), []
    for tok in out:
        if tok not in seen:
            seen.add(tok)
            uniq.append(tok)
    return uniq[:6]


def _denom_gt(a: str, b: str) -> bool:
    order = ("C", "D", "H", "S", "NT")
    return order.index(a) > order.index(b) if b else True


def _seats_of(req: AnalysisRequest):
    auction = Auction.from_tokens(req.dealer, req.auction)
    return [s for s, _ in auction.calls_with_seats()]


# ---------------------------------------------------------------------------
def run_analysis(req: AnalysisRequest, progress=None) -> AnalysisResult:
    t0 = time.perf_counter()
    _validate(req)
    stem = req.auction[:req.decision_index]
    actual = (req.auction[req.decision_index]
              if req.decision_index < len(req.auction) else None)

    candidates = req.candidates or suggest_candidates(req)
    if actual is not None and actual not in candidates:
        candidates = [actual] + candidates
    state = replay(req.dealer, stem)
    candidates = [c for c in candidates if state.is_legal(c)]
    if not candidates:
        raise ValueError("no legal candidate actions at the decision point")

    # constraints come from the STEM only — the hero cannot condition the
    # world on calls made after the decision; the full auction is still
    # interpreted for the report's call-by-call reading.
    table = load_system(req.system)
    stem_ia = interpret_auction(Auction.from_tokens(req.dealer, stem),
                                req.my_seat, table, table,
                                overrides=req.overrides)
    full_ia = interpret_auction(Auction.from_tokens(req.dealer, req.auction),
                                req.my_seat, table, table,
                                overrides=req.overrides)

    engine = ContinuationEngine(req.dealer, stem, req.my_seat, req.vul)
    policies_cfg = load_policies()
    source = RejectionDealSource(my_seat=req.my_seat)
    correction = load_default_correction()

    deals, weights_list = [], []
    diagnostics_acc = {"attempts": 0, "shortfall": 0}
    # per policy -> candidate -> list of per-block arrays
    raw_acc = {p: {c: [] for c in candidates} for p in HERO_POLICIES}
    cor_acc = {p: {c: [] for c in candidates} for p in HERO_POLICIES}
    contracts_acc = {p: {c: [] for c in candidates} for p in HERO_POLICIES}
    partner_calls_acc = {p: {c: [] for c in candidates}
                         for p in HERO_POLICIES}

    stopped_early = False
    block_i = 0
    while len(deals) < req.max_deals:
        want = min(req.block, req.max_deals - len(deals))
        block_seed = req.seed + 7919 * block_i
        block, diag = source.generate(
            req.my_hand, stem_ia.profile, want, block_seed,
            GenerationBudget(max_attempts=4_000_000, max_seconds=25))
        diagnostics_acc["attempts"] += diag.attempts
        if not block:
            if not deals:
                raise RuntimeError(
                    "generation produced no deals — the auction constraints "
                    f"appear contradictory (diagnostics: {diag.to_dict()})")
            diagnostics_acc["shortfall"] = req.max_deals - len(deals)
            break

        _score_block(block, candidates, engine, req, correction,
                     raw_acc, cor_acc, contracts_acc, partner_calls_acc)
        deals.extend(block)
        weights_list.extend(wd.weight for wd in block)
        block_i += 1
        if progress:
            progress(len(deals), req.max_deals)

        if _settled(cor_acc["realistic"], np.array(weights_list)):
            stopped_early = len(deals) < req.max_deals
            break

    weights = np.array(weights_list)
    acceptance = (len(deals) / diagnostics_acc["attempts"]
                  if diagnostics_acc["attempts"] else 0.0)
    shortfall = diagnostics_acc["shortfall"]
    ci_widen = float(np.sqrt(req.max_deals / len(deals))) if shortfall else 1.0

    policy_outcomes: dict[str, PolicyOutcome] = {}
    for pol in HERO_POLICIES:
        raw_scores = {c: np.concatenate(raw_acc[pol][c]) for c in candidates}
        cor_scores = {c: np.concatenate(cor_acc[pol][c]) for c in candidates}
        raw_cmp = compare_candidates(raw_scores, weights, ci_widen=ci_widen)
        cor_cmp = compare_candidates(cor_scores, weights, ci_widen=ci_widen)
        mp_pct = _mp_percent(cor_scores, weights)
        freqs = {c: _freq_table(contracts_acc[pol][c], weights)
                 for c in candidates}
        resp = {c: _freq_table(partner_calls_acc[pol][c], weights)
                for c in candidates}
        top = (max(mp_pct, key=mp_pct.get) if req.scoring == "MP"
               else cor_cmp.candidates[0].action)
        policy_outcomes[pol] = PolicyOutcome(
            policy=pol, he=policies_cfg[pol]["he"],
            he_desc=policies_cfg[pol]["he_desc"],
            raw=raw_cmp, corrected=cor_cmp, mp_pct=mp_pct,
            contract_freqs=freqs, partner_response_freqs=resp,
            top_action=top)

    tops = {p: policy_outcomes[p].top_action for p in HERO_POLICIES}
    stable = len(set(tops.values())) == 1
    if stable:
        stability_note = ("המסקנה יציבה: אותה פעולה מובילה תחת כל שלוש "
                          "המדיניות (שמרנית, ריאלית וחסם עליון).")
    else:
        parts = [f"{policies_cfg[p]['he']}: {tops[p]}" for p in HERO_POLICIES]
        stability_note = ("המסקנה רגישה להנחות ההמשך — הפעולה המובילה "
                          "מתחלפת בין המדיניות (" + "; ".join(parts) +
                          "). ההנחה הקובעת היא מדיניות ההמשך של השותף "
                          "והיריבים (ראו analysis/policies.yaml).")

    realistic = policy_outcomes["realistic"]
    recommended = realistic.top_action
    top_cand = realistic.corrected.candidates[0]
    second = top_cand.best_alternative
    diff = realistic.corrected.imp_matrix[(top_cand.action, second)]
    mean, half, _ = weighted_ci(diff, weights, ci_widen)

    reps = _representatives(deals, weights, realistic, contracts_acc,
                            raw_acc, recommended, engine)
    in_dd_fog = (realistic.raw.candidates[0].action
                 != realistic.corrected.candidates[0].action)

    return AnalysisResult(
        request=req, stem=stem, actual_call=actual, candidates=candidates,
        meanings=full_ia.meanings,
        transparency_notes=stem_ia.transparency_notes,
        policies=policy_outcomes, stable=stable,
        stability_note=stability_note, recommended=recommended,
        n_deals=len(deals),
        ess=float((weights.sum() ** 2) / (weights ** 2).sum()),
        acceptance_rate=acceptance, shortfall=shortfall, ci_widen=ci_widen,
        stopped_early=stopped_early,
        top_pair=(top_cand.action, second), top_pair_mean_imp=mean,
        top_pair_ci=half, representative=reps,
        elapsed_s=time.perf_counter() - t0, seed=req.seed,
        in_dd_fog=in_dd_fog)


# ---------------------------------------------------------------------------
def _validate(req: AnalysisRequest) -> None:
    from ..dealing.features import parse_hand_pbn
    parse_hand_pbn(req.my_hand)   # raises on malformed / != 13 cards
    if req.vul not in ("None", "NS", "EW", "Both"):
        raise ValueError(f"bad vulnerability {req.vul!r}")
    if req.scoring not in ("IMP", "MP"):
        raise ValueError(f"bad scoring mode {req.scoring!r}")
    state = replay(req.dealer, req.auction)  # AuctionStateError if illegal
    if not (0 <= req.decision_index <= len(req.auction)):
        raise ValueError("decision_index out of range")
    if req.decision_index == len(req.auction):
        # stem-only mode: the auction stops at the hero's turn
        if state.finished:
            raise AuctionStateError(
                "the auction is already over — enter it only up to your "
                "turn (no trailing passes)")
        if state.turn != req.my_seat:
            raise AuctionStateError(
                f"it is {state.turn}'s turn after the entered auction, "
                f"not {req.my_seat}'s")
        return
    seats = _seats_of(req)
    if seats[req.decision_index] != req.my_seat:
        raise AuctionStateError(
            f"call #{req.decision_index + 1} was made by "
            f"{seats[req.decision_index]}, not by {req.my_seat}")


def _score_block(block, candidates, engine, req, correction,
                 raw_acc, cor_acc, contracts_acc, partner_calls_acc) -> None:
    """Project + DD-solve + score one block under every policy."""
    from ..dd.solver import DDSolver
    denoms = set()
    for wd in block:
        denoms |= engine.denoms_possible(wd.deal, candidates)
    solver = DDSolver()
    tricks = solver.solve(block, denoms)

    evaluator = ScoreEvaluator(req.my_seat, req.vul, correction)
    evaluator.set_tricks(tricks, len(block))
    per_deal_tricks = [{k: int(v[i]) for k, v in tricks.items()}
                       for i in range(len(block))]

    pard = partner_of(req.my_seat)
    for pol in HERO_POLICIES:
        dd_mode = pol == "omniscient"
        for cand in candidates:
            contracts: list[FinalContract] = []
            first_partner_call: list[str] = []
            for i, wd in enumerate(block):
                per_deal = per_deal_tricks[i] if dd_mode else None
                fc, calls = engine.project_with_calls(
                    wd.deal, cand, pol, tricks=per_deal)
                contracts.append(fc)
                first_partner_call.append(_first_call_of(
                    calls, pard, engine, cand))
            raw, cor = evaluator.evaluate(block, contracts)
            raw_acc[pol][cand].append(raw)
            cor_acc[pol][cand].append(cor)
            contracts_acc[pol][cand].extend(str(c) for c in contracts)
            partner_calls_acc[pol][cand].extend(first_partner_call)


def _first_call_of(calls, pard, engine, cand) -> str:
    """Partner's first continuation call after the candidate."""
    state = replay(engine.dealer, engine.stem_tokens).apply(cand)
    seat = state.turn
    for tok in calls:
        if seat == pard:
            return tok
        state = state.apply(tok)
        seat = state.turn
    return "—"


def _settled(cor_by_cand: dict[str, list], weights: np.ndarray) -> bool:
    """Adaptive stop: leading-pair IMP gap significant, or a precise tie."""
    if len(weights) < 2 * DEFAULT_BLOCK and len(weights) < 500:
        return False   # never stop on the first block
    scores = {c: np.concatenate(a) for c, a in cor_by_cand.items()}
    cmp_res = compare_candidates(scores, weights)
    top = cmp_res.candidates[0]
    diff = cmp_res.imp_matrix[(top.action, top.best_alternative)]
    mean, half, _ = weighted_ci(diff, weights)
    return mean > half or half <= TOSS_UP_PRECISION_IMPS


def _mp_percent(scores: dict[str, np.ndarray],
                weights: np.ndarray) -> dict[str, float]:
    """Matchpoint % against the candidate field on the same deal (spec 3.6:
    frequency-based, not expectation-based). Field = the other candidates'
    results on the identical deal — the standard proxy when no real field
    data exists (documented in the report's caveats)."""
    cands = list(scores)
    out = {}
    for c in cands:
        rivals = [scores[b] for b in cands if b != c]
        if not rivals:
            out[c] = 50.0
            continue
        pct = np.zeros(len(weights))
        for r in rivals:
            pct += (scores[c] > r) + 0.5 * (scores[c] == r)
        pct /= len(rivals)
        out[c] = float(np.average(pct, weights=weights) * 100)
    return out


def _freq_table(items: list[str], weights: np.ndarray,
                top_k: int = 6) -> list[tuple[str, float]]:
    total = float(weights.sum()) or 1.0
    acc: Counter = Counter()
    for it, w in zip(items, weights):
        acc[it] += float(w)
    rows = [(k, v / total) for k, v in acc.most_common(top_k)]
    return [(k, round(share, 4)) for k, share in rows]


def _continuation_pairs(engine, deal, candidate: str) -> list:
    """(seat, call) pairs of the realistic continuation after `candidate`,
    passes trimmed off the tail — how the report shows the assumed auction."""
    _, calls = engine.project_with_calls(deal, candidate, "realistic")
    state = replay(engine.dealer, engine.stem_tokens).apply(candidate)
    pairs = []
    for tok in calls:
        pairs.append([state.turn, tok])
        state = state.apply(tok)
    while pairs and pairs[-1][1] == "P":
        pairs.pop()
    return pairs


def _representatives(deals, weights, realistic, contracts_acc, raw_acc,
                     recommended, engine,
                     big_loss=-5.0) -> list[RepresentativeDeal]:
    """3-5 concrete deals for the recommended action (spec 3.5): typical
    (nearest the median swing), best case, characteristic failure (~p10),
    and a disaster if one occurs with real frequency."""
    top = realistic.corrected.result_for(recommended)
    alt = top.best_alternative
    diff = realistic.corrected.imp_matrix[(recommended, alt)]
    raw_top = np.concatenate(raw_acc["realistic"][recommended])
    raw_alt = np.concatenate(raw_acc["realistic"][alt])
    n = len(diff)
    order = np.argsort(diff)

    def q_index(q: float) -> int:
        return int(order[min(n - 1, max(0, round(q * (n - 1))))])

    picks: list[tuple[str, int]] = [
        ("typical", q_index(0.5)),
        ("best", q_index(0.97)),
        ("failure", q_index(0.10)),
    ]
    worst = int(order[0])
    if diff[worst] <= big_loss:
        picks.append(("disaster", worst))

    out, seen = [], set()
    for kind, i in picks:
        if i in seen:
            continue
        seen.add(i)
        views_pbn = _hands_of(deals[i].deal)
        out.append(RepresentativeDeal(
            kind=kind, hands=views_pbn, imp_swing=float(diff[i]),
            contract_top=contracts_acc["realistic"][recommended][i],
            contract_alt=contracts_acc["realistic"][alt][i],
            score_top=float(raw_top[i]), score_alt=float(raw_alt[i]),
            weight=float(weights[i]),
            cont_top=_continuation_pairs(engine, deals[i].deal, recommended),
            cont_alt=_continuation_pairs(engine, deals[i].deal, alt)))
    return out


def _hands_of(deal) -> dict[str, str]:
    from endplay.types import Player
    return {s: str(deal[Player.find(s)]) for s in "NESW"}
