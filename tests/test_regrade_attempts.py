"""Attempt regrading (pool/firestore_store.py regrade_attempts).

Stored attempts are grading SNAPSHOTS; when problem docs change (e.g. the
dead-option backfill), the history goes stale. The regrade recomputes the
derived fields with the client's own scoring module under node and rewrites
only real changes — the user's guess and timestamps are never touched.
"""
from __future__ import annotations

import shutil

import pytest

from bridge_trainer.app import cli
from bridge_trainer.pool.firestore_store import (changed_grade_fields,
                                                 recompute_attempt_grades)

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available")

# ben1-19f939859fa as published AFTER the dead-option backfill (real
# numbers). A user who answered 3S while the stale dead flag was live
# carries score 0 / outcomeClass "dead" in their history.
PROBLEM = {
    "id": "ben1-19f939859fa",
    "kind": "bidding",
    "created_at": "2026-07-24T10:11:30+00:00",
    "classification": {"type": "invite_or_game", "difficulty_level": 4},
    "quality": {"stakes": 6.69, "n_samples": 512},
    "candidates": [{"call": "3S", "policy": 0.52},
                   {"call": "4S", "policy": 0.293},
                   {"call": "P", "policy": 0.11}],
    "verdict": {
        "accepted": "4S", "toss_up": False, "toss_up_set": [],
        "dead_options": [],
        "table": [
            {"bid": "4S", "ev_imp_vs_top": 1.58, "ci": 0.63,
             "p_gain": 0.412, "p_loss": 0.52, "p_push": 0.068},
            {"bid": "3S", "ev_imp_vs_top": -1.58, "ci": 0.63,
             "p_gain": 0.52, "p_loss": 0.412, "p_push": 0.068},
            {"bid": "P", "ev_imp_vs_top": -1.77, "ci": 0.68,
             "p_gain": 0.529, "p_loss": 0.471, "p_push": 0},
        ],
    },
}

LEAD = {
    "id": "lead1-test",
    "kind": "lead",
    "created_at": "2026-07-01T00:00:00+00:00",
    "classification": {"type": "trump", "difficulty_level": 2},
    "verdict": {
        "accepted": ["SK"],
        "by_mode": {"MP": {"accepted": ["SK"], "recommended": "SK"},
                    "IMP": {"accepted": ["HA"], "recommended": "HA"}},
        "table": [
            {"card": "SK", "avg_def_tricks": 4.1, "vs_best": 0.0,
             "ben_softmax": 0.5, "exp_imps": 0.5, "rank_mp": 1, "rank_imp": 2},
            {"card": "HA", "avg_def_tricks": 3.8, "vs_best": -0.3,
             "ben_softmax": 0.3, "exp_imps": 1.1, "rank_mp": 2, "rank_imp": 1},
        ],
    },
}

PROBLEMS = {p["id"]: p for p in (PROBLEM, LEAD)}


@needs_node
def test_stale_dead_attempt_is_regraded():
    out = recompute_attempt_grades(PROBLEMS, [
        {"key": "u1", "problemId": PROBLEM["id"], "action": "3S"}])["u1"]
    # what the client would store for the same answer today
    assert out["score"] == 83 and out["outcomeClass"] == "suboptimal"
    assert out["correct"] is False
    assert out["gradedCost"] == pytest.approx(1.58)
    assert out["acceptedSet"] == ["4S"]
    assert out["problemVersion"] == PROBLEM["created_at"]
    assert out["type"] == "invite_or_game" and out["difficultyLevel"] == 4
    # the stale stored snapshot -> exactly the fields that must change
    stored = {"chosenCall": "3S", "score": 0, "outcomeClass": "dead",
              "correct": False, "gradedCost": 1.58, "acceptedSet": ["4S"],
              "problemVersion": PROBLEM["created_at"],
              "type": "invite_or_game", "difficultyLevel": 4}
    diff = changed_grade_fields(stored, out)
    assert diff == {"score": 83, "outcomeClass": "suboptimal"}


