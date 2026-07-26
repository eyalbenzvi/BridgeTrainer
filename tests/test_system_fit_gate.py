"""The two system-fit gates (docs/system_fit_gate.md), both reported by the
owner on published boards:

R7 ``band_vs_shaded_hand`` — ben1-19f975caec3 offered (and graded best) a
   third-seat 2♠ on ♠JT875 ♥KJ53 ♦Q9 ♣KT, glossed with GIB's weak-two card
   "6+ !S". Five spades against six is the shade ``SLACK_LEN`` forgives, but
   Ben's own meaning of that 2♠ is avg 5.09 spades with P(6+)=0.09: the
   shortfall is the system, not a stretch, so the gloss describes another call.

R6 ``game_force_stop_violations`` — ben1-19f9c2b962c, after
   1NT-P-2♣-P-2♦-P-3♣-P, offered 4♣ and showed "Leads to 4♣N 57%" while the
   two hands' own glosses had stated 15 + 13 = 28 points in an uncontested
   auction. A partnership with game values does not park in a four-club
   partscore, so the IMPs charged against 4♣ measure a partner nobody plays
   with.
"""
import pytest

from bridge_trainer.engine.explain_check import (BAND_PLEN_DENIED, GAME_PTS,
                                                 band_share_at,
                                                 band_vs_shaded_hand,
                                                 game_force_stop_violations,
                                                 record_violations,
                                                 side_stated_min_pts,
                                                 uncontested)
from bridge_trainer.engine.gib_explain import parse_meaning

N = 512
WEAK_2S = "Weak two bid -- 1-4 !C; 1-3 !D; 1-3 !H; 6+ !S; 10- HCP"
HERO_19F975CAEC3 = "JT875.KJ53.Q9.KT"          # five spades, 9 HCP


def _card(gib_raw):
    return parse_meaning(gib_raw)


def _feats(avg, ge, n=128, suit="S"):
    """A feature dict shaped like ``ben.seat_features``: *ge* maps a length to
    the measured P(len >= length) for *suit*."""
    ladder = {k: [1.0] * 14 for k in "SHDC"}
    ladder[suit] = [ge.get(t, 1.0 if t <= int(avg) else 0.0)
                    for t in range(14)]
    return {"n": n, "len_avg": {k: 3.25 for k in "SHDC"} | {suit: avg},
            "len5plus": {k: 0.1 for k in "SHDC"} | {suit: ladder[suit][5]},
            "len_ge": ladder}


# ---------------------------------------------------------------------------
# R7: the shade SLACK_LEN forgives, arbitrated by the call's own band
# ---------------------------------------------------------------------------

def test_the_reported_weak_two_dies_on_bens_own_meaning():
    # measured on the published board: avg 5.09 spades, six on 9% of layouts
    bad = band_vs_shaded_hand(_card(WEAK_2S), _feats(5.09, {5: 1.0, 6: 0.086}),
                              "2S", HERO_19F975CAEC3)
    assert len(bad) == 1
    assert "promises 6+S and the hand holds 5" in bad[0]
    assert "P(6+)=0.09" in bad[0] and "not a shade" in bad[0]


def test_a_genuine_one_card_stretch_survives():
    # ben1-19f947b9769: 3♣ glossed "6+ !C" bid on five, and Ben means six on
    # 52% of the layouts it accepts — the stretch this trainer trades in
    assert band_vs_shaded_hand(_card("Preempt -- 6+ !C"),
                               _feats(5.64, {5: 1.0, 6: 0.516}, suit="C"),
                               "3C", "A4.T83.AJ54.AK52") == []


def test_the_promise_the_hand_meets_is_never_flagged():
    # ben1-19f95435b8f: the same five-card-meaning 2♦, held with six
    assert band_vs_shaded_hand(_card("Weak two bid -- 6+ !D; 10- HCP"),
                               _feats(5.09, {5: 1.0, 6: 0.086}, suit="D"),
                               "2D", "82.T4.KQ9764.J53") == []


