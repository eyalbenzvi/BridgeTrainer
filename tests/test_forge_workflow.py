"""The GitHub Actions forge workflows: problem creation runs on GitHub.

Production shape — one continuous factory. `forge-cycle.yml` owns the schedule
and calls three reusable stage workflows back-to-back, each forging a batch of
15:

    bidding (~11 min) -> leads MP (~50 min) -> leads IMP (~32 min)   = ~93 min

The stages chain on `needs:`, so each starts when the previous one finishes
rather than on a clock. The cycle schedule fires every 90 minutes — shorter
than the cycle — so a run is always queued and the factory never idles.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WF_DIR = Path(".github/workflows")
WF_CYCLE = WF_DIR / "forge-cycle.yml"
WF_MP = WF_DIR / "forge-leads-mp.yml"
WF_IMP = WF_DIR / "forge-leads-imp.yml"
WF_BIDDING = WF_DIR / "forge-bidding.yml"
SCRIPT = Path("scripts/generate_and_push_leads.sh")

# bidding first (cheapest), then the two lead modes — the cycle order
STAGES = [WF_BIDDING, WF_MP, WF_IMP]
LEAD_WORKFLOWS = [WF_MP, WF_IMP]

# observed average wall-clock per stage; the cycle schedule is derived from it
OBSERVED_MINUTES = {WF_BIDDING: 11, WF_MP: 50, WF_IMP: 32}


def _load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _on(path: Path):
    # YAML 1.1 parses the `on:` key as boolean True
    return _load(path)[True]


def _cron_minutes_of_day(path: Path) -> list[int]:
    """Every minute-of-day a workflow's crons fire. Only the restricted forms
    this repo uses are expanded: literal minute + `*`/`*/n`/`a-b/n` hours."""
    fires = []
    for entry in _on(path)["schedule"]:
        minute, hours, dom, month, dow = entry["cron"].split()
        assert (dom, month, dow) == ("*", "*", "*"), entry
        if hours == "*":
            hrs = range(24)
        elif hours.startswith("*/"):
            hrs = range(0, 24, int(hours[2:]))
        else:
            span, _, step = hours.partition("/")
            lo, _, hi = span.partition("-")
            hrs = range(int(lo), int(hi) + 1, int(step) if step else 1)
        fires += [h * 60 + int(minute) for h in hrs]
    return sorted(fires)


def test_the_combined_lead_workflow_is_gone():
    """One file per mode — the old both-modes-in-one-job workflow must not
    linger, or every lead batch would be forged twice."""
    assert not (WF_DIR / "forge-leads.yml").exists()


def test_the_cycle_is_the_only_scheduled_forge():
    """Two schedules driving the same forge would double-run it. The stages are
    reusable workflows plus a manual escape hatch, nothing more."""
    for stage in STAGES:
        assert sorted(_on(stage)) == ["workflow_call", "workflow_dispatch"], stage
    assert sorted(_on(WF_CYCLE)) == ["schedule", "workflow_dispatch"]


def test_the_cycle_runs_the_three_stages_strictly_in_sequence():
    """Back-to-back, not in parallel and not on a clock: each stage `needs:` the
    previous one, so it starts the moment that one finishes."""
    jobs = _load(WF_CYCLE)["jobs"]
    assert list(jobs) == ["bidding", "leads-mp", "leads-imp"]
    assert jobs["bidding"].get("needs") is None
    assert jobs["leads-mp"]["needs"] == "bidding"
    assert jobs["leads-imp"]["needs"] == "leads-mp"
    for name, stage in zip(jobs, STAGES):
        assert jobs[name]["uses"] == f"./{stage.as_posix()}"
        # the stages need FIREBASE_SERVICE_ACCOUNT (and bidding a models token)
        assert jobs[name]["secrets"] == "inherit"


def test_a_failed_stage_does_not_stop_the_factory():
    """A bidding failure must not cost the cycle its two lead batches; the
    failure surfaces through the stage's own issue notification instead."""
    jobs = _load(WF_CYCLE)["jobs"]
    for name in ("leads-mp", "leads-imp"):
        assert jobs[name]["if"] == "${{ !cancelled() }}", name


def test_the_cycle_fires_every_ninety_minutes_so_it_never_idles():
    """The cadence must be uniform and no longer than the real cycle: a firing
    that lands mid-cycle sits pending and starts the instant the cycle ends, so
    the forges are always working. Slower than the cycle would leave dead air."""
    fires = _cron_minutes_of_day(WF_CYCLE)
    gaps = {b - a for a, b in zip(fires, fires[1:])}
    gaps.add(1440 - fires[-1] + fires[0])       # the wrap past midnight
    assert gaps == {90}, f"uneven cadence: {sorted(gaps)}"
    assert len(fires) == 16
    assert min(gaps) <= sum(OBSERVED_MINUTES.values())


