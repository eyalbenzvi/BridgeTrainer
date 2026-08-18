"""Static guards for the analyze-requests workflow (no Actions runner in
tests — same approach as the other workflow tests)."""
from __future__ import annotations

import pathlib

import yaml

WF_PATH = (pathlib.Path(__file__).resolve().parent.parent
           / ".github" / "workflows" / "analyze-requests.yml")
WF_TEXT = WF_PATH.read_text(encoding="utf-8")
WF = yaml.safe_load(WF_TEXT)
STEPS = WF["jobs"]["worker"]["steps"]


def _step(name: str) -> dict:
    return next(s for s in STEPS if s.get("name") == name)


def test_runs_on_a_short_cron_and_manual_dispatch():
    on = WF[True] if True in WF else WF["on"]   # yaml parses `on:` as True
    assert on["schedule"][0]["cron"] == "*/5 * * * *"
    assert "workflow_dispatch" in on


def test_no_overlapping_runs():
    assert WF["concurrency"]["group"] == "analyze-requests"
    assert WF["concurrency"]["cancel-in-progress"] is False


def test_cheap_gate_runs_before_the_heavy_install():
    names = [s.get("name") for s in STEPS]
    assert names.index("Count pending requests") < \
        names.index("Install the engine (Ben + repo)")
    gate = _step("Count pending requests")
    assert "firebase-admin" in gate["run"]
    assert "setup_ben" not in gate["run"] and \
        "pip install -e" not in gate["run"]
    # the heavy steps are skipped when the queue is empty
    for heavy in ("Cache the Ben engine", "Install the engine (Ben + repo)",
                  "Process the queue"):
        assert _step(heavy)["if"] == "steps.gate.outputs.pending != '0'"


def test_uses_the_shared_service_account_secret_and_drops_it():
    assert "secrets.FIREBASE_SERVICE_ACCOUNT" in WF_TEXT
    drop = _step("Drop the key")
    assert drop["if"] == "always()"
    assert "rm -f sa-key.json" in drop["run"]


def test_worker_invocation_is_bounded():
    run = _step("Process the queue")["run"]
    assert "analyze-worker" in run
    assert "benv" in run              # runs under the Ben venv (py3.12+tf)
    assert "--max 6" in run
    assert WF["jobs"]["worker"]["timeout-minutes"] <= 30


def test_gate_script_does_not_import_the_heavy_package():
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "scripts" / "analysis_queue_gate.py").read_text(encoding="utf-8")
    imports = [ln for ln in src.splitlines()
               if ln.strip().startswith(("import ", "from "))]
    blob = "\n".join(imports)
    assert "bridge_trainer" not in blob
    assert "numpy" not in blob and "endplay" not in blob
