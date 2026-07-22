"""Firestore backend for the problem pool.

Mirrors the ``ProblemPool`` interface (add / ids / get) but stores each
problem as a document in the ``problems`` collection, so the web app reads
them live — a newly generated problem is on the site immediately, with no
pull request and no redeploy.

Writing needs the Firebase Admin SDK and a service-account key (kept locally,
never committed). See ``docs/firebase_setup.md``. The dependency is imported
lazily so the rest of the package works without ``firebase-admin`` installed.

Read-cost discipline (the whole reason meta/index exists): the web client and
these tools must read the small ``meta/index`` document(s) instead of the full
``problems`` collection. ``push_local_pool`` updates the index INCREMENTALLY
from the existing index (one small read) rather than re-streaming every problem
(N reads) — a full collection scan on each push previously exhausted the
free-tier daily read quota. The index is SHARDED so it never hits Firestore's
1 MiB per-document limit as the pool grows.

Typical use (generate locally, push to the DB)::

    trainer pool add --count 5              # writes data/*.json locally
    trainer pool push --key sa-key.json     # uploads the pool to Firestore
"""
from __future__ import annotations

import os
import time
from pathlib import Path

COLLECTION = "problems"
META = "meta"
INDEX_DOC = "index"                 # pointer doc: {shards:[...], count, ...}
SHARD_PREFIX = "index_shard_"       # meta/index_shard_0, _1, ...
SHARD_MAX_ENTRIES = 3000            # ~150-200 B/entry -> well under 1 MiB
# While the whole index still fits comfortably in one doc, keep the LEGACY
# single-doc format (inline `problems`, no shards) so older deployed clients
# that read meta/index.problems directly keep working. Only shard once the pool
# outgrows this — by which point the sharded-aware client must be deployed.
SINGLE_DOC_MAX_ENTRIES = 4000       # ~4000 * 200 B ~= 0.8 MiB, safe under 1 MiB
_MAX_TRANSIENT_RETRIES = 4


def _firestore_safe(value):
    """Make a value storable in Firestore.

    Firestore forbids an array element that is itself an array (a directly
    nested array). Some problem docs have those (e.g. ``top_contracts`` is a
    list of ``[contract, count]`` pairs, ``policy_trail[].policy`` is a list of
    lists). We wrap each such inner array in a one-key map ``{"items": [...]}``,
    which is legal and reversible. Maps and scalars pass through unchanged.
    None of these wrapped fields are read by the web client.
    """
    if isinstance(value, dict):
        return {k: _firestore_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        out = []
        for e in value:
            e = _firestore_safe(e)
            out.append({"items": e} if isinstance(e, list) else e)
        return out
    return value


def _client(key_path: str | None = None):
    """Initialize (once) and return a Firestore client.

    Credentials resolution order:
      1. explicit *key_path* (a service-account JSON),
      2. GOOGLE_APPLICATION_CREDENTIALS env var (Admin SDK default).
    """
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
    except ImportError as e:  # pragma: no cover - depends on optional extra
        raise RuntimeError(
            "Firestore backend needs the 'firebase-admin' package. "
            "Install with: pip install -e '.[firestore]'") from e

    if not firebase_admin._apps:
        key_path = key_path or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        cred = credentials.Certificate(key_path) if key_path else \
            credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred)
    return firestore.client()


def _retry_transient(fn):
    """Run *fn*, retrying transient Firestore errors with exponential backoff.

    ResourceExhausted (429) is NOT retried here: on the free tier that is the
    daily quota, which will not clear in seconds, so we surface it immediately
    and let the caller stop cleanly (and try again later).
    """
    try:
        from google.api_core import exceptions as gexc
    except ImportError:      # pragma: no cover
        return fn()
    delay = 2.0
    for attempt in range(_MAX_TRANSIENT_RETRIES):
        try:
            return fn()
        except (gexc.ServiceUnavailable, gexc.DeadlineExceeded,
                gexc.Aborted, gexc.InternalServerError) as e:
            if attempt == _MAX_TRANSIENT_RETRIES - 1:
                raise
            time.sleep(delay)
            delay *= 2


