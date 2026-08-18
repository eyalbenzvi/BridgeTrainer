"""Unit tests: analysis system interpreter (classification + constraints)."""
from __future__ import annotations

import numpy as np
import pytest

from bridge_trainer.analysis.systems import interpret_auction, load_system
from bridge_trainer.analysis.systems.interpreter import classify_calls
from bridge_trainer.domain.auction import Auction

SAYC = load_system("sayc")
TWO1 = load_system("two_over_one")


def keys(dealer, tokens):
    return [m.key for m in classify_calls(Auction.from_tokens(dealer, tokens))]


# ---------------------------------------------------------------------------
# classification

def test_openings_classified():
    assert keys("N", ["1C"]) == ["open.1m"]
    assert keys("N", ["1S"]) == ["open.1M"]
    assert keys("N", ["1NT"]) == ["open.1NT"]
    assert keys("N", ["2C"]) == ["open.2C"]
    assert keys("N", ["2H"]) == ["open.weak2"]
    assert keys("N", ["3D"]) == ["open.preempt3"]
    assert keys("N", ["4S"]) == ["open.preempt4"]
    assert keys("N", ["P", "P", "1H"]) == ["open.pass", "open.pass", "open.1M"]


def test_responses_classified():
    assert keys("N", ["1S", "P", "2S"])[-1] == "resp.raise_simple"
    assert keys("N", ["1S", "P", "3S"])[-1] == "resp.raise_invite"
    assert keys("N", ["1S", "P", "4S"])[-1] == "resp.raise_game"
    assert keys("N", ["1S", "P", "1NT"])[-1] == "resp.nt1_forcing"
    assert keys("N", ["1S", "P", "2C"])[-1] == "resp.new2"
    assert keys("N", ["1D", "P", "1H"])[-1] == "resp.new1"
    assert keys("N", ["1D", "P", "2S"])[-1] == "resp.jumpshift"
    assert keys("N", ["1NT", "P", "2C"])[-1] == "resp.nt.stayman"
    assert keys("N", ["1NT", "P", "2D"])[-1] == "resp.nt.transfer"
    assert keys("N", ["1S", "P", "2NT"])[-1] == "resp.nt2_major"


def test_transfer_target_suit():
    ms = classify_calls(Auction.from_tokens("N", ["1NT", "P", "2D"]))
    assert ms[-1].params["own"] == "H"


def test_overcalls_and_defence():
    assert keys("N", ["1H", "1S"])[-1] == "ovc.simple1"
    assert keys("N", ["1H", "2C"])[-1] == "ovc.simple2"
    assert keys("N", ["1H", "2S"])[-1] == "ovc.jump_weak"
    assert keys("N", ["1H", "X"])[-1] == "dbl.takeout"
    assert keys("N", ["1H", "1NT"])[-1] == "ovc.nt1"
    assert keys("N", ["1H", "2H"])[-1] == "ovc.cue"
    # advancer over partner's takeout double
    assert keys("N", ["1H", "X", "P", "1S"])[-1] == "adv.x_min"
    assert keys("N", ["1H", "X", "P", "2S"])[-1] == "adv.x_jump"
    # advancer raises the overcall
    assert keys("N", ["1H", "1S", "P", "2S"])[-1] == "adv.raise"


def test_passes_are_informative():
    ks = keys("N", ["1H", "P"])
    assert ks[-1] == "pass.no_direct_action"
    ks = keys("N", ["1H", "P", "P"])
    assert ks[-1] == "resp.pass"
    ks = keys("N", ["3S", "P"])
    assert ks[-1] == "pass.no_action_high"


def test_pass_of_partner_preempt_is_not_0_to_5():
    assert keys("N", ["2H", "P", "P"])[-1] == "resp.preempt.pass"
    assert keys("N", ["3H", "3NT", "P"])[-1] == "resp.preempt.pass"
    ia = _profile(["2H", "P", "P"], my_seat="W", dealer="N")
    sc = ia.profile.seats["S"]
    assert sc.hcp_weights[12] == 1.0     # 12 HCP may still pass a weak two
    assert sc.hcp_weights[17] == 0.0     # but not a strong hand


def test_direct_nt_over_preempt_has_real_meaning():
    ms = classify_calls(Auction.from_tokens("N", ["3H", "3NT"]))
    assert ms[-1].key == "ovc.nt_other"
    ia = _profile(["3H", "3NT"], my_seat="W", dealer="N")
    sc = ia.profile.seats["E"]
    assert sc.hcp_weights[13] == 0.0
    assert sc.hcp_weights[16] == 1.0


def test_penalty_double_at_game_level():
    assert keys("N", ["4S", "X"])[-1] == "dbl.penalty_high"


def test_negative_double():
    assert keys("N", ["1D", "1S", "X"])[-1] == "dbl.negative"


