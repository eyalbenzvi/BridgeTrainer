"""A call's note shows what its SEAT has shown — not a floor of zero.

User report on lead1-b8b58ea96 (1♣-P-1♥-P-2♦-P-4♥, all pass): two calls were
displayed with a point range starting at 0, and both contradicted an earlier
call by the same seat that had promised more —

    [0] N 1♣   Minor suit opening, 3+♣, 11-21
    [4] N 2♦   Opener reverse, 5+♣, 4+♦, 0-21     <- North already showed 11+
    [6] S 4♥   Long suit, 7+♥, 0-10           <- South already showed 6+ pts

GIB glosses every call in isolation, so its upper-bound-only clauses ("21-
HCP", "10- HCP", "16- total points") arrived as (0, hi) bands and rendered as
ranges. Two fixes, both display-only — the stored per-call ``card`` stays
GIB's, since the gates check each gloss against the hand that made it:

  * a seat's promises accumulate (``merge_promises``): highest floor, lowest
    ceiling, since its thirteen cards do not change during the auction;
  * a band with no floor renders as the upper bound it is ("21-", the mirror
    of the "21+" already used at the other end).
"""
from __future__ import annotations

import json
import re
import shutil

import pytest

from bridge_trainer.engine.explain import (accumulated_cards, merge_promises,
                                           seat_promises, terse_meaning)
from bridge_trainer.engine.gib_explain import parse_meaning

# The cards the published record actually stores for lead1-b8b58ea96, in
# auction order from the dealer (North). Verbatim GIB glosses.
BOARD_GLOSSES = [
    "Minor suit opening -- 3+ !C; 11-21 HCP; 12-22 total points",   # N 1C
    "No suitable call -- 16- total points",                         # E P
    "One over one -- 4+ !H; 6+ total points",                       # S 1H
    "No suitable call -- 20- total points",                         # W P
    "Opener reverse -- 5+ !C; 4+ !D; 3- !H; 21- HCP; 18-22 total points",
    "No suitable call -- 16- total points",                         # E P
    "Long suit -- 7+ !H; 10- HCP",                                  # S 4H
    "No suitable call -- 20- total points",                         # W P
    "No suitable call -- 5+ !C; 4+ !D; 3- !H; 21- HCP; 18-22 total points",
    "No suitable call -- 16- total points",                         # E P
]
BOARD_CALLS = ["1C", "P", "1H", "P", "2D", "P", "4H", "P", "P", "P"]


def board_texts():
    cards = [parse_meaning(m) for m in BOARD_GLOSSES]
    shown = accumulated_cards(0, cards)          # dealer North
    return [terse_meaning(c, call=tok) for c, tok in zip(shown, BOARD_CALLS)]


# ------------------------------------------------------- the reported board
def test_the_reverse_keeps_the_floor_its_opening_promised():
    """[4] N 2♦ was "0-21" three calls after N 1♣ was "11-21"."""
    assert board_texts()[4] == "Opener reverse, 5+♣, 4+♦, 11-21"


def test_the_jump_keeps_the_floor_its_one_over_one_promised():
    """[6] S 4♥ was "0-10"; GIB gave that call an HCP CEILING only, and the
    floor South showed with 1♥ (6+ total points) is what the 0 denied."""
    assert board_texts()[6] == "Long suit, 7+♥, 10-, 6+ pts"


def test_the_final_pass_does_not_re_open_the_range():
    """North's pass carries the same 21- ceiling; it must not read as 0-21."""
    assert board_texts()[8] == "No suitable call, 5+♣, 4+♦, 11-21"


def test_no_call_on_the_board_is_displayed_with_a_zero_floor():
    for txt in board_texts():
        assert not re.search(r"(^|[\s,])0-\d", txt), txt


def test_the_seats_own_first_call_is_untouched():
    assert board_texts()[0] == "Minor suit opening, 3+♣, 11-21"


def test_an_unlimited_pass_still_shows_its_ceiling():
    # East never bid: 0-16 was not a contradiction, but it is still not what
    # "16- total points" says.
    assert board_texts()[1] == "No suitable call, 16- pts"


# ------------------------------------------------------- the band rendering
def test_a_floorless_band_renders_as_an_upper_bound():
    assert terse_meaning({"hcp": [0, 10]}, call="4H") == "10-"
    assert terse_meaning({"pts": [0, 8]}, call="P") == "8- pts"


