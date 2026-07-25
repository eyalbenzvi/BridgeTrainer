"""Audit published bidding problems with the CURRENT explanation gates and,
with --remove, delete the ones that would not be published today.

The gates in engine/explain_check.py run at generation time, so every board
forged before a gate existed was never vetted by it. This script closes that
gap: it re-runs them over stored records — the live Firestore pool or a local
pool dir — using the cards the record itself carries (no GIB refetch, so the
verdict of the audit is exactly what the stored explanations say).

Two levels:

  cheap (default, no engine, no network)
      ``record_violations``: every stem call and offered option's gloss vs the
      13 actual cards of the bidder, plus the forcing-pass rule (Pass offered
      while the hero's side is under a live force).

  --band (needs the Ben engine: BEN_HOME + the Ben venv)
      ``band_violations`` as well: Ben's OWN measured meaning of each non-pass
      stem call and each offered option — the HCP/suit-length statistics of the
      layouts its sampler accepts after that call — against the same glosses.
      Costs one sampling pass per checked call (~7 s per board), which is why
      it is opt-in.

Lead problems are skipped: both gates are bidding-shaped (stem + option
cards). Leads have their own pruning path (scripts/prune_obvious_leads.py).

Usage:
    python3 scripts/audit_pool.py --firestore [--key K] [--band] [--remove]
    python3 scripts/audit_pool.py <pool_dir> [--band]
    trainer pool audit --firestore --band            # same thing

Exit code 1 when offenders remain (audit without --remove), so CI can gate
on it; 0 when the pool is clean or the offenders were removed.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bridge_trainer.engine.explain_check import (band_violations,
                                                 record_violations)
from bridge_trainer.engine.scanner import SEATS, VUL_NAMES, Spot


def spot_from_record(rec: dict) -> Spot:
    """A Spot the band check can sample from, rebuilt out of a stored record.

    Only the fields band_violations reads are meaningful (hands, dealer, vul,
    stem, hero seat, candidates); seed/p_top/turns carry the record's own
    values or harmless placeholders."""
    vul = next(k for k, v in VUL_NAMES.items() if v == rec["vul"])
    return Spot(
        seed=(rec.get("generator") or {}).get("seed", 0),
        dealer_i=SEATS.index(rec["dealer"]), vul=vul,
        hands=[rec["full_deal"][s] for s in SEATS],
        stem=list(rec.get("auction") or []),
        hero_i=SEATS.index(rec["seat"]),
        candidates=[(c["call"], c.get("policy", 0.0))
                    for c in (rec.get("candidates") or [])],
        p_top=0.0, full_auction=list(rec.get("engine_auction_complete") or []))


def audit_record(rec: dict, engine=None) -> list[str]:
    """Every violation the current gates find in *rec*. With *engine*, the
    band half runs too."""
    fatal, _soft = record_violations(rec)
    if engine is None:
        return fatal
    ex = rec.get("explanations") or {}
    option_cards = {o["bid"]: o.get("card") for o in (ex.get("options") or [])
                    if o.get("bid")}
    return fatal + band_violations(engine, spot_from_record(rec),
                                   ex.get("stem") or [], option_cards)


def _local_records(pool_dir: str) -> list[dict]:
    out = []
    for p in sorted(Path(pool_dir).glob("problems/*.json")):
        out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pool", nargs="?", help="local pool dir (omit with "
                                           "--firestore)")
    ap.add_argument("--firestore", action="store_true",
                    help="audit the live Firestore pool")
    ap.add_argument("--key", default=None,
                    help="service-account JSON (or set "
                         "GOOGLE_APPLICATION_CREDENTIALS)")
    ap.add_argument("--band", action="store_true",
                    help="also run the engine band check (needs Ben)")
    ap.add_argument("--remove", action="store_true",
                    help="delete the offenders from Firestore (index first)")
    ap.add_argument("--limit", type=int, default=0,
                    help="audit at most N records (smoke runs)")
    ap.add_argument("--ids", default="",
                    help="comma-separated problem ids to audit (re-check a "
                         "finding, or remove one board's worth of them)")
    ap.add_argument("--out", default=None,
                    help="write the full findings to this JSON file")
    args = ap.parse_args(argv)
    if bool(args.pool) == bool(args.firestore):
        ap.error("give a pool dir OR --firestore")
    if args.remove and not args.firestore:
        ap.error("--remove only applies to --firestore")

    remote = None
    if args.firestore:
        from bridge_trainer.pool.firestore_store import FirestorePool
        remote = FirestorePool(args.key)
        records = remote.stream_records()
    else:
        records = _local_records(args.pool)
    records = [r for r in records if r.get("kind") != "lead"]
    if args.ids:
        want = {i.strip() for i in args.ids.split(",") if i.strip()}
        records = [r for r in records if r["id"] in want]
        missing = want - {r["id"] for r in records}
        if missing:
            print(f"not in the pool: {', '.join(sorted(missing))}")
    if args.limit:
        records = records[:args.limit]

    engine = None
    if args.band:
        from bridge_trainer.engine.ben import get_engine
        engine = get_engine()

    findings = {}
    for i, rec in enumerate(records, 1):
        try:
            bad = audit_record(rec, engine)
        except Exception as e:                       # never lose the report
            bad = [f"audit error ({type(e).__name__}: {e})"]
        if bad:
            findings[rec["id"]] = bad
            print(f"[{i}/{len(records)}] {rec['id']}: " +
                  "; ".join(bad[:3]) +
                  (f" (+{len(bad) - 3} more)" if len(bad) > 3 else ""),
                  flush=True)
        elif i % 25 == 0:
            print(f"[{i}/{len(records)}] clean so far: "
                  f"{i - len(findings)}/{i}", flush=True)

    print(f"\n{len(findings)} of {len(records)} bidding problems violate the "
          f"current gates ({'cheap + band' if engine else 'cheap only'})")
    if args.out:
        Path(args.out).write_text(json.dumps(findings, indent=1,
                                            ensure_ascii=False),
                                 encoding="utf-8")
        print(f"findings written to {args.out}")
    if findings and args.remove:
        gone = sum(bool(remote.remove(pid)) for pid in findings)
        print(f"deleted {gone} problem(s) from Firestore")
        return 0
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