def test_opener_rebids():
    assert keys("N", ["1S", "P", "1NT", "P", "2S"])[-1] == "reb.opener.same_min"
    assert keys("N", ["1S", "P", "2C", "P", "2NT"])[-1] == "reb.opener.nt_min"
    assert keys("N", ["1D", "P", "1S", "P", "2H"])[-1] == "reb.opener.reverse"
    assert keys("N", ["1D", "P", "1S", "P", "2C"])[-1] == "reb.opener.new"
    assert keys("N", ["1D", "P", "1S", "P", "2S"])[-1] == "reb.opener.raise"


# ---------------------------------------------------------------------------
# constraints via system tables

def _profile(tokens, my_seat="S", system=SAYC, dealer="N", overrides=None):
    return interpret_auction(Auction.from_tokens(dealer, tokens), my_seat,
                             system, system, overrides=overrides)


def test_weak2_constraints_bind():
    ia = _profile(["2H"], my_seat="S")
    sc = ia.profile.seats["N"]
    assert sc.hcp_weights[4] == 0          # below core+margin
    assert sc.hcp_weights[7] == 1.0        # core
    assert sc.hcp_weights[11] == pytest.approx(0.3)   # margin
    assert sc.suit_weights["H"][5] == 0    # 5-card suit not a weak two
    assert sc.suit_weights["H"][6] == 1.0


def test_pass_carries_information():
    # E passed over 1H: capped values and discounted 5-card side suits
    ia = _profile(["1H", "P"], my_seat="S")
    sc = ia.profile.seats["E"]
    assert sc.hcp_weights[20] == 0
    assert sc.hcp_weights[15] == pytest.approx(0.25)
    assert any(d.suit == "S" and d.min_len == 5 for d in sc.denials)
    # trap pass in the enemy suit is NOT denied
    assert not any(d.suit == "H" for d in sc.denials)
    assert any(x.startswith("takeout_shape_over_H") for x in sc.exclusions)


def test_two_over_one_differs_from_sayc():
    sayc = _profile(["1S", "P", "2C"], my_seat="W", system=SAYC)
    two1 = _profile(["1S", "P", "2C"], my_seat="W", system=TWO1)
    s_sc = sayc.profile.seats["S"]
    t_sc = two1.profile.seats["S"]
    assert s_sc.hcp_weights[10] == 1.0     # SAYC: 10+ ok
    assert t_sc.hcp_weights[10] == 0.0     # 2/1: game force, 12+ (11 margin)
    assert t_sc.hcp_weights[12] == 1.0


def test_fallback_produces_note_and_constraints():
    # 5C response to 1NT — not in any table
    ia = _profile(["1NT", "P", "5C"], my_seat="W")
    m = ia.meanings[-1]
    assert m.is_fallback
    assert ia.transparency_notes  # surfaced in the report
    sc = ia.profile.seats["S"]
    assert sc.suit_weights["C"][2] == 0    # fallback promises 4+ (3 margin)
    assert sc.suit_weights["C"][4] == 1.0


def test_user_override_replaces_meaning():
    ov = {2: {"hcp": [9, 11], "suits": {"C": [6, 13]},
              "note": "3C כאן = מזמין ולא מנע"}}
    ia = _profile(["1S", "P", "3C"], my_seat="W", overrides=ov)
    sc = ia.profile.seats["S"]
    assert sc.hcp_weights[8] == 0 and sc.hcp_weights[10] == 1.0
    assert sc.suit_weights["C"][5] == 0
    assert any("הסכם אישי" in n for n in ia.transparency_notes)


def test_meanings_cover_all_calls_and_hero_excluded():
    ia = _profile(["1H", "1S", "2H", "2S", "P", "P"], my_seat="S")
    assert len(ia.meanings) == 6
    assert "S" not in ia.profile.seats           # hero's hand is fixed
    assert set(ia.profile.seats) <= {"N", "E", "W"}


def test_constraints_merge_across_calls():
    # E opened 1S then rebid spades: 6+ spades, minimum
    ia = _profile(["1S", "P", "1NT", "P", "2S"], my_seat="S", dealer="E")
    sc = ia.profile.seats["E"]
    assert sc.suit_weights["S"][4] == 0
    assert sc.suit_weights["S"][6] == 1.0
    assert sc.hcp_weights[19] == 0       # capped by the minimum rebid


def test_generation_with_interpreted_constraints():
    """End-to-end: interpreted constraints actually generate deals."""
    from bridge_trainer.dealing.rejection import RejectionDealSource
    from bridge_trainer.domain.interfaces import GenerationBudget
    ia = _profile(["2H", "P"], my_seat="S", dealer="W", overrides=None)
    # W opened weak-2H, N passed; S (hero) holds a strong balanced hand
    src = RejectionDealSource(my_seat="S")
    deals, diag = src.generate(
        "AQ2.K53.KQ54.A32", ia.profile, 50, seed=7,
        budget=GenerationBudget(max_attempts=2_000_000, max_seconds=20))
    assert len(deals) == 50
    from bridge_trainer.projection.tree import deal_features
    for wd in deals[:10]:
        f = deal_features(wd.deal, "S")
        assert f["west_hearts"] >= 6
        assert f["west_hcp"] <= 11
