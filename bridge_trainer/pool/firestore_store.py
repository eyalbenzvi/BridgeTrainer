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
_MAX_INDEX_CAS_RETRIES = 5


class IndexConflict(RuntimeError):
    """The meta/index generation changed under us between read and write.
    The caller should re-read the index, re-apply its changes, and retry."""


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
        data.setdefault("generation", 0)   # optimistic-lock counter (T11)
        if "problems" in data:            # legacy single-doc index
            return data
        problems = []
        for sid in data.get("shards", []):
            snap = self._meta.document(sid).get()
            if snap.exists:
                problems.extend((snap.to_dict() or {}).get("problems", []))
        return {**data, "problems": problems}

    def _cas_pointer(self, ptr_fields: dict,
                     expect_generation: int | None) -> int:
        """Write the index pointer inside a transaction that reads the current
        ``generation`` and, when *expect_generation* is given, refuses the write
        (raising IndexConflict) if it changed — optimistic locking so concurrent
        producers can't silently drop each other's index entries. The new
        pointer's generation is the current one + 1. Returns the new generation.
        """
        from google.cloud import firestore  # provided by firebase-admin

        ref = self._meta.document(INDEX_DOC)

        @firestore.transactional
        def _txn(transaction):
            snap = ref.get(transaction=transaction)
            cur = (snap.to_dict() or {}).get("generation", 0) \
                if snap.exists else 0
            if expect_generation is not None and cur != expect_generation:
                raise IndexConflict(
                    f"index generation {cur} != expected {expect_generation}")
            doc = dict(ptr_fields)
            doc["generation"] = cur + 1
            transaction.set(ref, _firestore_safe(doc))
            return cur + 1

        return _txn(self._db.transaction())

    def write_index(self, index: dict,
                    expect_generation: int | None = None) -> int:
        """Store the pool index. While it fits one document it is written in the
        LEGACY single-doc form (inline ``problems``), which every client — old
        or sharded-aware — can read. Once it outgrows SINGLE_DOC_MAX_ENTRIES it
        is SHARDED (pointer ``meta/index`` lists shard ids; each shard holds up
        to SHARD_MAX_ENTRIES rows) so no doc nears the 1 MiB limit.

        The pointer is written via a generation-checked transaction (T11): pass
        *expect_generation* (the generation from the read used to build *index*)
        and the write is refused with IndexConflict if another producer bumped
        it meanwhile. Shards are written first (fixed ids, idempotent); the
        pointer — written last and atomically — is what makes the new rows
        visible. Returns the new generation."""
        entries = list(index.get("problems", []))

        # learn the previous shard set (1 read) so we can delete stale shards
        # when we shrink or fall back to single-doc, leaving no orphans.
        prev = self._meta.document(INDEX_DOC).get()
        old_shards = set((prev.to_dict() or {}).get("shards", [])
                         if prev.exists else [])

        if len(entries) <= SINGLE_DOC_MAX_ENTRIES:
            doc = {k: v for k, v in index.items()
                   if k not in ("shards", "generation")}
            doc["count"] = len(entries)
            new_gen = self._cas_pointer(doc, expect_generation)
            for sid in old_shards:                 # drop any old shards
                _retry_transient(self._meta.document(sid).delete)
            return new_gen

        shards = [entries[i:i + SHARD_MAX_ENTRIES]
                  for i in range(0, len(entries), SHARD_MAX_ENTRIES)]
        # Version the shard ids per write (unique token) instead of reusing
        # fixed index_shard_<i> in place. Fixed ids let a concurrent reader load
        # the OLD pointer but the NEW shard content (torn read), and a lost CAS
        # left the winner's pointer over our shard bodies. With unique ids: new
        # shards are written first, the pointer CAS publishes them atomically,
        # and the OLD shards are deleted only after the CAS commits — so a
        # reader's pointer and shards always agree. A lost CAS cleans up its own
        # just-written shards so they don't orphan.
        token = f"{time.time_ns():x}"
        shard_ids = [f"{SHARD_PREFIX}{token}_{i}" for i in range(len(shards))]
        batch = self._db.batch()
        for sid, chunk in zip(shard_ids, shards):
            batch.set(self._meta.document(sid),
                      _firestore_safe({"problems": chunk}))
        _retry_transient(batch.commit)             # new shards first
        ptr = {k: v for k, v in index.items()
               if k not in ("problems", "generation")}
        ptr["shards"] = shard_ids
        ptr["count"] = len(entries)
        try:
            new_gen = self._cas_pointer(ptr, expect_generation)   # pointer last
        except IndexConflict:
            for sid in shard_ids:      # we lost the race; don't orphan our shards
                _retry_transient(self._meta.document(sid).delete)
            raise
        for sid in old_shards:         # pointer now references the new shards
            _retry_transient(self._meta.document(sid).delete)
        return new_gen

    def rebuild_index(self) -> dict:
        """Repair path: rebuild the index by streaming the WHOLE collection
        (O(N) reads — expensive; not used on the hot push path). Use only to
        recover after drift/corruption."""
        from .store import build_index
        index = build_index(self.stream_records(
            fields=["kind", "classification", "difficulty", "created_at",
                    "training"]))
        self.write_index(index)
        return index


