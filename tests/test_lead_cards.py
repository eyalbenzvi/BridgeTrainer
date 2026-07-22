"""Physical card / policy action / seat-conversion mapping tests (no DDS)."""
from __future__ import annotations

import pytest

from bridge_trainer.engine.lead_cards import (
    FULL_DECK, RANKS, canonical_hand, hero_first_to_absolute, is_low_spot,
    lead_code32, physical_cards, policy_action, rank_index)

HAND = "K93.752.A854.T62"


def test_physical_cards_are_13_distinct_once_each():
    cards = physical_cards(HAND)
    assert len(cards) == 13
    assert len(set(cards)) == 13
    # S2..S7 (and all spots) are separate physical candidates
    spades = "K93"
    assert [c for c in cards if c[0] == "S"] == ["SK", "S9", "S3"]


def test_low_spots_are_distinct_physical_cards():
    cards = physical_cards("7654.AKQ.AKQ.AKQ")   # 4+3+3+3 = 13
    spade_cards = [c for c in cards if c[0] == "S"]
    assert spade_cards == ["S7", "S6", "S5", "S4"]
    assert len(set(spade_cards)) == 4       # NOT folded


def test_rank_index_cannot_invert_2_to_A():
    # strictly decreasing strength: A strongest (index 0), 2 weakest (12)
    idx = [rank_index("S" + r) for r in "AKQJT98765432"]
    assert idx == list(range(13))
    assert rank_index("SA") < rank_index("SK") < rank_index("S2")


def test_policy_action_folds_only_low_spots():
    assert policy_action("SK") == "SK"
    assert policy_action("S8") == "S8"        # 8 keeps identity
    for r in "765432":
        assert policy_action("S" + r) == "S-low"
    assert is_low_spot("S7") and not is_low_spot("S8")


def test_policy_action_never_changes_physical_card_identity():
    # the physical card string is untouched; only a SEPARATE label folds
    for c in physical_cards(HAND):
        assert policy_action(c) in (c, c[0] + "-low")
        assert c in FULL_DECK                 # still a real physical card


def test_lead_code32_folds_7_to_2():
    assert lead_code32("SA") == 0
    assert lead_code32("S8") == 6
    assert lead_code32("S7") == lead_code32("S2") == 7
    assert lead_code32("HA") == 8            # next suit block


def test_canonical_hand_orders_high_to_low():
    assert canonical_hand("39K.257.458A.26T") == "K93.752.A854.T62"


def test_seat_conversion_all_leaders():
    rows = ["HERO", "LHO", "PARD", "RHO"]
    # hero at each absolute seat -> hero lands at that seat, order preserved
    assert hero_first_to_absolute(rows, 0) == ("HERO", "LHO", "PARD", "RHO")
    assert hero_first_to_absolute(rows, 1) == ("RHO", "HERO", "LHO", "PARD")
    assert hero_first_to_absolute(rows, 2) == ("PARD", "RHO", "HERO", "LHO")
    assert hero_first_to_absolute(rows, 3) == ("LHO", "PARD", "RHO", "HERO")


def test_seat_conversion_rejects_bad_input():
    with pytest.raises(ValueError):
        hero_first_to_absolute(["a", "b", "c"], 0)
    with pytest.raises(ValueError):
        hero_first_to_absolute(["a", "b", "c", "d"], 4)


def test_physical_cards_rejects_malformed():
    for bad in ("K93.752.A854", "K93.752.A854.T62.X", "K9X.752.A854.T62",
                "AKQJT98765432.752.A854.T62"):
        with pytest.raises(ValueError):
            physical_cards(bad)
