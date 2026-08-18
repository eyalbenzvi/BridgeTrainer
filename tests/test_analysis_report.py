"""Tests: facts building, Hebrew template narration, HTML report, PDF."""
from __future__ import annotations

import json
import re

import pytest

from bridge_trainer.analysis.llm_narrator import (estimate_prompt_tokens,
                                                  llm_narrate)
from bridge_trainer.analysis.pdf import export_pdf, find_chromium
from bridge_trainer.analysis.pipeline import AnalysisRequest, run_analysis
from bridge_trainer.analysis.report import (build_facts, facts_to_json,
                                            narrate_all, render_report)


@pytest.fixture(scope="module")
def result():
    return run_analysis(AnalysisRequest(
        dealer="E", vul="Both", my_seat="S",
        my_hand="AQ2.KJ3.KQ54.A32",
        auction=["2H", "X", "P", "3S", "P", "4S", "P", "P", "P"],
        decision_index=1, system="two_over_one", scoring="IMP",
        candidates=["X", "3NT", "P"], seed=11, max_deals=200, block=100))


@pytest.fixture(scope="module")
def facts(result):
    return build_facts(result)


def test_facts_are_json_serializable_and_complete(facts):
    blob = facts_to_json(facts)
    round_trip = json.loads(blob)
    assert round_trip["candidates"] == ["X", "3NT", "P"]
    assert set(round_trip["policies"]) == \
        {"conservative", "realistic", "omniscient"}
    rows = round_trip["policies"]["realistic"]["rows"]
    assert {r["action"] for r in rows} == {"X", "3NT", "P"}
    for r in rows:
        assert "ev_imp" in r and "ci" in r and "mp_pct" in r
        assert 0 <= r["p_gain"] <= 1
    assert 3 <= len(round_trip["representative"]) <= 5


def test_template_narration_covers_all_sections(facts):
    prose = narrate_all(facts)
    assert prose["narrator"] == "template"
    assert "<p>" in prose["situation_html"]
    assert set(prose["candidates_html"]) == {"X", "3NT", "P"}
    assert "השורה התחתונה" in prose["conclusion_html"]


def test_report_structure_follows_spec(facts):
    html_doc = render_report(facts)
    # RTL + Hebrew shell
    assert 'dir="rtl"' in html_doc and 'lang="he"' in html_doc
    # all seven numbered sections of spec 4.1
    for i, title in enumerate(["תיאור המצב", "הפעולות המועמדות",
                               "טבלת תוצאות", "טבלאות תדירויות",
                               "חלוקות מייצגות", "סייגים", "מסקנה"], 1):
        assert re.search(f"<h2>{i}\\. .*{title}", html_doc), title
    # suit symbols with red class for hearts/diamonds
    assert 'class="red">♥' in html_doc or 'class="red">♦' in html_doc
    # real CI shown
    assert "±" in html_doc
    # representative deals render four hands
    assert html_doc.count('class="deal-diagram"') >= 3
    # print CSS present (PDF-ready)
    assert "@media print" in html_doc


def test_report_marks_recommended_and_actual(facts, result):
    html_doc = render_report(facts)
    assert 'class="rec"' in html_doc
    assert "ההכרזה שלך בפועל" in html_doc


def test_llm_narrator_falls_back_without_key(facts, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    prose = llm_narrate(facts)
    assert prose["narrator"] == "template"


def test_prompt_token_estimate(facts):
    est = estimate_prompt_tokens(facts)
    assert est["approx_static_tokens"] > 100
    assert est["approx_dynamic_tokens"] > 200


def test_pdf_export(tmp_path, facts):
    html_doc = render_report(facts)
    html_file = tmp_path / "report.html"
    html_file.write_text(html_doc, encoding="utf-8")
    if find_chromium() is None:
        pytest.skip("no chromium available")
    pdf = export_pdf(html_file, tmp_path / "report.pdf")
    assert pdf is not None
    data = pdf.read_bytes()
    assert data[:5] == b"%PDF-"
    assert len(data) > 10_000
