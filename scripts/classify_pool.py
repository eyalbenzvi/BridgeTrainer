"""Assign classifications to pool records (idempotent).

For every record in <pool_dir>/problems this ensures:
- classification.difficulty_score / difficulty_level — pure computation
  (bridge_trainer/engine/difficulty.py), recomputed only when missing;
- classification.type — for bidding records the LLM classifier
  (bridge_trainer/engine/classify.py, claude CLI headless; also sets
  type_reason). For lead records the category is a deterministic function of
  the final contract (bridge_trainer/engine/lead_classify.py) — no LLM.

Fully classified records are skipped, so the same script is the one-time
backfill AND the per-batch classification step after ben-forge. Rebuilds
the pool index at the end.

Usage: python3 scripts/classify_pool.py <pool_dir> [--model MODEL]
                                        [--difficulty-only]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bridge_trainer.engine.classify import (
    DEFAULT_CHUNK_SIZE, MODEL, classify_records)
from bridge_trainer.engine.difficulty import difficulty_classification
from bridge_trainer.engine.lead_classify import classify_lead_record
from bridge_trainer.pool.store import ProblemPool

ap = argparse.ArgumentParser()
ap.add_argument("pool_dir")
ap.add_argument("--model", default=MODEL)
ap.add_argument("--difficulty-only", action="store_true",
                help="skip the LLM type classification")
ap.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
                help="bidding problems per LLM call (default "
                     f"{DEFAULT_CHUNK_SIZE}; a chunk that hangs/fails is split "
                     "and retried). Pass 0 to force the whole pool into one "
                     "call — fastest to load but risks a timeout/truncation "
                     "hang on a large pool.")
args = ap.parse_args()

pool = ProblemPool(args.pool_dir)

# Pass 1: pure/deterministic work (difficulty for bidding, category for
# leads) and collect the bidding records that still need an LLM type. The
# type classification is then a handful of batched claude calls
# (classify_records, chunked), not one CLI launch per problem; whatever
# classifies successfully is returned even if some chunk hangs or fails.
records = {}          # path -> record
changed_paths = set()
need_type = []        # bidding records missing classification.type
for path in sorted(pool.problems_dir.glob("*.json")):
    rec = json.loads(path.read_text())
    records[path] = rec
    cls = rec.setdefault("classification", {})
    is_lead = rec.get("kind") == "lead"
    if "difficulty_level" not in cls and not is_lead:
        # leads set their own difficulty_level at generation; only bidding
        # records need the difficulty computation here.
        cls.update(difficulty_classification(rec))
        changed_paths.add(path)
    if "type" not in cls and not args.difficulty_only:
        if is_lead:
            # deterministic category from the contract — no LLM, never fails.
            cls["type"] = classify_lead_record(rec)
            changed_paths.add(path)
        else:
            need_type.append(rec)

failed = 0
if need_type:
    print(f"classifying {len(need_type)} bidding problem(s) in "
          f"{'one call' if not args.chunk_size else f'chunks of {args.chunk_size}'} "
          f"...", file=sys.stderr)
    by_id = {r["id"]: p for p, r in records.items()}
    types = classify_records(need_type, model=args.model,
                             chunk_size=args.chunk_size or None,
                             log=lambda m: print(m, file=sys.stderr))
    for rec in need_type:
        got = types.get(rec["id"])
        if got:
            rec["classification"].update(got)
            changed_paths.add(by_id[rec["id"]])
        else:
            failed += 1
            print(f"FAILED {rec['id']}: no valid classification returned",
                  file=sys.stderr)

for path in sorted(changed_paths):
    rec = records[path]
    cls = rec["classification"]
    path.write_text(json.dumps(rec, separators=(",", ":")))
    print(f"{rec['id']}: level {cls.get('difficulty_level')} "
          f"(score {cls.get('difficulty_score')}) "
          f"type {cls.get('type', '-')}")

pool.rebuild_index()
print(f"{len(changed_paths)} classified, "
      f"{len(records) - len(changed_paths)} already done, {failed} failed")
sys.exit(1 if failed else 0)
