"""Scoring correctness: per-physical-card DDS, sign convention, and a
golden-board comparison of the production scoring path against a direct,
independent endplay call.

These exercise real double-dummy via endplay (a hard dependency of the
project), so they run in normal CI. Ben is NOT required.
"""
from __future__ import annotations

import numpy as np
from endplay.dds import solve_all_boards
from endplay.types import Deal, Denom, Player

from bridge_trainer.engine.lead_cards import (physical_cards,
                                              token_from_endplay_card)
from bridge_trainer.engine.lead_evaluate import (Contract, Layout,
                                                 opening_leader_for_contract,
                                                 score_layouts)

# A non-trivial deal (from tests/test_dd.MIXED). Declarer E, 3NT -> leader S.
N = "K93.752.A854.T62"
E = "AQJ4.KQ4.K3.AK54"
S = "T87.JT86.QJ7.Q83"
W = "652.A93.T962.J97"
HANDS = (N, E, S, W)
_DENOM = {"S": Denom.spades, "H": Denom.hearts, "D": Denom.diamonds,
          "C": Denom.clubs, "NT": Denom.nt}
_PLAYER = {0: Player.north, 1: Player.east, 2: Player.south, 3: Player.west}


def _direct_defensive(hands, denom, leader_i):
    """Independent per-card defensive tricks via a bare endplay call."""
    d = Deal("N:" + " ".join(hands))
    d.trump = _DENOM[denom]
    d.first = _PLAYER[leader_i]
    sb = solve_all_boards([d])[0]
    return {token_from_endplay_card(c): int(t) for c, t in sb}


def _layouts(hands, n):
    return [Layout(hands=hands, sample_index=i, sample_seed=i)
            for i in range(n)]


def test_leader_for_all_four_declarers():
    for decl in range(4):
        c = Contract(4, "H", declarer_i=decl)
        assert c.leader_i == (decl + 1) % 4
        assert opening_leader_for_contract(c) == (decl + 1) % 4


def test_all_13_physical_cards_scored_separately():
    contract = Contract(3, "NT", declarer_i=1)
    cands = physical_cards(S)
    dt = score_layouts(_layouts(HANDS, 2), contract, cands, check=True,
                       displayed_leader_hand=S)
    assert set(dt) == set(cands)
    assert len(dt) == 13
    for c in cands:
        assert dt[c].shape == (2,)


def test_golden_board_matches_direct_dds_and_ranking():
    contract = Contract(3, "NT", declarer_i=1)
    leader_i = contract.leader_i
    cands = physical_cards(S)
    dt = score_layouts(_layouts(HANDS, 1), contract, cands, check=True,
                       displayed_leader_hand=S)
    direct = _direct_defensive(HANDS, "NT", leader_i)

    # same legal card list
    assert set(dt) == set(direct)
    # same per-card defensive tricks
    for c in cands:
        assert dt[c][0] == direct[c], (
            f"{c}: production {dt[c][0]} != direct {direct[c]}")
    # same ranking (production vs independent direct DDS)
    prod_rank = sorted(cands, key=lambda c: (-dt[c][0], c))
    direct_rank = sorted(cands, key=lambda c: (-direct[c], c))
    assert prod_rank == direct_rank


def test_sign_convention_is_defensive_not_declarer():
    """Defensive tricks are the LEADER's side; 13 - that is declarer.

    Catches a reversed sign (x vs 13-x): with the flipped convention the
    ranking would invert and the reported best card would be the WORST.
    """
    contract = Contract(3, "NT", declarer_i=1)
    cands = physical_cards(S)
    dt = score_layouts(_layouts(HANDS, 1), contract, cands,
                       displayed_leader_hand=S)
    direct = _direct_defensive(HANDS, "NT", contract.leader_i)

    best = max(cands, key=lambda c: dt[c][0])
    # best defensive lead here yields 3 tricks for the defence (declarer 10)
    assert dt[best][0] == direct[best] == max(direct.values())
    assert 0 <= dt[best][0] <= 13
    # a flipped convention (13 - x) would rank the true-best card LAST
    flipped = {c: 13 - dt[c][0] for c in cands}
    worst_by_flip = min(cands, key=lambda c: flipped[c])  # == best def card
    assert flipped[best] == 13 - dt[best][0]
    assert dt[best][0] != flipped[best]     # sign actually matters here


def test_display_card_equals_dds_card():
    """Every candidate the UI would show is the exact token DDS scored."""
    contract = Contract(4, "S", declarer_i=0)   # N declares -> E leads
    cands = physical_cards(E)
    dt = score_layouts(_layouts(HANDS, 1), contract, cands, check=True,
                       displayed_leader_hand=E)
    assert sorted(dt) == sorted(cands)          # display tokens == dds tokens


def test_spot_cards_resolved_independently_not_folded():
    """Spot cards each get their own DDS entry (no 32-code folding). deal_board
    seed 1's North hand (J6.K9754.KJ752.J) has suits with several low spots
    (7/5/4 of hearts, 7/5/2 of diamonds) that Ben's 32-code space collapses to
    9 codes; the scorer must keep all 13 physical entries."""
    from bridge_trainer.engine.lead_cards import lead_code32
    from bridge_trainer.engine.scanner import deal_board
    hands, _, _ = deal_board(1)
    hands = tuple(hands)
    leader = hands[0]                            # North
    contract = Contract(3, "NT", declarer_i=3)   # W declares -> N leads
    cands = physical_cards(leader)
    dt = score_layouts([Layout(hands=hands, sample_index=0)], contract,
                       cands, check=True, displayed_leader_hand=leader)
    # more physical candidates than Ben's folded 32-codes -> folding would
    # have lost distinct entries; the scorer keeps every physical card.
    n_folded = len({lead_code32(c) for c in cands})
    assert len(dt) == 13 > n_folded
    for c in cands:
        assert c in dt
