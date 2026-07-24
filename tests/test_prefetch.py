"""Prefetch the next problem (task T15 / PERF-D-2).

After an answer, the trainer pages pick the next problem's id, fetch its doc,
and stash {id, doc} in sessionStorage; the "next" tap navigates to that id and
the destination page consumes the stashed doc instead of a fresh Firestore
read, so the transition is near-instant. These tests pin the wiring and unit-
test the pure prefetch helpers under node.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile

import pytest

from bridge_trainer.app.webapp import _index_html, _lead_html, _problem_html
from tests.test_home_early_click import _extract_function

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available")


@needs_node
def test_take_prefetch_matches_id_and_clears():
    read = _extract_function(_index_html(), "readPrefetch")
    take = _extract_function(_index_html(), "takePrefetch")
    harness = (
        'const PREFETCH_KEY = "bt_prefetch";\n' + read + "\n" + take + """
        const store = {};
        const sessionStorage = {
          getItem: (k) => store[k] || null,
          setItem: (k, v) => { store[k] = v; },
          removeItem: (k) => { delete store[k]; },
        };
        globalThis.sessionStorage = sessionStorage;
        store["bt_prefetch"] = JSON.stringify({ id: "p1", doc: { id: "p1" } });
        const hit = takePrefetch("p1");              // matching id -> doc
        const clearedAfterHit = store["bt_prefetch"] === undefined;
        store["bt_prefetch"] = JSON.stringify({ id: "p1", doc: { id: "p1" } });
        const miss = takePrefetch("other");          // wrong id -> null
        const clearedAfterMiss = store["bt_prefetch"] === undefined;
        console.log(JSON.stringify([hit, clearedAfterHit, miss,
                                    clearedAfterMiss]));
        """
    )
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        os.write(fd, harness.encode("utf-8"))
        os.close(fd)
        res = subprocess.run(["node", path], capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
        hit, cleared_hit, miss, cleared_miss = json.loads(
            res.stdout.strip().splitlines()[-1])
    finally:
        os.unlink(path)
    assert hit == {"id": "p1"}          # matching id returns the doc
    assert cleared_hit is True          # and always clears the stash
    assert miss is None                 # wrong id returns nothing
    assert cleared_miss is True         # (still clears the stale stash)


@pytest.mark.parametrize("html_fn", [_problem_html, _lead_html])
def test_answer_triggers_prefetch_and_init_consumes_it(html_fn):
    js = html_fn()
    commit = _extract_function(js, "commit" if "function commit" in js
                               else "choose")
    assert "prefetchNext(INDEX, flt)" in commit     # answer warms the next
    init = _extract_function(js, "init")
    assert "takePrefetch(id) ||" in init            # destination consumes it


@pytest.mark.parametrize("html_fn", [_problem_html, _lead_html])
def test_next_prefers_prefetched_id_when_still_unseen(html_fn):
    js = html_fn()
    assert "const pf = readPrefetch();" in js
    assert "(pf && !store()[pf.id]) ? pf.id : pickUnseen(INDEX, flt)" in js
