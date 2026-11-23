"""Opening-lead analysis (lead_analyze.html): validation, facts, report,
and the worker's kind=="lead" dispatch — against a fake Ben engine."""
from __future__ import annotations

import json

import numpy as np
import pytest

from bridge_trainer.analysis import worker
from bridge_trainer.analysis.lead_analysis import (LeadAnalysisRequest,
                                                   final_contract,
                                                   run_lead_analysis,
                                                   validate)
from bridge_trainer.analysis.lead_report import render_lead_report
from bridge_trainer.engine.lead_verdict import LeadEvaluation
from bridge_trainer.validate.auction_state import AuctionStateError

HAND = "KQJ4.T93.852.A72"        # West leads against 4H by South
AUCTION = ["1H", "P", "3H", "P", "4H", "P", "P", "P"]


class FakeEngine:
    """lead_evaluate stand-in: spade honours beat everything else."""

    def __init__(self, n=300):
        self.n = n
        self.calls = []

    def lead_evaluate(self, hand, seat_i, dealer_i, vuln, auction, denom,
                      contract, doubled, n_samples=None):
        self.calls.append(dict(seat_i=seat_i, dealer_i=dealer_i, vuln=vuln,
                               denom=denom, contract=contract,
                               doubled=doubled, n=n_samples))
        rng = np.random.default_rng(0)
        base = rng.integers(2, 5, self.n).astype(float)
        cards = []
        for suit, h in zip("SHDC", hand.split(".")):
            cards += [suit + r for r in h]
        dt = {}
        for c in cards:
            if c[0] == "S" and c[1] in "KQJ":
                dt[c] = base + 1          # equivalent honours -> grouped
            elif c == "CA":
                dt[c] = base - 1
            elif c[1] in "98765432":
                dt[c] = base.copy()       # spot cards fold together
            else:
                dt[c] = base.copy()
        smx = {c: (0.6 if c == "CA" else 0.02) for c in cards}
        return LeadEvaluation(cards=cards, def_tricks=dt, softmax=smx,
                              n_samples=self.n, quality=0.9,
                              contract=contract, doubled=doubled)


def _req(**kw):
    base = dict(dealer="S", vul="NS", my_seat="W", my_hand=HAND,
                auction=list(AUCTION), scoring="IMP")
    base.update(kw)
    return LeadAnalysisRequest(**base)


def test_final_contract_and_leader():
    fc = final_contract("S", AUCTION)
    assert fc["contract"] == "4HS" and fc["leader"] == "W"
    fc = final_contract("N", ["1S", "2H", "X", "P", "P", "P"])
    assert fc["contract"] == "2HEx" and fc["leader"] == "S"


@pytest.mark.parametrize("auction", [
    ["1H", "P", "3H", "P", "4H"],            # not finished
    ["P", "P", "P", "P"],                     # passed out
])
def test_incomplete_or_passed_out_rejected(auction):
    with pytest.raises(AuctionStateError):
        validate(_req(auction=auction))


def test_wrong_leader_rejected():
    with pytest.raises(AuctionStateError):
        validate(_req(my_seat="E"))


def test_actual_lead_must_be_held():
    with pytest.raises(ValueError):
        validate(_req(actual_lead="SA"))


def test_facts_rank_group_and_compare():
    eng = FakeEngine()
    facts = run_lead_analysis(_req(actual_lead="CA"), engine=eng)
    call = eng.calls[0]
    assert call["seat_i"] == 3 and call["dealer_i"] == 2
    assert call["vuln"] == (True, False) and call["contract"] == "4HS"
    assert facts["recommended"] == "SK"
    assert facts["recommended_cards"] == ["SK", "SQ", "SJ"]
    worst = facts["rows"][-1]
    assert worst["cards"] == ["CA"] and worst["verdict"] == "worse"
    assert worst["is_actual"] and worst["diff"] < 0
    assert facts["ben_top"] == "CA"
    assert all(abs(sum(r["hist"]) - 1) < 1e-3 for r in facts["rows"])
    json.dumps(facts)                       # Firestore-safe


def test_report_renders_hebrew():
    facts = run_lead_analysis(_req(actual_lead="CA"), engine=FakeEngine())
    html = render_lead_report(facts)
    assert "ניתוח הובלת פתיחה" in html and "ההובלה המומלצת" in html
    assert "ההובלה שלך בפועל" in html


def test_worker_dispatches_lead_kind():
    req = {"kind": "lead", "dealer": "S", "vul": "None", "my_seat": "W",
           "my_hand": HAND, "auction": AUCTION, "scoring": "MP",
           "actual_lead": "SK"}
    summary, html, facts_json = worker.process_request(
        req, engine=FakeEngine())
    assert summary["kind"] == "lead" and summary["recommended"] == "SK"
    assert summary["contract"] == "4HS" and summary["n_deals"] == 300
    assert json.loads(facts_json)["kind"] == "lead"


def test_lead_page_is_built_and_linked(tmp_path):
    from bridge_trainer.app import webapp
    webapp.write_app(tmp_path)
    page = (tmp_path / "lead_analyze.html").read_text(encoding="utf-8")
    assert 'data-nav="lead-analyze"' in page
    assert "lead_analyze.js?v=" in page and "bt-analyze-ui.js?v=" in page
    js = (tmp_path / "lead_analyze.js").read_text(encoding="utf-8")
    assert 'mode: "lead"' in js and 'kind: "lead"' in js
    assert "lead_analyze.html" in (tmp_path / "analyze.html").read_text(
        encoding="utf-8")
    # the bidding page hides lead rows of the shared queue
    assert 'r.req.kind === "lead"' in (tmp_path / "analyze.js").read_text(
        encoding="utf-8")
