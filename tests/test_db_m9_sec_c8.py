"""DB-M-9 (multi-device re-answer sync + orphan attempts) and SEC-C-8 (clear
local caches on sign-out). No Firestore emulator here, so the client wiring is
pinned with source assertions + a node syntax check on the dashboard JS.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from bridge_trainer.app.webapp import _DASHBOARD_JS, _SHARED_JS

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available")

_FB = (Path(__file__).resolve().parent.parent / "bridge_trainer" / "web"
       / "bt-firebase.js").read_text(encoding="utf-8")


# ---- DB-M-9: re-answer bumps ts (cross-device), first attempt stamps firstTs -
def test_first_attempt_writes_firstTs():
    # both the direct write and the pending-flush write persist firstTs
    assert "firstTs: serverTimestamp()" in _FB
    assert "firstTs: { seconds: nowSec }" in _FB


def test_reanswer_bumps_ts_not_just_lastTs():
    # the merge write for a re-answer must set ts (so incremental sync on
    # another device notices) alongside lastTs/attemptCount
    seg = _FB[_FB.index("re-answer: keep the first-attempt"):
              _FB.index("async resetAll")]
    assert "attemptCount: increment(1)" in seg
    assert "ts: serverTimestamp()" in seg
    assert "lastTs: serverTimestamp()" in seg


def test_dashboard_orders_by_firstTs_not_bumped_ts():
    # ordering uses firstMs (firstTs || ts), so a re-answer's bumped ts can't
    # reshuffle the streak/trend/recent lists
    assert "function firstMs(a)" in _DASHBOARD_JS
    assert "a.firstTs" in _DASHBOARD_JS
    assert "sort((a, b) => firstMs(b) - firstMs(a))" in _DASHBOARD_JS
    assert "sort((a, b) => firstMs(a) - firstMs(b))" in _DASHBOARD_JS


def test_dashboard_marks_orphan_attempts():
    # deleted-problem attempts render a non-link "removed" row using LIVE_IDS
    assert "let LIVE_IDS = null;" in _DASHBOARD_JS
    assert "LIVE_IDS = new Set(" in _DASHBOARD_JS
    assert "בעיה שהוסרה" in _DASHBOARD_JS
    assert "await window.BT.fetchIndex()" in _DASHBOARD_JS


# ---- SEC-A-6: esc() on user-owned attempt fields in the dashboard -----------
def test_dashboard_escapes_attempt_fields():
    seg = _DASHBOARD_JS[_DASHBOARD_JS.index("const missList"):]
    assert "esc(m.chosenCall)" in seg
    assert "esc(m.acceptedSet.join" in seg
    assert "esc(OUTCOME_HE[m.outcomeClass]" in seg


# ---- SEC-C-8: sign-out clears the per-user localStorage caches --------------
def test_signout_clears_local_caches():
    seg = _FB[_FB.index("onAuthStateChanged"):_FB.index('gate("signin")')]
    assert "const prevUid = USER && USER.uid;" in seg
    assert "localStorage.removeItem(cacheKey(prevUid))" in seg
    assert "localStorage.removeItem(pendingKey(prevUid))" in seg


@needs_node
def test_dashboard_js_still_parses():
    script = _SHARED_JS + "\n" + _DASHBOARD_JS
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        os.write(fd, script.encode("utf-8"))
        os.close(fd)
        res = subprocess.run(["node", "--check", path],
                             capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
    finally:
        os.unlink(path)