def test_short_minima_are_shape_statements_not_promises():
    # GIB puts "3+ !H" on a raise; two hearts is ordinary bridge, and the
    # rule stays out of it (the cheap hand check owns 2+ card breaches)
    assert band_vs_shaded_hand(_card("Raise -- 3+ !H; 8-11 HCP"),
                               _feats(3.9, {3: 0.05}, suit="H"),
                               "3H", "AK765.QJ.KQ64.98") == []


def test_thin_bands_prove_nothing():
    assert band_vs_shaded_hand(_card(WEAK_2S),
                               _feats(5.09, {6: 0.0}, n=11),
                               "2S", HERO_19F975CAEC3) == []


def test_an_unmeasured_threshold_says_nothing():
    # a feature dict without the ladder cannot answer P(6+); the rule must
    # not fall back to the 5+ share, which is 1.00 here
    feats = {"n": 128, "len_avg": {k: 3.25 for k in "SHDC"} | {"S": 5.09},
             "len5plus": {k: 0.1 for k in "SHDC"} | {"S": 1.0}}
    assert band_share_at(feats, "S", 5) == 1.0
    assert band_share_at(feats, "S", 6) is None
    assert band_vs_shaded_hand(_card(WEAK_2S), feats, "2S",
                               HERO_19F975CAEC3) == []


def test_prose_length_promises_count_too():
    # "twice rebiddable !S" is GIB's prose for six cards
    bad = band_vs_shaded_hand(_card("Opener rebid -- twice rebiddable !S"),
                              _feats(5.0, {5: 1.0, 6: 0.0}), "2S",
                              HERO_19F975CAEC3)
    assert len(bad) == 1 and "promises 6+S" in bad[0]


def test_the_threshold_is_the_documented_one():
    assert BAND_PLEN_DENIED == 0.15
    just_below = _feats(5.09, {5: 1.0, 6: BAND_PLEN_DENIED - 0.01})
    just_above = _feats(5.09, {5: 1.0, 6: BAND_PLEN_DENIED})
    assert band_vs_shaded_hand(_card(WEAK_2S), just_below, "2S",
                               HERO_19F975CAEC3)
    assert band_vs_shaded_hand(_card(WEAK_2S), just_above, "2S",
                               HERO_19F975CAEC3) == []


# ---------------------------------------------------------------------------
# R6: the rollout stops below game with game values stated
# ---------------------------------------------------------------------------

DEALER_I, HERO_I = 1, 2          # ben1-19f9c2b962c: dealer E, hero S
AUCTION = ["P", "1NT", "P", "2C", "P", "2D", "P", "3C", "P"]
STEM_19F9C2B962C = [
    {"idx": 0, "seat": "E", "call": "P",
     "card": _card("No suitable call -- 11- HCP; 12- total points")},
    {"idx": 1, "seat": "S", "call": "1NT",
     "card": _card("notrump opener. Could have 5M. -- 2-5 !C; 2-5 !D; "
                   "2-5 !H; 2-5 !S; 15-17 HCP; 18- total points")},
    {"idx": 3, "seat": "N", "call": "2C", "card": _card("Stayman --  ")},
    {"idx": 5, "seat": "S", "call": "2D",
     "card": _card("No major suits -- 2-5 !C; 2-3 !H; 15-17 HCP")},
    {"idx": 7, "seat": "N", "call": "3C",
     "card": _card("5+ !C; 13+ total points")},
]
TABLE_19F9C2B962C = [
    {"bid": "3NT", "top_contracts": [["3NS", 499], ["6NS", 13]]},
    {"bid": "5C", "top_contracts": [["5CN", 498], ["6NS", 10], ["6CN", 4]]},
    {"bid": "4C", "top_contracts": [["4CN", 290], ["5CN", 169], ["6CN", 49]]},
]


def test_stated_values_are_read_per_seat_and_by_max():
    hero, partner = side_stated_min_pts(STEM_19F9C2B962C, DEALER_I, HERO_I)
    assert (hero, partner) == (15, 13)      # 1NT's HCP floor, 3♣'s points
    assert hero + partner >= GAME_PTS


