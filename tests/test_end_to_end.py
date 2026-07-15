"""End-to-end smoke: the M1 problem with a tiny deal count (INV1, INV6)."""
from pathlib import Path

import numpy as np
import pytest

from bridge_trainer.app.report import render_report
from bridge_trainer.app.runner import run_problem
from bridge_trainer.bank.schema import ProblemValidationError, load_problem

PROBLEM = Path("problems/comp_3s_over_3h.yaml")


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    cache_dir = tmp_path_factory.mktemp("cache")
    return run_problem(PROBLEM, seed=7, n_override=48, cache_dir=cache_dir)


def test_problem_loads_and_validates():
    p = load_problem(PROBLEM)
    assert p.my_seat == "S"
    assert p.vul == "EW"
    assert [c.call for c in p.candidates] == ["P", "3S", "X"]


def test_all_candidates_scored_on_identical_deal_set_inv1(result):
    n = len(result.deals)
    for call, contracts in result.contracts_by_candidate.items():
        assert len(contracts) == n, call
    for scores in (result.raw_scores, result.corrected_scores):
        assert all(len(v) == n for v in scores.values())


def test_run_is_deterministic_inv6(tmp_path):
    a = run_problem(PROBLEM, seed=9, n_override=32, cache_dir=tmp_path / "a")
    b = run_problem(PROBLEM, seed=9, n_override=32, cache_dir=tmp_path / "b")
    assert [str(d.deal) for d in a.deals] == [str(d.deal) for d in b.deals]
    for call in a.raw_scores:
        np.testing.assert_array_equal(a.raw_scores[call], b.raw_scores[call])
    assert a.constraint_hash == b.constraint_hash


def test_cache_roundtrip_preserves_results(tmp_path):
    a = run_problem(PROBLEM, seed=5, n_override=32, cache_dir=tmp_path)
    assert not a.cache_hit
    b = run_problem(PROBLEM, seed=5, n_override=32, cache_dir=tmp_path)
    assert b.cache_hit
    assert [str(d.deal) for d in a.deals] == [str(d.deal) for d in b.deals]
    for call in a.corrected_scores:
        np.testing.assert_allclose(a.corrected_scores[call],
                                   b.corrected_scores[call])


def test_report_renders_with_required_sections(result):
    html = render_report(result, user_answer="3S")
    for needle in ("Opponents assumed", "Generation diagnostics",
                   "Sample audit", "seed 7", "constraint hash",
                   "Toggle raw / corrected", "Your answer"):
        assert needle in html, needle


def test_verdict_text_mentions_both_raw_and_corrected(result):
    text = result.verdict_text()
    assert "[raw DD]" in text and "[corrected]" in text


def test_semantics_gaps_would_be_surfaced(result):
    # This problem's auction is fully covered by its rulesets.
    assert result.diagnostics.unrecognized_calls == []


def test_bad_problem_files_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("schema_version: 1\nid: x\n")
    with pytest.raises(ProblemValidationError):
        load_problem(bad)
