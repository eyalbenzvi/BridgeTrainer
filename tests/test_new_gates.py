"""The gates added 2026-07-28 after auditing the live pool (docs/
pool_audit_2026-07-28.md). Each test names the published board that motivated
its gate and pins BOTH directions: the real defect fires, and the legitimate
neighbour it must not swallow stays clean.
"""
from __future__ import annotations

from bridge_trainer.engine.explain_check import (SHADE_FATAL,
                                                band_gap,
                                                card_vs_hand,
                                                cold_contract_violations,
                                                ev_argmax_violations,
                                                hand_violations,
                                                max_total_points,
                                                mode_accept_violations,
                                                overbid_contract_violations,
                                                sellout_violations)
from bridge_trainer.engine.explain import terse_meaning
from bridge_trainer.engine.gib_explain import parse_meaning
from bridge_trainer.pool.store import deal_key, index_entry


# --------------------------------------------------------------- R8, the pts band
def test_max_total_points_is_the_loosest_bound():
    # HCP + shortness + length, both distributional methods added: nothing a
    # counting system can credit is above it.
    assert max_total_points("T654.932.T95.983") == 0        # 0 HCP, 4-3-3-3
    # AKQ = 9 HCP, a seven-card suit (+3 length) and two doubletons (+1+1)
    assert max_total_points("AKQ7654.32.32.3") == 9 + 3 + (1 + 1 + 2)


def test_pts_band_above_the_hand_is_a_violation():
    """lead1-b8b469b31 showed "6-11 pts" over a flat zero-count."""
    hand = "T654.932.T95.983"
    bad = card_vs_hand({"pts": [6, 11]}, hand)
    assert any("pts band 6-11 above" in v for v in bad)


def test_pts_band_below_the_hand_is_a_violation():
    """lead1i-19f92cab633 showed a pass as "0-0 pts" over twelve HCP."""
    bad = card_vs_hand({"pts": [0, 0]}, "2.KJ5.752.AKJ876")
    assert any("pts band 0-0 below" in v for v in bad)


def test_pts_band_within_slack_is_clean():
    # 13 HCP + a singleton and a five-card suit: 16 achievable, band says 14-16
    assert card_vs_hand({"pts": [14, 16]}, "AKQ32.4.K8765.Q2") == []


def test_hcp_band_still_wins_when_both_are_present():
    # only one band is rendered (hcp), and only one should be checked as the
    # primary claim — but a wrong pts band alongside a right hcp band is still
    # a wrong record, so both are reported.
    bad = card_vs_hand({"hcp": [11, 14], "pts": [30, 33]}, "AKQ32.4.K8765.Q2")
    assert any("pts band" in v for v in bad)
    assert not any(v.startswith("hcp ") for v in bad)


# ------------------------------------------------- R8/R6, the option shade cap
def _stem(call, seat, card):
    return [{"idx": 0, "seat": seat, "call": call, "card": card}]


def test_option_band_shade_is_soft_below_the_cap():
    """The stretch/underbid dilemma the trainer trades in stays publishable."""
    hero = "AJ853.3.Q2.KJ854"           # 11 HCP, so a 14-17 band is 3 out
    fatal, soft = hand_violations(
        [], {"4S": {"hcp": [14, 17]}}, [hero] * 4, 0, 0)
    assert 0 < band_gap({"hcp": [14, 17]}, hero) < SHADE_FATAL
    assert fatal == []
    assert soft and "hcp 11 outside 14-17" in soft[0]


def test_option_band_shade_is_fatal_at_the_cap():
    """ben1-19f94d0042d offered "Invitational to 3NT game, 24-24" to 9 HCP."""
    hero = "4.94.AQ874.K9843"           # 9 HCP
    fatal, _soft = hand_violations(
        [], {"2NT": {"hcp": [24, 24]}}, [hero] * 4, 0, 0)
    assert fatal and "hcp 9 outside 24-24" in fatal[0]
    assert band_gap({"hcp": [24, 24]}, hero) == 15 >= SHADE_FATAL


def test_band_gap_is_zero_inside_the_band():
    assert band_gap({"hcp": [11, 14]}, "AKQ32.4.K8765.Q2") == 0


# ------------------------------------------------------------- R-pass, gate 2
def test_stem_pass_gloss_is_vetted():
    """lead1-19fa45cd957 printed West's pass as "6+♥" over a singleton.

    The old gate skipped every Pass, so this shipped."""
    hand = "AKQT84.9.A52.KJ2"
    fatal, _soft = hand_violations(
        _stem("P", "W", {"minlen": {"H": 6}}), {}, [hand] * 4, 0, 0)
    assert fatal and "H len 1 < promised 6" in fatal[0]


