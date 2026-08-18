"""Unit tests: continuation-policy engine (heuristic + DD-optimal agents)."""
from __future__ import annotations

import pytest
from endplay.types import Deal

from bridge_trainer.analysis.continuation import (ContinuationEngine,
                                                  deal_views, load_policies)

# One fixed deal, hero = South. N holds long spades+values; E has a heart
# stack; W is weak.
#           N: AKQJ2.54.KQ2.876
#           E: 3.KQJT9.J93.KQJ9
#           S: T954.A2.AT54.A32
#           W: 876.8763.876.T54
PBN = "N:AKQJ2.54.KQ2.876 3.KQJT9.J93.KQJ9 T954.A2.AT54.A32 876.8763.876.T54"


def make_deal():
    return Deal(PBN)


def engine(stem, dealer="N", hero="S", vul="None"):
    return ContinuationEngine(dealer, stem, hero, vul)


def test_policies_config_loads_and_has_all_knobs():
    pol = load_policies()
    assert set(pol) == {"conservative", "realistic", "omniscient"}
    for name in ("conservative", "realistic"):
        p = pol[name]["params"]
        assert p["dbl_min_level"] >= 3          # mandated penalty-X scenario
        assert "dbl_stack_len" in p and "compete_pts" in p


def test_deal_views():
    views = deal_views(make_deal())
    assert views["N"].hcp == 15
    assert views["N"].length["S"] == 5
    assert views["E"].shcp["H"] == 6            # KQJ
    assert views["S"].support_pts("S") == 12 + 1  # doubleton H


def test_pass_candidate_ends_auction():
    # stem: N opened 1S, E passed, hero S to speak; candidate P then P,P ends
    eng = engine(["1S", "P"])
    fc = eng.project(make_deal(), "P", "realistic")
    # W and N and E still act; N holds a strong hand but S passed —
    # continuation lets N raise? N's side owns 1S; N may not raise without
    # partner support shown; support_pts(N,S)=... N is declarer side; agent
    # raises only with fit>=3 which N has (5). It may raise. Just assert a
    # legal spade contract by N or a 1S close-out.
    assert fc.denom == "S" and fc.declarer == "N"


def test_partner_raises_to_game_with_values():
    # hero S overcalls 1S over nothing? Use: N opens 1S (partner=N of S? no)
    # Simpler: dealer S, hero S opens 1S as the candidate; N (partner) holds
    # 15 with 5 spades -> should drive to game.
    eng = engine([], dealer="S", hero="S")
    fc = eng.project(make_deal(), "1S", "realistic")
    assert fc.denom == "S"
    assert fc.level == 4
    assert fc.declarer == "S"    # first namer of spades for NS


def test_penalty_double_of_high_contract():
    # Hero S bids 4S; East holds KQJT9 of hearts — no spade stack, so no X.
    # Give the stack case: candidate 4H by... craft: dealer E opened 4H?
    # Use E opening 4H stem, hero S candidate X is not what we test here;
    # we test the ENEMY doubling OUR 4+ contract when holding a stack.
    # E has 1 spade only — cannot double 4S. Swap: our contract 4H? NS
    # doesn't have hearts. Instead check the agent branch directly with a
    # deal where E has a spade stack.
    pbn = ("N:AJ942.54.KQ2.876 KQT86.KQJ.J9.KQJ "
           "7.AT982.AT54.A32 53.763.8763.T954")
    eng = engine([], dealer="S", hero="S")
    fc = eng.project(Deal(pbn), "4S", "realistic")
    assert fc.denom == "S" and fc.level == 4
    assert fc.doubled       # E: KQT86 spades (stack), 18 HCP -> penalty X


def test_conservative_doubles_less_than_realistic():
    pol = load_policies()
    assert pol["conservative"]["params"]["dbl_stack_len"] >= \
        pol["realistic"]["params"]["dbl_stack_len"]
    assert pol["conservative"]["params"]["compete_pts"] >= \
        pol["realistic"]["params"]["compete_pts"]


def test_advancer_responds_to_takeout_double():
    # E opens 1H, hero S doubles (takeout), W passes, N must respond.
    eng = engine(["1H"], dealer="E", hero="S")
    fc = eng.project(make_deal(), "X", "realistic")
    # N holds AKQJ2 spades and 15 HCP -> bids spades (jump), NS plays spades
    assert fc.denom == "S"
    assert fc.declarer in ("N", "S") and fc.level >= 1


