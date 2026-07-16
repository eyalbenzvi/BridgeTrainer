"""Backfill auction/option notes onto existing pool records.

Usage: python3 scripts/attach_notes.py <notes.json> <pool_dir>
notes.json: {"<id>": {"stem_explanations": [...],
                      "option_explanations": {opt: {shows, partner}}}}
"""
import json
import sys
from pathlib import Path

notes = json.loads(Path(sys.argv[1]).read_text())
pool = Path(sys.argv[2])

for path in sorted((pool / "problems").glob("*.json")):
    rec = json.loads(path.read_text())
    n = notes.get(rec["id"])
    if n is None:
        raise SystemExit(f"no notes for {rec['id']}")
    stem_notes = n["stem_explanations"]
    opt_notes = n["option_explanations"]
    if len(stem_notes) != len(rec["auction"]):
        raise SystemExit(f"{rec['id']}: {len(stem_notes)} notes for "
                         f"{len(rec['auction'])} calls")
    if set(opt_notes) != set(rec["candidates"]):
        raise SystemExit(f"{rec['id']}: option notes mismatch")
    for spec in opt_notes.values():
        if not spec.get("shows") or not spec.get("partner"):
            raise SystemExit(f"{rec['id']}: empty note text")
    rec["auction_notes"] = stem_notes
    rec["option_notes"] = opt_notes
    path.write_text(json.dumps(rec, separators=(",", ":")))
    print("noted", rec["id"])
