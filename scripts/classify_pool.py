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

from bridge_trainer.engine.classify import MODEL, classify_record
from bridge_trainer.engine.difficulty import difficulty_classification
from bridge_trainer.engine.lead_classify import classify_lead_record
from bridge_trainer.pool.store import ProblemPool

ap = argparse.ArgumentParser()
ap.add_argument("pool_dir")
ap.add_argument("--model", default=MODEL)
ap.add_argument("--difficulty-only", action="store_true",
                help="skip the LLM type classification")
args = ap.parse_args()

pool = ProblemPool(args.pool_dir)
done = skipped = failed = 0
for path in sorted(pool.problems_dir.glob("*.json")):
    rec = json.loads(path.read_text())
    cls = rec.setdefault("classification", {})
    changed = False
    is_lead = rec.get("kind") == "lead"
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
            try:
                cls.update(classify_record(rec, model=args.model))
                changed = True
            except Exception as e:
                failed += 1
                print(f"FAILED {rec['id']}: {e}", file=sys.stderr)
    if changed:
        path.write_text(json.dumps(rec, separators=(",", ":")))
        done += 1
        print(f"{rec['id']}: level {cls.get('difficulty_level')} "
              f"(score {cls.get('difficulty_score')}) "
              f"type {cls.get('type', '-')}")
    else:
        skipped += 1

pool.rebuild_index()
print(f"{done} classified, {skipped} already done, {failed} failed")
sys.exit(1 if failed else 0)
