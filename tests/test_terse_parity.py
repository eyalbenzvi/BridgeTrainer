"""terse() JS <-> terse_meaning() Python parity, and the pts fallback (BUG-6).

terse() lives in the tail of _SHARED_JS, which runs applyTheme()/initChrome()
at load — not DOM-free like _SCORE_JS. So we evaluate the whole _SHARED_JS
under node behind a minimal DOM stub (readyState="loading" defers initChrome;
localStorage/documentElement are no-ops), then call terse().

The Python terse_meaning gained a pts fallback (explain.py) that the JS lacked;
this pins the JS branch and checks the two implementations agree on cards whose
rendering is plain text (hcp/pts ranges), where the glyph HTML doesn't differ.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile

import pytest

from bridge_trainer.app.webapp import _SHARED_JS
from bridge_trainer.engine.explain import terse_meaning

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available")

_DOM_STUB = r"""
const noop = () => {};
globalThis.localStorage = { getItem: () => null, setItem: noop, removeItem: noop };
globalThis.document = {
  documentElement: { setAttribute: noop, removeAttribute: noop,
                     classList: { add: noop, remove: noop } },
  body: { dataset: {}, insertBefore: noop, firstChild: null, appendChild: noop },
  readyState: "loading",
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
  createElement: () => ({ style: {}, classList: { add: noop, remove: noop },
                          setAttribute: noop, appendChild: noop,
                          addEventListener: noop }),
  addEventListener: noop,
};
globalThis.window = globalThis;
globalThis.addEventListener = noop;
globalThis.matchMedia = () => ({ matches: false, addEventListener: noop,
                                 addListener: noop });
globalThis.requestIdleCallback = (f) => f;
"""


def run_shared(exprs: list[str]):
    """Evaluate expressions after loading the full _SHARED_JS behind a DOM stub."""
    script = (_DOM_STUB + _SHARED_JS +
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


@needs_node
def test_terse_pts_branch_present():
    # pts-only cards (no HCP band) must render a points range, not empty.
    limited, wide, open_top = run_shared([
        "terse({pts:[8,8]}, 'P')",
        "terse({pts:[5,10]}, 'P')",
        "terse({pts:[12,40]}, 'P')",   # hi>=25 -> "lo+ pts"
    ])
    assert limited == "8-8 pts"
    assert wide == "5-10 pts"
    assert open_top == "12+ pts"


@needs_node
def test_terse_pts_yields_to_hcp():
    # when both present, hcp wins (mirrors the Python elif)
    (both,) = run_shared(["terse({hcp:[10,14], pts:[8,20]}, 'P')"])
    assert both == "10-14"


@needs_node
def test_terse_matches_python_on_plain_range_cards():
    # cards whose rendering is plain text (no suit glyphs / convention name),
    # so the JS glyph HTML and the Python glyphs can't diverge the comparison.
    cards = [
        {"pts": [8, 8]},
        {"pts": [5, 10]},
        {"pts": [12, 40]},
        {"hcp": [6, 9]},
        {"hcp": [15, 40]},
    ]
    js = run_shared([f"terse({json.dumps(c)}, 'P')" for c in cards])
    py = [terse_meaning(c, call="P") for c in cards]
    assert js == py