def test_option_pass_gloss_stays_exempt():
    """An option's Pass card restates the hero's OWN earlier calls, and those
    entries are vetted in their own right."""
    fatal, soft = hand_violations(
        [], {"P": {"minlen": {"H": 6}}}, ["AKQT84.9.A52.KJ2"] * 4, 0, 0)
    assert fatal == [] and soft == []


def test_prose_length_may_not_override_an_explicit_maximum():
    """lead1-19f9f6c19be: "5- !S" (five OR FEWER) then "rebiddable !S" — the
    prose won and a MAXIMUM was published as a promise of five spades."""
    card = parse_meaning("No suitable call -- 2-5 !C; 5- !S; 25-27 HCP; "
                         "rebiddable !S")
    assert card["maxlen"]["S"] == 5
    assert card["minlen"]["S"] == 0          # was 5 before the fix
    assert card_vs_hand(card, "AK8.AK.KJ83.AK93") == []


def test_prose_length_still_sets_minlen_without_a_numeric_range():
    # the clause exists because "biddable !C; 6+ HCP" used to render as "6+",
    # hiding the suit — that must keep working
    card = parse_meaning("Overcall -- biddable !C; 6+ HCP")
    assert card["minlen"]["C"] == 4


# --------------------------------------------------------- R12, the EV argmax
def test_a_row_beating_the_accepted_call_is_fatal():
    """ben1-19f9609a4b3 accepted 3♥ while publishing X at +0.10 against it."""
    table = [{"bid": "3H", "ev_imp_vs_top": 0.42, "best_share": 0.312},
             {"bid": "P", "ev_imp_vs_top": -0.42, "best_share": 0.023},
             {"bid": "X", "ev_imp_vs_top": 0.10, "best_share": 0.609}]
    bad = ev_argmax_violations(table, "3H")
    assert len(bad) == 1 and "option X measures +0.10" in bad[0]


def test_the_winners_own_positive_margin_is_not_a_violation():
    # the accepted row states its margin against the RUNNER-UP, so it is the
    # one row that is legitimately positive
    table = [{"bid": "4S", "ev_imp_vs_top": 0.43},
             {"bid": "P", "ev_imp_vs_top": -0.43}]
    assert ev_argmax_violations(table, "4S") == []


# ------------------------------------------------ R13, the target-mode accept
def test_accepted_must_match_the_grading_mode():
    """lead1i-19fa11e39af accepted ♣T; its IMP mode — the one that grades the
    board — did not."""
    rec = {"training": {"target_mode": "IMP"},
           "verdict": {"accepted": ["CT", "C5", "C4", "C3"],
                       "by_mode": {"IMP": {"accepted": ["C5", "C4", "C3"]},
                                   "MP": {"accepted": ["CT", "C5", "C4",
                                                       "C3"]}}}}
    bad = mode_accept_violations(rec)
    assert len(bad) == 1 and "target mode" in bad[0]


def test_a_disagreeing_non_target_mode_is_fine():
    # the two modes rank by different metrics; only the target mode grades
    rec = {"training": {"target_mode": "IMP"},
           "verdict": {"accepted": ["S7"],
                       "by_mode": {"IMP": {"accepted": ["S7"]},
                                   "MP": {"accepted": ["H8"]}}}}
    assert mode_accept_violations(rec) == []


# --------------------------------------------------------- R9, the sell-out
def test_a_fifteen_count_that_never_bid_is_fatal():
    """lead1i-19fa5b321a7 ran P-P-1NT-P-P-P with the hero holding 15 HCP,
    six clubs and a singleton, then asked it for the opening lead."""
    hands = ["5.AK75.Q6.AQ9432", "J972.J43.972.KJ8", "A643.982.T853.T5",
             "KQT8.QT6.AKJ4.76"]
    bad = sellout_violations(["P", "P", "1NT", "P", "P", "P"], hands, 1)
    assert bad and bad[0].startswith("N never bid, holds 15 HCP")


def test_a_seat_that_passed_then_bid_is_not_a_sellout():
    # a trap pass behind an opener followed by an overcall is real bridge
    hands = ["743.QJ96.75.A432", "4.AK83.Q.KQJ7652", "K652.72.KJT32.T8",
             "JT87.T54.A9864.9"]
    assert sellout_violations(["1C", "P", "1D", "P", "1H", "2C", "P", "P",
                               "P"], hands, 0) == []


