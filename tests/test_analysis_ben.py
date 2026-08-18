"""Tests for the Ben-powered analysis pipeline.

The pure helpers run everywhere; the end-to-end path needs the external
Ben checkout + its Python 3.12 venv (scripts/setup_ben.sh) and runs as a
subprocess under that venv when present, otherwise skips (the publish CI
has no Ben — the analyze-requests worker installs it separately)."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import numpy as np
import pytest

from bridge_trainer.analysis.ben_pipeline import (_concat_batches,
                                                  _contract_display,
                                                  _continuation_pairs,
                                                  _first_partner_call)

BEN_VENV = os.path.expanduser("~/benv/bin/python")
BEN_HOME = os.path.expanduser("~/ben")


def test_contract_display_formats():
    assert _contract_display("4SXE") == "4SEx"
    assert _contract_display("4SXXE") == "4SEx"
    assert _contract_display("3NN") == "3NTN"
    assert _contract_display("7CXS") == "7CSx"
    assert _contract_display("PASS") == "Pass-out"


def test_partner_response_and_continuation_parsing():
    # dealer E (idx 1); stem ["4S"]; hero S doubled at idx 1
    toks = "4S X P 5C P P P".split()
    assert _first_partner_call(toks, 1, 1, "N") == "5C"
    pairs = _continuation_pairs(toks, 1, 1)
    assert pairs == [["W", "P"], ["N", "5C"]]   # trailing passes trimmed
    assert _first_partner_call("4S X P P P".split(), 1, 1, "N") == "P"


def test_concat_batches_pairs_rows():
    from bridge_trainer.engine.ben import Evaluation
    a = Evaluation(bids=["X", "P"],
                   ev={"X": np.array([1.0]), "P": np.array([2.0])},
                   contracts={"X": ["4SXE"], "P": ["4SE"]},
                   auctions={"X": ["4S X P P P"], "P": ["4S P P P"]},
                   n_samples=1, quality=0.9, sample_deals=["a b c d"])
    b = Evaluation(bids=["X", "P"],
                   ev={"X": np.array([3.0]), "P": np.array([4.0])},
                   contracts={"X": ["5CN"], "P": ["4SE"]},
                   auctions={"X": ["4S X P 5C P P P"], "P": ["4S P P P"]},
                   n_samples=1, quality=0.7, sample_deals=["e f g h"])
    m = _concat_batches(a, b)
    assert m.n_samples == 2
    assert list(m.ev["X"]) == [1.0, 3.0]
    assert m.contracts["X"] == ["4SXE", "5CN"]
    assert m.sample_deals == ["a b c d", "e f g h"]
    assert m.quality == pytest.approx(0.8)


@pytest.mark.skipif(not (os.path.exists(BEN_VENV)
                         and os.path.isdir(os.path.join(BEN_HOME, "src"))),
                    reason="Ben venv/checkout not installed")
def test_ben_pipeline_end_to_end_subprocess():
    """Full Ben analysis in the Ben venv (py3.12 + tensorflow)."""
    code = r"""
import json, sys
sys.path.insert(0, %r)
from bridge_trainer.analysis.pipeline import AnalysisRequest
from bridge_trainer.analysis.ben_pipeline import run_analysis_ben
from bridge_trainer.analysis.report import build_facts, render_report

req = AnalysisRequest(dealer="E", vul="None", my_seat="S",
                      my_hand="A2.AK3.AKQT8.A32",
                      auction=["4S"], decision_index=1,
                      scoring="IMP", seed=7)
res = run_analysis_ben(req)
facts = build_facts(res)
html = render_report(facts)
print(json.dumps({
    "n": res.n_deals,
    "candidates": res.candidates,
    "recommended": res.recommended,
    "quality": res.acceptance_rate,
    "n_reps": len(res.representative),
    "has_cont": all(isinstance(r.cont_top, list)
                    for r in res.representative),
    "resp_after_top": res.policies["realistic"]
        .partner_response_freqs.get(res.candidates[0], []),
    "html_ok": ("חלוקות מייצגות" in html and "המשך משוער" in html
                and 'dir="rtl"' in html and "Ben" in html),
}))
""" % os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    env = dict(os.environ, BEN_HOME=BEN_HOME)
    out = subprocess.run([BEN_VENV, "-c", code], capture_output=True,
                         text=True, timeout=600, env=env)
    assert out.returncode == 0, out.stderr[-2000:]
    data = json.loads(out.stdout.strip().splitlines()[-1])
    assert data["n"] >= 200
    assert len(data["candidates"]) >= 2
    assert data["recommended"] in data["candidates"]
    assert 0 < data["quality"] <= 1
    assert data["n_reps"] >= 3 and data["has_cont"]
    assert data["html_ok"]
    # the continuation is REAL: partner responses are not one degenerate bin
    resp = dict(data["resp_after_top"])
    assert sum(resp.values()) > 0.9


def test_worker_requires_ben_outside_legacy(monkeypatch):
    from bridge_trainer.analysis import worker
    monkeypatch.delenv("BT_ANALYSIS_ENGINE", raising=False)
    monkeypatch.setenv("BEN_HOME", "/nonexistent")
    with pytest.raises(RuntimeError, match="Ben"):
        worker.resolve_engine()
    monkeypatch.setenv("BT_ANALYSIS_ENGINE", "legacy")
    from bridge_trainer.analysis.pipeline import run_analysis
    assert worker.resolve_engine() is run_analysis
