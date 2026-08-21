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


def test_user_extras_join_the_menu():
    """A mainstream call the policy starves (3NT over a preempt at 0.9%)
    must be evaluable when the user asks — legal extras join the menu,
    duplicates and illegal ones don't."""
    from bridge_trainer.analysis.ben_pipeline import _with_extras
    from bridge_trainer.validate.auction_state import replay
    state = replay("W", ["3C", "P", "P"])
    menu, added = _with_extras(["3D", "X", "P"],
                               ["3NT", "3D", "2C", "4D"], state)
    assert menu == ["3D", "X", "P", "3NT", "4D"]   # dup + illegal dropped
    assert added == ["3NT", "4D"]
    menu, added = _with_extras(["3D"], None, state)
    assert menu == ["3D"] and added == []
    # the cap: at most 4 extras are honored
    menu, added = _with_extras([], ["3NT", "4C", "4D", "4H", "4S"], state)
    assert len(added) == 4


def test_web_ui_exposes_extra_candidates():
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent / "bridge_trainer"
    ui = (root / "web" / "bt-analyze-ui.js").read_text(encoding="utf-8")
    assert "extraCandidates" in ui and "extra-add" in ui
    assert "reset(" in ui                       # cleared after submit
    site = (root / "app" / "webapp.py").read_text(encoding="utf-8")
    assert "extra_candidates = extras" in site and "extras-area" in site
    assert "UI.reset()" in site and "an-close" in site
    assert "an-open-print" not in site          # print button removed
    local = (root / "analysis" / "webui.py").read_text(encoding="utf-8")
    assert "extra_candidates" in local and "extras-area" in local


def test_menu_fills_to_six_from_policy_order():
    from types import SimpleNamespace as NS
    from bridge_trainer.analysis.ben_pipeline import _menu_from_policy
    # the user's 3C-P-P menu: 3NT (0.94%) and 4D (0.48%) must now be
    # evaluated; 3H at 0.06% is numeric noise and stays out
    policy = [NS(bid="3D", p=0.814), NS(bid="X", p=0.1253),
              NS(bid="P", p=0.0431), NS(bid="3NT", p=0.0094),
              NS(bid="4D", p=0.0048), NS(bid="3H", p=0.0006),
              NS(bid="3S", p=0.0005)]
    assert _menu_from_policy(policy) == ["3D", "X", "P", "3NT", "4D"]
    # the cap: never more than six
    policy = [NS(bid=b, p=0.1) for b in
              ["1C", "1D", "1H", "1S", "1NT", "2C", "2D"]]
    assert len(_menu_from_policy(policy)) == 6


def test_plans_parse_into_per_candidate_rules():
    from bridge_trainer.analysis.ben_pipeline import _plans_by_candidate
    plans = _plans_by_candidate([
        ["X", "3S", "3NT"], ["X", "3H", "P"], ["x", "3s", "4S"],  # dup rule
        ["3D", "4C"],            # malformed row dropped
        "junk",                  # malformed row dropped
    ])
    assert plans == {"X": {"3S": "3NT", "3H": "P"}}
    assert _plans_by_candidate(None) == {}


def test_worker_accepts_plan_maps_and_lists():
    # Firestore rejects nested arrays, so the web client ships {c,r,m}
    # maps; local tools still send 3-lists. Both must normalize.
    from bridge_trainer.analysis.worker import _plan_row
    assert _plan_row({"c": "X", "r": "3S", "m": "3NT"}) == ["X", "3S", "3NT"]
    assert _plan_row(["X", "3H", "P"]) == ["X", "3H", "P"]
    assert _plan_row({"c": "X", "r": "3S"}) is None
    assert _plan_row("junk") is None


def test_stop_rule_has_no_first_crossing_bias():
    from bridge_trainer.analysis.ben_pipeline import _should_stop
    # the shipped 2D-vs-P signature — mean barely over the CI. The old rule
    # stopped here and reported a fabricated edge; the new one must not.
    assert not _should_stop(0.43, 0.401, 600)
    # precision target reached: stop regardless of the mean
    assert _should_stop(0.05, 0.35, 600)
    # clear dominance stops, but only once the sample is respectable
    assert _should_stop(1.0, 0.4, 600)
    assert not _should_stop(1.0, 0.4, 400)