@needs_node
def test_current_attempt_is_untouched():
    out = recompute_attempt_grades(PROBLEMS, [
        {"key": "u2", "problemId": PROBLEM["id"], "action": "4S"}])["u2"]
    stored = {"score": 100, "correct": True, "outcomeClass": "winner",
              "gradedCost": 0, "acceptedSet": ["4S"],
              "problemVersion": PROBLEM["created_at"],
              "type": "invite_or_game", "difficultyLevel": 4}
    assert changed_grade_fields(stored, out) == {}


@needs_node
def test_lead_regrade_is_mode_aware():
    mp, imp = recompute_attempt_grades(PROBLEMS, [
        {"key": "mp", "problemId": LEAD["id"], "action": "HA", "mode": "MP"},
        {"key": "imp", "problemId": LEAD["id"], "action": "HA", "mode": "IMP"},
    ]).values()
    assert mp["correct"] is False and mp["gradedCost"] == pytest.approx(0.3)
    assert mp["chosenRank"] == 2 and mp["rankingMetric"] == "exp_def_tricks"
    assert mp["recommendedLead"] == "SK"
    assert imp["correct"] is True and imp["score"] == 100
    assert imp["outcomeClass"] == "winner" and imp["recommendedLead"] == "HA"


@needs_node
def test_deleted_problem_is_excluded():
    out = recompute_attempt_grades(PROBLEMS, [
        {"key": "gone", "problemId": "ben1-deleted", "action": "3S"},
        {"key": "u1", "problemId": PROBLEM["id"], "action": "3S"}])
    assert set(out) == {"u1"}


def test_changed_grade_fields_semantics():
    # float noise is not a change; bools compare by identity, not 1 == True
    assert changed_grade_fields({"gradedCost": 1.58},
                                {"gradedCost": 1.58 + 1e-12}) == {}
    assert changed_grade_fields({"correct": 1}, {"correct": True}) \
        == {"correct": True}
    # a missing stored field (legacy attempt without score) IS a change
    assert changed_grade_fields({}, {"score": 83}) == {"score": 83}
    assert changed_grade_fields({"acceptedSet": ["4S"]},
                                {"acceptedSet": ["4S"]}) == {}


def test_cli_wires_regrade_attempts(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "cmd_pool_regrade_attempts",
                        lambda a: seen.update(hit=True, dry=a.dry_run) or 0)
    assert cli.main(["pool", "regrade-attempts", "--dry-run"]) == 0
    assert seen == {"hit": True, "dry": True}


# ---- orphan attempts: history on problems that no longer exist -------------

def test_orphan_attempt_keys_selects_only_the_dead_ones():
    from bridge_trainer.pool.firestore_store import orphan_attempt_keys

    live = {"ben1-live", "lead1-live"}
    attempts = [
        {"key": "users/u/attempts/ben1-live", "problemId": "ben1-live"},
        {"key": "users/u/attempts/lead1-live", "problemId": "lead1-live"},
        {"key": "users/u/attempts/ben1-gone", "problemId": "ben1-gone"},
        {"key": "users/u/attempts/no-id"},          # legacy doc, no field
    ]
    assert orphan_attempt_keys(live, attempts) == [
        "users/u/attempts/ben1-gone", "users/u/attempts/no-id"]
    # an empty pool would orphan everything — the caller must pass real ids
    assert len(orphan_attempt_keys(set(), attempts)) == 4


def test_cli_wires_purge_orphan_attempts(monkeypatch):
    from bridge_trainer.app import cli

    seen = {}
    monkeypatch.setattr(cli, "cmd_pool_purge_orphan_attempts",
                        lambda a: seen.update(hit=True, dry=a.dry_run) or 0)
    assert cli.main(["pool", "purge-orphan-attempts", "--dry-run"]) == 0
    assert seen == {"hit": True, "dry": True}
