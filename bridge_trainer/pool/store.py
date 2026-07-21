"""The problem pool (local filesystem backend).

A directory of JSON documents plus an index file. This is now a SCRATCH
staging area for generation only — it is not committed and not served.
Production reads from Firestore (``pool.firestore_store``): the generator
writes problems here, then ``trainer pool push`` uploads them and the web
app fetches each document live from the ``problems`` collection.

The interface is deliberately database-shaped (add / list / get) so the
Firestore backend mirrors it without touching the producer.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1


def index_entry(rec: dict) -> dict:
    """The lightweight per-problem row the web app reads for its list and
    filters (kind / type / difficulty). Shared by the local and Firestore
    index builders so both stay in lock-step."""
    cls = rec.get("classification", {})
    return {
        "id": rec["id"],
        # scenario router; legacy records predate it and are bidding
        "kind": rec.get("kind", "bidding"),
        "type": cls.get("type"),
        "difficulty": rec.get("difficulty"),
        "difficulty_level": cls.get("difficulty_level"),
        "created_at": rec.get("created_at"),
    }


def index_from_entries(entries) -> dict:
    """Assemble the meta/index document from already-built index rows
    (newest first). Lets callers update the index incrementally without
    re-reading every problem document."""
    entries = sorted(entries, key=lambda e: e["created_at"] or "", reverse=True)
    return {
        "schema": SCHEMA_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(entries),
        "problems": entries,
    }


def build_index(records) -> dict:
    """Assemble the meta/index document from an iterable of problem records
    (newest first)."""
    return index_from_entries(index_entry(r) for r in records)


class ProblemPool:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.problems_dir = self.root / "problems"

    def add(self, record: dict) -> str:
        """Store one finished problem document. Returns its id."""
        if record.get("schema") != SCHEMA_VERSION:
            raise ValueError(f"record schema must be {SCHEMA_VERSION}")
        pid = record["id"]
        self.problems_dir.mkdir(parents=True, exist_ok=True)
        path = self.problems_dir / f"{pid}.json"
        if path.exists():
            raise FileExistsError(f"problem {pid} already in pool")
        path.write_text(json.dumps(record, separators=(",", ":")))
        return pid

    def ids(self) -> list[str]:
        if not self.problems_dir.exists():
            return []
        return sorted(p.stem for p in self.problems_dir.glob("*.json"))

    def get(self, pid: str) -> dict:
        return json.loads((self.problems_dir / f"{pid}.json").read_text())

    def rebuild_index(self) -> dict:
        """Rewrite data/index.json from the stored documents."""
        index = build_index(self.get(pid) for pid in self.ids())
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "index.json").write_text(
            json.dumps(index, separators=(",", ":")))
        return index
