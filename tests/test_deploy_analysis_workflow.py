"""Static guards: the Ben Cloud Run deploy + the Actions worker's Ben use."""
from __future__ import annotations

import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEPLOY = yaml.safe_load((ROOT / ".github" / "workflows"
                         / "deploy-functions.yml").read_text(encoding="utf-8"))
WORKER_WF = (ROOT / ".github" / "workflows"
             / "analyze-requests.yml").read_text(encoding="utf-8")
DOCKER = (ROOT / "Dockerfile").read_text(encoding="utf-8")
SETUP = (ROOT / "scripts" / "setup_ben.sh").read_text(encoding="utf-8")


def _steps():
    return DEPLOY["jobs"]["deploy"]["steps"]


def test_deploy_targets_cloud_run_in_the_firestore_region():
    assert DEPLOY["env"]["REGION"] == "me-west1"
    run_step = next(s for s in _steps()
                    if s.get("name") == "Deploy to Cloud Run")
    assert "--memory 2Gi" in run_step["run"]
    assert "--concurrency 1" in run_step["run"]
    assert "--no-allow-unauthenticated" in run_step["run"]


def test_build_streams_its_logs_into_the_actions_job():
    # `gcloud run deploy --source` hides docker errors behind "check build
    # logs"; an explicit `gcloud builds submit` streams them into the job.
    build = next(s for s in _steps()
                 if s.get("name") == "Build the container image")
    assert "gcloud builds submit" in build["run"]
    deploy = next(s for s in _steps() if s.get("name") == "Deploy to Cloud Run")
    assert "--image" in deploy["run"] and "--source" not in deploy["run"]


def test_dockerfile_avoids_source_only_pins_on_the_slim_base():
    # psutil==5.9.0 (Ben's pin) has no cp312 wheel; the slim image has no
    # compiler, so the build must bump it to a wheel-backed release.
    assert "psutil==5.9.8" in DOCKER
    assert re.search(r"sed .*psutil", DOCKER)


def test_deploy_wires_the_firestore_trigger_and_kills_the_old_function():
    text = (ROOT / ".github" / "workflows"
            / "deploy-functions.yml").read_text(encoding="utf-8")
    assert "google.cloud.firestore.document.v1.created" in text
    assert "document=analysis_requests/{id}" in text
    assert "gcloud functions delete analyze_request" in text


def test_dockerfile_pins_the_same_ben_commit_as_setup_script():
    setup_commit = re.search(r'BEN_COMMIT="([0-9a-f]{40})"', SETUP).group(1)
    docker_commit = re.search(r"ARG BEN_COMMIT=([0-9a-f]{40})",
                              DOCKER).group(1)
    assert docker_commit == setup_commit
    assert "ben_rollout_context.patch" in DOCKER
    assert "bridge_trainer.analysis.cloudrun" in DOCKER


def test_worker_workflow_installs_and_uses_ben():
    assert "scripts/setup_ben.sh" in WORKER_WF
    assert "~/benv/bin/python -m bridge_trainer.app.cli analyze-worker" \
        in WORKER_WF
    assert "actions/cache" in WORKER_WF
    # the cheap empty-queue gate still avoids the heavy install
    assert "steps.gate.outputs.pending != '0'" in WORKER_WF


def test_cloudrun_subject_parsing():
    from bridge_trainer.analysis.cloudrun import _request_id
    assert _request_id("documents/analysis_requests/abc123") == "abc123"
    assert _request_id("//firestore/.../documents/analysis_requests/x") == "x"
    assert _request_id("documents/other/x") is None
    assert _request_id(None) is None
