"""The GitHub Actions forge workflows: problem creation runs on GitHub.

The lead forge is split one-workflow-per-mode (forge-leads-mp.yml /
forge-leads-imp.yml) so each mode gets its own schedule slot, log and failure
signal. The three forge workflows are staggered 40 minutes apart inside a
2-hour cycle: bidding :00, leads-MP :40, leads-IMP +1:20 — each forging 15
problems per firing.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WF_MP = Path(".github/workflows/forge-leads-mp.yml")
WF_IMP = Path(".github/workflows/forge-leads-imp.yml")
WF_BIDDING = Path(".github/workflows/forge-bidding.yml")
SCRIPT = Path("scripts/generate_and_push_leads.sh")

LEAD_WORKFLOWS = [WF_MP, WF_IMP]


def _load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_the_combined_lead_workflow_is_gone():
    """One file per mode — the old both-modes-in-one-job workflow must not
    linger, or every lead batch would be forged twice."""
    assert not Path(".github/workflows/forge-leads.yml").exists()


@pytest.mark.parametrize("wf", LEAD_WORKFLOWS)
def test_lead_workflow_is_manually_dispatchable_with_a_count(wf):
    # YAML 1.1 parses the `on:` key as boolean True
    inputs = _load(wf)[True]["workflow_dispatch"]["inputs"]
    assert inputs["count"]["required"] is True
    # the mode is fixed by the workflow, so it is no longer a dispatch input
    assert "mode" not in inputs


@pytest.mark.parametrize("wf,mode", [(WF_MP, "MP"), (WF_IMP, "IMP")])
def test_lead_workflow_pins_its_mode_and_runs_the_shared_script(wf, mode):
    text = wf.read_text(encoding="utf-8")
    assert "scripts/generate_and_push_leads.sh" in text
    assert "secrets.FIREBASE_SERVICE_ACCOUNT" in text
    # MODE is job-level env, not a dispatch input: the file *is* the mode
    assert f"MODE: {mode}" in text
    # ben needs python 3.12 (vendored DDS binary)
    assert 'python-version: "3.12"' in text


@pytest.mark.parametrize("wf", LEAD_WORKFLOWS + [WF_BIDDING])
def test_pushes_are_serialized_not_cancelled(wf):
    assert _load(wf)["concurrency"]["cancel-in-progress"] is False


@pytest.mark.parametrize("wf,group", [(WF_MP, "forge-leads-mp"),
                                      (WF_IMP, "forge-leads-imp")])
def test_each_mode_has_its_own_concurrency_group(wf, group):
    """A slow MP run must not starve IMP (and vice versa). Concurrent pool
    pushes are safe: the index update is an optimistic-locked read-union-write
    that retries on conflict."""
    assert _load(wf)["concurrency"]["group"] == group


def test_the_three_forges_are_staggered_forty_minutes_apart():
    """bidding :00 -> leads-MP :40 -> leads-IMP +1:20, every 2 hours."""
    assert [s["cron"] for s in _load(WF_BIDDING)[True]["schedule"]] \
        == ["0 */2 * * *"]
    assert [s["cron"] for s in _load(WF_MP)[True]["schedule"]] \
        == ["40 */2 * * *"]
    assert [s["cron"] for s in _load(WF_IMP)[True]["schedule"]] \
        == ["20 1-23/2 * * *"]


@pytest.mark.parametrize("wf,var", [
    (WF_MP, "FORGE_LEADS_MP_COUNT"),
    (WF_IMP, "FORGE_LEADS_IMP_COUNT"),
    (WF_BIDDING, "FORGE_BIDDING_COUNT"),
])
def test_each_scheduled_firing_forges_fifteen_problems(wf, var):
    text = wf.read_text(encoding="utf-8")
    assert '"${FORGE_COUNT:-15}"' in text      # default...
    assert f"vars.{var}" in text               # ...overridable per workflow


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