class FirestorePool:
    """add / ids / get against the Firestore ``problems`` collection."""

    def __init__(self, key_path: str | None = None):
        self._db = _client(key_path)
        self._col = self._db.collection(COLLECTION)
        self._meta = self._db.collection(META)

    # ---- problem docs ---------------------------------------------------
    def add(self, record: dict, *, overwrite: bool = False) -> str:
        pid = record["id"]
        ref = self._col.document(pid)
        if not overwrite and ref.get().exists:
            raise FileExistsError(f"problem {pid} already in Firestore")
        _retry_transient(lambda: ref.set(_firestore_safe(record)))
        return pid

    def add_unchecked(self, record: dict) -> str:
        """set() a problem without a prior existence read. Use when the caller
        has already determined the doc is new (e.g. from the index), to avoid
        one read per uploaded document."""
        ref = self._col.document(record["id"])
        _retry_transient(lambda: ref.set(_firestore_safe(record)))
        return record["id"]

    def ids(self) -> list[str]:
        """Document ids only. ``list_documents`` returns references without
        downloading document bodies — far cheaper than streaming full docs."""
        return sorted(d.id for d in self._col.list_documents())

    def stream_records(self, fields: list[str] | None = None) -> list[dict]:
        """Every problem document, read once. Pass *fields* to project only the
        columns needed (cuts bandwidth on the big embedded tables; read COUNT
        is unchanged). Each record carries its ``id`` even when projected."""
        q = self._col.select(fields) if fields else self._col
        out = []
        for d in q.stream():
            rec = d.to_dict() or {}
            rec.setdefault("id", d.id)
            out.append(rec)
        return out

    def get(self, pid: str) -> dict:
        snap = self._col.document(pid).get()
        if not snap.exists:
            raise KeyError(pid)
        return snap.to_dict()

    def remove(self, pid: str) -> bool:
        ref = self._col.document(pid)
        if not ref.get().exists:
            return False
        _retry_transient(ref.delete)
        return True

    # ---- the sharded meta/index ----------------------------------------
    def read_index(self) -> dict | None:
        """Read the pool index. Returns a dict with a flat ``problems`` list
        (shards merged), or None if no index exists. Costs 1 read for the
        pointer + one read per shard (2-8 total), never O(collection)."""
        ptr = self._meta.document(INDEX_DOC).get()
        if not ptr.exists:
            return None
        data = ptr.to_dict() or {}
        if "problems" in data:            # legacy single-doc index
            return data
        problems = []
        for sid in data.get("shards", []):
            snap = self._meta.document(sid).get()
            if snap.exists:
                problems.extend((snap.to_dict() or {}).get("problems", []))
        return {**data, "problems": problems}

    def write_index(self, index: dict) -> None:
        """Store the pool index. While it fits one document it is written in the
        LEGACY single-doc form (inline ``problems``), which every client — old
        or sharded-aware — can read. Once it outgrows SINGLE_DOC_MAX_ENTRIES it
        is SHARDED (pointer ``meta/index`` lists shard ids; each shard holds up
        to SHARD_MAX_ENTRIES rows) so no doc nears the 1 MiB limit."""
        entries = list(index.get("problems", []))

        # learn the previous shard set (1 read) so we can delete stale shards
        # when we shrink or fall back to single-doc, leaving no orphans.
        prev = self._meta.document(INDEX_DOC).get()
        old_shards = set((prev.to_dict() or {}).get("shards", [])
                         if prev.exists else [])

        if len(entries) <= SINGLE_DOC_MAX_ENTRIES:
            doc = {k: v for k, v in index.items() if k != "shards"}
            doc["count"] = len(entries)
            _retry_transient(lambda: self._meta.document(INDEX_DOC).set(
                _firestore_safe(doc)))
            for sid in old_shards:                 # drop any old shards
                _retry_transient(self._meta.document(sid).delete)
            return

        shards = [entries[i:i + SHARD_MAX_ENTRIES]
                  for i in range(0, len(entries), SHARD_MAX_ENTRIES)]
        shard_ids = [f"{SHARD_PREFIX}{i}" for i in range(len(shards))]
        batch = self._db.batch()
        for sid, chunk in zip(shard_ids, shards):
            batch.set(self._meta.document(sid),
                      _firestore_safe({"problems": chunk}))
        ptr = {k: v for k, v in index.items() if k != "problems"}
        ptr["shards"] = shard_ids
        ptr["count"] = len(entries)
        batch.set(self._meta.document(INDEX_DOC), _firestore_safe(ptr))
        _retry_transient(batch.commit)
        for sid in old_shards - set(shard_ids):
            _retry_transient(self._meta.document(sid).delete)

    def rebuild_index(self) -> dict:
        """Repair path: rebuild the index by streaming the WHOLE collection
        (O(N) reads — expensive; not used on the hot push path). Use only to
        recover after drift/corruption."""
        from .store import build_index
        index = build_index(self.stream_records(
            fields=["kind", "classification", "difficulty", "created_at"]))
        self.write_index(index)
        return index


