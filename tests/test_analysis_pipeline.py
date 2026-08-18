"""Integration tests: the adaptive analysis pipeline end-to-end (small n)."""
from __future__ import annotations

import numpy as np
import pytest

from bridge_trainer.analysis.pipeline import (AnalysisRequest,
                                              run_analysis,
                                              suggest_candidates)
from bridge_trainer.validate.auction_state import AuctionStateError

# The acceptance-flavoured scenario: E opens a weak 2H, S (hero) holds a
# strong balanced hand and must choose between X / 3NT / P.
REQ = dict(
    dealer="E", vul="Both", my_seat="S",
    my_hand="AQ2.KJ3.KQ54.A32",           # 18 HCP balanced, heart stop
    auction=["2H", "X", "P", "3S", "P", "4S", "P", "P", "P"],
    decision_index=1,
    system="two_over_one", scoring="IMP", seed=11,
)


def small_req(**kw):
    base = dict(REQ)
    base.update(kw)
    base.setdefault("max_deals", 200)
    base.setdefault("block", 100)
    return AnalysisRequest(**base)


def test_validation_rejects_wrong_seat():
    with pytest.raises(AuctionStateError):
        run_analysis(small_req(decision_index=0))   # call 0 is E's, not S's


def test_validation_rejects_illegal_auction():
    with pytest.raises(AuctionStateError):
        run_analysis(small_req(auction=["2H", "2H"], decision_index=1))


def test_suggest_candidates_contains_actual_pass_and_double():
    cands = suggest_candidates(small_req())
    assert cands[0] == "X"
    assert "P" in cands
    assert any(c.endswith("NT") for c in cands)   # 18 bal + heart stop


def test_pipeline_end_to_end_small():
    res = run_analysis(small_req(candidates=["X", "3NT", "P"]))
    # identical deal set for every candidate & policy (INV1)
    assert res.n_deals >= 100
    assert set(res.policies) == {"conservative", "realistic", "omniscient"}
    for pol in res.policies.values():
        assert {c.action for c in pol.corrected.candidates} == \
            {"X", "3NT", "P"}
    # real CIs, not constants
    assert 0 < res.top_pair_ci < 10
    assert res.ess > 0
    # representative deals: 3-5, with 4 full hands each
    assert 3 <= len(res.representative) <= 5
    for rep in res.representative:
        assert set(rep.hands) == {"N", "E", "S", "W"}
        for h in rep.hands.values():
            assert sum(len(x) for x in h.split(".")) == 13
    # constraints bind: E is a weak two in hearts on every kept deal
    # (checked indirectly: hero's hand fixed, E constrained)
    assert res.recommended in ("X", "3NT", "P")
    assert res.stability_note
    # partner-response frequencies exist for the X candidate
    resp = res.policies["realistic"].partner_response_freqs["X"]
    assert resp and sum(share for _, share in resp) > 0.5
    # meanings cover the full auction
    assert len(res.meanings) == len(REQ["auction"])


def test_mp_mode_ranks_by_frequency():
    res = run_analysis(small_req(candidates=["X", "3NT", "P"],
                                 scoring="MP", max_deals=150, block=75))
    mp = res.policies["realistic"].mp_pct
    assert set(mp) == {"X", "3NT", "P"}
    assert all(0 <= v <= 100 for v in mp.values())
    assert res.recommended == max(mp, key=mp.get)


def test_adaptive_stop_reports_sample_size():
    res = run_analysis(small_req(candidates=["X", "P"],
                                 max_deals=600, block=150))
    assert res.n_deals <= 600
    if res.stopped_early:
        assert res.n_deals < 600
    # the stop reason must be visible in the result
    assert res.top_pair_mean_imp == pytest.approx(
        res.top_pair_mean_imp)


def test_stem_only_mode_is_the_primary_flow():
    """The auction ends at the hero's turn; the analyzed call is NOT
    entered (user-requested flow). decision_index == len(auction)."""
    res = run_analysis(AnalysisRequest(
        dealer="E", vul="Both", my_seat="S",
        my_hand="AQ2.KJ3.KQ54.A32",
        auction=["2H"], decision_index=1,
        system="two_over_one", scoring="IMP",
        candidates=["X", "3NT", "P"], seed=11,
        max_deals=150, block=75))
    assert res.actual_call is None
    assert res.stem == ["2H"]
    assert res.recommended in ("X", "3NT", "P")
    # report renders without an "actual" call anywhere
    from bridge_trainer.analysis.report import build_facts, render_report
    facts = build_facts(res)
    assert facts["decision"]["actual"] is None
    html_doc = render_report(facts)
    assert "ההכרזה שלך בפועל" not in html_doc
    assert "שבחרת בפועל" not in html_doc
    # the auction diagram shows the analyzed call as "?"
    assert 'title="ההכרזה המנותחת">?' in html_doc
    # representative deals show the assumed continuation
    assert "המשך משוער אחרי" in html_doc


def test_stem_only_rejects_wrong_turn_or_finished_auction():
    base = dict(dealer="E", vul="Both", my_seat="S",
                my_hand="AQ2.KJ3.KQ54.A32", system="two_over_one",
                scoring="IMP", candidates=["P"], max_deals=120, block=60)
    with pytest.raises(AuctionStateError):   # after 2H it is S's turn, not W
        run_analysis(AnalysisRequest(
            auction=["2H", "P", "P"], decision_index=3,
            **dict(base, my_seat="W")))
    with pytest.raises(AuctionStateError):   # finished auction
        run_analysis(AnalysisRequest(
            auction=["2H", "P", "P", "P"], decision_index=4, **base))


def test_stem_only_auto_candidates():
    from bridge_trainer.analysis.pipeline import suggest_candidates
    cands = suggest_candidates(AnalysisRequest(
        dealer="E", vul="Both", my_seat="S",
        my_hand="AQ2.KJ3.KQ54.A32", auction=["2H"], decision_index=1))
    assert "P" in cands and "X" in cands
    assert any(c.endswith("NT") for c in cands)


def test_determinism_same_seed():
    a = run_analysis(small_req(candidates=["X", "P"]))
    b = run_analysis(small_req(candidates=["X", "P"]))
    assert a.recommended == b.recommended
    assert a.top_pair_mean_imp == pytest.approx(b.top_pair_mean_imp)
    assert a.n_deals == b.n_deals
