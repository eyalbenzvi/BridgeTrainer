"""ARCH-10/ARCH-11: `trainer pool` dispatches per-subcommand via set_defaults
(not one if-chain), the per-board constraint sampler lives in the engine layer,
and the stable maintenance scripts are reachable as `pool` subcommands.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from bridge_trainer.app import cli


def test_per_board_sampler_moved_to_engine():
    from bridge_trainer.engine.lead_samplers import PerBoardConstraintSampler
    assert PerBoardConstraintSampler.sampling_model == "auction_constraint_bands"
    assert hasattr(PerBoardConstraintSampler(), "sample")
    # the CLI no longer defines its own copy
    assert not hasattr(cli, "_PerBoardConstraintSampler")


def test_pool_ls_dispatches_and_runs_on_empty_pool(capsys):
    d = tempfile.mkdtemp()
    rc = cli.main(["pool", "ls", "--pool", d])
    assert rc == 0
    assert "0 problems" in capsys.readouterr().out


def test_pool_rm_dispatches(capsys):
    d = tempfile.mkdtemp()
    (Path(d) / "problems").mkdir()
    (Path(d) / "problems" / "p1.json").write_text(json.dumps(
        {"id": "p1", "schema": 1, "kind": "bidding",
         "classification": {}, "created_at": "2026-01-01T00:00:00"}))
    rc = cli.main(["pool", "rm", "p1", "--pool", d])
    assert rc == 0
    assert not (Path(d) / "problems" / "p1.json").exists()
    assert "1 removed" in capsys.readouterr().out


def test_each_pool_subcommand_routes_to_its_own_handler(monkeypatch):
    """Every subcommand has its OWN func (set_defaults), not a shared cmd_pool."""
    seen = {}

    def _mk(n):
        def _fn(a):
            seen["hit"] = n
            return 0
        return _fn
    for name in ("cmd_pool_ls", "cmd_pool_rm", "cmd_pool_add", "cmd_pool_push",
                 "cmd_pool_backfill_training", "cmd_pool_backfill_leads"):
        monkeypatch.setattr(cli, name, _mk(name))
    assert cli.main(["pool", "push", "--pool", "x"]) == 0
    assert seen["hit"] == "cmd_pool_push"


def test_maintenance_scripts_are_pool_subcommands(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "_run_pool_script",
                        lambda f, argv: calls.append((f, argv)) or 0)
    for sub, filename in (("classify", "classify_pool.py"),
                          ("reexplain", "reexplain_pool.py"),
                          ("backfill-notes", "backfill_bot_notes.py")):
        calls.clear()
        rc = cli.main(["pool", sub, "--some", "arg"])
        assert rc == 0
        assert calls == [(filename, ["--some", "arg"])]


def test_run_pool_script_missing_file_errors(capsys):
    rc = cli._run_pool_script("does_not_exist.py", [])
    assert rc == 2
    assert "not found" in capsys.readouterr().err
