"""Home-page filter resolution guardrail.

``resolveFilters`` turns a stored (or absent) practice filter into concrete
selected difficulty/type sets. A stale or corrupt stored filter — most
importantly an empty ``levels`` array (difficulty cleared, or an older
string-vs-number level format) — must NOT be restored verbatim: that matches
no problems and strands the home page on "0 of N" with every category showing
a 0 count. This test executes the real generated function in node with a
stubbed pool and asserts such states heal back to the full pool.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile

import pytest

from bridge_trainer.app.webapp import _index_html, _SHARED_JS


def _extract_resolve_filters(js: str) -> str:
    """Pull the resolveFilters source out of the generated index script."""
    start = js.index("function resolveFilters(")
    depth = 0
    i = js.index("{", start)
    for j in range(i, len(js)):
        if js[j] == "{":
            depth += 1
        elif js[j] == "}":
            depth -= 1
            if depth == 0:
                return js[start:j + 1]
    raise AssertionError("resolveFilters body not found")


def _run_resolve(stored) -> dict:
    """Evaluate resolveFilters with a stub pool (levels 1-5, three types)."""
    fn = _extract_resolve_filters(_SHARED_JS)
    harness = (
        fn
        + """
        // stubs the function closes over
        function poolFacets() {
          return { levels: [1, 2, 3, 4, 5], types: ['a', 'b', 'c'] };
        }
        function leadMode() { return 'MP'; }
        const out = resolveFilters({}, %s, 'bidding');
        console.log(JSON.stringify(out));
        """ % json.dumps(stored)
    )
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as fh:
        fh.write(harness)
        path = fh.name
    res = subprocess.run(["node", path], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node not available")


def test_absent_filter_selects_whole_pool():
    out = _run_resolve(None)
    assert out["levels"] == [1, 2, 3, 4, 5]
    assert out["types"] == ["a", "b", "c"]


def test_empty_levels_heals_to_all():
    # the exact stuck state observed in the field: difficulty cleared to [],
    # every type still selected -> 0 problems, 0 category counts.
    out = _run_resolve({"levels": [], "types": ["a", "b", "c"]})
    assert out["levels"] == [1, 2, 3, 4, 5]
    assert out["types"] == ["a", "b", "c"]


def test_string_levels_are_coerced_and_matched():
    # a legacy filter that stored difficulty levels as strings must still
    # match the numeric pool instead of collapsing to zero.
    out = _run_resolve({"levels": ["2", "4"], "types": ["b"]})
    assert out["levels"] == [2, 4]
    assert out["types"] == ["b"]


def test_stale_values_are_dropped_and_real_selection_kept():
    out = _run_resolve({"levels": [3, 99], "types": ["b", "gone"]})
    assert out["levels"] == [3]
    assert out["types"] == ["b"]


def test_source_carries_sanitization():
    js = _SHARED_JS
    assert "kept.length ? kept : all.slice()" in js
