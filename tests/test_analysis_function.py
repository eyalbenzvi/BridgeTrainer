"""Static guards for the Cloud Functions fast path (no firebase_functions
package in the test env — the function module is checked as text, its
shared logic is unit-tested in test_analysis_worker.py)."""
from __future__ import annotations

import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAIN = (ROOT / "functions" / "main.py").read_text(encoding="utf-8")
REQS = (ROOT / "functions" / "requirements.txt").read_text(encoding="utf-8")
FBJSON = (ROOT / "firebase.json").read_text(encoding="utf-8")
DEPLOY = yaml.safe_load(
    (ROOT / ".github" / "workflows" / "deploy-functions.yml")
    .read_text(encoding="utf-8"))


def test_trigger_watches_the_request_collection():
    assert 'document="analysis_requests/{req_id}"' in MAIN
    assert "on_document_created" in MAIN


def test_function_reuses_the_shared_worker_entry_point():
    # one implementation for both compute paths: the function must go
    # through handle_request (CAS claim + process), never its own logic
    assert "from bridge_trainer.analysis.worker import handle_request" in MAIN
    assert "handle_request(" in MAIN


def test_function_cost_and_safety_bounds():
    assert "max_instances=2" in MAIN
    assert "concurrency=1" in MAIN
    assert "timeout_sec=540" in MAIN


def test_heavy_imports_stay_inside_the_handler():
    # the CLI's deploy-time discovery imports this module; the engine
    # (numpy/endplay) must not load at module level
    head = MAIN[:MAIN.index("def analyze_request")]
    module_imports = [ln for ln in head.splitlines()
                      if ln.strip().startswith(("import ", "from "))]
    assert not any("bridge_trainer" in ln for ln in module_imports)
    assert any("firebase_functions" in ln for ln in module_imports)


def test_engine_installed_from_the_public_repo():
    assert "git+https://github.com/eyalbenzvi/BridgeTrainer.git@main" in REQS
    assert "firebase-functions" in REQS and "firebase-admin" in REQS


def test_firebase_json_targets_python_functions():
    assert '"source": "functions"' in FBJSON
    assert '"runtime": "python311"' in FBJSON


def test_deploy_workflow_is_manual_and_bounded():
    on = DEPLOY[True] if True in DEPLOY else DEPLOY["on"]
    assert on == "workflow_dispatch" or "workflow_dispatch" in on
    steps = DEPLOY["jobs"]["deploy"]["steps"]
    names = [s.get("name") for s in steps]
    assert names.index("Prepare the functions venv (CLI discovery)") < \
        names.index("Deploy")
    deploy = next(s for s in steps if s.get("name") == "Deploy")
    assert "--only functions" in deploy["run"]
    assert "--project bridgetrainer-3c759" in deploy["run"]
    drop = next(s for s in steps if s.get("name") == "Drop the key")
    assert drop["if"] == "always()"