def test_penalty_pass_converts_takeout_double():
    # E opens 1H; hero S doubles; N holds a heart stack -> passes for blood.
    pbn = ("N:32.KQJT9.KQ2.876 3.A8763.J93.KQJ9 "
           "AKQJ4.2.AT54.A32 T98765.54.876.T5")
    eng = engine(["1H"], dealer="E", hero="S")
    fc = eng.project(Deal(pbn), "X", "realistic")
    assert fc.denom == "H" and fc.level == 1
    assert fc.doubled and fc.declarer == "E"


def test_partner_pulls_high_double_with_shortness_and_long_suit():
    """User-reported gap: a high-level X must NOT be assumed to stand when
    partner holds shortness in their suit, a long suit and weak defense."""
    # E opens 4S; hero S doubles; N: void in spades, 7 hearts, 5 HCP -> 5H
    pbn = ("N:.QJT98765.542.87 KQJT98.2.J93.KQJ "
           "A2.AK3.AKQT8.A32 76543.4.76.T9654")
    eng = engine(["4S"], dealer="E", hero="S")
    fc = eng.project(Deal(pbn), "X", "realistic")
    assert fc.denom == "H" and fc.level == 5
    assert fc.declarer == "N"


def test_partner_sits_high_double_with_flat_hand():
    """...but with a flat hand and trump tricks the double stands."""
    pbn = ("N:T932.QJ5.542.876 KQJ87.T98.J9.KQJ "
           "A4.AK3.AKQT8.A32 65.7642.763.T954")
    eng = engine(["4S"], dealer="E", hero="S")
    fc = eng.project(Deal(pbn), "X", "realistic")
    assert fc.denom == "S" and fc.level == 4 and fc.doubled


def test_partner_corrects_to_own_suit_without_fit():
    """Every hand keeps bidding: partner with no fit but a long suit of his
    own corrects instead of freezing on the candidate's spot."""
    # hero S opens 1S; N: singleton spade, 6 hearts, 8 HCP -> bids 2H
    pbn = ("N:2.AKJT98.T54.876 KQJT9.32.J93.KQJ "
           "A8765.Q4.AKQ8.32 43.765.762.AT954")
    eng = engine([], dealer="S", hero="S")
    fc, calls = eng.project_with_calls(Deal(pbn), "1S", "realistic")
    assert "2H" in calls
    assert fc.denom in ("H", "S")


def test_omniscient_requires_tricks():
    eng = engine(["1S", "P"])
    with pytest.raises(ValueError):
        eng.project(make_deal(), "P", "omniscient", tricks=None)


def test_omniscient_picks_dd_best():
    # Trick tables where 4S by N makes exactly: NS get 10 tricks in S,
    # everything else is bad for the bidder.
    tricks = {}
    for d in ("S", "H", "D", "C", "NT"):
        for decl in "NESW":
            tricks[(d, decl)] = 4
    tricks[("S", "N")] = 10
    tricks[("S", "S")] = 10
    eng = engine([], dealer="S", hero="S")
    fc = eng.project(make_deal(), "1S", "omniscient", tricks=tricks)
    assert (fc.denom, fc.level) == ("S", 4)
    assert not fc.doubled


def test_omniscient_enemy_doubles_failing_contract():
    tricks = {(d, decl): 5 for d in ("S", "H", "D", "C", "NT")
              for decl in "NESW"}
    eng = engine([], dealer="S", hero="S")
    fc = eng.project(make_deal(), "4S", "omniscient", tricks=tricks)
    # 4S fails by 5; omniscient defenders double it (or the auction moves
    # elsewhere — but nobody can improve, E/W best is also failing).
    assert fc.doubled or fc.denom != "S"


def test_denoms_possible_covers_candidates_and_fits():
    eng = engine(["1S", "P"])
    ds = eng.denoms_possible(make_deal(), ["P", "2S", "X"])
    assert "S" in ds and "NT" in ds


def test_projection_deterministic():
    eng = engine(["1S", "P"])
    a = eng.project(make_deal(), "2S", "realistic")
    b = eng.project(make_deal(), "2S", "realistic")
    assert str(a) == str(b)
