"""Explanation-consistency gate (engine/explain_check.py).

Fixtures reproduce the motivating board ben1-01354c2d: Ben answered a
club-Blackwood 4NT with 5D ("One or four key cards") holding two keycards,
and the 5NT/5S candidate glosses asserted the club queen the hero does not
hold. The gate must kill that board, must NOT kill soft HCP stretches
(they are the training content), and must read stored records.
"""
from bridge_trainer.engine.explain_check import (
    band_vs_card, card_vs_hand, hand_hcp, hand_violations, holds, keycards,
    record_violations, suit_lengths)

# ben1-01354c2d: E dealer, hero S
HANDS = ["QJ64.Q65.A85.A62",        # N
         "AKT932.98.J732.4",        # E
         ".AKJT4.KQ4.KT975",        # S
         "875.732.T96.QJ83"]        # W
HERO = HANDS[2]


def _card(gib_raw="", text="", hcp=None, minlen=None, maxlen=None):
    return {"gib_raw": gib_raw, "text": text, "hcp": hcp,
            "minlen": minlen or {}, "maxlen": maxlen or {},
            "forcing": False}


def test_hand_helpers():
    assert hand_hcp(HERO) == 16
    assert suit_lengths(HERO) == {"S": 0, "H": 5, "D": 3, "C": 5}
    assert holds(HERO, "C", "K") and not holds(HERO, "C", "Q")
    assert keycards(HERO, "C") == 2      # HA + CK
    assert keycards(HERO, "H") == 2      # HA + HK
    assert keycards(HERO, None) == 1     # aces only


def test_card_vs_hand_bands_with_slack():
    # within slack: 16 hcp against a 14-17 band, 5 clubs against 5+ -> clean
    ok = _card(hcp=(14, 17), minlen={"C": 5})
    assert card_vs_hand(ok, HERO) == []
    # beyond slack: fails
    assert card_vs_hand(_card(hcp=(19, 37)), HERO)         # 16 < 19-2
    assert card_vs_hand(_card(minlen={"S": 4}), HERO)      # 0 < 4-1
    assert card_vs_hand(_card(maxlen={"H": 3}), HERO)      # 5 > 3+1
    # explicit holding assertions are exact
    assert card_vs_hand(_card(gib_raw="!CQ"), HERO)
    assert card_vs_hand(_card(gib_raw="!CK"), HERO) == []


def _stem_01354c2d():
    return [
        {"idx": 0, "seat": "E", "call": "2S",
         "card": _card("Weak two bid -- 6+ !S; 10- HCP", "Weak two bid",
                       hcp=(0, 10), minlen={"S": 6})},
        {"idx": 1, "seat": "S", "call": "4C",
         "card": _card("Overcall -- twice rebiddable !C; 19+ total points",
                       "Overcall")},
        {"idx": 2, "seat": "W", "call": "P", "card": _card()},
        {"idx": 3, "seat": "N", "call": "4NT",
         "card": _card("Blackwood (C) -- 2+ !C; 13+ total points",
                       "Blackwood (C)", minlen={"C": 2})},
        {"idx": 4, "seat": "E", "call": "P", "card": _card()},
        {"idx": 5, "seat": "S", "call": "5D",
         "card": _card("One or four key cards -- twice rebiddable !C",
                       "One or four key cards")},
        {"idx": 6, "seat": "W", "call": "P", "card": _card()},
        {"idx": 7, "seat": "N", "call": "5H",
         "card": _card("? queen -- 2+ !C", "? queen", minlen={"C": 2})},
        {"idx": 8, "seat": "E", "call": "P", "card": _card()},
    ]


def test_keycard_answer_mismatch_is_fatal():
    fatal, soft = hand_violations(_stem_01354c2d(), {}, HANDS,
                                  dealer_i=1, hero_i=2)
    assert any("5D" in v and "2 keycard" in v for v in fatal)


def test_option_holding_assertions_are_fatal_soft_bands_are_not():
    options = {
        # asserts the club queen hero lacks -> fatal (twice: !CQ + 'queen.')
        "5NT": _card("queen. No lower kings -- twice rebiddable !C; !CQ",
                     "queen. No lower kings"),
        # plain hcp stretch -> soft only (the upgrade dilemma)
        "6H": _card(hcp=(19, 22)),
    }
    fatal, soft = hand_violations(_stem_01354c2d()[:4], options, HANDS,
                                  dealer_i=1, hero_i=2)
    assert any("5NT" in v for v in fatal)
    assert not any("6H" in v for v in fatal)
    assert any("6H" in v for v in soft)


def test_queen_ask_is_not_a_statement():
    # "? queen" (N's ask) must not be read as asserting the queen
    fatal, _ = hand_violations(_stem_01354c2d(), {}, HANDS,
                               dealer_i=1, hero_i=2)
    assert not any("5H" in v and "queen" in v for v in fatal)


def test_clean_stem_passes():
    stem = [
        {"idx": 0, "seat": "E", "call": "2S",
         "card": _card("Weak two bid -- 6+ !S; 10- HCP", "Weak two bid",
                       hcp=(0, 10), minlen={"S": 6})},
        {"idx": 1, "seat": "S", "call": "4C",
         "card": _card("Overcall", "Overcall")},
    ]
    fatal, soft = hand_violations(stem, {}, HANDS, dealer_i=1, hero_i=2)
    assert fatal == [] and soft == []


def test_record_violations_reads_a_stored_record():
    rec = {
        "full_deal": dict(zip("NESW", HANDS)),
        "dealer": "E", "seat": "S",
        "explanations": {
            "stem": _stem_01354c2d(),
            "options": [{"bid": "5NT",
                         "card": _card("!CQ", "queen. No lower kings")}],
        },
    }
    fatal, soft = record_violations(rec)
    assert any("5D" in v for v in fatal)
    assert any("5NT" in v for v in fatal)


def test_band_vs_card_flags_omitted_suit_and_refuted_promise():
    feats = {"n": 121, "hcp_p10": 13, "hcp_p90": 17, "hcp_avg": 14.8,
             "len_avg": {"S": 0.6, "H": 5.1, "D": 1.8, "C": 5.5},
             "len5plus": {"S": 0.0, "H": 1.0, "D": 0.0, "C": 1.0}}
    # ben1-01354c2d's 4C: gloss omits the hearts the bid promises
    bad = band_vs_card(_card("Overcall", "Overcall"), feats, "4C")
    assert any("5+H" in v for v in bad)
    # the bid suit itself never fires the omitted-suit rule
    assert not any("5+C" in v for v in bad)
    # a gloss promising a suit the band refutes
    bad = band_vs_card(_card(minlen={"S": 5}), feats, "4C")
    assert any("gloss promises" in v for v in bad)
    # low-n bands prove nothing
    assert band_vs_card(_card(minlen={"S": 5}), dict(feats, n=10),
                        "4C") == []
    # disjoint hcp bands fire
    bad = band_vs_card(_card(hcp=(20, 22)), feats, "4C")
    assert any("hcp" in v for v in bad)
