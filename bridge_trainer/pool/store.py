"""The ever-growing problem pool.

v1 backend: a directory of JSON documents plus an index file, served as
static assets (deployed on the gh-pages branch under data/). The web app
fetches data/index.json, picks a random unseen id, then fetches
data/problems/<id>.json. The producer appends documents and rewrites the
index; nothing else in the site needs rebuilding.

The interface is deliberately database-shaped (add / list / get) so a
Firestore backend can replace it without touching the producer or the app.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1


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
        entries = []
        for pid in self.ids():
            rec = self.get(pid)
            entries.append({
                "id": pid,
                # legacy records predate the type field: they are all bidding
                "type": rec.get("type", "bidding"),
                "difficulty": rec.get("difficulty"),
                "created_at": rec.get("created_at"),
            })
        entries.sort(key=lambda e: e["created_at"] or "", reverse=True)
        index = {
            "schema": SCHEMA_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "count": len(entries),
            "problems": entries,
        }
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "index.json").write_text(
            json.dumps(index, separators=(",", ":")))
        return index
