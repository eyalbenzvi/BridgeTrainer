"""One-time schema canonicalization over the pool (ARCH-9).

Applies bridge_trainer.pool.migrate.canonicalize_record to every problem —
stamping the real schema version, ensuring classification is a dict, and adding
the `bid` alias to legacy `action`-keyed verdict rows — so the web client can
eventually drop its read-time legacy branches.

DRY-RUN BY DEFAULT: it only reports what would change. Pass --overwrite to
actually write. This must be run against the live DB in coordination with the
client cleanup (removing normalize()'s legacy branches), which is a SEPARATE
approved step — do not remove those branches until this has run. See
docs/infra_fixes_plan_round2.md.

Usage:
    python3 scripts/migrate_schema.py <pool_dir>              # local, dry-run
    python3 scripts/migrate_schema.py --firestore [--key K]   # live, dry-run
    python3 scripts/migrate_schema.py --firestore --overwrite # live, WRITE
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bridge_trainer.pool.migrate import canonicalize_record, detect_schema


def _records(args):
    """Yield (id, record, writer) where writer(new_rec) persists it."""
    if args.firestore:
        from bridge_trainer.pool.firestore_store import FirestorePool
        pool = FirestorePool(args.key)
        for pid in pool.ids():
            rec = pool.get(pid)
            yield pid, rec, (lambda r, p=pid: pool.add(r, overwrite=True))
    else:
        from bridge_trainer.pool.store import ProblemPool
        pool = ProblemPool(args.pool_dir)
        for pid in pool.ids():
            rec = pool.get(pid)

            def _w(r, p=pid):
                (pool.problems_dir / f"{p}.json").write_text(
                    __import__("json").dumps(r, separators=(",", ":")))
            yield pid, rec, _w


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pool_dir", nargs="?", help="local pool dir")
    ap.add_argument("--firestore", action="store_true",
                    help="operate on the live Firestore pool")
    ap.add_argument("--key", help="service-account JSON (Firestore)")
    ap.add_argument("--overwrite", action="store_true",
                    help="write changes (default: dry-run report only)")
    args = ap.parse_args()
    if not args.firestore and not args.pool_dir:
        ap.error("give a pool_dir or --firestore")

    before = Counter()
    changed = 0
    total = 0
    for pid, rec, write in _records(args):
        total += 1
        before[detect_schema(rec)] += 1
        new_rec, did = canonicalize_record(rec)
        if did:
            changed += 1
            if args.overwrite:
                write(new_rec)
    mode = "WROTE" if args.overwrite else "would change (dry-run)"
    print(f"scanned {total} records; schema histogram (by content): "
          f"{dict(sorted(before.items()))}")
    print(f"{mode}: {changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
