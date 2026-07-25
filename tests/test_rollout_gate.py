"""The ben1-19f975cad49 rules (docs/4nt_projection_and_gloss_gate.md).

The board: dealer E, hero North with ♠KQJ62 ♥AK ♦8 ♣KT954 after
(P) 1♣ (1♦) 1♠ (3♦) P (P). It was published with

  * 4NT glossed "4+♠, 6+ pts" — GIB has no rule for 4NT there and returned
    exactly the card it gave North's own 1♠ (R2),
  * "Leads to 6♣S 100%" — partner answered 5♥/5♣/5♦/5♠ and Ben bid 6♣ over
    every one of them (R1),
  * "Leads to ... 4♦N 9%" — a cue-bid GIB calls "forcing to 5C", passed out
    (R3),

and it passed every gate because four of its six candidates sampled at Ben's
15-layout rescue floor, below the band check's blanket n < 30 skip (R0).

Numbers in the fixtures are the board's real ones (423 samples).
"""
from types import SimpleNamespace

from bridge_trainer.engine.explain_check import (
    answer_insensitive_violations, band_vs_card, contract_call,
    contract_pairs, conventional_call, forcing_contract_violations,
    gloss_adds_nothing, hero_prior_card, meaningless_gloss_violations,
    point_mass_suspects, record_violations)

N = 423
STEM = ["P", "1C", "1D", "1S", "3D", "P", "P"]      # dealer E, hero N
DEALER_I, HERO_I = 1, 0
HANDS = {"N": "KQJ62.AK.8.KT954", "E": "8754.743.T963.J3",
         "S": "AT9.QJT9.AJ5.Q86", "W": "3.8652.KQ742.A72"}


def _card(gib_raw="", text="", hcp=None, pts=None, minlen=None, maxlen=None,
          forcing=False):
    return {"gib_raw": gib_raw, "text": text, "hcp": hcp, "pts": pts,
            "minlen": minlen or {}, "maxlen": maxlen or {}, "forcing": forcing}


# North's own stem call, whose card GIB handed back for the 4NT
STEM_ENTRIES = [
    {"idx": 0, "seat": "E", "call": "P", "card": _card()},
    {"idx": 1, "seat": "S", "call": "1C",
     "card": _card("Minor suit opening -- 3+ !C; 11-21 HCP",
                   "Minor suit opening", hcp=(11, 21), minlen={"C": 3})},
    {"idx": 2, "seat": "W", "call": "1D",
     "card": _card("One-level overcall -- 5+ !D", "One-level overcall",
                   minlen={"D": 5})},
    {"idx": 3, "seat": "N", "call": "1S",
     "card": _card("Free bid -- 4+ !S; 6+ total points; forcing", "Free bid",
                   pts=(6, 40), minlen={"S": 4}, maxlen={"S": 13},
                   forcing=True)},
    {"idx": 4, "seat": "E", "call": "3D",
     "card": _card("4+ !D; 4-8 total points", pts=(4, 8), minlen={"D": 4})},
    {"idx": 5, "seat": "S", "call": "P", "card": _card()},
    {"idx": 6, "seat": "W", "call": "P", "card": _card()},
]

CARD_4NT = _card("4+ !S; 6+ total points", pts=(6, 40), minlen={"S": 4},
                 maxlen={"S": 13})
CARD_4D = _card("5+ !C; 4+ !S; 17+ total points; forcing to 5C",
                pts=(17, 40), minlen={"C": 5, "S": 4}, forcing=True)
CARD_3S = _card("6+ !S; 11-12 total points", pts=(11, 12), minlen={"S": 6})

TABLE = [
    {"bid": "4NT", "top_contracts": [["6CS", 423]]},
    {"bid": "3S", "top_contracts": [["6SN", 301], ["5SN", 58], ["3SN", 39]]},
    {"bid": "4D", "top_contracts": [["4SN", 276], ["6CS", 110], ["4DN", 36]]},
    {"bid": "5C", "top_contracts": [["5CS", 423]]},
    {"bid": "3NT", "top_contracts": [["3NN", 422], ["4DW", 1]]},
]


# ---------------------------------------------------------------- helpers
def test_contract_helpers_read_both_stored_shapes():
    assert contract_call("6CS") == "6C"
    assert contract_call("3NN") == "3NT"
    assert contract_call("PASS") is None
    assert contract_call("5DXW") is None          # doubled: not a bare call
    # the forge's tuples and the Firestore {"items": [...]} wrapping
    assert contract_pairs([["6CS", 423]]) == [("6CS", 423)]
    assert contract_pairs([{"items": ["6CS", 423]}]) == [("6CS", 423)]
    assert contract_pairs(None) == []


