"""Re-grade stored lead problems under their own auction's GIB constraints.

For each lead problem this rebuilds the public state, derives a
ConstraintProfile from the problem's persisted GIB explanation cards
(engine/lead_gib_constraints.py — hcp/length bands, announced stops, silence
denials), samples card-conserving layouts with the existing Ben-free
ConstraintSampler, grades every physical lead with endplay DDS, and compares
the winner against the published verdict.

A board is flagged ``answer_unstable`` when the published single answer is
no longer the weighted-mean winner under the auction-constrained
distribution, or the published gap collapses below the noise floor (CI on
the published-winner-minus-constraint-winner delta includes 0). Those boards
should be re-audited (docs/lead_auction_inference_gap.md) before being kept
as single-answer problems.

Usage:
  python scripts/audit_lead_inference.py --pool data --ids lead1-19fa5daef4b
  python scripts/audit_lead_inference.py --key sa.json --all-leads --out r.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from bridge_trainer.engine.lead_posterior import (  # noqa: E402
    build_problem, delta_report, evaluate_layouts)
from bridge_trainer.engine.lead_gib_constraints import (  # noqa: E402
    sampler_from_record)


def _one_reading(rec, problem, samples, seed, n_boot, miss_scale) -> dict:
    sampler = sampler_from_record(rec, stop_miss_scale=miss_scale,
                                  max_seconds=120.0)
    ls = sampler.sample(problem, samples, seed)
    out = {"constraint_diagnostics": getattr(ls, "constraint_diagnostics", {})}
    if ls.n == 0:
        out["status"] = "empty_accepted_set"
        return out
    ev = evaluate_layouts(ls)
    means = ev.weighted_mean()
    order = ev.ranking()
    out["winner"] = order[0]
    out["lead_means"] = {c: round(means[c], 3) for c in order}
    published = ((rec.get("verdict") or {}).get("accepted") or [None])[0]
    if published and published in ev.def_tricks:
        dr = delta_report(ev.def_tricks[published], ev.def_tricks[order[0]],
                          weight=ls.weight, n_boot=n_boot, seed=seed)
        out["published_vs_winner"] = {
            "delta": dr["mean"], "ci95": dr["boot_ci95"], "ess": dr["ess"]}
        lost = published != order[0] and not (
            dr["boot_ci95"][0] <= 0 <= dr["boot_ci95"][1])
        out["status"] = ("published_loses" if lost else
                         "published_ties" if published != order[0]
                         else "stable")
    else:
        out["status"] = "no_published_answer"
    return out


def audit_record(rec: dict, samples: int, seed: int, n_boot: int) -> dict:
    """Grade the board under BOTH interpretation strengths of its own GIB
    cards: default (soft miss mass on announced stops) and strict (stops
    taken literally). The published answer must survive both to be stable —
    a winner that changes across readings is honor-location-sensitive
    (lead1-19fa5daef4b: SA under soft, a passive diamond under strict)."""
    problem = build_problem(rec["hand"], list(rec["auction"]), rec["dealer"],
                            rec.get("vul", "None"), rec["contract"])
    out = {"id": rec["id"], "contract": rec["contract"],
           "published": list((rec.get("verdict") or {}).get("accepted") or [])}
    out["soft"] = _one_reading(rec, problem, samples, seed, n_boot, 1.0)
    out["strict"] = _one_reading(rec, problem, samples, seed, n_boot, 0.0)
    statuses = {out["soft"]["status"], out["strict"]["status"]}
    winners = {out["soft"].get("winner"), out["strict"].get("winner")}
    published = set(out["published"])
    if statuses == {"stable"}:
        out["status"] = "stable"
    elif "published_loses" in statuses:
        out["status"] = "published_loses"
    elif not winners <= published and len(winners - {None}) > 1:
        out["status"] = "honor_sensitive"
    else:
        out["status"] = "|".join(sorted(statuses))
    out["answer_unstable"] = out["status"] != "stable"
    return out


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
