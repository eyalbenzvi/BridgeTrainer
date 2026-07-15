"""Weighted statistics (INV2) and toss-up labeling (INV7)."""
import numpy as np

from bridge_trainer.scoring.comparison import compare_candidates
from bridge_trainer.scoring.stats import (effective_sample_size, weighted_ci,
                                          weighted_mean, weighted_probability)


def test_ess_uniform_weights_equals_n():
    w = np.ones(100)
    assert effective_sample_size(w) == 100


def test_ess_concentrated_weights_shrinks():
    w = np.array([1.0] + [1e-9] * 99)
    assert effective_sample_size(w) < 1.01


def test_weighted_mean_and_probability():
    v = np.array([0.0, 10.0])
    w = np.array([1.0, 3.0])
    assert weighted_mean(v, w) == 7.5
    assert weighted_probability(v > 5, w) == 0.75


def test_ci_uses_ess_not_raw_n():
    rng = np.random.default_rng(0)
    v = rng.normal(size=1000)
    uniform = np.ones(1000)
    # Same values, but weight concentrated on 10 deals -> much wider CI.
    concentrated = np.full(1000, 1e-6)
    concentrated[:10] = 1.0
    _, half_uniform, ess_u = weighted_ci(v, uniform)
    _, half_conc, ess_c = weighted_ci(v, concentrated)
    assert ess_u == 1000
    assert ess_c < 11
    assert half_conc > 5 * half_uniform


def test_ci_widen_factor_scales_half_width():
    v = np.arange(100, dtype=float)
    w = np.ones(100)
    _, half1, _ = weighted_ci(v, w, widen=1.0)
    _, half2, _ = weighted_ci(v, w, widen=2.0)
    assert np.isclose(half2, 2 * half1)


def test_clear_winner_is_labelled():
    n = 400
    rng = np.random.default_rng(1)
    base = rng.normal(0, 30, size=n)
    scores = {"A": base + 300, "B": base}  # ~7 IMPs apart, every deal
    w = np.ones(n)
    result = compare_candidates(scores, w)
    assert not result.toss_up
    assert result.verdict == "A"
    top = result.candidates[0]
    assert top.action == "A"
    assert top.p_gain > 0.9


def test_tiny_difference_is_toss_up_never_a_winner():
    n = 400
    rng = np.random.default_rng(2)
    base = rng.normal(0, 30, size=n)
    scores = {"A": base + 5, "B": base}  # 5 points: 0 IMPs on most deals
    w = np.ones(n)
    result = compare_candidates(scores, w)
    assert result.toss_up
    assert result.verdict == ""
    assert "B" in result.toss_up_with or "A" in result.toss_up_with


def test_paired_comparison_identical_deal_set():
    # INV1 is structural: scores arrays must be same length; the IMP matrix
    # is antisymmetric on the shared deal set.
    n = 50
    rng = np.random.default_rng(3)
    scores = {"A": rng.normal(size=n) * 100, "B": rng.normal(size=n) * 100}
    result = compare_candidates(scores, np.ones(n))
    np.testing.assert_array_equal(result.imp_matrix[("A", "B")],
                                  -result.imp_matrix[("B", "A")])
