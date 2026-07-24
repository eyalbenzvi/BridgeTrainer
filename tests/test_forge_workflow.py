"""The GitHub Actions lead-forge workflow: problem creation runs on GitHub,
with a mode (MP / IMP) choice and a problem count as the interface."""
from __future__ import annotations

from pathlib import Path

import yaml

WF = Path(".github/workflows/forge-leads.yml")
SCRIPT = Path("scripts/generate_and_push_leads.sh")


def _load():
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


def test_workflow_is_manually_dispatchable_with_mode_and_count():
    wf = _load()
    # YAML 1.1 parses the `on:` key as boolean True
    inputs = wf[True]["workflow_dispatch"]["inputs"]
    assert inputs["mode"]["type"] == "choice"
    assert inputs["mode"]["options"] == ["MP", "IMP"]
    assert inputs["count"]["required"] is True


def test_workflow_runs_the_shared_forge_script_with_the_secret():
    text = WF.read_text(encoding="utf-8")
    assert "scripts/generate_and_push_leads.sh" in text
    assert "secrets.FIREBASE_SERVICE_ACCOUNT" in text
    assert "MODE: ${{ inputs.mode }}" in text
    # ben needs python 3.12 (vendored DDS binary)
    assert 'python-version: "3.12"' in text


def test_pushes_are_serialized_not_cancelled():
    wf = _load()
    assert wf["concurrency"]["cancel-in-progress"] is False


def test_hourly_schedule_forges_ten_of_each_mode():
    wf = _load()
    assert [s["cron"] for s in wf[True]["schedule"]] == ["0 * * * *"]
    text = WF.read_text(encoding="utf-8")
    # each firing runs one MP batch then one IMP batch...
    assert "for M in MP IMP" in text
    # ...of 10 problems each by default (repo variable FORGE_COUNT overrides)
    assert '"${FORGE_COUNT:-10}"' in text
    assert "vars.FORGE_COUNT" in text
    # hour-based seeds so consecutive hours forge fresh boards
    assert "HOUR=$(( $(date +%s) / 3600 ))" in text


def test_default_seed_is_unique_per_run_not_flattened_to_a_day():
    """A manual dispatch with a blank seed must NOT reuse the same boards on
    every run of the same day. The old day-flattened default (date +%s / 86400)
    produced identical problem ids each day, so the Firestore push skipped them
    all ("uploaded 0") and the pool never grew. The default must vary per run."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "SEED=" in text
    # the per-day flattening must be gone from the seed default...
    assert "/ 86400" not in text
    # ...and the default must be a per-run (epoch-second) value.
    assert 'SEED="${SEED:-$(date +%s)000}"' in text
