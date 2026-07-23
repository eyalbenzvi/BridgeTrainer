"""The Opening Lead Trainer's two training modes: MP and IMP.

Proves the task-level guarantees:
  * MP ranks by expected defensive tricks;
  * IMP ranks by expected IMP value (never by the trick average);
  * one scenario can produce DIFFERENT best leads in MP and IMP;
  * both tricks and IMP metrics are present in both modes;
  * the training mode persists (record schema, index modes, attempt fields);
  * no "Set the Contract" mode and no "beat the field" wording anywhere.

All Ben-free: metrics are computed from synthetic per-sample DD arrays via
the same code path production uses (scoring/lead_metrics + lead_maker).
"""
from __future__ import annotations

import numpy as np
import pytest

from bridge_trainer.app.webapp import (_dashboard_html, _index_html,
                                       _lead_html, _problem_html)
from bridge_trainer.engine.lead_maker import LEAD_SCHEMA, build_lead_record
from bridge_trainer.engine.lead_verdict import LeadEvaluation, judge_lead
from bridge_trainer.pool.store import ProblemPool, index_entry
from bridge_trainer.scoring.lead_metrics import (
    LEAD_ALGO_VERSION, LEAD_IMP_BASELINE, MODE_GOALS, RANKING_METRICS,
    TRAINING_MODES, accepted_set, compute_lead_metrics, declarer_vulnerable,
    defender_score_table, legacy_training_block, mode_rankings,
    parse_contract_full, rank_leads, supported_modes, training_block)


# --------------------------------------------------------------------------
# fixture: one scenario where MP and IMP disagree about the best lead
# --------------------------------------------------------------------------
# Against 3NT by East, both vulnerable (defense needs 5 tricks to set):
#   SA: always exactly 4 defensive tricks — never sets (avg 4.0)
#   HK: 5 tricks half the time (down 1), 2 the other half (avg 3.5, sets 50%)
# MP (tricks) prefers SA; IMP (score swings) prefers HK.
DIVERGENT = {
    "SA": np.array([4, 4], dtype=int),
    "HK": np.array([5, 2], dtype=int),
}
CONTRACT = "3NTE"
VUL = "Both"


def divergent_metrics():
    return compute_lead_metrics(DIVERGENT, CONTRACT, VUL)


# --------------------------------------------------------------------------
# scoring plumbing
# --------------------------------------------------------------------------

def test_parse_contract_full():
    assert parse_contract_full("4HE") == (4, "H", 0, "E")
    assert parse_contract_full("3NTWx") == (3, "NT", 1, "W")
    assert parse_contract_full("6SSxx") == (6, "S", 2, "S")


def test_declarer_vulnerable():
    assert declarer_vulnerable("Both", "E")
    assert declarer_vulnerable("NS", "N")
    assert not declarer_vulnerable("NS", "E")
    assert not declarer_vulnerable("None", "W")


def test_defender_score_table_3nt_vul():
    t = defender_score_table(3, "NT", 0, True)
    assert t[4] == -600          # 4 defensive tricks: 3NT= for 600
    assert t[5] == 100           # 5 tricks: down 1 vul
    assert t[2] == -660          # 2 tricks: two overtricks


def test_metrics_values_on_divergent_fixture():
    m = divergent_metrics()
    assert m["SA"]["exp_def_tricks"] == pytest.approx(4.0)
    assert m["HK"]["exp_def_tricks"] == pytest.approx(3.5)
    assert m["SA"]["exp_score"] == pytest.approx(-600.0)
    assert m["HK"]["exp_score"] == pytest.approx(-280.0)
    # Butler datum: sample 1 -> A -8 / B +8 IMPs; sample 2 -> A +1 / B -1
    assert m["SA"]["exp_imps"] == pytest.approx(-3.5)
    assert m["HK"]["exp_imps"] == pytest.approx(3.5)
    assert m["SA"]["set_prob"] == pytest.approx(0.0)
    assert m["HK"]["set_prob"] == pytest.approx(0.5)


def test_unknown_baseline_rejected():
    with pytest.raises(ValueError):
        compute_lead_metrics(DIVERGENT, CONTRACT, VUL,
                             baseline={"id": "nope", "version": 9})


# --------------------------------------------------------------------------
# mode-aware ranking
# --------------------------------------------------------------------------

