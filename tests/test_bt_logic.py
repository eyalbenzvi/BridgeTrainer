"""Unit tests for bridge_trainer/web/bt-logic.js.

bt-logic.js is the side-effect-free half of the Firebase layer: it has no
firebase imports and no module-level initialization, so — unlike
bt-firebase.js (which calls initializeApp() at import) — it can be run under
plain node. We strip the ESM ``export`` keyword and concatenate the source
with test expressions, the same lightweight harness used for _SCORE_JS in
test_scoring_scale.py.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from importlib import resources

import pytest

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available")


def _logic_src() -> str:
    return (resources.files("bridge_trainer") / "web" / "bt-logic.js").read_text(
        encoding="utf-8")


def run_logic(exprs: list[str]):
    """Run bt-logic.js under node and evaluate each expression; returns the
    list of JSON-decoded results. ``export`` is stripped so the pure module
    loads as a plain script (it has no imports of its own)."""
    src = re.sub(r"^export\s+", "", _logic_src(), flags=re.M)
    script = (src +
              "\nconsole.log(JSON.stringify([" + ",".join(exprs) + "]));\n")
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        os.write(fd, script.encode("utf-8"))
        os.close(fd)
        res = subprocess.run(["node", path], capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
        return json.loads(res.stdout.strip().splitlines()[-1])
    finally:
        os.unlink(path)


def test_bt_logic_is_import_free():
    """The node harness (and the strip-export trick) only works if the module
    stays import-free and side-effect-free."""
    # strip line comments so prose mentioning "import"/"initializeApp" (this
    # module documents why it avoids them) doesn't trip the structural check.
    code = "\n".join(ln for ln in _logic_src().splitlines()
                     if not ln.lstrip().startswith("//"))
    assert not re.search(r"^\s*import\b", code, flags=re.M)  # no ESM import
    assert "initializeApp" not in code                       # no SDK init


@needs_node
def test_classify_sign_in_error_redirect_only_when_blocked():
    (blocked, unsupported, closed, cancelled, user_cancel,
     network, missing) = run_logic([
        "classifySignInError('auth/popup-blocked')",
        "classifySignInError('auth/operation-not-supported-in-this-environment')",
        "classifySignInError('auth/popup-closed-by-user')",
        "classifySignInError('auth/cancelled-popup-request')",
        "classifySignInError('auth/user-cancelled')",
        "classifySignInError('auth/network-request-failed')",
        "classifySignInError(undefined)",
    ])
    # only a genuinely blocked popup falls back to redirect
    assert blocked == "redirect"
    # "unsupported environment" would fail a redirect too — surface it instead
    assert unsupported == "error"
    # a user dismissing the popup is a normal cancellation, not a redirect
    assert closed == "cancel"
    assert cancelled == "cancel"
    assert user_cancel == "cancel"
    # anything else is a real error the caller should surface
    assert network == "error"
    assert missing == "error"


@needs_node
def test_merge_and_prune_pending_keep_unsynced_answers():
    keep, pruned, overlaid = run_logic([
        # a pending answer the server lacks is kept; one the server has is not
        "prunePending({a: {score: 90}, b: {score: 50}}, {b: {score: 50}})",
        # nothing pending -> empty
        "prunePending({}, {x: 1})",
        # merge overlays pending onto a fresh snapshot without clobbering it
        "mergePending({b: {score: 51}}, {a: {score: 90}, b: {score: 99}})",
    ])
    assert keep == {"a": {"score": 90}}          # only the unsynced one stays
    assert pruned == {}
    # server's b wins (not clobbered by pending); a is added back
    assert overlaid == {"b": {"score": 51}, "a": {"score": 90}}


@needs_node
def test_index_stamp_detects_pointer_changes():
    same, diff_count, diff_updated, diff_format, missing = run_logic([
        # identical stamps -> cache is fresh
        "sameStamp(indexStamp({updated_at:'t1',count:10,index_format:2}),"
        " indexStamp({updated_at:'t1',count:10,index_format:2}))",
        # any of count / updated_at / index_format changing -> stale
        "sameStamp(indexStamp({updated_at:'t1',count:10}),"
        " indexStamp({updated_at:'t1',count:11}))",
        "sameStamp(indexStamp({updated_at:'t1',count:10}),"
        " indexStamp({updated_at:'t2',count:10}))",
        "sameStamp(indexStamp({updated_at:'t1',count:10,index_format:1}),"
        " indexStamp({updated_at:'t1',count:10,index_format:2}))",
        # a null cached stamp is never 'same'
        "sameStamp(null, indexStamp({updated_at:'t1',count:10}))",
    ])
    assert same is True
    assert diff_count is False
    assert diff_updated is False
    assert diff_format is False      # index_format bump (T12) invalidates cache
    assert missing is False


@needs_node
def test_unwrap_firestore_inverts_firestore_safe():
    """unwrapFirestore (applied in getProblem) is the exact inverse of the
    producer's _firestore_safe nested-array wrapping (DB-M-8)."""
    from bridge_trainer.pool.firestore_store import _firestore_safe
    samples = [
        {"top_contracts": [["4SW", 231], ["3SW", 104]]},   # verdict shape
        {"a": {"b": [[1, 2], [3]]}},                        # deeper nesting
        [[[1]]],                                            # array of arrays
        # a real record fragment: flat arrays/scalars must round-trip untouched
        {"auction": ["P", "1D", "P"], "difficulty": 1.6,
         "candidates": [{"call": "3NT", "policy": 0.46}]},
        {"verdict": {"table": [{"bid": "4S",
                                "top_contracts": [["4SW", 5]]}]}},
    ]
    wrapped = [_firestore_safe(s) for s in samples]
    got = run_logic([f"unwrapFirestore({json.dumps(w)})" for w in wrapped])
    assert got == samples


@needs_node
def test_unwrap_firestore_idempotent_on_flat_records():
    """Static-file records were never wrapped; unwrapping them is a no-op."""
    flat = {"auction": ["P", "1H"], "candidates": [{"call": "2H"}],
            "top_contracts": [["4H", 3]]}   # already-flat pair list
    (once, twice) = run_logic([
        f"unwrapFirestore({json.dumps(flat)})",
        f"unwrapFirestore(unwrapFirestore({json.dumps(flat)}))",
    ])
    assert once == flat and twice == flat
