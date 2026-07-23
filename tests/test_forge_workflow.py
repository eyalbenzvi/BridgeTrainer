"""The GitHub Actions lead-forge workflow: problem creation runs on GitHub,
with a mode (MP / IMP) choice and a problem count as the interface."""
from __future__ import annotations

from pathlib import Path

import yaml

WF = Path(".github/workflows/forge-leads.yml")


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
