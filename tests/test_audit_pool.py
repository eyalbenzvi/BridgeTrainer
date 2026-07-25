"""The published-pool audit (scripts/audit_pool.py).

The gates in engine/explain_check.py only ever ran at generation time, so
boards forged before a gate existed were never vetted by it. The audit
re-runs them over STORED records; these tests pin the record -> Spot
reconstruction the engine half samples from, and the cheap half's verdict
on the reported board (ben1-19f93c01296) using its real stored cards.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from audit_pool import audit_record, spot_from_record  # noqa: E402

from bridge_trainer.engine.gib_explain import parse_meaning  # noqa: E402


def _card(gib_raw):
    return parse_meaning(gib_raw)


def _record():
    """ben1-19f93c01296 as it was published (trimmed to the audited fields)."""
    return {
        "id": "ben1-19f93c01296", "kind": "bidding", "schema": 1,
        "dealer": "S", "seat": "S", "vul": "Both",
        "auction": ["1C", "P", "1H", "P", "2D", "P", "3C", "P"],
        "hand": "A75.Q.KQ84.AQ983",
        "full_deal": {"S": "A75.Q.KQ84.AQ983", "E": "QJ92.9732.AJ972.",
                      "W": "K643.K864.T6.JT7", "N": "T8.AJT5.53.K6542"},
        "engine_auction_complete": ["1C", "P", "1H", "P", "2D", "P", "3C",
                                    "P", "P", "P"],
        "generator": {"seed": 1784890266262},
        "candidates": [{"call": "P", "policy": 0.462},
                       {"call": "3NT", "policy": 0.381},
                       {"call": "3D", "policy": 0.077},
                       {"call": "4C", "policy": 0.06}],
        "explanations": {
            "stem": [
                {"idx": 0, "seat": "S", "call": "1C", "card": _card(
                    "Minor suit opening -- 3+ !C; 11-21 HCP")},
                {"idx": 1, "seat": "W", "call": "P", "card": _card(
                    "No suitable call -- 16- total points")},
                {"idx": 2, "seat": "N", "call": "1H", "card": _card(
                    "One over one -- 4+ !H; 6+ total points")},
                {"idx": 3, "seat": "E", "call": "P", "card": _card(
                    "No suitable call -- 20- total points")},
                {"idx": 4, "seat": "S", "call": "2D", "card": _card(
                    "Opener reverse -- 5+ !C; 4+ !D; 3- !H; 21- HCP")},
                {"idx": 5, "seat": "W", "call": "P", "card": _card(
                    "No suitable call -- 16- total points")},
                {"idx": 6, "seat": "N", "call": "3C", "card": _card(
                    "3+ !C; 4+ !H; 8+ HCP; forcing to 3N")},
                {"idx": 7, "seat": "E", "call": "P", "card": _card(
                    "No suitable call -- 20- total points")},
            ],
            "options": [
                {"bid": "P", "card": _card(
                    "No suitable call -- 5+ !C; 4+ !D; 3- !H; 21- HCP; "
                    "forcing to 3N")},
                {"bid": "3NT", "card": _card("5+ !C; 4+ !D; 17-21 HCP")},
                {"bid": "3D", "card": _card("5+ !C; rebiddable !D; 21- HCP")},
                {"bid": "4C", "card": _card("5+ !C; 4+ !D; 21- HCP")},
            ],
        },
    }


def test_spot_is_rebuilt_from_the_stored_record():
    spot = spot_from_record(_record())
    assert spot.dealer_i == 2 and spot.hero_i == 2          # S dealer, hero S
    assert spot.vul == (True, True)                         # "Both"
    assert spot.hands[0] == "T8.AJT5.53.K6542"              # N
    assert spot.hands[2] == "A75.Q.KQ84.AQ983"              # hero
    assert spot.stem == ["1C", "P", "1H", "P", "2D", "P", "3C", "P"]
    assert [b for b, _ in spot.candidates] == ["P", "3NT", "3D", "4C"]
    assert spot.seed == 1784890266262


def test_cheap_audit_flags_the_reported_board():
    bad = audit_record(_record())          # no engine: cheap half only
    assert any("option P" in v and "may not pass" in v for v in bad)


def test_cheap_audit_passes_a_board_without_the_pass_option():
    rec = _record()
    ex = rec["explanations"]
    ex["options"] = [o for o in ex["options"] if o["bid"] != "P"]
    rec["candidates"] = [c for c in rec["candidates"] if c["call"] != "P"]
    assert audit_record(rec) == []
