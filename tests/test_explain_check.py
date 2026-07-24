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


# ben1-0135752a: W dealer, hero S. After P-1NT-P Ben's 2NT is a natural
# invitational raise, but GIB's 2/1 card glosses it "Minor transfer -- 6+ !C".
HANDS_0135752A = ["AJ3.AK43.KT87.73",       # N (the 1NT opener)
                  "Q82.QJ8.Q6432.Q6",       # E
                  "K74.T5.AJ95.JT42",       # S (hero, 4 clubs)
                  "T965.9762..AK985"]       # W


def test_option_promising_suit_hero_lacks_is_fatal():
    stem = [
        {"idx": 0, "seat": "W", "call": "P", "card": _card()},
        {"idx": 1, "seat": "N", "call": "1NT",
         "card": _card("notrump opener. Could have 5M. -- 15-17 HCP",
                       "notrump opener. Could have 5M", hcp=(15, 17))},
        {"idx": 2, "seat": "E", "call": "P", "card": _card()},
    ]
    options = {
        "2NT": _card("Minor transfer -- 6+ !C", "Minor transfer",
                     minlen={"C": 6}),
        "3NT": _card(hcp=(10, 15)),
    }
    fatal, soft = hand_violations(stem, options, HANDS_0135752A,
                                  dealer_i=3, hero_i=2)
    # 4 clubs against a promised 6 is 2 beyond slack: a different system,
    # not a stretch — must kill the board
    assert any("2NT" in v and "< promised 6" in v for v in fatal)
    assert not any("3NT" in v for v in fatal)


# ben1-19f93c012bc: S dealer, hero S (AQT.AJ853.K.T753 — 3 spades, a
# singleton diamond, 14 HCP). After 1H-P-1S-3D GIB glosses X as its own
# strong two-suited action double: "5+ !H; 1- !S; 17-21 HCP; biddable !D".
# Ben's double is nothing of the sort; the gloss lied about the taught
# option because X/XX options used to be skipped by the gate.
HANDS_19F93C012BC = ["K953.Q9.Q2.AJ984",       # N
                     "J87.4.AJ98765.Q6",       # E
                     "AQT.AJ853.K.T753",       # S (hero)
                     "642.KT762.T43.K2"]       # W


def _stem_19f93c012bc():
    return [
        {"idx": 0, "seat": "S", "call": "1H",
         "card": _card("Major suit opening -- 5+ !H; 11-21 HCP",
                       "Major suit opening", hcp=(11, 21), minlen={"H": 5})},
        {"idx": 1, "seat": "W", "call": "P", "card": _card()},
        {"idx": 2, "seat": "N", "call": "1S",
         "card": _card("One over one -- 4+ !S; 6+ total points",
                       "One over one", minlen={"S": 4})},
        {"idx": 3, "seat": "E", "call": "3D",
         "card": _card("Aggressive weak jump overcall -- 6+ !D; 10- HCP",
                       "Aggressive weak jump overcall", hcp=(0, 10),
                       minlen={"D": 6})},
    ]


def test_double_option_gloss_hero_contradicts_is_fatal():
    options = {
        "X": _card("5+ !H; 1- !S; 17-21 HCP; biddable !D; 22- total points",
                   hcp=(17, 21), minlen={"H": 5, "S": 0, "D": 4},
                   maxlen={"H": 13, "S": 1}),
        "P": _card("No suitable call -- 5+ !H; 11-21 HCP",
                   "No suitable call", hcp=(11, 21), minlen={"H": 5}),
    }
    fatal, soft = hand_violations(_stem_19f93c012bc(), options,
                                  HANDS_19F93C012BC, dealer_i=2, hero_i=2)
    # a singleton diamond against a promised 4 is 2 beyond slack — the
    # gloss describes a double Ben is not making; the board must die
    assert any("option X" in v and "D len 1 < promised 4" in v
               for v in fatal)
    # the HCP shade (14 vs 17-21) and the spade cap (3 vs 1-) stay soft
    assert any("option X" in v and "hcp" in v for v in soft)
    assert any("option X" in v and "> promised max" in v for v in soft)
    # Pass options are still exempt (their gloss restates earlier bids)
    assert not any("option P" in v for v in fatal + soft)


