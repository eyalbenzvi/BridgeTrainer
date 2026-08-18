"""Unit tests: the Firestore queue worker, against an in-memory fake DB."""
from __future__ import annotations

import time

import pytest

from bridge_trainer.analysis import worker
from bridge_trainer.analysis.worker import (DAILY_LIMIT, claim,
                                            over_daily_limit,
                                            process_request, run_queue)

# ---------------------------------------------------------------------------
# minimal fake Firestore (only the surface the worker touches)


class FakeSnap:
    def __init__(self, ref, data):
        self.reference = ref
        self.id = ref.id
        self._data = data

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class FakeRef:
    def __init__(self, coll, doc_id):
        self._coll = coll
        self.id = doc_id

    def _data(self):
        return self._coll._docs.get(self.id)

    def get(self, transaction=None):
        return FakeSnap(self, self._data())

    def set(self, data):
        self._coll._docs[self.id] = dict(data)

    def update(self, patch):
        self._coll._docs[self.id].update(patch)


class FakeQuery:
    def __init__(self, coll, filters=(), n=None):
        self._coll, self._filters, self._n = coll, filters, n

    def where(self, field, op, value):
        assert op == "=="
        return FakeQuery(self._coll, self._filters + ((field, value),),
                         self._n)

    def limit(self, n):
        return FakeQuery(self._coll, self._filters, n)

    def stream(self):
        out = []
        for doc_id, data in list(self._coll._docs.items()):
            if all(data.get(f) == v for f, v in self._filters):
                out.append(FakeSnap(FakeRef(self._coll, doc_id), data))
        return out[: self._n] if self._n else out


class FakeCollection(FakeQuery):
    def __init__(self):
        self._docs = {}
        super().__init__(self)

    def document(self, doc_id):
        return FakeRef(self, doc_id)


class FakeTransaction:
    def update(self, ref, patch):
        ref.update(patch)


class FakeDB:
    def __init__(self):
        self._colls = {}

    def collection(self, name):
        return self._colls.setdefault(name, FakeCollection())

    def transaction(self):
        return FakeTransaction()


REQ = {
    "dealer": "E", "vul": "Both", "my_seat": "S",
    "my_hand": "AQ2.KJ3.KQ54.A32",
    "auction": ["2H", "X", "P", "3S", "P", "4S", "P", "P", "P"],
    "decision_index": 1, "system": "two_over_one", "scoring": "IMP",
    "candidates": ["X", "P"], "seed": 11, "max_deals": 150,
}


def make_db(n_requests=1, req=None, uid="user1"):
    db = FakeDB()
    coll = db.collection("analysis_requests")
    for i in range(n_requests):
        coll.document(f"req{i}").set({
            "uid": uid, "status": "pending",
            "createdAt": time.time() - i,
            "req": dict(req or REQ),
        })
    return db


# ---------------------------------------------------------------------------
def test_claim_is_a_cas():
    db = make_db()
    ref = db.collection("analysis_requests").document("req0")
    assert claim(db, ref, "run1")
    assert not claim(db, ref, "run2")     # already running
    assert ref.get().to_dict()["status"] == "running"
    assert ref.get().to_dict()["runId"] == "run1"


def test_process_request_clamps_and_runs():
    summary, html, facts_json = process_request(dict(REQ, max_deals=99999))
    assert summary["recommended"] in ("X", "P")
    assert summary["n_deals"] <= worker.MAX_DEALS_CAP
    assert 'dir="rtl"' in html
    assert '"candidates"' in facts_json


def test_process_request_rejects_garbage():
    with pytest.raises(Exception):
        process_request(dict(REQ, my_hand="AQ2.KJ3"))     # not 13 cards
    with pytest.raises(Exception):
        process_request(dict(REQ, auction=["2H", "2H"]))  # illegal auction


def test_run_queue_happy_path():
    db = make_db()
    stats = run_queue(db, run_id="t", max_requests=6, log=lambda *_: None)
    assert stats == {"processed": 1, "done": 1, "errors": 0, "skipped": 0}
    doc = db.collection("analysis_requests")._docs["req0"]
    assert doc["status"] == "done"
    assert doc["summary"]["recommended"] in ("X", "P")
    rep = db.collection("analysis_reports")._docs["req0"]
    assert rep["uid"] == "user1"
    assert "חלוקות מייצגות" in rep["html"]


def test_run_queue_marks_bad_request_as_error():
    db = make_db(req=dict(REQ, my_hand="garbage"))
    stats = run_queue(db, run_id="t", log=lambda *_: None)
    assert stats["errors"] == 1
    doc = db.collection("analysis_requests")._docs["req0"]
    assert doc["status"] == "error"
    assert doc["error"]
    assert "req0" not in db.collection("analysis_reports")._docs


def test_run_queue_respects_max_requests():
    db = make_db(n_requests=3)
    stats = run_queue(db, run_id="t", max_requests=1, log=lambda *_: None)
    assert stats["processed"] == 1
    statuses = [d["status"] for d in
                db.collection("analysis_requests")._docs.values()]
    assert statuses.count("pending") == 2


def test_run_queue_oldest_first():
    db = make_db(n_requests=2)   # req1 is OLDER (createdAt - i)
    run_queue(db, run_id="t", max_requests=1, log=lambda *_: None)
    docs = db.collection("analysis_requests")._docs
    assert docs["req1"]["status"] == "done"
    assert docs["req0"]["status"] == "pending"


def test_daily_limit_blocks_flooding():
    db = make_db(n_requests=DAILY_LIMIT + 2)
    assert over_daily_limit(db, "user1")
    stats = run_queue(db, run_id="t", max_requests=2, log=lambda *_: None)
    assert stats["errors"] == 2
    errs = [d for d in db.collection("analysis_requests")._docs.values()
            if d["status"] == "error"]
    assert len(errs) == 2
    assert all("מכסה" in d["error"] for d in errs)


def test_handle_request_trigger_entry_point():
    """The Cloud Functions path: claim + process a single doc."""
    from bridge_trainer.analysis.worker import handle_request
    db = make_db()
    ref = db.collection("analysis_requests").document("req0")
    assert handle_request(db, ref, run_id="fn1", log=lambda *_: None) == "done"
    assert ref.get().to_dict()["status"] == "done"
    assert "req0" in db.collection("analysis_reports")._docs
    # at-least-once event delivery: a second invocation is a harmless skip
    assert handle_request(db, ref, run_id="fn2",
                          log=lambda *_: None) == "skipped"


def test_stale_running_docs_are_reset():
    from bridge_trainer.analysis.worker import reset_stale_running
    db = make_db(n_requests=2)
    docs = db.collection("analysis_requests")._docs
    docs["req0"].update({"status": "running",
                         "startedAt": time.time() - 3600})   # stale
    docs["req1"].update({"status": "running",
                         "startedAt": time.time() - 60})     # fresh
    n = reset_stale_running(db, log=lambda *_: None)
    assert n == 1
    assert docs["req0"]["status"] == "pending"
    assert docs["req1"]["status"] == "running"


def test_worker_logs_never_contain_the_hand():
    db = make_db()
    lines = []
    run_queue(db, run_id="t", log=lambda m: lines.append(str(m)))
    blob = "\n".join(lines)
    assert "AQ2" not in blob and "KQ54" not in blob   # public CI logs
