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
    # only a genuinely blocked/unsupported popup falls back to redirect
    assert blocked == "redirect"
    assert unsupported == "redirect"
    # a user dismissing the popup is a normal cancellation, not a redirect
    assert closed == "cancel"
    assert cancelled == "cancel"
    assert user_cancel == "cancel"
    # anything else is a real error the caller should surface
    assert network == "error"
    assert missing == "error"
