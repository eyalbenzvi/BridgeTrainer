"""Optimistic-locked index update (task T11 / DB-M-3, DB-O-4).

meta/index is updated read-union-write; without a guard, two producers pushing
concurrently overwrite each other and entries silently vanish from the index.
push_local_pool now re-reads and re-unions under a generation check, retrying on
conflict. The Firestore transaction itself is manual-verify (no emulator); here
we drive push_local_pool with an in-memory fake remote that simulates a
concurrent producer bumping the generation, and assert nobody's entries are
lost. (Also unit-covers that a stale expected-generation raises IndexConflict.)
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from bridge_trainer.pool import firestore_store as fs
from bridge_trainer.pool.firestore_store import IndexConflict, push_local_pool


def _local_pool(pids):
    d = tempfile.mkdtemp()
    probs = Path(d) / "problems"
    probs.mkdir(parents=True)
    for pid in pids:
        (probs / f"{pid}.json").write_text(json.dumps({
            "id": pid, "schema": 1, "kind": "bidding",
            "classification": {"type": "invite", "difficulty_level": 2},
            "difficulty": 2.0, "created_at": "2026-01-01T00:00:00",
        }))
    return d


class _FakeRemote:
    """Minimal stand-in for FirestorePool exercising push_local_pool's paths."""
    def __init__(self, always_conflict=False):
        self.problems = {}       # pid -> index entry (the "server" index)
        self.gen = 0
        self.uploaded = {}       # pid -> doc body
        self.write_calls = 0
        self.always_conflict = always_conflict
        self._db = self
        self._col = self

    # _db.bulk_writer()
    def bulk_writer(self):
        remote = self

        class _W:
            def set(self, ref, data): remote.uploaded[ref] = data
            def close(self): pass
        return _W()

    # _col.document(pid) -> a ref (just the id here)
    def document(self, pid): return pid

    def read_index(self):
        return {"problems": list(self.problems.values()),
                "generation": self.gen}

    def write_index(self, index, expect_generation=None):
        self.write_calls += 1
        if self.always_conflict:
            self.gen += 1          # a concurrent writer wins every round
            raise IndexConflict(f"{expect_generation} != {self.gen}")
        if self.write_calls == 1:
            # a concurrent producer commits an entry + bumps the generation
            # right before our first write lands.
            self.problems["other"] = {"id": "other",
                                      "created_at": "2026-01-02T00:00:00"}
            self.gen += 1
        if expect_generation is not None and expect_generation != self.gen:
            raise IndexConflict(f"{expect_generation} != {self.gen}")
        self.problems = {e["id"]: e for e in index.get("problems", [])}
        self.gen += 1
        return self.gen


def test_push_retries_on_conflict_and_preserves_all_entries(monkeypatch):
    monkeypatch.setattr(fs.time, "sleep", lambda *_: None)   # no real backoff
    remote = _FakeRemote()
    res = push_local_pool(_local_pool(["p1", "p2"]), remote=remote)

    assert res["uploaded"] == 2
    assert remote.write_calls == 2                 # first conflicted, retried
    ids = set(remote.problems)
    assert {"p1", "p2"}.issubset(ids)              # our entries are present
    assert "other" in ids                          # the concurrent one survived
    assert "p1" in remote.uploaded and "p2" in remote.uploaded


def test_push_gives_up_after_max_retries(monkeypatch):
    """If every index write loses the race, push raises after the retry budget
    (docs are uploaded; the operator re-runs). Exercises the real retry loop."""
    monkeypatch.setattr(fs.time, "sleep", lambda *_: None)
    remote = _FakeRemote(always_conflict=True)
    raised = False
    try:
        push_local_pool(_local_pool(["p1"]), remote=remote)
    except IndexConflict:
        raised = True
    assert raised
    assert remote.write_calls == fs._MAX_INDEX_CAS_RETRIES  # tried the budget
    assert "p1" in remote.uploaded                          # doc still uploaded
