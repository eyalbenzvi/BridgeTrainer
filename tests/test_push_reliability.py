"""Push/remove index integrity and schema enforcement (DB-O-5, DB-M-5, DB-M-7).

No emulator, so these drive the pure logic with in-memory fakes: a BulkWriter
that fails a chosen pid (DB-O-5), the index-first remove path (DB-M-5), and the
schema guards + real schema_min/max (DB-M-7).
"""
from __future__ import annotations

import types

import pytest

from bridge_trainer.pool import firestore_store as fs
from bridge_trainer.pool.firestore_store import (IndexConflict, _bulk_retryable,
                                                 _check_schema, push_local_pool)
from bridge_trainer.pool.store import index_entry, index_from_entries

# module-name import (CI runs `pytest`, not `python -m pytest`)
from test_index_cas import _local_pool


class _FakeRemoteWithFailures:
    """push_local_pool remote whose BulkWriter fails a chosen set of pids via
    the on_write_error callback (as a permanent RESOURCE_EXHAUSTED)."""
    def __init__(self, fail_pids=()):
        self.problems = {}
        self.gen = 0
        self.uploaded = {}
        self.fail = set(fail_pids)
        self._db = self
        self._col = self
        self._handler = None
        self._pending = []

    def bulk_writer(self):
        outer = self

        class _W:
            def on_write_error(self, h): outer._handler = h

            def set(self, ref, data):
                if ref in outer.fail:
                    outer._pending.append(ref)
                else:
                    outer.uploaded[ref] = data

            def close(self):
                for ref in outer._pending:
                    err = types.SimpleNamespace(
                        operation=types.SimpleNamespace(
                            reference=types.SimpleNamespace(id=ref)),
                        code=types.SimpleNamespace(name="RESOURCE_EXHAUSTED"),
                        attempts=1)
                    if outer._handler:
                        outer._handler(err)
        return _W()

    def document(self, pid): return pid

    def read_index(self):
        return {"problems": list(self.problems.values()),
                "generation": self.gen}

    def write_index(self, index, expect_generation=None):
        if expect_generation is not None and expect_generation != self.gen:
            raise IndexConflict("stale")
        self.problems = {e["id"]: e for e in index.get("problems", [])}
        self.gen += 1
        return self.gen


def test_failed_write_is_excluded_from_index_and_reported():
    remote = _FakeRemoteWithFailures(fail_pids={"p2"})
    res = push_local_pool(_local_pool(["p1", "p2", "p3"]), remote=remote)
    assert res["failed"] == ["p2"]
    assert res["uploaded"] == 2                 # p2 not counted as uploaded
    assert set(remote.problems) == {"p1", "p3"}  # p2 kept OUT of the index
    assert "p2" not in remote.uploaded


def test_clean_push_reports_no_failures():
    remote = _FakeRemoteWithFailures()
    res = push_local_pool(_local_pool(["p1", "p2"]), remote=remote)
    assert res["failed"] == []
    assert res["uploaded"] == 2
    assert set(remote.problems) == {"p1", "p2"}


def test_remove_drops_index_entry_before_deleting_doc():
    calls = []

    class Ref:
        def get(self):
            calls.append("doc.get")
            return types.SimpleNamespace(exists=True)

        def delete(self):
            calls.append("doc.delete")

    class Fake(fs.FirestorePool):
        def __init__(self):   # skip the firebase client __init__
            self.problems = {"p1": {"id": "p1", "created_at": "t"},
                             "p2": {"id": "p2", "created_at": "t"}}
            self.gen = 0
            self._col = types.SimpleNamespace(document=lambda pid: Ref())

        def read_index(self):
            return {"problems": list(self.problems.values()),
                    "generation": self.gen}

        def write_index(self, index, expect_generation=None):
            calls.append("index.write")
            self.problems = {e["id"]: e for e in index["problems"]}
            self.gen += 1
            return self.gen

    f = Fake()
    assert f.remove("p1") is True
    assert set(f.problems) == {"p2"}                 # index entry removed
    assert calls.index("index.write") < calls.index("doc.delete")   # index-first


def test_remove_missing_doc_is_noop():
    class Fake(fs.FirestorePool):
        def __init__(self):
            self._col = types.SimpleNamespace(
                document=lambda pid: types.SimpleNamespace(
                    get=lambda: types.SimpleNamespace(exists=False)))
    assert Fake().remove("nope") is False


def test_bulk_retryable_handles_int_and_enum_codes():
    import types as _t
    # bare int gRPC statuses (the real BulkWriteFailure.code form)
    assert _bulk_retryable(14, 1) is True          # UNAVAILABLE
    assert _bulk_retryable(4, 1) is True           # DEADLINE_EXCEEDED
    assert _bulk_retryable(8, 1) is False          # RESOURCE_EXHAUSTED (quota)
    # enum-like code with a .name
    assert _bulk_retryable(_t.SimpleNamespace(name="unavailable"), 1) is True
    assert _bulk_retryable(_t.SimpleNamespace(name="PERMISSION_DENIED"), 1) \
        is False
    # transient but out of budget -> give up
    assert _bulk_retryable(14, 99) is False
    # unknown / missing code -> not retryable
    assert _bulk_retryable(None, 1) is False


def test_check_schema_enforced():
    _check_schema({"id": "a", "schema": 1})       # ok
    _check_schema({"id": "b", "schema": 2})       # ok
    for bad in ({"id": "c"}, {"id": "d", "schema": 3}, {"id": "e", "schema": 0}):
        with pytest.raises(ValueError):
            _check_schema(bad)


def test_index_reports_real_schema_span():
    recs = [
        {"id": "a", "schema": 1, "created_at": "2026-01-01T00:00:00"},
        {"id": "b", "schema": 2, "kind": "lead",
         "created_at": "2026-01-02T00:00:00"},
    ]
    idx = index_from_entries(index_entry(r) for r in recs)
    assert idx["schema_min"] == 1
    assert idx["schema_max"] == 2
    assert idx["schema"] == 1            # scalar kept = min for old readers


def test_index_defaults_missing_entry_schema():
    # a bare entry with no schema (e.g. the concurrent-writer fixture) must not
    # KeyError and defaults to schema 1
    idx = index_from_entries([{"id": "x", "created_at": "2026-01-01T00:00:00"}])
    assert idx["schema_min"] == 1 and idx["schema_max"] == 1