def test_mp_ranks_by_expected_defensive_tricks():
    m = divergent_metrics()
    order = rank_leads(m, "MP")
    tricks = [m[c]["exp_def_tricks"] for c in order]
    assert tricks == sorted(tricks, reverse=True)
    assert order[0] == "SA"


def test_imp_ranks_by_expected_imp_value_not_tricks():
    m = divergent_metrics()
    order = rank_leads(m, "IMP")
    imp_vals = [m[c]["exp_imps"] for c in order]
    assert imp_vals == sorted(imp_vals, reverse=True)
    # explicitly NOT the tricks order
    assert order[0] == "HK"
    assert m[order[0]]["exp_def_tricks"] < m[order[1]]["exp_def_tricks"]


def test_same_scenario_different_best_leads_per_mode():
    m = divergent_metrics()
    assert rank_leads(m, "MP")[0] != rank_leads(m, "IMP")[0]
    r = mode_rankings(m)
    assert r["MP"]["recommended"] == "SA"
    assert r["IMP"]["recommended"] == "HK"
    assert r["MP"]["ranking_metric"] == "exp_def_tricks"
    assert r["IMP"]["ranking_metric"] == "exp_imps"


def test_deterministic_tie_breakers():
    # identical metrics -> fixed suit-then-rank order, every time
    tricks = {"C2": np.array([4, 5]), "SA": np.array([4, 5]),
              "H7": np.array([4, 5])}
    m = compute_lead_metrics(tricks, CONTRACT, VUL)
    for mode in TRAINING_MODES:
        assert rank_leads(m, mode) == ["SA", "H7", "C2"]
    assert accepted_set(m, "MP") == ["SA", "H7", "C2"]


def test_unknown_mode_rejected():
    with pytest.raises(ValueError):
        rank_leads(divergent_metrics(), "TOTAL_POINTS")


# --------------------------------------------------------------------------
# record building: both metrics in both modes, per-mode ranks, metadata
# --------------------------------------------------------------------------

def make_record():
    cards = list(DIVERGENT)
    le = LeadEvaluation(
        cards=cards, def_tricks=DIVERGENT,
        softmax={c: 0.1 for c in cards}, n_samples=2, quality=1.0,
        contract=CONTRACT, doubled=False)
    verdict = judge_lead(le, force=True)
    fc = {"level": 3, "denom": "NT", "declarer_i": 1, "doubled": ""}
    hands = ["A32.K54.7654.432"] * 4
    return build_lead_record(
        seed=1, hands=hands, dealer_i=0, vul=(True, True), fc=fc,
        leader_i=2, hand=hands[2], full_auction=["1NT", "P", "3NT", "P",
                                                 "P", "P"],
        le=le, verdict=verdict, auc_meanings=[], card_notes={}, elapsed=0.1)


def test_record_carries_all_metrics_in_both_modes():
    rec = make_record()
    assert rec["schema"] == LEAD_SCHEMA
    for row in rec["candidates"] + rec["verdict"]["table"]:
        # every lead retains tricks AND score AND IMP AND set probability
        for key in ("avg_def_tricks", "exp_score", "exp_imps", "set_prob",
                    "rank_mp", "rank_imp", "recommended_mp",
                    "recommended_imp"):
            assert key in row, key
    by_mode = rec["verdict"]["by_mode"]
    assert set(by_mode) == {"MP", "IMP"}
    assert by_mode["MP"]["recommended"] == "SA"
    assert by_mode["IMP"]["recommended"] == "HK"
    # per-mode ranks follow each mode's own metric
    rows = {r["card"]: r for r in rec["verdict"]["table"]}
    assert rows["SA"]["rank_mp"] == 1 and rows["SA"]["rank_imp"] == 2
    assert rows["HK"]["rank_imp"] == 1 and rows["HK"]["rank_mp"] == 2
    assert rows["HK"]["recommended_imp"] and not rows["HK"]["recommended_mp"]


def test_record_training_metadata():
    rec = make_record()
    t = rec["training"]
    assert t["algorithm_version"] == LEAD_ALGO_VERSION
    assert t["n_samples"] == 2
    assert set(t["modes"]) == set(TRAINING_MODES)
    for mode in TRAINING_MODES:
        assert t["modes"][mode]["ranking_metric"] == RANKING_METRICS[mode]
        assert t["modes"][mode]["goal"] == MODE_GOALS[mode]
    assert t["modes"]["IMP"]["imp_baseline"] == LEAD_IMP_BASELINE


