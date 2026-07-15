"""Paired comparison of candidate actions (INV1, INV5, INV7).

All candidates are scored on the IDENTICAL deal set; per-deal IMP differences
are computed pairwise and summarized with weighted statistics. Verdicts are
computed independently on raw and corrected scores; if they disagree the
problem is labelled "inside the DD fog". Differences within the CI or below
0.5 IMPs are a toss-up, never a winner.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .stats import weighted_ci, weighted_probability
from .tables import imps

TOSS_UP_IMPS = 0.5


@dataclass
class CandidateResult:
    action: str
    label: str
    ev_vs_best_alt: float = 0.0
    ci_half_width: float = 0.0
    ess: float = 0.0
    p_gain: float = 0.0
    p_loss: float = 0.0
    p_push: float = 0.0
    p_big_gain: float = 0.0  # P(swing >= +5 IMPs)
    p_big_loss: float = 0.0  # P(swing <= -5 IMPs)
    best_alternative: str = ""


@dataclass
class ComparisonResult:
    verdict: str            # winning action, or "" if toss-up
    toss_up: bool
    toss_up_with: list[str] = field(default_factory=list)
    candidates: list[CandidateResult] = field(default_factory=list)
    imp_matrix: dict[tuple[str, str], np.ndarray] = field(default_factory=dict)

    def result_for(self, action: str) -> CandidateResult:
        return next(c for c in self.candidates if c.action == action)


def pairwise_imps(scores: dict[str, np.ndarray]) -> dict[tuple[str, str], np.ndarray]:
    """Per-deal IMPs of action a over action b, for every ordered pair."""
    vimps = np.vectorize(imps, otypes=[np.int64])
    out = {}
    actions = list(scores)
    for a in actions:
        for b in actions:
            if a != b:
                out[(a, b)] = vimps(scores[a] - scores[b])
    return out


def compare_candidates(
    scores: dict[str, np.ndarray],
    weights: np.ndarray,
    labels: dict[str, str] | None = None,
    ci_widen: float = 1.0,
) -> ComparisonResult:
    """scores: action -> per-deal score from my side's perspective, all on
    the same deal set (INV1)."""
    actions = list(scores)
    labels = labels or {a: a for a in actions}
    matrix = pairwise_imps(scores)

    # Mean IMPs of each action against each alternative.
    means = {pair: weighted_ci(diff, weights, ci_widen)[0]
             for pair, diff in matrix.items()}

    # An action's "best alternative" is the rival it fares worst against.
    best_alt = {}
    for a in actions:
        rivals = [b for b in actions if b != a]
        best_alt[a] = min(rivals, key=lambda b: means[(a, b)])

    results = []
    for a in actions:
        b = best_alt[a]
        diff = matrix[(a, b)]
        mean, half, ess = weighted_ci(diff, weights, ci_widen)
        results.append(CandidateResult(
            action=a,
            label=labels[a],
            ev_vs_best_alt=mean,
            ci_half_width=half,
            ess=ess,
            p_gain=weighted_probability(diff > 0, weights),
            p_loss=weighted_probability(diff < 0, weights),
            p_push=weighted_probability(diff == 0, weights),
            p_big_gain=weighted_probability(diff >= 5, weights),
            p_big_loss=weighted_probability(diff <= -5, weights),
            best_alternative=b,
        ))

    # Winner = action with the best EV against its toughest rival.
    results.sort(key=lambda r: r.ev_vs_best_alt, reverse=True)
    top = results[0]
    # Toss-up (INV7): the top action must beat its best alternative by more
    # than both its CI half-width and 0.5 IMPs.
    toss_up_with = []
    if top.ev_vs_best_alt <= max(top.ci_half_width, TOSS_UP_IMPS):
        for r in results[1:]:
            mean, half, _ = weighted_ci(
                matrix[(top.action, r.action)], weights, ci_widen)
            if mean <= max(half, TOSS_UP_IMPS):
                toss_up_with.append(r.action)
    toss_up = bool(toss_up_with)
    return ComparisonResult(
        verdict="" if toss_up else top.action,
        toss_up=toss_up,
        toss_up_with=toss_up_with,
        candidates=results,
        imp_matrix=matrix,
    )
