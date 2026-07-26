"""DB-O-7: the forge workflow notifies on failure, and the monitoring setup is
documented. (The Cloud Monitoring/budget alerts are console config, not code —
only their documentation is asserted here.)"""
from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
# every stage of the forge cycle notifies: with the three running back-to-back
# around the clock, a silent failure in any one of them quietly stops a third of
# the pool from growing.
_WFS = [_ROOT / ".github" / "workflows" / f"forge-{n}.yml"
        for n in ("bidding", "leads-mp", "leads-imp")]
_DOC = _ROOT / "docs" / "firebase_setup.md"


@pytest.mark.parametrize("path", _WFS, ids=lambda p: p.name)
def test_forge_workflow_notifies_on_failure(path):
    wf = path.read_text(encoding="utf-8")
    assert "issues: write" in wf                 # permission to open an issue
    assert "Notify on failure" in wf
    assert "if: failure()" in wf
    assert "gh issue" in wf                       # creates/comments an issue
    # it de-dupes onto one tracking issue rather than spamming a new one
    assert "gh issue list" in wf


def test_monitoring_documented():
    doc = _DOC.read_text(encoding="utf-8")
    assert "Monitoring & alerts" in doc
    assert "document/read_count" in doc
    assert "Budget alert" in doc
