"""Weighted statistics (INV2): every estimate uses importance weights and
confidence intervals use the effective sample size, never the raw count."""
from __future__ import annotations

import numpy as np

Z95 = 1.959963984540054


def effective_sample_size(weights: np.ndarray) -> float:
    if len(weights) == 0:
        return 0.0
    s = weights.sum()
    return float(s * s / (weights ** 2).sum())


def weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    return float(np.average(values, weights=weights))


def weighted_ci(values: np.ndarray, weights: np.ndarray,
                widen: float = 1.0) -> tuple[float, float, float]:
    """(mean, half_width, ess). 95% CI via ESS; `widen` scales the half-width
    (used for generation shortfall per INV7)."""
    if len(values) == 0:
        return 0.0, float("inf"), 0.0
    mean = weighted_mean(values, weights)
    ess = effective_sample_size(weights)
    if ess <= 1:
        return mean, float("inf"), ess
    var = float(np.average((values - mean) ** 2, weights=weights))
    half = Z95 * np.sqrt(var / ess) * widen
    return mean, float(half), ess


def weighted_probability(mask: np.ndarray, weights: np.ndarray) -> float:
    if len(mask) == 0:
        return 0.0
    return float(weights[mask].sum() / weights.sum())
