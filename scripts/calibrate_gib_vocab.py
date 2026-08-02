"""Calibrate the GIB-clause miss weights against REAL deals.

For every probabilistic clause kind in the GIB vocabulary (stops, partial
stops, honor holdings, solid suits, ...) this measures, over the pool's
stored complete deals:

  p   = P(the announcing seat's ACTUAL hand satisfies the clause's core)
  p0  = the same test on the OTHER concealed seats of the same deals
        (the unconditional base rate)

and converts them into the miss weight the compiler applies to the
"announced but doesn't hold it" region — the aggregate likelihood ratio

  weight = [(1-p)/p] * [p0/(1-p0)]      (clamped to [0.02, 0.90])

so the sampler's posterior odds of "holds it" given the announcement match
the measured odds, instead of a hand-invented constant. Kinds with fewer
than --min-n observations keep the compiler default (reported, not fitted).

Output: bridge_trainer/semantics/gib_calibration.json (checked in; loaded
automatically by engine/lead_gib_constraints.miss_weight).

Usage:
  python scripts/calibrate_gib_vocab.py --key sa.json
  python scripts/calibrate_gib_vocab.py --pool data --out /tmp/cal.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bridge_trainer.engine.lead_gib_constraints import (  # noqa: E402
    CALIBRATION_PATH, DEFAULT_MISS_WEIGHTS, _clauses, clause_core_satisfied,
    clause_kind)

MIN_N = 30
CLAMP = (0.02, 0.90)


def measure(records) -> dict:
    """{kind: {n, hold, base_n, base_hold}} over all lead records."""
    stats = defaultdict(lambda: {"n": 0, "hold": 0,
                                 "base_n": 0, "base_hold": 0})
    for rec in records:
        if rec.get("kind") != "lead":
            continue
        fd = rec.get("full_deal") or {}
        leader = rec.get("leader")
        hand = rec.get("hand")
        if not fd or not leader or not hand:
            continue
        for e in (rec.get("explanations") or {}).get("auction") or []:
            seat = e.get("seat")
            raw = ((e.get("card") or {}).get("gib_raw")) or ""
            if seat not in fd:
                continue
            for clause in _clauses(raw):
                kind = clause_kind(clause)
                if kind is None:
                    continue
                sat = clause_core_satisfied(clause, hand, fd[seat])
                if sat is None:
                    continue
                st = stats[kind]
                st["n"] += 1
                st["hold"] += int(sat)
                for other, other_hand in fd.items():
                    if other in (seat, leader):
                        continue
                    base = clause_core_satisfied(clause, hand, other_hand)
                    if base is not None:
                        st["base_n"] += 1
                        st["base_hold"] += int(base)
    return dict(stats)


def fit_weights(stats: dict, min_n: int = MIN_N) -> dict:
    """Laplace-smoothed likelihood ratios (add-1/2), so the extremes a
    VALIDATED pool produces (p -> 1.0 once gloss-contradicting boards can no
    longer ship) fit cleanly to the near-strict clamp floor instead of
    falling back to the un-validated defaults."""
    out = {}
    for kind, st in sorted(stats.items()):
        n, hold = st["n"], st["hold"]
        bn, bh = st["base_n"], st["base_hold"]
        entry = {"n": n, "p": round(hold / n, 4) if n else None,
                 "base_n": bn, "p0": round(bh / bn, 4) if bn else None}
        if n >= min_n and bn >= min_n:
            p = (hold + 0.5) / (n + 1)
            p0 = (bh + 0.5) / (bn + 1)
            w = ((1 - p) / p) * (p0 / (1 - p0))
            entry["weight"] = round(min(max(w, CLAMP[0]), CLAMP[1]), 4)
        else:
            entry["weight"] = None      # keep the compiler default
            entry["kept_default"] = DEFAULT_MISS_WEIGHTS.get(kind)
        out[kind] = entry
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pool", default=None, help="local pool dir (data/)")
    ap.add_argument("--key", default=None,
                    help="service-account JSON -> calibrate on Firestore")
    ap.add_argument("--min-n", type=int, default=MIN_N)
    ap.add_argument("--out", default=str(CALIBRATION_PATH))
    args = ap.parse_args()

    if args.key:
        from bridge_trainer.pool.firestore_store import FirestorePool
        records = FirestorePool(args.key).stream_records(
            fields=["kind", "full_deal", "leader", "hand", "explanations"])
    elif args.pool:
        from bridge_trainer.pool.store import ProblemPool
        pool = ProblemPool(args.pool)
        records = [pool.get(pid) for pid in pool.ids()]
    else:
        ap.error("pass --pool DIR or --key SA_JSON")

    stats = measure(records)
    fitted = fit_weights(stats, args.min_n)
    for kind, entry in fitted.items():
        print(f"{kind:18s} n={entry['n']:5d} p={entry['p']}"
              f"  p0={entry['p0']}  -> weight={entry['weight']}"
              + ("" if entry["weight"] is not None
                 else f" (default {entry.get('kept_default')})"))
    Path(args.out).write_text(json.dumps(fitted, indent=1) + "\n")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
