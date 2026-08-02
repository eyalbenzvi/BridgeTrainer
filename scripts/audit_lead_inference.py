"""Re-grade stored lead problems under their own auction's GIB constraints.

For each lead problem this rebuilds the public state, derives a
ConstraintProfile from the problem's persisted GIB explanation cards
(engine/lead_gib_constraints.py — hcp/length bands, announced stops, silence
denials), samples card-conserving layouts with the existing Ben-free
ConstraintSampler, grades every physical lead with endplay DDS, and compares
the winner against the published verdict.

The verdict per board is engine/lead_gib_constraints.inference_verdict —
the SAME definition the forge gate now applies, so pool audit and forge
cannot drift:

  * ``inference_refuted``  the published answer loses decisively in some
                           reading — the board's answer is contradicted by
                           the auction's own stated meaning. Delete it.
  * ``honor_sensitive``    the soft and strict readings crown different
                           winners — there is no single answer to teach.
                           Delete it (the forge regenerates better boards).
  * ``stable`` / ``abstain``  keep.

``--purge`` deletes the flagged boards in place (Firestore: index-first
``remove``, same machinery as the forcing-pass/menu purges; stored user
attempts are left untouched and regrade as ``missing_problem``).

Usage:
  python scripts/audit_lead_inference.py --pool data --ids lead1-19fa5daef4b
  python scripts/audit_lead_inference.py --key sa.json --all-leads --out r.json
  python scripts/audit_lead_inference.py --key sa.json --all-leads --purge
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bridge_trainer.engine.lead_gib_constraints import (  # noqa: E402
    inference_verdict, regrade_readings)


def audit_record(rec: dict, samples: int, seed: int, n_boot: int) -> dict:
    """Grade the board under BOTH interpretation strengths of its own GIB
    cards — soft (default miss mass on announced stops) and strict (stops
    taken literally) — and judge the published answer with the SAME
    ``inference_verdict`` the forge gate applies, so the pool audit and the
    forge cannot drift (lead1-19fa5daef4b: SA soft, a passive diamond
    strict => inference_refuted)."""
    readings = regrade_readings(rec, samples=samples, seed=seed,
                                n_boot=n_boot)
    published = list((rec.get("verdict") or {}).get("accepted") or [])
    status, detail = inference_verdict(published[0] if published else None,
                                       readings)
    return {"id": rec["id"], "contract": rec["contract"],
            "published": published, "status": status, "detail": detail,
            "answer_unstable": status in ("inference_refuted",
                                          "honor_sensitive"),
            "soft": readings.get("soft", {}),
            "strict": readings.get("strict", {})}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pool", default=None, help="local pool dir (data/)")
    ap.add_argument("--key", default=None,
                    help="service-account JSON -> audit Firestore problems")
    ap.add_argument("--ids", nargs="*", default=None)
    ap.add_argument("--all-leads", action="store_true")
    ap.add_argument("--samples", type=int, default=400)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--out", default=None)
    ap.add_argument("--purge", action="store_true",
                    help="DELETE flagged boards (inference_refuted / "
                         "honor_sensitive) from the pool after the audit")
    args = ap.parse_args()

    if args.key:
        from bridge_trainer.pool.firestore_store import FirestorePool
        pool = FirestorePool(args.key)
    elif args.pool:
        from bridge_trainer.pool.store import ProblemPool
        pool = ProblemPool(args.pool)
    else:
        ap.error("pass --pool DIR or --key SA_JSON")

    ids = list(args.ids or [])
    if args.all_leads:
        ids = [i for i in pool.ids() if i.startswith("lead")]
    if not ids:
        ap.error("no ids: pass --ids ... or --all-leads")

    reports = []
    for pid in ids:
        rec = pool.get(pid)
        if rec.get("kind") != "lead":
            continue
        rep = audit_record(rec, args.samples, args.seed, args.n_boot)
        reports.append(rep)
        print(f"{rep['id']}: {rep['status']}"
              f"  published={rep.get('published')}"
              f"  soft_winner={rep['soft'].get('winner')}"
              f"  strict_winner={rep['strict'].get('winner')}")

    if args.out:
        Path(args.out).write_text(json.dumps(reports, indent=1))
        print(f"wrote {args.out}")
    unstable = [r["id"] for r in reports if r.get("answer_unstable")]
    print(f"\n{len(reports)} audited, {len(unstable)} unstable: {unstable}")
    if args.purge and unstable:
        if not hasattr(pool, "remove"):
            print("--purge needs the Firestore pool (--key); local pools "
                  "have no remove — delete data/problems/<id>.json and "
                  "rebuild the index instead")
            return 1
        removed = 0
        for pid in unstable:                # index-first delete, per board
            removed += bool(pool.remove(pid))
        print(f"purged {removed}/{len(unstable)} flagged boards")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