@pytest.mark.skipif(not (os.path.exists(BEN_VENV)
                         and os.path.isdir(os.path.join(BEN_HOME, "src"))),
                    reason="Ben venv/checkout not installed")
def test_adaptive_batches_sample_fresh_deals_subprocess():
    """Ben reseeds its sampler from hash(hand) on every call, so two
    evaluate() calls on the same bot return IDENTICAL deals — the bug that
    turned '600 samples' into 200 triplicated ones. The batch loop varies
    bot.hash_integer; this pins both halves of that contract."""
    code = r"""
import json, sys
sys.path.insert(0, __ROOT__)
import numpy as np
from bridge_trainer.engine.ben import get_engine

engine = get_engine()
bot = engine.bot("J87.976.A64.K843", 0, 0, (False, False))
stem = ["P", "P", "1D", "2C", "P", "P", "X", "P"]
memo = {}
a = engine.evaluate(bot, 0, stem, ["2D"], n_samples=40, dd_memo=memo)
b = engine.evaluate(bot, 0, stem, ["2D"], n_samples=40, dd_memo=memo)
bot.hash_integer = (bot.hash_integer + 1) % (2 ** 31)
c = engine.evaluate(bot, 0, stem, ["2D"], n_samples=40, dd_memo=memo)
print(json.dumps({
    "same_hash_identical": a.sample_deals == b.sample_deals,
    "new_hash_fresh": a.sample_deals != c.sample_deals,
}))
""".replace("__ROOT__", repr(os.path.abspath(
        os.path.join(os.path.dirname(__file__), ".."))))
    env = dict(os.environ, BEN_HOME=BEN_HOME)
    out = subprocess.run([BEN_VENV, "-c", code], capture_output=True,
                         text=True, timeout=600, env=env)
    assert out.returncode == 0, out.stderr[-2000:]
    data = json.loads(out.stdout.strip().splitlines()[-1])
    assert data["same_hash_identical"]   # Ben's determinism (the trap)
    assert data["new_hash_fresh"]        # the loop's antidote


@pytest.mark.skipif(not (os.path.exists(BEN_VENV)
                         and os.path.isdir(os.path.join(BEN_HOME, "src"))),
                    reason="Ben venv/checkout not installed")
def test_continuation_plan_overrides_ben_subprocess():
    """The owner's example: over 3C-P-P force X with the plan 'partner 3S
    -> I bid 3NT'. The plan must actually fire (plan_hits > 0) and 3NT
    contracts must appear in X's rollouts where Ben alone reached 3S."""
    code = r"""
import json, sys
sys.path.insert(0, __ROOT__)
from bridge_trainer.engine.ben import get_engine

engine = get_engine()
bot = engine.bot("K4.AT95.AT943.AJ", 2, 3, (True, False))
stem = ["3C", "P", "P"]
plain = engine.evaluate(bot, 3, stem, ["X"], n_samples=60, dd_memo={})
planned = engine.evaluate(bot, 3, stem, ["X"], n_samples=60, dd_memo={},
                          plans={"X": {"3S": "3NT"}})
def n_nt(ev): return sum(1 for c in ev.contracts["X"] if c.startswith("3N"))
print(json.dumps({
    "hits": planned.plan_hits,
    "nt_plain": n_nt(plain), "nt_planned": n_nt(planned),
    "n": planned.n_samples,
}))
""".replace("__ROOT__", repr(os.path.abspath(
        os.path.join(os.path.dirname(__file__), ".."))))
    env = dict(os.environ, BEN_HOME=BEN_HOME)
    out = subprocess.run([BEN_VENV, "-c", code], capture_output=True,
                         text=True, timeout=600, env=env)
    assert out.returncode == 0, out.stderr[-2000:]
    data = json.loads(out.stdout.strip().splitlines()[-1])
    total_hits = sum(data["hits"].values())
    assert total_hits > 0                      # the rule actually fired
    assert data["nt_planned"] > data["nt_plain"]   # and changed contracts
    assert data["nt_planned"] >= total_hits * 0.5  # mostly stands (P-P-P)


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
