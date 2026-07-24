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
from tests.test_home_filters import _extract_resolve_filters

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available")


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
def test_resolve_filters_throws_on_null_index():
    """Documents the crash the guard prevents: the facet path derefs the
    index, so calling it with a null index must throw."""
    fn = _extract_resolve_filters(_index_html())
    harness = (
        fn
        + """
        function poolFacets(index) { return { levels: index.problems,
                                               types: [] }; }
        function leadMode() { return 'MP'; }
        try {
          resolveFilters(null, null, 'bidding');
          console.log(JSON.stringify({ threw: false }));
        } catch (e) {
          console.log(JSON.stringify({ threw: true }));
        }
        """
    )
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as fh:
        fh.write(harness)
        path = fh.name
    res = subprocess.run(["node", path], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout.strip().splitlines()[-1])
    assert out["threw"] is True
