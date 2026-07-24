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
# schema 2 = mode-aware lead records (MP + IMP metrics; engine/lead_maker).
# Version-1 records (bidding, and legacy tricks-only leads) stay readable.
SUPPORTED_SCHEMAS = (1, 2)


def index_entry(rec: dict) -> dict:
    """The lightweight per-problem row the web app reads for its list and
    filters (kind / type / difficulty). Shared by the local and Firestore
    index builders so both stay in lock-step."""
    cls = rec.get("classification", {})
    entry = {
        "id": rec["id"],
        # scenario router; legacy records predate it and are bidding
        "kind": rec.get("kind", "bidding"),
        "type": cls.get("type"),
        "difficulty": rec.get("difficulty"),
        "difficulty_level": cls.get("difficulty_level"),
        "created_at": rec.get("created_at"),
        # the record's own schema version (DB-M-7), so the index can report a
        # real schema_min/max instead of a hard-coded 1. Legacy records predate
        # the field and are schema 1.
        "schema": rec.get("schema", SCHEMA_VERSION),
    }
    if entry["kind"] == "lead":
        # training modes this problem can serve: legacy tricks-only records
        # are MP-only; schema-2 records carry IMP metrics too. The web app
        # filters the IMP tab on this flag.
        from ..scoring.lead_metrics import supported_modes, target_mode_of
        entry["modes"] = supported_modes(rec)
        # which mode's generator FORGED this board (whose gates found it
        # interesting); each trainer section serves its own generator's pool
        entry["target_mode"] = target_mode_of(rec)
    return entry


def index_from_entries(entries) -> dict:
    """Assemble the meta/index document from already-built index rows
    (newest first). Lets callers update the index incrementally without
    re-reading every problem document."""
    entries = sorted(entries, key=lambda e: e["created_at"] or "", reverse=True)
    # real schema span across the entries (DB-M-7). Default missing per-entry
    # schema to SCHEMA_VERSION so a bare/legacy entry (e.g. one without the
    # field) never KeyErrors here. `schema` stays = schema_min for backward
    # compatibility with any reader that still reads the scalar field.
    schemas = [e.get("schema", SCHEMA_VERSION) for e in entries]
    schema_min = min(schemas) if schemas else SCHEMA_VERSION
    schema_max = max(schemas) if schemas else SCHEMA_VERSION
    return {
        "schema": schema_min,
        "schema_min": schema_min,
        "schema_max": schema_max,
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
        if record.get("schema") not in SUPPORTED_SCHEMAS:
            raise ValueError(f"record schema must be one of "
                             f"{SUPPORTED_SCHEMAS}")
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
