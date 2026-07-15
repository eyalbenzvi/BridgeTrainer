"""Orchestrates one problem run: semantics -> dealing -> projection -> DD ->
scoring -> comparison. Produces a RunResult consumed by the CLI and the HTML
report."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..bank.schema import load_problem, resolve_ruleset_path
from ..dd.cache import DealSetCache, deal_set_cache_key, library_versions
from ..dd.correction import CorrectionTable, load_default_correction
from ..dealing.rejection import RejectionDealSource
from ..domain.deals import GenerationDiagnostics, WeightedDeal
from ..domain.interfaces import GenerationBudget
from ..domain.problem import BiddingProblem
from ..projection.tree import ConditionalTreeProjector, deal_features
from ..scoring.comparison import ComparisonResult, compare_candidates
from ..scoring.evaluate import ScoreEvaluator, needed_denoms
from ..semantics.engine import RuleEngine, load_ruleset


@dataclass
class BreakdownRow:
    bucket: str
    weight_share: float
    ev_by_pair: dict[str, float]  # "A vs B" -> weighted mean IMPs
    n: int


@dataclass
class Breakdown:
    feature: str
    label: str
    rows: list[BreakdownRow]


@dataclass
class DisasterDeal:
    pbn: str
    imp_swing: float
    contract_top: str
    contract_alt: str
    score_top: float
    score_alt: float


@dataclass
class RunResult:
    problem: BiddingProblem
    seed: int
    constraint_hash: str
    cache_key: str
    cache_hit: bool
    versions: dict[str, str]
    diagnostics: GenerationDiagnostics
    ci_widen: float
    raw: ComparisonResult
    corrected: ComparisonResult
    in_dd_fog: bool
    contracts_by_candidate: dict[str, list]
    raw_scores: dict[str, np.ndarray]
    corrected_scores: dict[str, np.ndarray]
    deals: list[WeightedDeal]
    features: list[dict]
    breakdowns: list[Breakdown] = field(default_factory=list)
    disasters: list[DisasterDeal] = field(default_factory=list)
    elapsed_s: float = 0.0

    @property
    def verdict_action(self) -> str:
        """Corrected verdict drives the headline (INV5 shows both)."""
        comp = self.corrected
        return comp.candidates[0].action

    def verdict_text(self) -> str:
        lines = []
        for name, comp in (("raw DD", self.raw), ("corrected", self.corrected)):
            if comp.toss_up:
                tied = ", ".join([comp.candidates[0].action] + comp.toss_up_with)
                lines.append(f"[{name}] toss-up between {tied}")
            else:
                top = comp.candidates[0]
                lines.append(
                    f"[{name}] {top.label}: {top.ev_vs_best_alt:+.2f} IMPs "
                    f"(±{top.ci_half_width:.2f}) vs {top.best_alternative}")
        if self.in_dd_fog:
            lines.append("⚠ raw and corrected verdicts disagree — "
                         "this problem is inside the DD fog")
        return "\n".join(lines)


def run_problem(
    problem_path: str | Path,
    seed: int,
    n_override: int | None = None,
    use_cache: bool = True,
    cache_dir: str | Path = ".trainer_cache",
    budget: GenerationBudget | None = None,
    correction: CorrectionTable | None = None,
) -> RunResult:
    t_start = time.perf_counter()
    problem_path = Path(problem_path)
    problem = load_problem(problem_path)
    n = n_override or problem.n_deals

    # Semantics: auction -> constraints (INV8: every call, incl. passes).
    our_rules = load_ruleset(
        resolve_ruleset_path(problem.our_system.ruleset, problem_path.parent))
    opps_rules = load_ruleset(
        resolve_ruleset_path(problem.opps_system.ruleset, problem_path.parent))
    engine = RuleEngine(our_rules, opps_rules, problem.my_seat)
    constraints = engine.extract(problem.auction)

    # INV4 cache key; INV6 determinism metadata.
    key = deal_set_cache_key(
        my_hand=problem.my_hand,
        constraints=constraints,
        system_fingerprints={
            problem.our_system.name: our_rules.fingerprint(),
            problem.opps_system.name: opps_rules.fingerprint(),
        },
        dealer=problem.dealer,
        vul=problem.vul,
        seed=seed,
        n=n,
    )
    constraint_hash = key[:16]

    cache = DealSetCache(cache_dir)
    cached = cache.load(key) if use_cache else None
    if cached is not None:
        deals, diagnostics = cached
        cache_hit = True
    else:
        source = RejectionDealSource(my_seat=problem.my_seat)
        deals, diagnostics = source.generate(
            problem.my_hand, constraints, n, seed, budget or GenerationBudget())
        if use_cache:
            cache.store(key, deals, diagnostics)
        cache_hit = False

    if not deals:
        raise RuntimeError(
            "generation produced no deals — constraints may be contradictory; "
            f"diagnostics: {diagnostics.to_dict()}")

    # Shortfall widens CIs and is reported (INV7).
    ci_widen = math.sqrt(n / len(deals)) if diagnostics.shortfall else 1.0

    # Projection: identical deal set for every candidate (INV1).
    features = [deal_features(wd.deal, problem.my_seat) for wd in deals]
    trees = {c.call: c.projection for c in problem.candidates}
    projector = ConditionalTreeProjector(trees, problem.my_seat)
    contracts_by_candidate = {
        c.call: [projector.project_features(f, c.call) for f in features]
        for c in problem.candidates
    }

    # DD + scoring, raw and corrected applied symmetrically (INV5). Trick
    # tables are cached per (deal-set key, denoms): the key already pins the
    # exact deal set (INV4), so cached DD results stay valid.
    evaluator = ScoreEvaluator(
        problem.my_seat, problem.vul, correction or load_default_correction())
    denoms = needed_denoms(contracts_by_candidate)
    tricks = cache.load_tricks(key, denoms) if use_cache else None
    if tricks is None:
        tricks = evaluator.solver.solve(deals, denoms)
        if use_cache:
            cache.store_tricks(key, denoms, tricks)
    evaluator.set_tricks(tricks, len(deals))
    weights = np.array([wd.weight for wd in deals])
    raw_scores, corrected_scores = {}, {}
    for call, contracts in contracts_by_candidate.items():
        raw_scores[call], corrected_scores[call] = evaluator.evaluate(
            deals, contracts)

    labels = {c.call: c.label for c in problem.candidates}
    raw_cmp = compare_candidates(raw_scores, weights, labels, ci_widen)
    corr_cmp = compare_candidates(corrected_scores, weights, labels, ci_widen)
    in_dd_fog = (raw_cmp.toss_up != corr_cmp.toss_up
                 or raw_cmp.verdict != corr_cmp.verdict)

    result = RunResult(
        problem=problem,
        seed=seed,
        constraint_hash=constraint_hash,
        cache_key=key,
        cache_hit=cache_hit,
        versions=library_versions(),
        diagnostics=diagnostics,
        ci_widen=ci_widen,
        raw=raw_cmp,
        corrected=corr_cmp,
        in_dd_fog=in_dd_fog,
        contracts_by_candidate=contracts_by_candidate,
        raw_scores=raw_scores,
        corrected_scores=corrected_scores,
        deals=deals,
        features=features,
    )
    result.breakdowns = _breakdowns(problem, result, weights)
    result.disasters = _disasters(result, weights)
    result.elapsed_s = time.perf_counter() - t_start
    return result


def _breakdowns(problem: BiddingProblem, result: RunResult,
                weights: np.ndarray) -> list[Breakdown]:
    """Weighted EV of the top action vs each rival, conditional on a feature."""
    comp = result.corrected
    top = comp.candidates[0].action
    rivals = [c.action for c in comp.candidates[1:]]
    out = []
    for spec in problem.breakdowns:
        feat = spec["feature"]
        values = np.array([f.get(feat, -1) for f in result.features])
        rows = []
        for v in sorted(set(values.tolist())):
            mask = values == v
            w = weights[mask]
            evs = {}
            for r in rivals:
                diffs = comp.imp_matrix[(top, r)][mask]
                evs[f"{top} vs {r}"] = float(np.average(diffs, weights=w))
            rows.append(BreakdownRow(
                bucket=str(v),
                weight_share=float(w.sum() / weights.sum()),
                ev_by_pair=evs,
                n=int(mask.sum()),
            ))
        out.append(Breakdown(feature=feat,
                             label=spec.get("label", feat), rows=rows))
    return out


def _disasters(result: RunResult, weights: np.ndarray,
               top_k: int = 3) -> list[DisasterDeal]:
    """Worst deals for the recommended action vs its best alternative."""
    comp = result.corrected
    top = comp.candidates[0]
    alt = top.best_alternative
    diffs = comp.imp_matrix[(top.action, alt)]
    order = np.argsort(diffs)[:top_k]
    out = []
    for i in order:
        if diffs[i] >= 0:
            break
        out.append(DisasterDeal(
            pbn=str(result.deals[i].deal),
            imp_swing=float(diffs[i]),
            contract_top=str(result.contracts_by_candidate[top.action][i]),
            contract_alt=str(result.contracts_by_candidate[alt][i]),
            score_top=float(result.raw_scores[top.action][i]),
            score_alt=float(result.raw_scores[alt][i]),
        ))
    return out
