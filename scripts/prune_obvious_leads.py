#!/usr/bin/env python3
"""Delete opening-lead problems that fail the corrected C1 "obvious" rule.

The rule: BEN's opening-lead policy, summed over the tied-best ANSWER set and
deduped by Ben's 32-card lead code (so touching honors count separately but
folded low spots share one code), must be <= threshold (default: the engine's
P_OBVIOUS). A
problem where BEN is that sure of the answer is obvious and not a real problem.

Operates directly on Firestore (the live pool), so it also catches records that
exist in the DB but not in the local git checkout. Run with the Firestore venv:

    $HOME/fbenv/bin/python scripts/prune_obvious_leads.py --key sa-key.json --dry-run
    $HOME/fbenv/bin/python scripts/prune_obvious_leads.py --key sa-key.json

Exits non-zero (leaving the DB untouched) if Firestore is unreachable, e.g. the
free-tier daily quota is exhausted (429) — safe to retry later.
"""
from __future__ import annotations

import argparse
import sys

from bridge_trainer.engine.lead_verdict import P_OBVIOUS  # single source of truth


def find_failures(records, threshold: float) -> list[str]:
    from bridge_trainer.engine.lead_classify import answer_policy_mass
    fails = []
    for r in records:
        if r.get("kind") != "lead":
            continue
        soft = {c["card"]: (c.get("ben_softmax") or 0)
                for c in r.get("candidates", [])}
        best = (r.get("verdict") or {}).get("accepted", [])
        if soft and best and answer_policy_mass(best, soft) > threshold:
            fails.append(r["id"])
    return sorted(fails)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=None,
                    help="service-account JSON (or GOOGLE_APPLICATION_CREDENTIALS)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report failures without deleting")
    ap.add_argument("--threshold", type=float, default=P_OBVIOUS)
    args = ap.parse_args(argv)

    from bridge_trainer.pool.firestore_store import FirestorePool

    try:
        pool = FirestorePool(args.key)
        records = pool.stream_records()
    except Exception as e:  # ResourceExhausted (429) etc.
        print(f"Firestore unreachable, no changes made: "
              f"{type(e).__name__}: {str(e)[:120]}", file=sys.stderr)
        return 2

    leads = [r for r in records if r.get("kind") == "lead"]
    fails = find_failures(records, args.threshold)
    print(f"lead problems: {len(leads)}  failing >{args.threshold:.2f}: "
          f"{len(fails)}")
    for pid in fails:
        print("  ", pid)
    if args.dry_run:
        print("dry-run: no deletions")
        return 0
    from bridge_trainer.pool.store import build_index
    drop = set(fails)
    for pid in fails:
        pool.remove(pid)
    # rebuild the index from the records already in memory (minus the dropped
    # ones) — no second full-collection scan.
    pool.write_index(build_index(r for r in records if r.get("id") not in drop))
    print(f"deleted {len(fails)} from Firestore; meta/index rebuilt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
