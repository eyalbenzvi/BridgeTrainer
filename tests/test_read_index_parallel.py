"""PERF-D-4: FirestorePool.read_index fetches shards in ONE batched round-trip
(get_all) instead of a serial per-shard loop, and reassembles them in the
pointer's declared shard order (get_all gives no order guarantee). The client
side (Promise.all) was already parallel; this covers the Python reader.

The real Firestore client is not available here, so we build a FirestorePool
without its __init__ (no live client) and inject a fake _meta/_db.
"""
from __future__ import annotations

from bridge_trainer.pool.firestore_store import FirestorePool


class _Snap:
    def __init__(self, doc_id, data, exists=True):
        self.id = doc_id
        self._data = data
        self.exists = exists

    def to_dict(self):
        return self._data


class _Ref:
    def __init__(self, doc_id):
        self.id = doc_id


class _FakeMeta:
    def __init__(self, pointer, shard_data):
        self.pointer = pointer
        self.shard_data = shard_data

    def document(self, doc_id):
        ref = _Ref(doc_id)
        if doc_id == "index":
            ref.get = lambda: _Snap("index", self.pointer,
                                    exists=self.pointer is not None)
        return ref


class _FakeDb:
    def __init__(self, meta):
        self.meta = meta
        self.get_all_calls = 0

    def get_all(self, refs):
        self.get_all_calls += 1
        snaps = [_Snap(r.id, {"problems": self.meta.shard_data.get(r.id, [])},
                       exists=r.id in self.meta.shard_data) for r in refs]
        return list(reversed(snaps))   # deliberately NOT in request order


def _pool(pointer, shard_data):
    pool = FirestorePool.__new__(FirestorePool)   # skip live-client __init__
    meta = _FakeMeta(pointer, shard_data)
    pool._meta = meta
    pool._db = _FakeDb(meta)
    return pool


def test_sharded_index_reassembled_in_shard_order_one_batch():
    pool = _pool(
        {"shards": ["s0", "s1", "s2"], "count": 6, "generation": 3},
        {"s0": [{"id": "a"}, {"id": "b"}],
         "s1": [{"id": "c"}, {"id": "d"}],
         "s2": [{"id": "e"}, {"id": "f"}]})
    res = pool.read_index()
    # order follows the pointer's shard list, not get_all's response order
    assert [e["id"] for e in res["problems"]] == ["a", "b", "c", "d", "e", "f"]
    assert res["generation"] == 3
    assert pool._db.get_all_calls == 1          # a single batched read


def test_missing_shard_is_skipped():
    pool = _pool({"shards": ["s0", "gone"], "count": 2},
                 {"s0": [{"id": "a"}]})          # "gone" not present
    res = pool.read_index()
    assert [e["id"] for e in res["problems"]] == ["a"]


def test_legacy_single_doc_index_unchanged():
    pool = _pool({"problems": [{"id": "x"}], "count": 1}, {})
    res = pool.read_index()
    assert res["problems"] == [{"id": "x"}]
    assert pool._db.get_all_calls == 0          # no shard fetch for legacy


def test_no_index_returns_none():
    assert _pool(None, {}).read_index() is None