def test_double_option_hcp_shade_alone_stays_soft():
    # a sound off-shape X whose only sin is shading the gloss's HCP band
    # is the training content, not a lie — must NOT kill the board
    options = {"X": _card("11+ HCP; 3+ !S", hcp=(11, 37), minlen={"S": 3})}
    fatal, soft = hand_violations(_stem_19f93c012bc(), options,
                                  HANDS_19F93C012BC, dealer_i=2, hero_i=2)
    assert not any("option X" in v for v in fatal)


def test_stem_double_gloss_is_vetted_too():
    # an X inside the STEM whose gloss promises a suit the doubler lacks
    # misdescribes forced context — fatal, like any stem suit bid
    stem = _stem_19f93c012bc() + [
        {"idx": 4, "seat": "S", "call": "P", "card": _card()},
        {"idx": 5, "seat": "W", "call": "X",
         "card": _card("Penalty double -- 5+ !D", "Penalty double",
                       minlen={"D": 5})},   # W holds 3 diamonds
    ]
    fatal, _ = hand_violations(stem, {}, HANDS_19F93C012BC,
                               dealer_i=2, hero_i=2)
    assert any("stem X" in v and "D len 3 < promised 5" in v for v in fatal)


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


def test_band_refutes_promised_suit_by_scale_and_majority():
    # ben1-0135752a's 2NT, measured on the real engine: 7-9 hcp, avg 4.0
    # clubs, P(5+ clubs)=0.34 — against a "Minor transfer -- 6+ !C" gloss.
    # The average scrapes past 6-2, so the majority rule must catch it.
    feats = {"n": 128, "hcp_p10": 7, "hcp_p90": 9, "hcp_avg": 8.2,
             "len_avg": {"S": 3.0, "H": 3.0, "D": 3.0, "C": 4.0},
             "len5plus": {"S": 0.05, "H": 0.05, "D": 0.05, "C": 0.34}}
    bad = band_vs_card(_card(minlen={"C": 6}), feats, "2NT")
    assert any("6+C" in v for v in bad)
    # sister board ben1-013572ee (avg 3.8): the scaled average fires too
    feats38 = dict(feats, len_avg={**feats["len_avg"], "C": 3.8})
    assert band_vs_card(_card(minlen={"C": 6}), feats38, "2NT")
    # a genuine 5+ promise Ben merely shades (a good 4-carder about half
    # the time) is style, not a different convention — no violation
    shade = dict(feats, len_avg={**feats["len_avg"], "C": 4.6},
                 len5plus={**feats["len5plus"], "C": 0.55})
    assert band_vs_card(_card(minlen={"C": 5}), shade, "2NT") == []


def test_prose_lengths_and_total_points_parse_and_render():
    # ben1-013527db's unclear glosses (user report): "Dbl — 6+." hid the
    # clubs, and the limited pass rendered with no range at all
    from bridge_trainer.engine.explain import terse_meaning
    from bridge_trainer.engine.gib_explain import parse_meaning

    x = parse_meaning("6+ HCP; biddable !C; 8- total points")
    assert x["minlen"] == {"C": 4}
    assert x["hcp"] == (6, 37) and x["pts"] == (0, 8)
    assert terse_meaning(x, call="X") == "4+♣, 6+"

    p = parse_meaning("No suitable call -- 8- total points")
    assert p["pts"] == (0, 8)
    assert terse_meaning(p, call="P") == "No suitable call, 0-8 pts"

    c = parse_meaning("Overcall -- twice rebiddable !C; 19+ total points")
    assert c["minlen"] == {"C": 6} and c["pts"] == (19, 40)
    assert terse_meaning(c, call="4C") == "Overcall, 6+♣, 19+ pts"

    # an HCP band always outranks the vaguer total-points band
    o = parse_meaning("x -- 15-17 HCP; 18- total points")
    assert "pts" not in terse_meaning(o, call="1NT")
