"""Evaluator purity: the public-state evaluator conditions ONLY on public
information, is deterministic for a fixed sampler seed, and cannot leak the
source full deal. Uses a pure fake sampler (public-state only) + real endplay
DDS; no Ben.
"""
from __future__ import annotations

import numpy as np

from bridge_trainer.engine.lead_cards import (RANKS, SUITS, FULL_DECK,
                                              physical_cards)
from bridge_trainer.engine.lead_evaluate import (
    Contract, EvalConfig, Layout, SampleResult,
    evaluate_leads_from_public_state)

CONTRACT = Contract(3, "NT", declarer_i=1)   # E declares -> S leads
LEADER_HAND = "T87.JT86.QJ7.Q83"
AUCTION = ["1NT", "P", "3NT", "P", "P", "P"]


def _to_pbn(cards):
    by_suit = {s: [] for s in SUITS}
    for c in cards:
        by_suit[c[0]].append(c[1])
    return ".".join("".join(sorted(by_suit[s], key=RANKS.index))
                    for s in SUITS)


def make_fake_sampler(record=None):
    """A sampler that sees ONLY the public state. Deals the 39 non-leader
    cards uniformly at random (seeded) to the three hidden seats. If `record`
    is given, appends each call's kwargs so a test can prove no source deal
    was ever passed in."""
    def sampler(public, sampler_seed, config):
        if record is not None:
            record.append({"public": public, "seed": sampler_seed})
        leader_i = public.contract.leader_i
        remaining = sorted(FULL_DECK - set(physical_cards(public.leader_hand)))
        rng = np.random.default_rng(sampler_seed)
        others = [s for s in range(4) if s != leader_i]
        layouts = []
        for i in range(config.n_samples):
            shuffled = list(rng.permutation(remaining))
            hands = [None, None, None, None]
            hands[leader_i] = public.leader_hand
            for k, s in enumerate(others):
                hands[s] = _to_pbn(shuffled[k * 13:(k + 1) * 13])
            layouts.append(Layout(hands=tuple(hands), sample_index=i,
                                  sample_seed=sampler_seed * 1000 + i,
                                  accept={"rule": "fake_uniform"}))
        return SampleResult(layouts=layouts, quality=1.0)
    return sampler


def _evaluate(source_deal, seed=7, n=16):
    cfg = EvalConfig(n_samples=n, check_invariants=True)
    return evaluate_leads_from_public_state(
        LEADER_HAND, AUCTION, CONTRACT, dealer_i=1, vul=(False, False),
        sampler_seed=seed, config=cfg, sampler=make_fake_sampler(),
        source_deal=source_deal, problem_id="purity")


def _avgs(le):
    return {c: float(np.mean(le.def_tricks[c])) for c in le.cards}


def test_deterministic_same_public_state_and_seed():
    a = _evaluate(source_deal=None)
    b = _evaluate(source_deal=None)
    assert a.cards == b.cards
    for c in a.cards:
        np.testing.assert_array_equal(a.def_tricks[c], b.def_tricks[c])


def test_two_different_source_deals_same_public_state_identical():
    # Same displayed hand + public state, DIFFERENT hidden source deals.
    deal1 = {"N": "AKQ.AKQ.AKQ.AKQJ", "E": "...", "S": LEADER_HAND, "W": "..."}
    deal2 = {"N": "234.234.234.23456", "E": "xxx", "S": LEADER_HAND, "W": "y"}
    a = _evaluate(source_deal=deal1)
    b = _evaluate(source_deal=deal2)
    for c in a.cards:
        np.testing.assert_array_equal(a.def_tricks[c], b.def_tricks[c])


def test_sampler_never_receives_source_deal():
    record = []
    cfg = EvalConfig(n_samples=4, check_invariants=True)
    evaluate_leads_from_public_state(
        LEADER_HAND, AUCTION, CONTRACT, dealer_i=1, vul=(False, False),
        sampler_seed=3, config=cfg, sampler=make_fake_sampler(record),
        source_deal={"N": "SECRET", "S": LEADER_HAND}, problem_id="spy")
    assert len(record) == 1
    public = record[0]["public"]
    # the only hand the sampler can see is the leader's; no full deal attribute
    assert public.leader_hand == LEADER_HAND
    assert not hasattr(public, "source_deal")
    assert not hasattr(public, "full_deal")
    # public fields are exactly the allowed set
    assert set(vars(public)) == {"leader_hand", "auction", "contract",
                                 "dealer_i", "vul"}


def test_leader_hand_is_fixed_across_all_samples():
    le = _evaluate(source_deal=None, n=32)
    # every sampled layout kept the displayed leader hand (checked already by
    # invariants); here assert the candidate set is exactly the 13 shown cards
    assert set(le.cards) == set(physical_cards(LEADER_HAND))
    assert le.n_samples == 32
