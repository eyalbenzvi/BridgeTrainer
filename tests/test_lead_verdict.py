"""Pure unit tests for the opening-lead verdict and contract mechanics.

These need no BEN engine, so they run in the normal test job — the coverage
the bidding engine pipeline never got.
"""
from __future__ import annotations

import numpy as np
import pytest

from bridge_trainer.engine.conventions import (
    contract_str, final_contract, opening_leader)
from bridge_trainer.engine.lead_verdict import (
    GAP_MIN, N_MIN, P_OBVIOUS, LeadEvaluation, judge_lead)


# --------------------------------------------------------------------------
# contract mechanics
# --------------------------------------------------------------------------

def test_final_contract_simple_suit():
    # dealer N (0): N 1H, E P, S 4H, W P, N P, E P  -> 4H by North
    fc = final_contract(["1H", "P", "4H", "P", "P", "P"], 0)
    assert fc == {"level": 4, "denom": "H", "declarer_i": 0, "doubled": ""}
    assert contract_str(fc) == "4HN"
    assert opening_leader(fc["declarer_i"]) == 1  # East leads


def test_final_contract_declarer_is_first_to_name_strain():
    # dealer N: N 1S, E P, S 2S, W P, S ... actually declarer is the first
    # of the N/S side to bid spades = North, even though South raised.
    fc = final_contract(["1S", "P", "2S", "P", "P", "P"], 0)
    assert fc["declarer_i"] == 0
    assert contract_str(fc) == "2SN"


def test_final_contract_notrump_and_doubled():
    # dealer W (3): W 1NT, N P, E 3NT, S X, all pass -> 3NTx by W (first NT)
    fc = final_contract(["1NT", "P", "3NT", "X", "P", "P", "P"], 3)
    assert fc["denom"] == "NT"
    assert fc["declarer_i"] == 3
    assert fc["doubled"] == "x"
    assert contract_str(fc) == "3NTWx"


def test_final_contract_passed_out():
    assert final_contract(["P", "P", "P", "P"], 0) is None


# --------------------------------------------------------------------------
# lead verdict
# --------------------------------------------------------------------------

def _hand13():
    return ["SA", "SK", "S3", "HQ", "HJ", "H7", "H2",
            "DA", "D6", "CT", "C8", "C5", "C3"]


def _eval(avg_by_card, softmax=None, n=512, doubled=False,
          jitter=0.0, seed=0):
    """Build a LeadEvaluation whose per-card mean tricks match avg_by_card."""
    rng = np.random.default_rng(seed)
    cards = _hand13()
    def_tricks = {}
    for c in cards:
        base = avg_by_card.get(c, 3.0)
        if jitter:
            def_tricks[c] = base + rng.normal(0, jitter, size=n)
        else:
            def_tricks[c] = np.full(n, base, dtype=float)
    softmax = softmax or {c: 1.0 / len(cards) for c in cards}
    return LeadEvaluation(cards=cards, def_tricks=def_tricks, softmax=softmax,
                          n_samples=n, quality=0.9, contract="4HE",
                          doubled=doubled)


def test_accepts_clear_cross_suit_winner():
    avg = {"DA": 4.6}          # diamond ace clearly best; next suit ~4.0
    for c in _hand13():
        avg.setdefault(c, 4.0)
    avg["HQ"] = 4.0
    v = judge_lead(_eval(avg, softmax={c: 0.1 for c in _hand13()}))
    assert v.accepted, v.reason
    assert v.best == ["DA"]
    assert v.table[0]["card"] == "DA"


def test_criterion1_obvious_rejected():
    avg = {c: 4.0 for c in _hand13()}
    avg["DA"] = 4.6
    sm = {c: 0.02 for c in _hand13()}
    sm["DA"] = P_OBVIOUS + 0.05      # BEN over 70% on one card
    v = judge_lead(_eval(avg, softmax=sm))
    assert not v.accepted
    assert v.reason == "obvious"


def test_criterion2_suit_indifferent_rejected():
    # best diamond only 0.1 over the best heart -> suit doesn't matter
    avg = {c: 4.0 for c in _hand13()}
    avg["DA"] = 4.10
    avg["HQ"] = 4.00
    v = judge_lead(_eval(avg, softmax={c: 0.1 for c in _hand13()}))
    assert not v.accepted
    assert v.reason == "suit_indifferent"


def test_criterion2_boundary():
    avg = {c: 4.0 for c in _hand13()}
    avg["DA"] = 4.0 + GAP_MIN + 0.01
    v = judge_lead(_eval(avg, softmax={c: 0.1 for c in _hand13()}))
    assert v.accepted, v.reason


def test_touching_cards_all_accepted():
    # SA and SK identical (touching) and both clearly best across suits
    avg = {c: 3.5 for c in _hand13()}
    avg["SA"] = avg["SK"] = 4.5
    v = judge_lead(_eval(avg, softmax={c: 0.1 for c in _hand13()}))
    assert v.accepted, v.reason
    assert set(v.best) == {"SA", "SK"}


def test_within_suit_choice_survives_c2():
    # The whole decision is A vs low in ONE suit; other suits are far worse,
    # so criterion 2 (different-suit gap) must NOT reject it.
    avg = {c: 3.0 for c in _hand13()}
    avg["SA"] = 4.8       # best
    avg["SK"] = 4.0       # same suit, clearly worse -> a real within-suit call
    v = judge_lead(_eval(avg, softmax={c: 0.1 for c in _hand13()}))
    assert v.accepted, v.reason
    assert v.best == ["SA"]


def test_doubled_excluded():
    avg = {c: 4.0 for c in _hand13()}
    avg["DA"] = 4.6
    v = judge_lead(_eval(avg, doubled=True,
                         softmax={c: 0.1 for c in _hand13()}))
    assert not v.accepted
    assert v.reason == "doubled_excluded"


def test_insufficient_samples():
    avg = {c: 4.0 for c in _hand13()}
    avg["DA"] = 4.6
    v = judge_lead(_eval(avg, n=N_MIN - 1,
                         softmax={c: 0.1 for c in _hand13()}))
    assert not v.accepted
    assert v.reason == "insufficient_samples"


def test_difficulty_trap_is_hard():
    # BEN wants a heart, but the diamond ace is decisively best -> trap.
    avg = {c: 3.8 for c in _hand13()}
    avg["DA"] = 4.7
    avg["HQ"] = 3.8
    sm = {c: 0.03 for c in _hand13()}
    sm["HQ"] = 0.45          # confident on the WRONG card
    v = judge_lead(_eval(avg, softmax=sm))
    assert v.accepted, v.reason
    assert v.measured["trap"] is True
    assert v.difficulty == 5


def test_difficulty_clear_is_easy():
    avg = {c: 3.0 for c in _hand13()}
    avg["DA"] = 4.5          # one suit clearly best, big gap
    sm = {c: 0.03 for c in _hand13()}
    sm["DA"] = 0.5           # BEN agrees (not a trap)
    # BEN over 0.7 would reject; keep it under.
    v = judge_lead(_eval(avg, softmax=sm))
    assert v.accepted, v.reason
    assert v.measured["trap"] is False
    assert v.difficulty <= 2