def test_passing_above_the_one_level_is_never_a_sellout():
    hands = ["AKQ2.AK32.432.32", "5432.QJT.KQJ.QJT", "876.9876.T98.K98",
             "JT9.54.A765.A765"]
    assert sellout_violations(["3H", "P", "P", "P"], hands, 1) == []


# ------------------------------------------------------ R10, the overbid game
def test_uncontested_game_on_nothing_is_fatal():
    """lead1-b8b5bf70a bid 3NT on 21 combined, uncontested."""
    hands = ["A32.KJT72.T62.T7", "T86..A853.AQ6543", "975.A4.QJ97.KJ98",
             "KQJ4.Q98653.K4.2"]                       # E+W = 21
    bad = overbid_contract_violations(
        ["1H", "P", "3C", "P", "3S", "P", "3NT", "P", "P", "P"], hands, 3)
    assert bad and "21 combined HCP" in bad[0]


def test_a_cheap_game_the_opponents_bid_over_is_a_sacrifice():
    hands = ["AKT6.T3.A.KJ8543", "QJ8732.AJ762.82.", "94.Q4.KJT6.QT976",
             "5.K985.Q97543.A2"]                       # E+W = 17, but N bid
    assert overbid_contract_violations(
        ["P", "1C", "2C", "P", "4H", "P", "P", "P"], hands, 3) == []


def test_a_sound_game_is_clean():
    hands = ["AKQ2.AKJ32.A32.3", "T9543.QT.QJ.QJT9", "876.9876.KT98.K8",
             "J.54.7654.A76542"]                       # N+S = 21+5 = 26
    assert overbid_contract_violations(["4H", "P", "P", "P"], hands, 0) == []


# -------------------------------------------------------- R11, cold contracts
def test_a_contract_no_lead_beats_is_fatal():
    cands = [{"card": "DA", "set_prob": 0.01}, {"card": "C6", "set_prob": 0.0},
             {"card": "H9", "set_prob": 0.0}]
    bad = cold_contract_violations(cands, "4SS")
    assert bad and "no offered lead beats 4SS" in bad[0]


def test_a_contract_every_lead_beats_is_fatal():
    cands = [{"card": "DA", "set_prob": 1.0}, {"card": "C6", "set_prob": 0.99}]
    bad = cold_contract_violations(cands, "6NW")
    assert bad and "every offered lead beats 6NW" in bad[0]


def test_a_real_defensive_decision_is_clean():
    cands = [{"card": "S6", "set_prob": 0.303}, {"card": "CT",
                                                 "set_prob": 0.144}]
    assert cold_contract_violations(cands, "3NTW") == []


# ------------------------------------------------------- R14, duplicate boards
_DEAL = {"N": "AJT52.J875.K85.9", "E": "K43.A3.QJT92.876",
         "S": "Q976.KT6.A73.KT4", "W": "8.Q942.64.AQJ532"}


def _rec(pid, **kw):
    return {"id": pid, "schema": 1, "kind": "lead", "dealer": "N",
            "full_deal": _DEAL, "auction": ["1S", "P", "P", "P"],
            "classification": {"type": "lead_part_score",
                               "difficulty_level": 2},
            "difficulty": 2, "created_at": "2026-01-01T00:00:00", **kw}


def test_the_same_board_has_the_same_key_under_a_different_id():
    assert deal_key(_rec("lead1-a")) == deal_key(_rec("lead1i-a"))


def test_a_different_auction_is_a_different_board():
    assert deal_key(_rec("x")) != deal_key(
        _rec("y", auction=["1S", "P", "2S", "P", "P", "P"]))


def test_a_record_with_no_deal_has_no_key():
    assert deal_key({"id": "p1", "kind": "bidding"}) == ""


def test_the_index_entry_carries_the_key():
    assert index_entry(_rec("lead1-a"))["deal_key"] == deal_key(_rec("lead1-a"))


# ---------------------------------------------------- R7, the degenerate band
def test_a_one_point_band_renders_as_one_number():
    """157 published calls said things like "9-9" over a seven-count."""
    assert terse_meaning({"hcp": [9, 9]}, call="2NT") == "9"
    assert terse_meaning({"pts": [16, 16]}, call="P") == "16 pts"


def test_a_real_range_still_renders_as_a_range():
    assert terse_meaning({"hcp": [11, 14]}, call="1C") == "11-14"
    assert terse_meaning({"pts": [6, 11]}, call="P") == "6-11 pts"
