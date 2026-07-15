"""Rejection DealSource: correctness of constraints/weights, determinism
(INV6), budget degradation, and the INV3 chi-square sanity check."""
import numpy as np
import pytest
from endplay.types import Player

from bridge_trainer.dealing.features import HCP_BY_RANK, parse_hand_pbn
from bridge_trainer.dealing.rejection import RejectionDealSource
from bridge_trainer.domain.auction import Auction
from bridge_trainer.domain.constraints import Band, ConstraintProfile, SeatConstraints
from bridge_trainer.domain.interfaces import GenerationBudget

MY_HAND = "K93.752.A854.T62"


def hand_stats(deal, seat):
    cards = parse_hand_pbn(str(deal[Player.find(seat)]))
    hcp = int(sum(HCP_BY_RANK[c % 13] for c in cards))
    lengths = {s: sum(1 for c in cards if c // 13 == i)
               for i, s in enumerate("SHDC")}
    return hcp, lengths


def profile_1h_1s_3h():
    return ConstraintProfile(seats={
        "W": SeatConstraints.from_bands(
            hcp=[Band(11, 21), Band(10, 10, 0.4)],
            suits={"H": [Band(5, 8)]}),
        "N": SeatConstraints.from_bands(
            hcp=[Band(8, 16)], suits={"S": [Band(5, 7)]}),
        "E": SeatConstraints.from_bands(
            hcp=[Band(2, 8)], suits={"H": [Band(4, 5), Band(3, 3, 0.2)]}),
    })


def test_generated_deals_satisfy_constraints_and_weights():
    source = RejectionDealSource("S", batch_size=20_000)
    deals, diag = source.generate(MY_HAND, profile_1h_1s_3h(), 50, seed=7)
    assert len(deals) == 50
    assert diag.shortfall == 0
    assert 0 < diag.acceptance_rate < 1
    assert 0 < diag.effective_sample_size <= 50
    for wd in deals:
        w_hcp, w_len = hand_stats(wd.deal, "W")
        n_hcp, n_len = hand_stats(wd.deal, "N")
        e_hcp, e_len = hand_stats(wd.deal, "E")
        assert 10 <= w_hcp <= 21 and 5 <= w_len["H"] <= 8
        assert 8 <= n_hcp <= 16 and 5 <= n_len["S"] <= 7
        assert 2 <= e_hcp <= 8 and 3 <= e_len["H"] <= 5
        # South's fixed hand really is mine on every deal.
        assert str(wd.deal[Player.south]) == MY_HAND
        # Weight = product of matched band weights.
        expected = 1.0
        if w_hcp == 10:
            expected *= 0.4
        if e_len["H"] == 3:
            expected *= 0.2
        assert wd.weight == pytest.approx(expected)


def test_determinism_same_seed_same_deals_inv6():
    source = RejectionDealSource("S")
    a, _ = source.generate(MY_HAND, profile_1h_1s_3h(), 30, seed=42)
    b, _ = source.generate(MY_HAND, profile_1h_1s_3h(), 30, seed=42)
    assert [str(x.deal) for x in a] == [str(x.deal) for x in b]
    c, _ = source.generate(MY_HAND, profile_1h_1s_3h(), 30, seed=43)
    assert [str(x.deal) for x in a] != [str(x.deal) for x in c]


def test_budget_degrades_gracefully_with_shortfall():
    source = RejectionDealSource("S", batch_size=5_000)
    budget = GenerationBudget(max_attempts=10_000, max_seconds=60)
    deals, diag = source.generate(MY_HAND, profile_1h_1s_3h(), 5_000, 1, budget)
    assert len(deals) < 5_000
    assert diag.shortfall == 5_000 - len(deals)
    assert diag.attempts <= 10_000


def test_exclusions_reject_matching_hands():
    profile = ConstraintProfile(seats={
        "W": SeatConstraints.from_bands(
            hcp=[Band(11, 21)], suits={"H": [Band(5, 8)]},
            exclusions=["balanced_15_17"]),
    })
    source = RejectionDealSource("S")
    deals, _ = source.generate(MY_HAND, profile, 200, seed=3)
    for wd in deals:
        hcp, lengths = hand_stats(wd.deal, "W")
        balanced = (min(lengths.values()) >= 2
                    and sum(1 for v in lengths.values() if v == 2) <= 1)
        assert not (balanced and 15 <= hcp <= 17)


def test_unconstrained_matches_hypergeometric_chi_square_inv3():
    """INV3 sanity: with no constraints, a hidden seat's spade-length
    distribution must match the exact combinatorial frequencies for the 39
    unseen cards (10 spades among them)."""
    from math import comb

    source = RejectionDealSource("S", batch_size=20_000)
    deals, _ = source.generate(MY_HAND, ConstraintProfile(), 4_000, seed=11)
    assert len(deals) == 4_000

    counts = np.zeros(11)
    for wd in deals:
        _, lengths = hand_stats(wd.deal, "W")
        counts[lengths["S"]] += 1

    # South holds 3 spades -> 10 spades in 39 unseen cards, W draws 13.
    probs = np.array([comb(10, k) * comb(29, 13 - k) / comb(39, 13)
                      for k in range(11)])
    # Merge tail bins with tiny expectation to keep chi-square valid.
    expected = probs * len(deals)
    keep = expected >= 5
    obs = np.append(counts[keep], counts[~keep].sum())
    exp = np.append(expected[keep], expected[~keep].sum())
    chi2 = float(((obs - exp) ** 2 / exp).sum())
    dof = len(obs) - 1
    # 99.9% quantile of chi2 with <=8 dof is < 27; be generous but real.
    assert chi2 < 27, f"chi2={chi2:.1f} on {dof} dof: dealing is biased"
