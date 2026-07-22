"""Pre-DDS invariant layer tests (no DDS): each check fails loudly on a bad
layout and names the offending seat/card."""
from __future__ import annotations

import pytest

from bridge_trainer.engine.lead_evaluate import Contract
from bridge_trainer.engine.lead_cards import physical_cards
from bridge_trainer.engine.lead_invariants import (
    LeadInvariantError, check_dds_result, check_layout, checks_enabled)

# A legal deal. Leader = declarer's LHO. Declarer E (1) -> leader S (2).
N = "K93.752.A854.T62"
E = "AQJ4.KQ4.K3.AK54"
S = "T87.JT86.QJ7.Q83"
W = "652.A93.T962.J97"
HANDS = (N, E, S, W)
CONTRACT = Contract(3, "NT", declarer_i=1)
LEADER_I = 2
CANDS = physical_cards(S)


def _ok(**kw):
    args = dict(hands_abs=HANDS, contract=CONTRACT, leader_i=LEADER_I,
                displayed_leader_hand=S, candidates=CANDS,
                sample_index=0, problem_id="t")
    args.update(kw)
    check_layout(**args)


def test_valid_layout_passes():
    _ok()


def test_leader_hand_must_match_display():
    with pytest.raises(LeadInvariantError, match="displayed leader hand"):
        _ok(displayed_leader_hand="AKQ.AKQ.AKQ.AKQJ")


def test_declarer_leader_mismatch_caught():
    with pytest.raises(LeadInvariantError, match="declarer's LHO"):
        _ok(leader_i=1)               # leader can't be declarer's own seat


def test_candidate_not_in_leader_hand_caught():
    bad = list(CANDS)
    bad[0] = "S2"                     # S2 is not in South's hand
    with pytest.raises(LeadInvariantError):
        _ok(candidates=bad)


def test_candidates_must_equal_displayed_hand():
    with pytest.raises(LeadInvariantError, match="candidate set"):
        _ok(candidates=CANDS[:-1])


def test_duplicate_card_across_hands_caught():
    dup = (N, E, S, "652.A93.T962.J9K")   # W now holds SK too (dup) & 12 cards
    with pytest.raises(LeadInvariantError):
        _ok(hands_abs=dup)


def test_not_full_deck_caught():
    # swap W to a 13-card hand that duplicates one of N's cards -> not 52 unique
    bad_w = "652.A93.T962.J98"        # C8? build a clean 13 that dups something
    # Replace W's J97 clubs with J98: C8 already in W? original W clubs J97;
    # C8 belongs to E. This makes C8 duplicated and (some card) missing.
    hands = (N, E, S, "652.A93.T962.J98")
    with pytest.raises(LeadInvariantError):
        _ok(hands_abs=hands)


def test_wrong_hand_count_caught():
    with pytest.raises(LeadInvariantError, match="4 hands"):
        _ok(hands_abs=(N, E, S))


def test_check_dds_result_detects_collapsed_candidates():
    per_card = {c: 3 for c in CANDS[:-3]}    # 3 candidates missing (folded)
    with pytest.raises(LeadInvariantError, match="missing"):
        check_dds_result(per_card, CANDS, problem_id="t")


def test_check_dds_result_ok():
    check_dds_result({c: 3 for c in CANDS}, CANDS)


def test_checks_enabled_env(monkeypatch):
    monkeypatch.delenv("BT_LEAD_CHECK", raising=False)
    assert not checks_enabled()
    monkeypatch.setenv("BT_LEAD_CHECK", "1")
    assert checks_enabled()
    monkeypatch.setenv("BT_LEAD_CHECK", "0")
    assert not checks_enabled()