def test_conventional_call_names_only_calls_that_cannot_be_natural():
    c = lambda call: conventional_call(call, STEM, DEALER_I, HERO_I)  # noqa: E731
    assert c("4NT") == "4NT/5NT ask"
    assert c("5NT") == "4NT/5NT ask"
    assert c("3NT") is None            # a natural NT contract bid
    assert c("6NT") is None
    assert c("4D") == "cue-bid"        # only W/E bid diamonds
    assert c("3S") is None             # our own suit
    assert c("5C") is None             # partner opened clubs
    assert c("P") is None
    assert c("X") is None


# ---------------------------------------------------------------- R2
def test_hero_prior_card_accumulates_only_the_heros_own_calls():
    prior = hero_prior_card(STEM_ENTRIES, DEALER_I, HERO_I)
    assert prior["calls"] == ["1S"]
    assert prior["minlen"] == {"S": 4} and prior["pts"] == (6, 40)
    assert prior["forcing"] is True
    assert "D" not in prior["minlen"]          # West's 5+♦ is not ours


def test_gloss_that_repeats_the_heros_own_card_adds_nothing():
    prior = hero_prior_card(STEM_ENTRIES, DEALER_I, HERO_I)
    assert gloss_adds_nothing(CARD_4NT, prior)
    # anything genuinely new clears it
    assert not gloss_adds_nothing(CARD_4D, prior)            # 5+♣, 17+
    assert not gloss_adds_nothing(CARD_3S, prior)            # 6+♠, 11-12
    assert not gloss_adds_nothing(
        _card("Blackwood (C) -- 2+ !C", "Blackwood (C)"), prior)   # named
    assert not gloss_adds_nothing(_card("4+ !S; !SQ", minlen={"S": 4}), prior)


def test_meaningless_gloss_kills_the_unexplained_4nt():
    bad = meaningless_gloss_violations(
        STEM_ENTRIES, {"4NT": CARD_4NT, "3S": CARD_3S, "4D": CARD_4D},
        STEM, DEALER_I, HERO_I)
    assert len(bad) == 1
    assert "option 4NT" in bad[0] and "1S" in bad[0]


def test_meaningless_gloss_spares_a_named_ask_and_an_informative_cue():
    cards = {"4NT": _card("Blackwood (C) -- 2+ !C; 20+ total points",
                          "Blackwood (C)", minlen={"C": 2}),
             "4D": CARD_4D, "3S": CARD_3S}
    assert meaningless_gloss_violations(STEM_ENTRIES, cards, STEM, DEALER_I,
                                        HERO_I) == []


def test_meaningless_gloss_fires_on_an_empty_card_but_only_for_conventions():
    empty = {"4D": _card(" ")}          # ben1-013527a9's cue-bid
    bad = meaningless_gloss_violations(STEM_ENTRIES, empty, STEM, DEALER_I,
                                       HERO_I)
    assert len(bad) == 1 and "no meaning stated" in bad[0]
    # a natural call explains itself: an empty gloss on 3NT is not this defect
    assert meaningless_gloss_violations(STEM_ENTRIES, {"3NT": _card(" ")},
                                        STEM, DEALER_I, HERO_I) == []


# ---------------------------------------------------------------- R3
def test_forcing_cue_left_as_the_contract_is_fatal():
    bad = forcing_contract_violations(TABLE, {"4D": CARD_4D, "3S": CARD_3S},
                                      STEM, DEALER_I, HERO_I, N)
    assert len(bad) == 1
    assert "option 4D" in bad[0] and "4DN" in bad[0] and "36/423" in bad[0]


def test_forcing_contract_ignores_noise_and_contracts_they_bought():
    # below the floor: one stray layout out of 423
    table = [{"bid": "4D", "top_contracts": [["4SN", 400], ["4DN", 2]]}]
    assert forcing_contract_violations(table, {"4D": CARD_4D}, STEM, DEALER_I,
                                       HERO_I, N) == []
    # 4♦ by WEST is the opponents playing their own suit — no force to break
    table = [{"bid": "4D", "top_contracts": [["4DW", 300]]}]
    assert forcing_contract_violations(table, {"4D": CARD_4D}, STEM, DEALER_I,
                                       HERO_I, N) == []
    # a non-forcing, non-cue candidate left in is just a sign-off
    table = [{"bid": "3S", "top_contracts": [["3SN", 400]]}]
    assert forcing_contract_violations(table, {"3S": CARD_3S}, STEM, DEALER_I,
                                       HERO_I, N) == []


