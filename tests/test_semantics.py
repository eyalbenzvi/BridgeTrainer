"""Hand-verified constraint extraction, pass handling (INV8), exclusions,
and graceful degradation for unrecognized calls."""
from pathlib import Path

import numpy as np

from bridge_trainer.dealing.features import SeatFeatures, parse_hand_pbn
from bridge_trainer.domain.auction import Auction
from bridge_trainer.semantics.engine import RuleEngine, load_ruleset
from bridge_trainer.semantics.predicates import PREDICATES

RULES = Path("bridge_trainer/semantics/rules")


def make_engine(my_seat="S"):
    return RuleEngine(
        load_ruleset(RULES / "our_2over1.yaml"),
        load_ruleset(RULES / "opps_light_preempts.yaml"),
        my_seat,
    )


def test_hand_verified_1h_opening_rule():
    """Golden: (1H) by W under the light-preempt profile."""
    engine = make_engine()
    auction = Auction.from_tokens("W", ["1H", "1S", "3H"])
    profile = engine.extract(auction)
    w = profile.seats["W"]
    # Core 11-19 at weight 1.0; 10 at 0.4; unbalanced 20-21 at 0.3.
    assert w.hcp_weights[9] == 0.0
    assert w.hcp_weights[10] == 0.4
    assert all(w.hcp_weights[h] == 1.0 for h in range(11, 20))
    assert w.hcp_weights[20] == 0.3 and w.hcp_weights[21] == 0.3
    assert w.hcp_weights[22] == 0.0
    # 5-7 hearts core, 8 at reduced weight.
    assert w.suit_weights["H"][4] == 0.0
    assert w.suit_weights["H"][5] == 1.0
    assert w.suit_weights["H"][7] == 1.0
    assert w.suit_weights["H"][8] == 0.2
    assert w.suit_weights["H"][9] == 0.0
    assert "balanced_15_17" in w.exclusions
    assert "balanced_20_21" in w.exclusions


def test_hand_verified_overcall_and_raise_rules():
    engine = make_engine()
    profile = engine.extract(Auction.from_tokens("W", ["1H", "1S", "3H"]))
    n = profile.seats["N"]
    assert n.hcp_weights[7] == 0.5 and n.hcp_weights[8] == 1.0
    assert n.suit_weights["S"][4] == 0.0 and n.suit_weights["S"][5] == 1.0
    assert "takeout_double_shape_over_hearts" in n.exclusions
    assert "light_overcall_junk_spades" in n.exclusions
    e = profile.seats["E"]
    # Preemptive jump raise: 3-8 core (2 at 0.4, 9 at 0.5), EXACTLY 4 trumps
    # in the core (5 at reduced weight, never 3).
    assert e.hcp_weights[2] == 0.4 and e.hcp_weights[3] == 1.0
    assert e.hcp_weights[9] == 0.5 and e.hcp_weights[10] == 0.0
    assert e.suit_weights["H"][3] == 0.0
    assert e.suit_weights["H"][4] == 1.0
    assert e.suit_weights["H"][5] == 0.4
    assert e.suit_weights["H"][6] == 0.0
    assert profile.unrecognized_calls == []


def test_pass_is_first_class_inv8():
    """A concealed pass extracts constraints like any other call."""
    engine = make_engine()
    # W opens 1H, N passes (my seat is S, so N's pass is concealed).
    profile = engine.extract(Auction.from_tokens("W", ["1H", "P"]))
    n = profile.seats["N"]
    assert n.hcp_weights[12] == 1.0
    assert n.hcp_weights[13] == 0.3  # trap-pass margin band
    assert n.hcp_weights[15] == 0.0
    assert n.suit_weights["S"][5] == 0.2


def test_unrecognized_call_degrades_gracefully():
    engine = make_engine()
    profile = engine.extract(Auction.from_tokens("W", ["1H", "1S", "4C"]))
    # 4C has no rule: gap surfaced, other constraints still extracted.
    assert len(profile.unrecognized_calls) == 1
    assert "E:4C" in profile.unrecognized_calls[0]
    assert "W" in profile.seats and "N" in profile.seats
    assert "E" not in profile.seats


def test_my_own_calls_are_skipped():
    engine = make_engine(my_seat="N")
    profile = engine.extract(Auction.from_tokens("W", ["1H", "1S", "3H"]))
    assert "N" not in profile.seats
    assert {"W", "E"} <= set(profile.seats)


def test_merge_multiplies_weights():
    engine = make_engine()
    p1 = engine.extract(Auction.from_tokens("W", ["1H"]))
    merged = p1.seats["W"].merge(p1.seats["W"])
    assert merged.hcp_weights[10] == 0.4 * 0.4
    assert merged.hcp_weights[11] == 1.0


def test_exclusion_predicates_vectorized():
    balanced = parse_hand_pbn("KQ32.A54.QJ4.K32")   # 16 hcp balanced
    unbalanced = parse_hand_pbn("AKQJ2.2.A5432.32")  # unbalanced
    f = SeatFeatures(cards=np.array([balanced, unbalanced]))
    mask = PREDICATES["balanced_15_17"](f)
    assert mask.tolist() == [True, False]

    takeout = parse_hand_pbn("KQ32.2.AJ54.K632")     # 13 hcp, 1 heart, 4-4-4
    overcall = parse_hand_pbn("KQJ32.32.A54.632")    # 5 spades, 2 hearts
    f2 = SeatFeatures(cards=np.array([takeout, overcall]))
    mask2 = PREDICATES["takeout_double_shape_over_hearts"](f2)
    assert mask2.tolist() == [True, False]