def test_a_real_range_and_a_pinned_count_are_unchanged():
    assert terse_meaning({"hcp": [11, 14]}, call="1C") == "11-14"
    assert terse_meaning({"hcp": [9, 9]}, call="2NT") == "9"
    assert terse_meaning({"hcp": [0, 0]}, call="P") == "0"


def test_an_open_ended_band_still_renders_as_a_floor():
    assert terse_meaning({"hcp": [15, 40]}, call="1NT") == "15+"


def test_a_points_floor_shows_beside_a_floorless_hcp_ceiling():
    assert terse_meaning({"hcp": [0, 10], "pts": [6, 40]}, call="4H") \
        == "10-, 6+ pts"


def test_a_points_band_still_yields_to_an_hcp_band_that_has_a_floor():
    assert terse_meaning({"hcp": [15, 17], "pts": [16, 20]}, call="1NT") \
        == "15-17"


def test_a_floorless_points_band_adds_nothing_to_a_floorless_hcp_band():
    assert terse_meaning({"hcp": [0, 10], "pts": [0, 12]}, call="4H") == "10-"


# ------------------------------------------------------------ accumulation
def test_promises_intersect_to_the_highest_floor_and_lowest_ceiling():
    merged = merge_promises({"hcp": (11, 21), "pts": (12, 22)},
                            {"hcp": (0, 21), "pts": (18, 22)})
    assert merged["hcp"] == (11, 21)
    assert merged["pts"] == (18, 22)


def test_a_silent_dimension_inherits_the_earlier_one():
    merged = merge_promises({"pts": (6, 40)}, {"hcp": (0, 10), "pts": None})
    assert merged["pts"] == (6, 40) and merged["hcp"] == (0, 10)


def test_suit_lengths_intersect_too():
    merged = merge_promises({"minlen": {"H": 4}, "maxlen": {"S": 4}},
                            {"minlen": {"H": 7}, "maxlen": {}})
    assert merged["minlen"]["H"] == 7 and merged["maxlen"]["S"] == 4


def test_contradictory_glosses_leave_this_calls_own_claim_standing():
    """Two glosses that cannot both be true describe different systemic
    hands; the call being explained is the one whose claim is shown."""
    merged = merge_promises({"hcp": (17, 21), "minlen": {"S": 5}},
                            {"hcp": (0, 10), "maxlen": {"S": 2}})
    assert merged["hcp"] == (0, 10)
    assert merged["maxlen"]["S"] == 2 and merged["minlen"].get("S", 0) == 0


def test_the_name_gloss_and_force_describe_this_call_only():
    prev = {"text": "Minor suit opening", "forcing": True,
            "gib_raw": "Minor suit opening -- 3+ !C", "hcp": (11, 21)}
    merged = merge_promises(prev, {"text": "Opener reverse", "forcing": False,
                                   "gib_raw": "Opener reverse -- 5+ !C",
                                   "hcp": (0, 21)})
    assert merged["text"] == "Opener reverse"
    assert merged["forcing"] is False
    assert merged["gib_raw"] == "Opener reverse -- 5+ !C"


def test_accumulation_follows_the_seats_round_the_table():
    # dealer North, so indexes 0/4 are North's and 2/6 are South's; an
    # opponent's ceiling must never leak onto the other side's call.
    cards = [{"hcp": (11, 21)}, {"hcp": (0, 8)}, {"hcp": (6, 37)},
             {"hcp": (0, 9)}, {"hcp": (0, 21)}]
    shown = accumulated_cards(0, cards)
    assert shown[4]["hcp"] == (11, 21)
    assert shown[1]["hcp"] == (0, 8)
    assert shown[2]["hcp"] == (6, 37)


def test_one_seats_promises_are_collected_for_its_next_call():
    """An offered option is one more call by the hero, displayed with what the
    hero has already shown (explain.option_explanations)."""
    cards = [{"hcp": (11, 21)}, {"hcp": (0, 8)}, {"hcp": (6, 37)},
             {"hcp": (0, 9)}]
    hero = seat_promises(0, cards, 2)            # South, index 2
    assert hero["hcp"] == (6, 37)
    assert merge_promises(hero, {"hcp": (0, 10)})["hcp"] == (6, 10)
    assert seat_promises(0, cards, 1)["hcp"] == (0, 8)


def test_an_empty_auction_accumulates_to_nothing():
    assert accumulated_cards(0, []) == []
    assert seat_promises(0, [], 0) is None


