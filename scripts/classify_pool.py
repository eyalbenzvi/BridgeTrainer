"""Assign classifications to pool records (idempotent, resumable).

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

Resilience: the LLM type classification runs in small chunks (default
DEFAULT_CHUNK_SIZE = 2 — larger chunks were observed to hang/truncate) and
EACH record is written back to disk as soon as its chunk returns. A killed
run therefore loses no completed work; re-running simply resumes on whatever
still lacks classification.type. Deterministic updates (difficulty, lead
category) are likewise written as they are computed.

Usage: python3 scripts/classify_pool.py <pool_dir> [--model MODEL]
                                        [--chunk-size N] [--difficulty-only]
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
                     "and retried, and each record is saved as its chunk "
                     "returns). Pass 0 to force the whole pool into one call — "
                     "fastest to load but risks a timeout/truncation hang on a "
                     "large pool, and forfeits the per-chunk resume.")
args = ap.parse_args()

pool = ProblemPool(args.pool_dir)


def _save(path: Path, rec: dict) -> None:
    path.write_text(json.dumps(rec, separators=(",", ":")))


# Pass 1: pure/deterministic work (difficulty for bidding, category for
# leads), written immediately so an interrupted run never loses or repeats it.
# Bidding records still missing an LLM type are collected for pass 2.
need_type = []        # bidding records missing classification.type
by_id = {}            # id -> path (for pass 2 writes)
done_already = 0
for path in sorted(pool.problems_dir.glob("*.json")):
    rec = json.loads(path.read_text())
    cls = rec.setdefault("classification", {})
    is_lead = rec.get("kind") == "lead"
    changed = False
    if "difficulty_level" not in cls and not is_lead:
        # leads set their own difficulty_level at generation; only bidding
        # records need the difficulty computation here.
        cls.update(difficulty_classification(rec))
        changed = True
    if "type" not in cls and not args.difficulty_only:
        if is_lead:
            # deterministic category from the contract — no LLM, never fails.
            cls["type"] = classify_lead_record(rec)
            changed = True
        else:
            need_type.append(rec)
            by_id[rec["id"]] = path
    elif "type" in cls:
        done_already += 1
    if changed:
        _save(path, rec)

# Pass 2: LLM type classification, chunk by chunk, writing each record the
# moment its chunk returns (resumable). chunk_size 0 means "one call for the
# whole pool" — one iteration, no per-chunk resume.
failed = []
done = 0
if need_type:
    step = args.chunk_size or len(need_type)
    inner = args.chunk_size or None
    print(f"classifying {len(need_type)} bidding problem(s) in "
          f"{'one call' if not args.chunk_size else f'chunks of {step}'} ...",
          file=sys.stderr, flush=True)
    for i in range(0, len(need_type), step):
        group = need_type[i:i + step]
        types = classify_records(group, model=args.model, chunk_size=inner,
                                 log=lambda m: print(m, file=sys.stderr,
                                                     flush=True))
        for rec in group:
            got = types.get(rec["id"])
            path = by_id[rec["id"]]
            if got:
                rec["classification"].update(got)
                _save(path, rec)
                done += 1
                cls = rec["classification"]
                print(f"{rec['id']}: level {cls.get('difficulty_level')} "
                      f"type {cls.get('type')}", file=sys.stderr, flush=True)
            else:
                failed.append(rec["id"])
                print(f"FAILED {rec['id']}: no valid classification returned",
                      file=sys.stderr, flush=True)
        print(f"progress: {done}/{len(need_type)} type-classified",
              file=sys.stderr, flush=True)

pool.rebuild_index()
print(f"{done} type-classified, {done_already} already done, "
      f"{len(failed)} failed" + (f" ({failed})" if failed else ""))
sys.exit(1 if failed else 0)
