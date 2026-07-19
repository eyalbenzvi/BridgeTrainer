"""Unit tests for the deterministic opening-lead category function."""
from __future__ import annotations

import pytest

from bridge_trainer.engine.lead_classify import (
    LEAD_TYPE_IDS, classify_contract, classify_lead_record, parse_contract)


@pytest.mark.parametrize("level,denom,doubled,expected", [
    # part scores (below game)
    (1, "NT", "", "lead_part_score"),
    (2, "NT", "", "lead_part_score"),
    (1, "S", "", "lead_part_score"),
    (3, "H", "", "lead_part_score"),
    (2, "S", "", "lead_part_score"),
    (4, "C", "", "lead_part_score"),   # 4C is still a part score
    (4, "D", "", "lead_part_score"),
    # notrump game
    (3, "NT", "", "lead_3nt"),
    (4, "NT", "", "lead_3nt"),         # rare 4NT/5NT NT games
    (5, "NT", "", "lead_3nt"),
    # suit games
    (4, "H", "", "lead_suit_game"),
    (4, "S", "", "lead_suit_game"),
    (5, "C", "", "lead_suit_game"),
    (5, "D", "", "lead_suit_game"),
    (5, "H", "", "lead_suit_game"),    # 5-major is a (over)game in a suit
    # slams (any strain)
    (6, "C", "", "lead_slam"),
    (6, "NT", "", "lead_slam"),
    (7, "S", "", "lead_slam"),
    # doubled takes precedence over every level/strain bucket
    (2, "S", "x", "lead_doubled"),
    (3, "NT", "x", "lead_doubled"),
    (4, "H", "xx", "lead_doubled"),
    (6, "S", "x", "lead_doubled"),
])
def test_classify_contract(level, denom, doubled, expected):
    assert classify_contract(level, denom, doubled) == expected


def test_every_result_is_a_known_id():
    for level in range(1, 8):
        for denom in ("C", "D", "H", "S", "NT"):
            for doubled in ("", "x", "xx"):
                assert classify_contract(level, denom, doubled) in LEAD_TYPE_IDS


@pytest.mark.parametrize("contract,expected", [
    ("4HE", (4, "H", "")),
    ("2SN", (2, "S", "")),
    ("3NTW", (3, "NT", "")),
    ("3NTWx", (3, "NT", "x")),
    ("6SSxx", (6, "S", "xx")),
    ("4SS", (4, "S", "")),            # 'S' as both strain and declarer seat
    ("5CWx", (5, "C", "x")),
])
def test_parse_contract(contract, expected):
    assert parse_contract(contract) == expected


@pytest.mark.parametrize("contract,expected", [
    ("3NTW", "lead_3nt"),
    ("4SN", "lead_suit_game"),
    ("4CS", "lead_part_score"),
    ("6NTE", "lead_slam"),
    ("4HEx", "lead_doubled"),
])
def test_classify_lead_record(contract, expected):
    assert classify_lead_record({"contract": contract}) == expected
