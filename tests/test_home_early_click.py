"""Early-click guard on the home page (BUG-1 / task T13).

The scenario cards (.scencard) and the MP/IMP mode pills (.modecard) register
their click handlers at script parse time, but INDEX is only populated after
an async Firebase auth + fetchIndex. A click landing before the index loads
used to call setScenario -> resolveFilters(INDEX=null) -> poolFacets, which
iterates index.problems and throws a TypeError, leaving the UI in an
inconsistent half-selected state.

The fix keeps the cheap, persisted part of the handler (SCEN + localStorage +
aria + pills) and returns before the INDEX-dependent facet build, so init()
re-applies the persisted choice once the index arrives. These tests assert the
guard is present and correctly ordered in both handlers, and that the facet
build genuinely needs a non-null index (documents the crash it prevents).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile

import pytest

from bridge_trainer.app.webapp import _index_html

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available")


def _extract_function(js: str, name: str) -> str:
    """Pull a named function's source (brace-matched) out of the script."""
    start = js.index("function " + name + "(")
    depth = 0
    i = js.index("{", start)
    for j in range(i, len(js)):
        if js[j] == "{":
            depth += 1
        elif js[j] == "}":
            depth -= 1
            if depth == 0:
                return js[start:j + 1]
    raise AssertionError(name + " body not found")


def test_set_scenario_guards_index_before_facets():
    js = _index_html()
    start = js.index("function setScenario(")
    body = js[start:js.index("resolveFilters(INDEX, loadCur(), kind)", start)]
    assert "if (!INDEX) return;" in body, \
        "setScenario must bail out before the INDEX-dependent facet build"


def test_modecard_handler_guards_index_before_facets():
    js = _index_html()
    start = js.index("setLeadMode(b.dataset.mode)")
    body = js[start:js.index("resolveFilters(INDEX, loadCur(), SCEN)", start)]
    assert "if (!INDEX) return;" in body, \
        "the MP/IMP mode handler must bail out before the facet build"


@needs_node
def test_real_pool_facets_crashes_on_null_index_but_works_on_a_pool():
    """Exercises the REAL poolFacets (the crash site the guard prevents): it
    derefs index.problems, so a null index throws, while a valid pool returns
    the present levels/types."""
    fn = _extract_function(_index_html(), "poolFacets")
    harness = (
        fn
        + """
        // the small deps poolFacets closes over
        const ALL_LEVELS = [1, 2, 3, 4, 5];
        const TYPE_NAMES = { a: '', b: '', c: '' };
        function kindOf(p) { return p.kind || 'bidding'; }
        function targetModeOf() { return 'MP'; }
        function leadMode() { return 'MP'; }
        let threw = false;
        try { poolFacets(null, 'bidding'); } catch (e) { threw = true; }
        const ok = poolFacets({ problems: [
          { kind: 'bidding', difficulty_level: 2, type: 'a' },
          { kind: 'bidding', difficulty_level: 3, type: 'b' },
        ] }, 'bidding');
        console.log(JSON.stringify({ threw, levels: ok.levels,
                                     types: ok.types }));
        """
    )
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as fh:
        fh.write(harness)
        path = fh.name
    res = subprocess.run(["node", path], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout.strip().splitlines()[-1])
    assert out["threw"] is True                    # null index -> real crash
    assert out["levels"] == [2, 3]                 # real facet output
    assert out["types"] == ["a", "b"]