def test_an_offered_option_is_shown_with_the_heros_own_promises(monkeypatch):
    """The hero's option is one more call by a hand that has already bid, so
    "0-10" is as wrong on an option as it is on a call in the auction."""
    from types import SimpleNamespace

    from bridge_trainer.engine import explain, gib_explain
    # the reported board's own reverse, offered as a candidate instead
    glosses = {("1C",): "Minor suit opening -- 3+ !C; 11-21 HCP",
               ("1C", "P"): "No suitable call -- 16- total points",
               ("1C", "P", "2D"): "Opener reverse -- 5+ !C; 4+ !D; 21- HCP"}
    monkeypatch.setattr(gib_explain, "card_for_auction",
                        lambda toks: gib_explain.parse_meaning(
                            glosses.get(tuple(toks), "")))
    spot = SimpleNamespace(dealer_i=0, hero_i=0, stem=["1C", "P"],
                           candidates=[("2D", 1.0)])
    verdict = SimpleNamespace(
        best="2D", dead=[], flags=[],
        table=[{"bid": "2D", "top_contracts": [("3CN", 8)],
                "ev_imp_vs_top": 0.0, "ci": 0.4, "p_gain": 0.5,
                "p_push": 0.2}],
        measured={"n_samples": 8, "top2": ["2D"], "gap_imps": 0.0,
                  "ci": 0.4, "p_top_wins": 0.6})
    (row,) = explain.option_explanations(spot, verdict, {"2D": 1.0})
    assert row["text"].startswith("2♦ — Opener reverse, 5+♣, 4+♦, 11-21.")


# ------------------------------------------- the audit reads the new forms
def test_the_pool_audit_parses_every_displayed_band_form():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from audit_pool_second import displayed_bands

    assert displayed_bands("Opener reverse, 5+♣, 4+♦, 11-21") \
        == [("hcp", 11, 21)]
    assert displayed_bands("Long suit, 7+♥, 10-, 6+ pts") \
        == [("hcp", 0, 10), ("pts", 6, 40)]
    assert displayed_bands("No suitable call, 16- pts") == [("pts", 0, 16)]
    assert displayed_bands("Balanced, 15-17") == [("hcp", 15, 17)]
    assert displayed_bands("2NT, 9") == [("hcp", 9, 9)]
    # a numeric convention name is not a band
    assert displayed_bands("Roman Key Card Blackwood 1430") == []
    # suit fragments are lengths, not points
    assert displayed_bands("Weak two bid, 6♠") == []


# ------------------------------------------------- JS <-> Python parity
needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available")


def run_shared(exprs: list[str]):
    from tests.test_terse_parity import run_shared as shared
    return shared(exprs)


@needs_node
def test_js_renders_the_new_band_forms_like_python():
    cards = [{"hcp": [0, 10]}, {"pts": [0, 8]}, {"hcp": [0, 10],
             "pts": [6, 40]}, {"hcp": [11, 21]}, {"hcp": [9, 9]},
             {"hcp": [15, 40]}, {"hcp": [15, 17], "pts": [16, 20]}]
    js = run_shared([f"terse({json.dumps(c)}, 'P')" for c in cards])
    assert js == [terse_meaning(c, call="P") for c in cards]


@needs_node
def test_js_accumulates_the_reported_auction_like_python():
    """The web client re-renders every note from the stored cards, so the
    fix reaches already-published boards through the JS mirror — which must
    agree with Python call for call."""
    entries = [{"seat": s, "card": c} for s, c in zip(
        ["N", "E", "S", "W"] * 3,
        [json.loads(json.dumps(parse_meaning(m))) for m in BOARD_GLOSSES])]
    expr = ("accumCards(" + json.dumps(entries) + ", 'N').map((c, j) => "
            "terse(c, " + json.dumps(BOARD_CALLS) + "[j]))")
    (js,) = run_shared([expr])
    # the JS wraps suit glyphs in markup (four-colour suits); the words and
    # the point bands are what must match
    assert [re.sub(r"<[^>]*>|︎", "", t) for t in js] == board_texts()


@needs_node
def test_js_and_python_agree_on_a_contradiction():
    prev = {"hcp": [17, 21], "minlen": {"S": 5}}
    cur = {"hcp": [0, 10], "maxlen": {"S": 2}}
    (js,) = run_shared([f"mergePromises({json.dumps(prev)}, "
                        f"{json.dumps(cur)})"])
    py = merge_promises(prev, cur)
    assert js["hcp"] == list(py["hcp"])
    assert js["maxlen"]["S"] == py["maxlen"]["S"]
    assert js["minlen"] == py["minlen"]
