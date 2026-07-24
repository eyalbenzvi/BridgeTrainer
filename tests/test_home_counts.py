"""PERF-F-6: buildCounts precomputes pool counts once so each filter
interaction derives its facets/tallies from the matrix in O(levels x types)
instead of re-scanning the whole index. This runs the pure helpers under node
and checks they reproduce the poolFacets/facetCounts semantics.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile

import pytest

from bridge_trainer.app.webapp import _SHARED_JS

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available")

# DOM/window stubs + an injected taxonomy (TYPE_NAMES = window.TAXONOMY_HE) so
# facetsFrom's Object.keys(TYPE_NAMES) sees the fixture's types, then the full
# _SHARED_JS (its tail runs applyTheme/initChrome, hence the stubs).
_STUB = r"""
const noop = () => {};
globalThis.localStorage = { getItem: () => null, setItem: noop, removeItem: noop };
globalThis.document = {
  documentElement: { setAttribute: noop, removeAttribute: noop,
                     classList: { add: noop, remove: noop } },
  body: { dataset: {}, insertBefore: noop, firstChild: null, appendChild: noop },
  readyState: "loading", getElementById: () => null,
  querySelector: () => null, querySelectorAll: () => [],
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
globalThis.window.TAXONOMY_HE = { t1: ["A", "?"], t2: ["B", "?"], t3: ["C", "?"] };
"""

_INDEX = {"problems": [
    {"kind": "bidding", "type": "t1", "difficulty_level": 1},
    {"kind": "bidding", "type": "t1", "difficulty_level": 2},
    {"kind": "bidding", "type": "t2", "difficulty_level": 1},
    {"kind": "bidding", "difficulty_level": 3},          # level, no type
    {"kind": "bidding", "type": "t3"},                   # type, no level
    {"kind": "lead", "type": "t1", "difficulty_level": 1, "target_mode": "MP"},
    {"kind": "lead", "type": "t2", "difficulty_level": 2, "target_mode": "IMP"},
]}


def run_shared(exprs):
    script = (_STUB + _SHARED_JS +
              f"\nconst IDX = {json.dumps(_INDEX)};" +
              "\nconst COUNTS = buildCounts(IDX);" +
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
def test_scen_totals():
    tot_b, tot_mp, tot_imp = run_shared([
        'scenTotal(COUNTS, "bidding")',
        'scenTotal(COUNTS, "lead", "MP")',
        'scenTotal(COUNTS, "lead", "IMP")'])
    assert (tot_b, tot_mp, tot_imp) == (5, 1, 1)


@needs_node
def test_facets_from_matches_pool():
    f = run_shared(['facetsFrom(COUNTS, "bidding")'])[0]
    assert f["levels"] == [1, 2, 3]
    assert sorted(f["types"]) == ["t1", "t2", "t3"]
    assert f["levelCount"] == {"1": 2, "2": 1, "3": 1}
    assert f["typeCount"] == {"t1": 2, "t2": 1, "t3": 1}


@needs_node
def test_facet_counts_cross_filtered_by_type():
    # only type t1 selected -> level tallies count t1-only problems; the type
    # axis ignores its OWN selection (standard faceting), so typeCount still
    # shows every type present at the selected levels.
    flt = {"kind": "bidding", "mode": None, "levels": [1, 2, 3], "types": ["t1"]}
    c = run_shared([f'facetCountsFrom(COUNTS, {json.dumps(flt)})'])[0]
    assert c["levelCount"] == {"1": 1, "2": 1}     # t1 lives at levels 1 and 2
    assert c["typeCount"] == {"t1": 2, "t2": 1}    # types present at levels 1-3


@needs_node
def test_facet_counts_cross_filtered_by_level():
    # only level 1 selected -> type tallies count level-1-only problems; the
    # level axis ignores its own selection, so levelCount shows every level
    # present for the selected types.
    flt = {"kind": "bidding", "mode": None, "levels": [1],
           "types": ["t1", "t2", "t3"]}
    c = run_shared([f'facetCountsFrom(COUNTS, {json.dumps(flt)})'])[0]
    assert c["levelCount"] == {"1": 2, "2": 1}     # levels present for t1/t2
    assert c["typeCount"] == {"t1": 1, "t2": 1}    # both live at level 1


@needs_node
def test_lead_mode_partitioning():
    fmp = run_shared(['facetsFrom(COUNTS, "lead", "MP")'])[0]
    fimp = run_shared(['facetsFrom(COUNTS, "lead", "IMP")'])[0]
    assert fmp["typeCount"] == {"t1": 1}           # MP board only
    assert fimp["typeCount"] == {"t2": 1}          # IMP board only
