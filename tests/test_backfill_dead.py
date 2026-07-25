"""The dead-option backfill's vetting rule (pool/firestore_store.py).

Records forged before the tied-wins fix (engine/verdict.py, see
tests/test_verdict_dead.py) required an option to be the strictly-UNIQUE
per-sample winner, so a call that merely tied another call's winning
result was published dead and scored 0. `vet_dead_options` decides which
stored flags the migration drops: a flag is stale exactly when the
option's own evidence row shows it tying-or-beating the accepted call on
at least DEAD_SHARE of the layouts.
"""
from __future__ import annotations

from bridge_trainer.app import cli
from bridge_trainer.pool.firestore_store import vet_dead_options

# the reported problem's real published verdict (ben1-19f939859fa): 3S,
# 1.6 IMP from best and winning 52% of layouts vs the 4S winner, was
# flagged dead — while the strictly-worse Pass (-1.8 IMP) was not
REPORTED = {
    "accepted": "4S", "toss_up": False,
    "table": [
        {"bid": "4S", "ev_imp_vs_top": 1.58, "ci": 0.63,
         "p_gain": 0.412, "p_loss": 0.52, "p_push": 0.068},
        {"bid": "3S", "ev_imp_vs_top": -1.58, "ci": 0.63,
         "p_gain": 0.52, "p_loss": 0.412, "p_push": 0.068},
        {"bid": "P", "ev_imp_vs_top": -1.77, "ci": 0.68,
         "p_gain": 0.529, "p_loss": 0.471, "p_push": 0},
    ],
    "dead_options": [{"bid": "3S", "best_share": 0.0039}],
}


def test_contradicted_flag_is_stale():
    kept, stale = vet_dead_options(REPORTED)
    assert kept == [] and stale == ["3S"]


def test_confirmed_flag_is_kept():
    v = {
        "table": [
            {"bid": "4H", "ev_imp_vs_top": 2.0, "p_gain": 0.6, "p_push": 0.1},
            {"bid": "X", "ev_imp_vs_top": -6.0, "p_gain": 0, "p_push": 0},
        ],
        "dead_options": [{"bid": "X", "best_share": 0.0}],
    }
    kept, stale = vet_dead_options(v)
    assert kept == v["dead_options"] and stale == []


def test_flag_without_evidence_row_is_kept():
    """No row to contradict the flag -> the migration must not guess."""
    v = {"table": [{"bid": "4H", "p_gain": 0.6, "p_push": 0.1}],
         "dead_options": [{"bid": "5C"}]}
    kept, stale = vet_dead_options(v)
    assert kept == v["dead_options"] and stale == []


def test_rows_missing_probabilities_are_kept():
    """Legacy rows without p_gain/p_push can't prove the option alive."""
    v = {"table": [{"bid": "P", "ev_imp_vs_top": -5.0, "ci": 1.0}],
         "dead_options": [{"bid": "P"}]}
    kept, stale = vet_dead_options(v)
    assert kept == v["dead_options"] and stale == []


def test_empty_and_missing_dead_options():
    assert vet_dead_options({"table": []}) == ([], [])
    assert vet_dead_options({"dead_options": []}) == ([], [])


def test_cli_wires_backfill_dead(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "cmd_pool_backfill_dead",
                        lambda a: seen.update(hit=True, dry=a.dry_run) or 0)
    assert cli.main(["pool", "backfill-dead", "--dry-run"]) == 0
    assert seen == {"hit": True, "dry": True}
