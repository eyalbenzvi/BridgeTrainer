"""ARCH-7: the shared BatchState core — dedup, stage-timing tally, rejection
counting, and the common summary shape — exercised directly (the maker/lead
subclasses are covered end-to-end by the forge suites)."""
from __future__ import annotations

import tempfile
import types

from bridge_trainer.engine.batch_state import BatchState


class _Plain(BatchState):
    """No quotas, no logging — just the shared core."""


def _out(status, rec=None, reason=None, timings=None):
    return types.SimpleNamespace(status=status, rec=rec, reason=reason,
                                 seed=0, detail="", audit=None,
                                 timings=timings or {})


def test_absorb_dedup_tally_and_summary():
    d = tempfile.mkdtemp()
    st = _Plain(d, count=3, log=lambda *_: None)

    st.absorb(_out("accepted", {"id": "p1", "schema": 1},
                   timings={"scan": 1.0, "judge": 0.5}))
    st.absorb(_out("rejected", reason="dd_fog", timings={"scan": 0.5}))
    st.absorb(_out("accepted", {"id": "p1", "schema": 1}))  # duplicate id
    st.absorb(_out("error", reason="engine", timings={"scan": 0.2}))

    assert st.made == ["p1"]                       # duplicate not re-added
    assert st.boards == 4                          # every outcome counts
    assert st.rejections == {"dd_fog": 1, "duplicate": 1, "engine": 1}
    assert st.stage_totals["scan"] == 1.7

    s = st.summary(wall=12.0)
    assert s["count"] == 1
    assert s["boards_scanned"] == 4                # default boards_key
    assert s["rejections"] == {"dd_fog": 1, "duplicate": 1, "engine": 1}
    assert s["per_accepted_s"] == 12.0
    assert s["mix"] == {}                          # base has no quota axes


def test_boards_key_is_overridable():
    class _Lead(BatchState):
        boards_key = "boards_bid"
    st = _Lead(tempfile.mkdtemp(), count=1, log=lambda *_: None)
    st.absorb(_out("rejected", reason="x"))
    assert "boards_bid" in st.summary(1.0)
    assert "boards_scanned" not in st.summary(1.0)


def test_per_accepted_none_when_nothing_made():
    st = _Plain(tempfile.mkdtemp(), count=1, log=lambda *_: None)
    st.absorb(_out("rejected", reason="x"))
    assert st.summary(5.0)["per_accepted_s"] is None