# --------------------------------------------------------------------------
# persistence: pool schema, index mode flags, legacy migration
# --------------------------------------------------------------------------

def test_training_mode_persists_through_pool(tmp_path):
    rec = make_record()
    pool = ProblemPool(tmp_path)
    pool.add(rec)
    back = pool.get(rec["id"])
    assert back["training"]["modes"]["IMP"]["ranking_metric"] == "exp_imps"
    assert back["verdict"]["by_mode"]["IMP"]["recommended"] == "HK"
    idx = pool.rebuild_index()
    assert idx["problems"][0]["modes"] == ["MP", "IMP"]


def test_legacy_lead_records_stay_readable_and_mp_only(tmp_path):
    legacy = {"schema": 1, "kind": "lead", "id": "lead1-old",
              "created_at": "2025-01-01T00:00:00+00:00",
              "contract": "4HE", "classification": {"type": "lead_suit_game",
                                                    "difficulty_level": 3},
              "verdict": {"accepted": ["SA"], "table": []}}
    pool = ProblemPool(tmp_path)
    pool.add(legacy)                      # schema 1 still accepted
    assert supported_modes(pool.get("lead1-old")) == ["MP"]
    assert index_entry(legacy)["modes"] == ["MP"]
    # the backfill stamp makes them self-describing but never IMP-capable
    stamped = {**legacy, "training": legacy_training_block()}
    assert supported_modes(stamped) == ["MP"]
    assert stamped["training"]["algorithm_version"] == 1


def test_training_block_shapes():
    t = training_block(512, {"screen": 128, "confirm": 512, "used": 512})
    assert t["sample_counts"]["confirm"] == 512
    assert "imp_baseline" in t["modes"]["IMP"]
    assert "imp_baseline" not in t["modes"]["MP"]


def test_attempts_persist_training_mode():
    js = (__import__("pathlib").Path("bridge_trainer/web/bt-firebase.js")
          .read_text(encoding="utf-8"))
    assert "trainingMode" in js
    assert "rank_imp" in js and "rank_mp" in js
    assert "gradeLead(P, card, mode)" in js


# --------------------------------------------------------------------------
# UX: two sections, exact copy, emphasized metric, methodology note
# --------------------------------------------------------------------------

def test_home_page_has_mp_and_imp_cards():
    html = _index_html()
    assert "<b>Matchpoints</b>" in html
    assert "Prioritize maximum defensive tricks" in html
    assert "<b>IMPs</b>" in html
    assert "Prioritize score swings" in html
    assert "bt_lead_mode" in html          # the persisted selection


def test_mode_goals_shown():
    for page in (_index_html(), _lead_html()):
        assert "Goal: maximize expected defensive tricks." in page
        assert "Goal: maximize expected IMP value from the final score." in page


def test_lead_page_mode_banner_and_results():
    html = _lead_html()
    assert 'id="modebanner"' in html
    assert "MATCHPOINTS" in html           # prominent current-mode label
    assert 'id="resid"' in html            # your lead / recommended / rank
    # ranked table shows both metrics + set probability in BOTH modes,
    # with the active mode's metric emphasized
    assert "טריקים צפויים" in html
    assert "IMP צפוי" in html
    assert "סיכוי הכשלה" in html
    assert "emph" in html
    # legacy problems are never ranked by IMPs — they fall back with a notice
    assert "hasImpMetrics" in html
    assert 'MODE = "MP"; MODE_FALLBACK = true;' in html


def test_methodology_note_exact():
    note = ("Recommendations are based on sampled hidden-hand deals and "
            "double-dummy analysis. The active scoring mode determines how "
            "leads are ranked.")
    assert note in _lead_html()


def test_no_forbidden_wording_anywhere():
    pages = {
        "index": _index_html(), "problem": _problem_html(),
        "lead": _lead_html(), "dashboard": _dashboard_html(),
        "bt-firebase": (__import__("pathlib")
                        .Path("bridge_trainer/web/bt-firebase.js")
                        .read_text(encoding="utf-8")),
        "record": repr(make_record()),
    }
    for name, text in pages.items():
        low = text.lower()
        assert "beat the field" not in low, name
        assert "set the contract" not in low, name
        assert "setthecontract" not in low.replace(" ", ""), name


def test_exactly_two_lead_modes():
    assert TRAINING_MODES == ("MP", "IMP")
    html = _index_html()
    # the mode picker offers exactly the two cards
    assert html.count('class="modecard"') == 2
