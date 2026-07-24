"""ARCH-8: auctionTableHtml and completeAuctionTableHtml are now thin wrappers
over one auctionTable(p, notes, opts). This pins their output to the snapshot
captured from the pre-refactor implementations (byte-for-byte), so the merge
changed nothing a user sees, and checks the structural differences the opts
encode (pending "?" cell for bidding; ".fin" on the contract for leads).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from bridge_trainer.app.webapp import _SHARED_JS

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available")

_FIX = Path(__file__).parent / "fixtures" / "auction_snapshot.json"

_DOM_STUB = r"""
const noop = () => {};
globalThis.localStorage = { getItem: () => null, setItem: noop, removeItem: noop };
globalThis.document = {
  documentElement: { setAttribute: noop, removeAttribute: noop,
                     classList: { add: noop, remove: noop } },
  body: { dataset: {}, insertBefore: noop, firstChild: null, appendChild: noop },
  readyState: "loading",
  getElementById: () => null, querySelector: () => null,
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

# the two fixtures the snapshot was captured from
BID_P = {"seat": "S", "dealer": "N", "vul": "NS",
         "auction": ["P", "1H", "X", "2H"]}
BID_NOTES = ["", "5+♥", "", ""]
LEAD_P = {"leader": "W", "declarer": "S", "dealer": "N", "vul": "None",
          "auction": ["1NT", "P", "3NT", "P", "P", "P"]}
LEAD_NOTES = [{"card": {}}, {}, {"text": "game"}, None, None, None]


def run_shared(exprs):
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
def test_wrappers_match_prerefactor_snapshot():
    snap = json.loads(_FIX.read_text(encoding="utf-8"))
    bidding, complete = run_shared([
        f"auctionTableHtml({json.dumps(BID_P)}, {json.dumps(BID_NOTES)})",
        f"completeAuctionTableHtml({json.dumps(LEAD_P)}, "
        f"{json.dumps(LEAD_NOTES)})",
    ])
    assert bidding == snap["bidding"]
    assert complete == snap["complete"]


@needs_node
def test_opts_encode_the_two_differences():
    bidding, complete = run_shared([
        f"auctionTableHtml({json.dumps(BID_P)}, {json.dumps(BID_NOTES)})",
        f"completeAuctionTableHtml({json.dumps(LEAD_P)}, "
        f"{json.dumps(LEAD_NOTES)})",
    ])
    # bidding has the pending "?" turn cell; the lead table does not
    assert 'class="turn">?' in bidding
    assert 'class="turn">?' not in complete
    # the lead table highlights the final contract call; bidding does not
    assert "fin" in complete
    assert "fin" not in bidding


def test_source_has_one_builder_and_two_thin_wrappers():
    js = _SHARED_JS
    assert "function auctionTable(p, notes, opts)" in js
    # the wrappers delegate rather than re-implement the table
    assert js.count("<table class=\"bidding\">") == 1
