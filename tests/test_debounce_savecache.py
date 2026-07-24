"""PERF-F-7: the per-user attempt cache write is deferred to idle time and
coalesced (not run synchronously on every answer), with a synchronous flush on
pagehide/visibilitychange so the last answer survives a page navigation.

bt-firebase.js imports the Firebase SDK at module top, so it cannot be executed
under node; these are source-level guards on the wiring.
"""
from __future__ import annotations

from pathlib import Path

_FB = (Path(__file__).resolve().parent.parent / "bridge_trainer" / "web"
       / "bt-firebase.js").read_text(encoding="utf-8")


def test_scheduler_and_flush_exist():
    assert "function scheduleSaveCache(uid)" in _FB
    assert "function flushCache()" in _FB
    assert "requestIdleCallback" in _FB


def test_hot_answer_path_defers_the_cache_write():
    """record() must schedule (not synchronously saveCache) on both the
    first-attempt and re-answer branches — that was the jank source."""
    rec = _FB[_FB.index("async record("):_FB.index("async resetAll")]
    assert rec.count("scheduleSaveCache(uid)") == 2
    assert "saveCache(uid)" not in rec        # no synchronous write on the hot path


def test_pagehide_and_visibility_flush_synchronously():
    assert 'addEventListener("pagehide", flushCache)' in _FB
    assert 'visibilitychange' in _FB
    assert 'document.visibilityState === "hidden"' in _FB


def test_pending_queue_stays_synchronous():
    """savePending must NOT be deferred — a failed first-attempt save must be
    durably queued immediately, or a reconcile could lose it."""
    assert "scheduleSavePending" not in _FB
    # savePending is still called directly on the failure/flush paths
    assert "savePending(uid);" in _FB


def test_background_sync_still_writes_cache_immediately():
    """The reconcile/incremental paths keep the synchronous saveCache — they run
    off the hot path (requestIdleCallback) and their result must be durable."""
    sync = _FB[_FB.index("async function _syncAttempts"):
               _FB.index("// ---- grading")]
    assert "saveCache(uid)" in sync