def test_the_reported_partscore_stop_dies():
    bad = game_force_stop_violations(TABLE_19F9C2B962C, STEM_19F9C2B962C,
                                     AUCTION, DEALER_I, HERO_I, N)
    assert len(bad) == 1
    assert bad[0].startswith("option 4C:")
    assert "15+13=28" in bad[0] and "4CN on 290/512 (57%)" in bad[0]


def test_a_game_contract_is_not_a_stop():
    # 5♣ and 3NT are games: their own rows must never fire
    table = [row for row in TABLE_19F9C2B962C if row["bid"] != "4C"]
    assert game_force_stop_violations(table, STEM_19F9C2B962C, AUCTION,
                                      DEALER_I, HERO_I, N) == []


def test_a_contested_auction_is_left_alone():
    # once an opponent bids, a partscore is a real resting place (and the
    # force may have been discharged) — the same reasoning forcing_pass
    # _violations applies to GIB's clause
    auction = AUCTION[:-1] + ["3H"]
    assert not uncontested(auction, DEALER_I, HERO_I)
    assert game_force_stop_violations(TABLE_19F9C2B962C, STEM_19F9C2B962C,
                                      auction, DEALER_I, HERO_I, N) == []


def test_invitational_values_are_below_the_line():
    # 1NT-2♥-2♠-2NT: 15 opposite 9 is an invitation, and opener's 3♠ IS a
    # place to play — the class the pool's uncontested stops actually contain
    stem = [dict(STEM_19F9C2B962C[1]),
            {"idx": 7, "seat": "N", "call": "2NT",
             "card": _card("Invitational to 3NT game -- 5+ !S; 9-11 "
                           "total points")}]
    hero, partner = side_stated_min_pts(stem, DEALER_I, HERO_I)
    assert hero + partner == 24 < GAME_PTS
    assert game_force_stop_violations(
        [{"bid": "3S", "top_contracts": [["3SS", N]]}], stem, AUCTION,
        DEALER_I, HERO_I, N) == []


def test_a_partscore_they_declare_is_not_our_stop():
    table = [{"bid": "4C", "top_contracts": [["4CE", 290]]}]
    assert game_force_stop_violations(table, STEM_19F9C2B962C, AUCTION,
                                      DEALER_I, HERO_I, N) == []


@pytest.mark.parametrize("cnt,fires", [(25, False), (26, True)])
def test_a_rare_stop_needs_the_share_floor(cnt, fires):
    table = [{"bid": "4C", "top_contracts": [["4CN", cnt]]}]
    bad = game_force_stop_violations(table, STEM_19F9C2B962C, AUCTION,
                                     DEALER_I, HERO_I, N)
    assert bool(bad) is fires


def test_thin_evidence_is_never_judged():
    assert game_force_stop_violations(TABLE_19F9C2B962C, STEM_19F9C2B962C,
                                      AUCTION, DEALER_I, HERO_I, 0) == []


def test_record_violations_flags_the_stored_board():
    rec = {
        "kind": "bidding", "dealer": "E", "seat": "S", "auction": AUCTION,
        "full_deal": {"N": "KT87.AQ.7.T98643", "S": "A4.T83.AJ54.AK52",
                      "E": "9652.K74.KQT83.7", "W": "QJ3.J9652.962.QJ"},
        "quality": {"n_samples": N},
        "verdict": {"accepted": "3NT", "table": TABLE_19F9C2B962C},
        "explanations": {
            "stem": STEM_19F9C2B962C,
            "options": [{"bid": "3NT", "card": _card("15-17 HCP")},
                        {"bid": "5C", "card": _card("3-5 !C; 15-17 HCP")},
                        {"bid": "4C", "card": _card("3-5 !C; 15-17 HCP")}],
        },
    }
    fatal, _soft = record_violations(rec)
    assert [v for v in fatal if "stops in the partscore 4CN" in v]
