"""Incremental, resumable LLM type-classification for a local pool.

Same taxonomy/prompt as scripts/classify_pool.py, but:
  - small chunks (default 3) instead of 10, and
  - writes each classified record back to disk immediately after its chunk
    returns, so a killed process never loses completed work and a re-run
    simply resumes on whatever still lacks classification.type.

Difficulty (pure computation) is already set at generation time; this only
fills in classification.type / type_reason via the claude CLI, then rebuilds
the pool index.

Usage: python3 scripts/classify_incremental.py <pool_dir> [--chunk-size N]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bridge_trainer.engine.classify import MODEL, classify_records
from bridge_trainer.pool.store import ProblemPool

ap = argparse.ArgumentParser()
ap.add_argument("pool_dir")
ap.add_argument("--model", default=MODEL)
ap.add_argument("--chunk-size", type=int, default=3)
args = ap.parse_args()

pool = ProblemPool(args.pool_dir)
paths = sorted(pool.problems_dir.glob("*.json"))

# collect records still missing a type (resumable)
need = []
by_id = {}
for p in paths:
    rec = json.loads(p.read_text())
    if rec.get("kind") == "lead":
        continue  # leads are deterministic; not handled here
    if "type" not in rec.setdefault("classification", {}):
        need.append(rec)
        by_id[rec["id"]] = p

print(f"{len(need)} problem(s) need a type; chunk size {args.chunk_size}",
      file=sys.stderr, flush=True)

done = 0
failed = []
for i in range(0, len(need), args.chunk_size):
    chunk = need[i:i + args.chunk_size]
    # classify_records already splits/retries a failing chunk down to 1
    types = classify_records(chunk, model=args.model,
                             chunk_size=args.chunk_size,
                             log=lambda m: print(m, file=sys.stderr, flush=True))
    for rec in chunk:
        got = types.get(rec["id"])
        p = by_id[rec["id"]]
        if got:
            rec["classification"].update(got)
            p.write_text(json.dumps(rec, separators=(",", ":")))
            done += 1
            print(f"  {rec['id']}: {got['type']}", file=sys.stderr, flush=True)
        else:
            failed.append(rec["id"])
            print(f"  FAILED {rec['id']}", file=sys.stderr, flush=True)
    print(f"progress: {done}/{len(need)} written", file=sys.stderr, flush=True)

pool.rebuild_index()
print(f"DONE: {done} classified, {len(failed)} failed"
      + (f" ({failed})" if failed else ""), file=sys.stderr, flush=True)
sys.exit(1 if failed else 0)