def test_the_cycle_grants_every_stage_the_scope_it_needs():
    """A reusable workflow's token is capped by the caller, so the cycle must
    grant the union: issues for the lead forges' failure notice, models for
    bidding's classifier."""
    ceiling = _load(WF_CYCLE)["permissions"]
    for stage in STAGES:
        for scope, level in _load(stage)["permissions"].items():
            assert ceiling.get(scope) == level, (stage, scope)


@pytest.mark.parametrize("wf", STAGES, ids=lambda p: p.stem)
def test_a_stage_forges_fifteen_problems_when_the_cycle_calls_it(wf):
    """The cycle passes no count; a blank count selects the batch size. It must
    not fall through to the script's own much larger default."""
    text = wf.read_text(encoding="utf-8")
    assert 'if [ -z "$COUNT" ]; then' in text
    assert '"${FORGE_COUNT:-15}"' in text
    # ...and the blank count must not trip the dispatch-only validation
    steps = _load(wf)["jobs"]["forge"]["steps"]
    validate = [s for s in steps if s.get("name") == "Validate inputs"][0]
    assert validate["if"] == "inputs.count != ''"


@pytest.mark.parametrize("wf,var", [
    (WF_BIDDING, "FORGE_BIDDING_COUNT"),
    (WF_MP, "FORGE_LEADS_MP_COUNT"),
    (WF_IMP, "FORGE_LEADS_IMP_COUNT"),
])
def test_batch_size_is_tunable_per_stage_without_editing_yaml(wf, var):
    assert f"vars.{var}" in wf.read_text(encoding="utf-8")


@pytest.mark.parametrize("wf", STAGES, ids=lambda p: p.stem)
def test_a_stage_is_still_runnable_by_hand_for_a_one_off_batch(wf):
    inputs = _on(wf)["workflow_dispatch"]["inputs"]
    assert inputs["count"]["required"] is True
    # the blank-means-cycle-batch contract the stage's shell relies on
    assert _on(wf)["workflow_call"]["inputs"]["count"]["default"] == ""


@pytest.mark.parametrize("wf,mode", [(WF_MP, "MP"), (WF_IMP, "IMP")])
def test_lead_stage_pins_its_mode_and_runs_the_shared_script(wf, mode):
    text = wf.read_text(encoding="utf-8")
    assert "scripts/generate_and_push_leads.sh" in text
    assert "secrets.FIREBASE_SERVICE_ACCOUNT" in text
    # MODE is job-level env, not an input: the file *is* the mode
    assert _load(wf)["jobs"]["forge"]["env"]["MODE"] == mode
    assert "mode" not in _on(wf)["workflow_dispatch"]["inputs"]
    # ben needs python 3.12 (vendored DDS binary)
    assert 'python-version: "3.12"' in text


@pytest.mark.parametrize("wf", STAGES + [WF_CYCLE], ids=lambda p: p.stem)
def test_runs_are_serialized_not_cancelled(wf):
    assert _load(wf)["concurrency"]["cancel-in-progress"] is False


@pytest.mark.parametrize("wf,group", [(WF_BIDDING, "forge-bidding"),
                                      (WF_MP, "forge-leads-mp"),
                                      (WF_IMP, "forge-leads-imp"),
                                      (WF_CYCLE, "forge-cycle")])
def test_each_stage_has_its_own_concurrency_group(wf, group):
    """Per-stage groups keep a manual batch from racing the cycle's stage,
    while letting different stages overlap: concurrent pool pushes are safe
    (the index update is an optimistic-locked read-union-write that retries)."""
    assert _load(wf)["concurrency"]["group"] == group


def test_default_seed_is_unique_per_run_not_flattened_to_a_day():
    """A run with a blank seed must NOT reuse the same boards on every run of
    the same day. The old day-flattened default (date +%s / 86400) produced
    identical problem ids each day, so the Firestore push skipped them all
    ("uploaded 0") and the pool never grew. The default must vary per run."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "SEED=" in text
    # the per-day flattening must be gone from the seed default...
    assert "/ 86400" not in text
    # ...and the default must be a per-run (epoch-second) value.
    assert 'SEED="${SEED:-$(date +%s)000}"' in text
