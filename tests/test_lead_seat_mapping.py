"""Seat/rotation consistency: deal -> auction -> contract -> leader -> DDS.

Compass seats are absolute NESW = 0,1,2,3 everywhere. These tests pin the
leader as declarer's LHO for all four declarer seats and prove the DDS
first-to-play seat matches, using real endplay (no Ben).
"""
from __future__ import annotations

from bridge_trainer.engine.conventions import (contract_str, final_contract,
                                                opening_leader)
from bridge_trainer.engine.lead_cards import physical_cards
from bridge_trainer.engine.lead_evaluate import Contract, Layout, score_layouts

# Four distinct legal hands, one per absolute seat.
HANDS = ("K93.752.A854.T62",     # N
         "AQJ4.KQ4.K3.AK54",     # E
         "T87.JT86.QJ7.Q83",     # S
         "652.A93.T962.J97")     # W
SEATS = "NESW"


def test_conventions_and_contract_agree_on_leader():
    for decl in range(4):
        fc = {"level": 4, "denom": "H", "declarer_i": decl, "doubled": ""}
        assert opening_leader(decl) == (decl + 1) % 4
        c = Contract.from_fc(fc)
        assert c.declarer_i == decl
        assert c.leader_i == opening_leader(decl)
        assert str(c) == contract_str(fc)


def test_final_contract_to_leader_to_dds_all_declarers():
    """For each declarer seat, the DDS-scored cards must be exactly the hand at
    declarer's-LHO seat — proving the leader/first-to-play rotation is right."""
    for decl in range(4):
        leader_i = (decl + 1) % 4
        contract = Contract(3, "NT", declarer_i=decl)
        leader_hand = HANDS[leader_i]
        cands = physical_cards(leader_hand)
        # check=True runs the full invariant layer (leader hand identity,
        # declarer/leader consistency, full-deck legality) before every solve.
        dt = score_layouts([Layout(hands=HANDS, sample_index=0)],
                           contract, cands, check=True,
                           problem_id=f"decl-{SEATS[decl]}",
                           displayed_leader_hand=leader_hand)
        assert set(dt) == set(cands)
        # the scored cards belong to the LHO seat, not any other seat
        for other in range(4):
            if other == leader_i:
                continue
            assert set(dt).isdisjoint(set(physical_cards(HANDS[other])))


def test_final_contract_declarer_first_to_name_strain():
    # N 1H, E P, S 4H ... -> declarer is N (first N/S to bid hearts), leader E
    fc = final_contract(["1H", "P", "4H", "P", "P", "P"], 0)
    assert fc["declarer_i"] == 0
    assert opening_leader(fc["declarer_i"]) == 1
