"""Firestore backend for the problem pool.

Mirrors the ``ProblemPool`` interface (add / ids / get) but stores each
problem as a document in the ``problems`` collection, so the web app reads
them live — a newly generated problem is on the site immediately, with no
pull request and no redeploy.

Writing needs the Firebase Admin SDK and a service-account key (kept locally,
never committed). See ``docs/firebase_setup.md``. The dependency is imported
lazily so the rest of the package works without ``firebase-admin`` installed.

Typical use (generate locally, push to the DB)::

    trainer pool add --count 5              # writes data/*.json locally
    trainer pool push --key sa-key.json     # uploads the pool to Firestore
"""
from __future__ import annotations

import os
from pathlib import Path

COLLECTION = "problems"


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


class FirestorePool:
    """add / ids / get against the Firestore ``problems`` collection."""

    def __init__(self, key_path: str | None = None):
        self._db = _client(key_path)
        self._col = self._db.collection(COLLECTION)

    def add(self, record: dict, *, overwrite: bool = False) -> str:
        pid = record["id"]
        ref = self._col.document(pid)
        if not overwrite and ref.get().exists:
            raise FileExistsError(f"problem {pid} already in Firestore")
        ref.set(_firestore_safe(record))
        return pid

    def ids(self) -> list[str]:
        return sorted(d.id for d in self._col.stream())

    def get(self, pid: str) -> dict:
        snap = self._col.document(pid).get()
        if not snap.exists:
            raise KeyError(pid)
        return snap.to_dict()

    def remove(self, pid: str) -> bool:
        ref = self._col.document(pid)
        if not ref.get().exists:
            return False
        ref.delete()
        return True

    def write_index(self, index: dict) -> None:
        """Store the lightweight pool index at meta/index.

        The web app reads this ONE document to build its problem list and
        filters, instead of reading every problem doc (read-count economy).
        """
        self._db.collection("meta").document("index").set(
            _firestore_safe(index))


def push_local_pool(local_dir: str | Path, key_path: str | None = None,
                    overwrite: bool = False) -> dict:
    """Upload every problem in a local JSON pool to Firestore.

    Returns a summary dict {uploaded, skipped, total}. Existing documents are
    skipped unless *overwrite* is set.
    """
    from .store import ProblemPool

    local = ProblemPool(local_dir)
    remote = FirestorePool(key_path)
    existing = set(remote.ids()) if not overwrite else set()
    uploaded = skipped = 0
    for pid in local.ids():
        if pid in existing:
            skipped += 1
            continue
        remote.add(local.get(pid), overwrite=overwrite)
        uploaded += 1
    # Refresh the meta/index doc so the app sees the new problems/filters.
    remote.write_index(local.rebuild_index())
    return {"uploaded": uploaded, "skipped": skipped, "total": len(local.ids())}
