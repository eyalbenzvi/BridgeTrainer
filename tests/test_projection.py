"""Conditional-tree projector: per-deal evaluation, per-deal sit/pull for
doubles, terminal flags, and safe-expression validation."""
import pytest
from endplay.types import Deal

from bridge_trainer.domain.deals import WeightedDeal
from bridge_trainer.projection.tree import (ConditionalTreeProjector,
                                            compile_predicate, deal_features)

def make_deal():
    # S (me): K93.752.A854.T62 ; N: QJT642.3.K2.Q543 ; E: A75.9864.T963.87 ;
    # W: 8.AKQJT.QJ7.AKJ9
    return Deal("N:QJT642.3.K2.Q543 A75.9864.T963.87 K93.752.A854.T62 8.AKQJT.QJ7.AKJ9")


TREES = {
    "P": [
        {"when": "west_hcp >= 17 and opps_combined_hearts >= 10",
         "contract": "4HW"},
        {"else": {"contract": "3HW", "terminal": True}},
    ],
    "X": [
        {"when": "partner_hearts >= 2 and partner_hcp >= 12", "contract": "3HWx"},
        {"when": "partner_spades >= 6", "contract": "3SN"},
        {"else": {"contract": "3SN", "terminal": False}},
    ],
}


def test_features_of_concrete_deal():
    f = deal_features(make_deal(), "S")
    assert f["north_spades"] == 6
    assert f["north_hcp"] == 8
    assert f["west_hcp"] == 21
    assert f["partner_spades"] == 6          # partner of S is N
    assert f["lho_hcp"] == 21                # LHO of S is W
    assert f["rho_hearts"] == 4              # RHO of S is E
    assert f["opps_combined_hearts"] == 9    # W 5 + E 4
    assert f["south_hcp"] == 7
    # Role alias for my own (known) hand, usable in continuation predicates.
    assert f["me_hcp"] == 7 and f["me_spades"] == 3
    # Per-suit honor points: W holds AKQJT of hearts, N holds Kx of diamonds.
    assert f["west_hearts_hcp"] == 10
    assert f["partner_diamonds_hcp"] == 3
    assert f["our_combined_hcp"] == 15       # S 7 + N 8
    assert f["our_combined_spades"] == 9


def test_projection_picks_first_matching_rule():
    projector = ConditionalTreeProjector(TREES, "S")
    wd = WeightedDeal(make_deal())
    # west_hcp=21 but opps_combined_hearts=9 -> falls to else.
    fc = projector.project(wd, "P")
    assert str(fc) == "3HW"
    assert fc.terminal


def test_double_sit_pull_is_per_deal():
    projector = ConditionalTreeProjector(TREES, "S")
    wd = WeightedDeal(make_deal())
    # Partner (N) has 1 heart and 8 hcp -> does not sit; has 6 spades -> pulls.
    fc = projector.project(wd, "X")
    assert str(fc) == "3SN"
    assert not fc.doubled


def test_terminal_flag_survives():
    projector = ConditionalTreeProjector(TREES, "S")
    nodes = projector._compiled["X"]
    assert nodes[-1][1].terminal is False


def test_contract_parsing_variants():
    from bridge_trainer.domain.contracts import FinalContract
    c = FinalContract.parse("3NTSx")
    assert (c.level, c.denom, c.declarer, c.doubled) == (3, "NT", "S", True)
    c2 = FinalContract.parse("3HWx")
    assert (c2.level, c2.denom, c2.declarer, c2.doubled) == (3, "H", "W", True)
    c3 = FinalContract.parse("P")
    assert c3.passed_out
    with pytest.raises(ValueError):
        FinalContract.parse("8H W")


def test_unsafe_expressions_rejected():
    names = {"west_hcp"}
    with pytest.raises(ValueError):
        compile_predicate("__import__('os').system('true')", names)
    with pytest.raises(ValueError):
        compile_predicate("west_hcp.__class__", names)
    with pytest.raises(ValueError):
        compile_predicate("unknown_feature > 3", names)
    pred = compile_predicate("west_hcp >= 17 and not west_hcp >= 20", names)
    assert pred({"west_hcp": 18}) is True
    assert pred({"west_hcp": 21}) is False


def test_tree_validation():
    with pytest.raises(ValueError):  # no else at the end
        ConditionalTreeProjector(
            {"P": [{"when": "west_hcp > 5", "contract": "3HW"}]}, "S")
    with pytest.raises(ValueError):  # else not last
        ConditionalTreeProjector(
            {"P": [{"else": {"contract": "3HW"}},
                   {"when": "west_hcp > 5", "contract": "4HW"}]}, "S")