def push_local_pool(local_dir: str | Path, key_path: str | None = None,
                    overwrite: bool = False, remote: "FirestorePool | None" = None
                    ) -> dict:
    """Upload every problem in a local JSON pool to Firestore.

    Cost: ONE index read (pointer + shards) regardless of pool size, plus one
    write per newly uploaded problem and the index write — never a full
    collection scan.

    The index update is an optimistic-locked read-union-write (T11): the docs
    are uploaded once (idempotent set), then the pointer is re-read and rewritten
    under a generation check; if a concurrent producer bumped the generation
    meanwhile, we re-read, re-union (so no one's entries are dropped) and retry.

    Returns {uploaded, skipped, total}. *remote* is injectable for testing.
    """
    from .store import ProblemPool, index_entry, index_from_entries

    local = ProblemPool(local_dir)
    remote = remote or FirestorePool(key_path)
    idx = remote.read_index() or {"problems": [], "generation": 0}
    have = {e["id"] for e in idx.get("problems", [])}

    # 1. upload the docs that are new to the current index (idempotent set).
    writer = remote._db.bulk_writer()
    new_entries = {}
    uploaded = skipped = 0
    try:
        for pid in local.ids():
            if pid in have and not overwrite:
                skipped += 1
                continue
            rec = local.get(pid)
            writer.set(remote._col.document(pid), _firestore_safe(rec))
            new_entries[pid] = index_entry(rec)
            uploaded += 1
    finally:
        writer.close()      # flush all buffered writes

    # 2. fold the new rows into the index under an optimistic lock, retrying on
    #    a concurrent write so no producer's entries are lost.
    if uploaded or overwrite:
        for attempt in range(_MAX_INDEX_CAS_RETRIES):
            cur = remote.read_index() or {"problems": [], "generation": 0}
            gen = cur.get("generation", 0)
            by_id = {e["id"]: e for e in cur.get("problems", [])}
            by_id.update(new_entries)
            try:
                remote.write_index(index_from_entries(by_id.values()),
                                   expect_generation=gen)
                break
            except IndexConflict:
                if attempt == _MAX_INDEX_CAS_RETRIES - 1:
                    # docs are uploaded but the index write kept losing the
                    # race; surface it so the operator can re-run (a re-push or
                    # rebuild_index reconciles — the set() writes are idempotent).
                    raise IndexConflict(
                        f"index update lost the race {_MAX_INDEX_CAS_RETRIES}x; "
                        f"{uploaded} docs uploaded but not yet indexed — re-run "
                        f"push (idempotent) or rebuild_index")
                time.sleep(0.5 * (attempt + 1))
    return {"uploaded": uploaded, "skipped": skipped, "total": len(local.ids())}


def backfill_lead_training(key_path: str | None = None,
                           dry_run: bool = False) -> dict:
    """Migration: mark every lead problem *in Firestore* with its training
    metadata and rebuild the index with per-problem mode flags.

    Legacy (algorithm-version-1) lead documents carry tricks-only evidence —
    no per-sample scores — so they can serve only the MP (Matchpoints) mode;
    this stamps them with ``scoring.lead_metrics.legacy_training_block`` so
    they stay readable and self-describing. Schema-2 documents (which already
    carry a ``training`` block with MP + IMP metrics) are left untouched.
    The rebuilt index gives every lead entry a ``modes`` list, which the web
    app's IMP tab filters on. Bidding docs are read but never written.

    Returns {lead_total, updated, total}. ``dry_run`` reports without writing.

    Rebuilds the index from a full snapshot (unconditional write), so run
    it when no producer is actively pushing — a concurrent push committed
    after this read would be dropped from the rebuilt index (T11).
    """
    from ..scoring.lead_metrics import legacy_training_block
    from .store import build_index

    remote = FirestorePool(key_path)
    records = remote.stream_records(
        fields=["kind", "contract", "classification", "difficulty",
                "created_at", "training"])
    updated = lead_total = 0
    block = legacy_training_block()
    for rec in records:
        if rec.get("kind") != "lead":
            continue
        lead_total += 1
        if rec.get("training"):
            continue
        rec["training"] = block
        updated += 1
        if not dry_run:
            _retry_transient(lambda rid=rec["id"]: remote._col.document(
                rid).set({"training": block}, merge=True))
    if not dry_run:
        remote.write_index(build_index(records))     # rebuild from memory
    return {"lead_total": lead_total, "updated": updated,
            "total": len(records)}


def backfill_lead_types(key_path: str | None = None,
                        dry_run: bool = False) -> dict:
    """Assign the opening-lead category to every lead problem *in Firestore*.

    Reads only the columns it needs (projection), computes each lead's category
    from the contract (engine/lead_classify.py — deterministic, no LLM), and
    writes back only ``classification.type`` (a merge, so difficulty_level is
    preserved). The index is rebuilt from the already-read rows (no second
    scan). Bidding docs are read but never written.

    Returns {lead_total, updated, total}. ``dry_run`` reports without writing.

    Rebuilds the index from a full snapshot (unconditional write), so run
    it when no producer is actively pushing — a concurrent push committed
    after this read would be dropped from the rebuilt index (T11).
    """
    from ..engine.lead_classify import classify_lead_record
    from .store import build_index

    remote = FirestorePool(key_path)
    records = remote.stream_records(
        fields=["kind", "contract", "classification", "difficulty",
                "created_at", "training"])
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