# ---------------------------------------------------------------- R1
def test_point_mass_suspects_flags_the_4nt_and_spares_signoffs():
    s = point_mass_suspects(TABLE, N)
    assert len(s) == 1 and "option 4NT" in s[0] and "6CS" in s[0]
    # 5♣ -> 5♣S on all 423 layouts is the call BEING the contract
    assert point_mass_suspects([TABLE[3]], N) == []
    # and the Firestore wrapping reads the same
    wrapped = [{"bid": "4NT", "top_contracts": [{"items": ["6CS", 423]}]}]
    assert len(point_mass_suspects(wrapped, N)) == 1


def _ev(auctions: dict, contracts: dict):
    return SimpleNamespace(bids=list(auctions), auctions=auctions,
                           contracts=contracts, n_samples=None)


def _rollout(reply_counts: dict, tail: str):
    """Rollout auctions for one candidate: stem + candidate + reply + *tail*."""
    out = []
    for reply, cnt in reply_counts.items():
        out += [" ".join(STEM + ["4NT", "P", reply, "P"] + tail.split())] * cnt
    return out


def test_answer_insensitive_fires_when_the_hero_blasts_over_every_answer():
    aucs = _rollout({"5H": 324, "5C": 67, "5D": 21, "5S": 11}, "6C P P P")
    ev = _ev({"4NT": aucs}, {"4NT": ["6CS"] * 423})
    bad = answer_insensitive_violations(ev, STEM)
    assert len(bad) == 1
    assert "5H x324" in bad[0] and "6CS" in bad[0] and "100%" in bad[0]


def test_answer_insensitive_spares_a_forced_continuation():
    # partner has ONE action on every layout (ben1-19f95ad1594: 4♥ -> 4♠ ×128)
    aucs = _rollout({"5H": 423}, "6C P P P")
    ev = _ev({"4NT": aucs}, {"4NT": ["6CS"] * 423})
    assert answer_insensitive_violations(ev, STEM) == []


def test_answer_insensitive_spares_a_projection_that_moves():
    aucs = _rollout({"5H": 200, "5C": 223}, "6C P P P")
    ev = _ev({"4NT": aucs}, {"4NT": ["6CS"] * 200 + ["6NN"] * 223})
    assert answer_insensitive_violations(ev, STEM) == []


def test_answer_insensitive_ignores_a_rare_second_reply():
    # a reply on 2% of layouts is not an answer the board hangs on
    aucs = _rollout({"5H": 415, "5C": 8}, "6C P P P")
    ev = _ev({"4NT": aucs}, {"4NT": ["6CS"] * 423})
    assert answer_insensitive_violations(ev, STEM) == []


# ---------------------------------------------------------------- R0
def _floor_feats(n):
    """Ben's rescue-floor sample for this board's 4♦ (measured: avg 3.6♣,
    P5+ 0.07, so GIB's "5+ !C" is refuted) — with the HCP band it cannot
    prove at n=15."""
    return {"n": n, "hcp_p10": 12, "hcp_p90": 17, "hcp_avg": 14.0,
            "len_avg": {"S": 5.2, "H": 3.5, "D": 0.7, "C": 3.6},
            "len5plus": {"S": 1.0, "H": 0.0, "D": 0.0, "C": 0.07}}


def test_band_length_rules_run_on_the_rescue_floor():
    bad = band_vs_card(CARD_4D, _floor_feats(15), "4D",
                       known_minlen={"S": 4})
    assert any("promises 5+C" in v for v in bad)


def test_band_hcp_percentile_still_waits_for_the_full_sample():
    # spades are already known (the hero bid 1♠), so only the HCP rule is live
    hcp_card = _card("20-24 HCP", hcp=(20, 24))     # measured p90 is 17
    known = {"S": 4}
    assert band_vs_card(hcp_card, _floor_feats(15), "4D", known) == []
    assert any("hcp 20-24" in v for v in
               band_vs_card(hcp_card, _floor_feats(30), "4D", known))


def test_a_sample_too_small_for_any_rule_proves_nothing():
    assert band_vs_card(CARD_4D, _floor_feats(4), "4D",
                        known_minlen={"S": 4}) == []


# ---------------------------------------------------------------- the record
def test_record_violations_kills_the_stored_board():
    rec = {
        "kind": "bidding", "dealer": "E", "seat": "N", "auction": STEM,
        "full_deal": HANDS,
        "quality": {"n_samples": N},
        "verdict": {"accepted": "4NT", "table": TABLE},
        "explanations": {
            "stem": STEM_ENTRIES,
            "options": [{"bid": "4NT", "card": CARD_4NT},
                        {"bid": "3S", "card": CARD_3S},
                        {"bid": "4D", "card": CARD_4D}],
        },
    }
    fatal, _soft = record_violations(rec)
    assert any("option 4NT" in v and "already showed" in v for v in fatal)
    assert any("option 4D" in v and "4DN" in v for v in fatal)
