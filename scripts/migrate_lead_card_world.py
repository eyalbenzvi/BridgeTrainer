"""Backward migration: re-grade every stored lead problem on its card world.

The forward fix (engine/lead_maker._card_world_grade) grades new boards on
the distribution their own displayed GIB glosses describe. This script
brings the EXISTING pool to the same standard, in four phases:

  1. VALIDATE   every lead record's actual deal against its glosses'
                probabilistic promises (gloss_violations). A deal that
                contradicts its own lesson is unfixable -> delete.
  2. RECALIBRATE the clause miss weights on the VALIDATED subset (the
                future pool honours its glosses by construction, so the
                measured weights land near the strict clamp floor). Applied
                as runtime overrides; written to the repo calibration file
                only with --apply.
  3. REGRADE    each surviving record with grade_record_card_world:
                new verdict/by_mode/candidates/notes/difficulty computed on
                the card world; the answer may CHANGE (that is the point).
                Records whose answer flips between the calibrated and
                strict readings have no single answer -> delete.
                Records whose auction constrained nothing -> kept as-is.
  4. WRITE      with --apply: merge updated fields into the changed docs,
                delete the flagged ones (index-first remove; user attempts
                survive and regrade as missing_problem), then run
                regrade_attempts so stored history matches the new
                verdicts. DEFAULT IS DRY-RUN: full report, zero writes.

Usage:
  python scripts/migrate_lead_card_world.py --key sa.json                # dry
  python scripts/migrate_lead_card_world.py --key sa.json --limit 80    # sample
  python scripts/migrate_lead_card_world.py --key sa.json --workers 8 --apply
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bridge_trainer.engine.lead_card_world import (  # noqa: E402
    gloss_violations, grade_record_card_world)

_WORKER_OVERRIDES: dict = {}


def _init_worker(overrides: dict) -> None:
    from bridge_trainer.engine.lead_gib_constraints import (
        set_calibration_overrides)
    set_calibration_overrides(overrides)


def _regrade_one(args: tuple) -> dict:
    rec, seed, n_samples = args
    try:
        return grade_record_card_world(rec, seed=seed, n_samples=n_samples)
    except Exception as e:  # noqa: BLE001 — one bad record must not kill 3k
        return {"id": rec.get("id"), "status": "error",
                "detail": f"{type(e).__name__}: {e}"}


def validate_record(rec: dict) -> list[str]:
    entries = ((rec.get("explanations") or {}).get("auction")) or []
    fd = rec.get("full_deal") or {}
    if not fd:
        return []
    return gloss_violations(entries, fd, rec["hand"], rec["leader"])


def recalibrate(records: list[dict]) -> dict:
    """Fit clause weights on the gloss-validated records (phase 2)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "calibrate_gib_vocab",
        Path(__file__).resolve().parent / "calibrate_gib_vocab.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fitted = mod.fit_weights(mod.measure(records))
    return {k: e["weight"] for k, e in fitted.items()
            if e.get("weight") is not None}, fitted


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--key", default=None,
                    help="service-account JSON (Firestore pool)")
    ap.add_argument("--pool", default=None, help="local pool dir")
    ap.add_argument("--limit", type=int, default=0,
                    help="regrade only a random sample of this size (0=all)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--samples", type=int, default=400)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--apply", action="store_true",
                    help="WRITE: merge regraded fields, delete flagged "
                         "boards, update the calibration file, regrade "
                         "stored attempts. Default is a dry run.")
    ap.add_argument("--out", default=None, help="write the JSON report here")
    args = ap.parse_args()

    if args.key:
        from bridge_trainer.pool.firestore_store import FirestorePool
        pool = FirestorePool(args.key)
        ids = [i for i in pool.ids() if i.startswith("lead")]
    elif args.pool:
        from bridge_trainer.pool.store import ProblemPool
        pool = ProblemPool(args.pool)
        ids = [i for i in pool.ids() if i.startswith("lead")]
    else:
        ap.error("pass --key SA_JSON or --pool DIR")

    print(f"lead problems: {len(ids)}")
    records = []
    for pid in ids:
        rec = pool.get(pid)
        if rec.get("kind") == "lead":
            records.append(rec)

    # ---- phase 1: gloss validation (cheap, no DDS) ----------------------
    deletions: dict[str, str] = {}
    validated = []
    for rec in records:
        bad = validate_record(rec)
        if bad:
            deletions[rec["id"]] = "gloss_unfulfilled: " + "; ".join(bad[:3])
        else:
            validated.append(rec)
    print(f"phase 1 gloss validation: {len(deletions)} deals contradict "
          f"their own glosses, {len(validated)} validated")

    # ---- phase 2: recalibrate on the validated subset -------------------
    overrides, fitted = recalibrate(validated)
    print("phase 2 recalibrated weights (validated subset):")
    for kind, e in fitted.items():
        print(f"  {kind:18s} n={e['n']:5d} p={e['p']} -> w={e['weight']}")

    # ---- phase 3: regrade ------------------------------------------------
    todo = validated
    if args.limit and args.limit < len(todo):
        rng = random.Random(args.seed)
        todo = rng.sample(todo, args.limit)
        print(f"phase 3 sampling {len(todo)}/{len(validated)} boards")
    jobs = [(rec, args.seed, args.samples) for rec in todo]
    if args.workers > 1:
        with ProcessPoolExecutor(max_workers=args.workers,
                                 initializer=_init_worker,
                                 initargs=(overrides,)) as ex:
            reports = list(ex.map(_regrade_one, jobs, chunksize=4))
    else:
        _init_worker(overrides)
        reports = [_regrade_one(j) for j in jobs]

    by_status = Counter(r["status"] for r in reports)
    changed = [r for r in reports
               if r["status"] == "regraded" and r.get("answer_changed")]
    for r in reports:
        if r["status"] in ("honor_sensitive", "empty_set", "error"):
            deletions.setdefault(r["id"], f"{r['status']}: "
                                 f"{r.get('detail', '')}"[:200])
    print(f"\nphase 3 regrade: {dict(by_status)}")
    print(f"answers CHANGED on {len(changed)}/{len(reports)} regraded boards")
    for r in changed[:12]:
        print(f"  {r['id']}: {r['published']} -> {r['new_accepted']}")

    # ---- phase 4: writes -------------------------------------------------
    summary = {
        "lead_total": len(records),
        "gloss_unfulfilled": sum(
            1 for v in deletions.values() if v.startswith("gloss")),
        "regraded": by_status.get("regraded", 0),
        "answers_changed": len(changed),
        "honor_sensitive": by_status.get("honor_sensitive", 0),
        "no_constraints_kept": by_status.get("no_constraints", 0),
        "errors": by_status.get("error", 0),
        "deletions": len(deletions),
        "applied": bool(args.apply),
        "recalibrated_weights": overrides,
    }
    if args.apply:
        from bridge_trainer.engine.lead_gib_constraints import (
            CALIBRATION_PATH)
        CALIBRATION_PATH.write_text(json.dumps(fitted, indent=1) + "\n")
        from bridge_trainer.pool.firestore_store import _firestore_safe
        updated = 0
        for r in reports:
            if r["status"] == "regraded" and r["id"] not in deletions:
                pool._col.document(r["id"]).set(
                    _firestore_safe(r["update"]), merge=True)
                updated += 1
        removed = 0
        for pid in deletions:
            removed += bool(pool.remove(pid))
        print(f"\napplied: {updated} docs updated, {removed} deleted")
        summary.update(updated=updated, removed=removed)
        from bridge_trainer.pool.firestore_store import regrade_attempts
        summary["regrade_attempts"] = regrade_attempts(args.key)
    else:
        print("\nDRY RUN — no writes. Re-run with --apply to execute.")

    if args.out:
        Path(args.out).write_text(json.dumps(
            {"summary": summary, "reports": reports,
             "deletions": deletions}, indent=1, default=str))
        print(f"report written to {args.out}")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
