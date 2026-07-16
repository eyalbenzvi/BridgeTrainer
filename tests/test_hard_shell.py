"""Hard shell V5/V6 + silence inferences + richer constraint schema."""
import numpy as np
import pytest

from bridge_trainer.domain.constraints import (Band, ConstraintProfile,
                                               Denial, SeatConstraints)
from bridge_trainer.validate.ground_truth import (check_deal_admissible,
                                                  hand_weight,
                                                  suspect_natural_calls)
from bridge_trainer.validate.inference import (default_silence_denials,
                                               silent_seats)
from bridge_trainer.validate.trees import (check_hero_stem,
                                           lint_projection_trees)

# ---------------------------------------------------------------- V5

NATURAL_2D = SeatConstraints.from_bands(
    hcp=[Band(8, 16)], suits={"D": [Band(5, 7)]})


def test_ground_truth_catches_conventional_overcall():
    # The b1 failure class: the real "2D natural" bidder has 6 spades
    # and 2 diamonds — a transfer, not a suit bid.
    weight = hand_weight("AJT932.A9.62.KJ3", NATURAL_2D)
    assert weight == 0.0
    profile = ConstraintProfile(seats={"W": NATURAL_2D})
    violations = check_deal_admissible(
        {"W": "AJT932.A9.62.KJ3", "N": "x" * 0 or "Q874.K872.AQ4.T2"},
        hero="N", profile=profile)
    assert len(violations) == 1 and "mis-read" in violations[0]


def test_ground_truth_accepts_atypical_but_possible_hand():
    # 8 HCP, 5 diamonds: inside the bands even if not the modal hand.
    assert hand_weight("932.A9.QJ862.KJ3", NATURAL_2D) > 0.0
    profile = ConstraintProfile(seats={"W": NATURAL_2D})
    assert check_deal_admissible(
        {"W": "932.A9.QJ862.KJ3"}, hero="N", profile=profile) == []


def test_suit_hcp_and_denial_weights():
    sc = SeatConstraints.from_bands(
        hcp=[Band(8, 16)], suits={"D": [Band(5, 7)]},
        suit_hcp={"D": [Band(3, 10)]},          # decent suit required
        denials=[Denial(8, 16, "S", 5, 0.2)])   # rarely 5 spades too
    assert hand_weight("932.A9.J8632.KJ3", sc) == 0.0   # Jxxxx suit
    assert hand_weight("932.A9.QJ862.KJ3", sc) > 0.0
    w_with_spades = hand_weight("AJT93.9.QJ862.J3", sc)
    assert w_with_spades == pytest.approx(0.2)


def test_suspect_natural_calls():
    # dealer S: S opens 1NT, W overcalls "2D" holding two diamonds
    hands = {"W": "AJT932.A9.62.KJ3", "N": "Q87.K87.AQ4.T752"}
    out = suspect_natural_calls("S", ["1NT", "2D"], hands, hero="N")
    assert len(out) == 1 and "conventional" in out[0]
    # a real diamond bid is not flagged
    out2 = suspect_natural_calls(
        "S", ["1NT", "2D"], {"W": "93.A9.QJT862.KJ3"}, hero="N")
    assert out2 == []


# ---------------------------------------------------------------- A3

def test_silent_seats_and_default_denials():
    # W and E only passed; both did so over a standing enemy 1-level bid.
    seats = silent_seats("W", ["P", "1D", "P", "1S", "P"], hero="S")
    assert seats == {"W": True, "E": True}
    denials = default_silence_denials("W", ["P", "1D", "P", "1S", "P"], "S")
    assert set(denials) == {"W", "E"}
    kinds = {(d.min_len, d.weight) for d in denials["W"]}
    assert (7, 0.10) in kinds and (5, 0.30) in kinds
    # a seat that later bid gets no silence denials (E stays silent)
    later = default_silence_denials("W", ["P", "1D", "P", "1S", "2C"], "S")
    assert "W" not in later and set(later) == {"E"}


# ---------------------------------------------------------------- V6

STEM = ["1H", "1S", "3H"]  # dealer W, hero S


def test_tree_lint_strength_floor():
    projections = {
        "P": [{"else": {"contract": "3HW"}}],
        "3S": [{"when": "lho_hearts >= 5", "contract": "4HW"},
               {"else": {"contract": "3SN"}}],
    }
    errors, _ = lint_projection_trees("W", STEM, "S", ["P", "3S"],
                                      projections, {})
    assert any("T1" in e for e in errors)


def test_tree_lint_deviation_needs_doubled_branch():
    projections = {
        "P": [{"else": {"contract": "3HW"}}],
        "3S": [{"when": "lho_hcp >= 17", "contract": "4HW"},
               {"else": {"contract": "3SN"}}],
    }
    dev = {"3S": {"note": "only five spades", "kind": "card_violation"}}
    errors, _ = lint_projection_trees("W", STEM, "S", ["P", "3S"],
                                      projections, dev)
    assert any("T2" in e for e in errors)
    projections["3S"].insert(
        1, {"when": "lho_hcp >= 14 and lho_spades_hcp >= 4",
            "contract": "3SNx"})
    errors, _ = lint_projection_trees("W", STEM, "S", ["P", "3S"],
                                      projections, dev)
    assert not any("T2" in e for e in errors)


def test_tree_lint_divergent_floors():
    projections = {
        "P": [{"when": "lho_hcp >= 10", "contract": "4HW"},
              {"else": {"contract": "3HW"}}],
        "3S": [{"when": "lho_hcp >= 17", "contract": "4HW"},
               {"else": {"contract": "3SN"}}],
    }
    errors, _ = lint_projection_trees("W", STEM, "S", ["P", "3S"],
                                      projections, {})
    assert any("T3" in e for e in errors)


def test_tree_lint_clean_pass():
    projections = {
        "P": [{"when": "lho_hcp >= 16", "contract": "4HW"},
              {"else": {"contract": "3HW"}}],
        "3S": [{"when": "lho_hcp >= 16", "contract": "4HW"},
               {"else": {"contract": "3SN"}}],
    }
    errors, _ = lint_projection_trees("W", STEM, "S", ["P", "3S"],
                                      projections, {})
    assert errors == []


def test_hero_stem_warnings():
    feats = {"hcp": 7, "S": 2, "H": 3, "D": 4, "C": 4}
    warns = check_hero_stem("S", ["1S", "P"], "S", feats)
    assert any("only 2 cards" in w for w in warns)
    assert any("opened with 7" in w for w in warns)
    ok = check_hero_stem("S", ["1S", "P"], "S",
                         {"hcp": 13, "S": 5, "H": 3, "D": 3, "C": 2})
    assert ok == []