def push_local_pool(local_dir: str | Path, key_path: str | None = None,
                    overwrite: bool = False) -> dict:
    """Upload every problem in a local JSON pool to Firestore.

    Cost: ONE index read (pointer + shards) regardless of pool size, plus one
    write per newly uploaded problem and the index write — never a full
    collection scan. The index is updated by unioning the existing index with
    the freshly uploaded rows, so a producer that holds only a subset of the
    pool locally never drops other producers' entries.

    Returns {uploaded, skipped, skipped_no_explanations, total}. Records whose
    bids went unexplained (generated with GIB/BBO unreachable) are never
    uploaded — counted under skipped_no_explanations.
    """
    from ..engine.explain import bid_notes_missing
    from .store import ProblemPool, index_entry, index_from_entries

    local = ProblemPool(local_dir)
    remote = FirestorePool(key_path)
    idx = remote.read_index() or {"problems": []}
    by_id = {e["id"]: e for e in idx.get("problems", [])}

    writer = remote._db.bulk_writer()   # batches + retries writes internally
    uploaded = skipped = no_expl = 0
    try:
        for pid in local.ids():
            if pid in by_id and not overwrite:
                skipped += 1
                continue
            rec = local.get(pid)
            # Never upload a problem whose bids went unexplained (generated
            # with GIB/BBO unreachable) — this is what stranded a batch of
            # note-less problems in Firestore before.
            if bid_notes_missing(rec):
                no_expl += 1
                continue
            writer.set(remote._col.document(pid), _firestore_safe(rec))
            by_id[pid] = index_entry(rec)
            uploaded += 1
    finally:
        writer.close()      # flush all buffered writes

    if uploaded:
        remote.write_index(index_from_entries(by_id.values()))
    return {"uploaded": uploaded, "skipped": skipped,
            "skipped_no_explanations": no_expl, "total": len(local.ids())}


def backfill_lead_types(key_path: str | None = None,
                        dry_run: bool = False) -> dict:
    """Assign the opening-lead category to every lead problem *in Firestore*.

    Reads only the columns it needs (projection), computes each lead's category
    from the contract (engine/lead_classify.py — deterministic, no LLM), and
    writes back only ``classification.type`` (a merge, so difficulty_level is
    preserved). The index is rebuilt from the already-read rows (no second
    scan). Bidding docs are read but never written.

    Returns {lead_total, updated, total}. ``dry_run`` reports without writing.
    """
    from ..engine.lead_classify import classify_lead_record
    from .store import build_index

    remote = FirestorePool(key_path)
    records = remote.stream_records(
        fields=["kind", "contract", "classification", "difficulty",
                "created_at"])
    updated = lead_total = 0
    for rec in records:
        if rec.get("kind") != "lead":
            continue
        lead_total += 1
        want = classify_lead_record(rec)
        cls = rec.setdefault("classification", {})
        if cls.get("type") == want:
            continue
        cls["type"] = want
        updated += 1
        if not dry_run:
            _retry_transient(lambda rid=rec["id"], w=want: remote._col.document(
                rid).set({"classification": {"type": w}}, merge=True))
    if not dry_run:
        remote.write_index(build_index(records))     # rebuild from memory
    return {"lead_total": lead_total, "updated": updated,
            "total": len(records)}
