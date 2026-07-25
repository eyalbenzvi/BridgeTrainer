"""Audit published problems with the CURRENT explanation gates and, with
--remove, delete the ones that would not be published today.

The gates in engine/explain_check.py run at generation time, so every board
forged before a gate existed was never vetted by it. This script closes that
gap: it re-runs them over stored records — the live Firestore pool or a local
pool dir — using the cards the record itself carries (no GIB refetch, so the
verdict of the audit is exactly what the stored explanations say).

Three levels:

  cheap (default, no engine, no network)
      ``record_violations``: every stem call and offered option's gloss vs the
      13 actual cards of the bidder, the forcing-pass rule (Pass offered while
      the hero's side is under a live force), an unexplained conventional call
      (R2) and a forcing candidate the rollout leaves in as the contract (R3).

  --band (needs the Ben engine: BEN_HOME + the Ben venv)
      ``band_violations`` as well: Ben's OWN measured meaning of each non-pass
      stem call and each offered option — the HCP/suit-length statistics of the
      layouts its sampler accepts after that call — against the same glosses.
      Costs one sampling pass per checked call (~7 s per board), which is why
      it is opt-in.

  --rollout (needs the Ben engine too)
      R1, ``answer_insensitive_violations``: re-rolls the board's candidates
      and fires when partner answered differently on different layouts while
      the final contract never moved. No record stores the rollout auctions, so
      this is the only way to vet a published board for it — and it is the only
      way to tell that defect from a legitimately forced continuation, which is
      why ``point_mass_suspects`` (printed as SUSPECT, never removed) is a
      pre-filter and not a verdict. ~40 s per board; combine with --ids or
      --suspects-only to pay it on the shortlist.

Lead problems are audited with ``lead_record_violations`` — the same
gloss-vs-cards rule over the complete auction they display, which is the whole
evidence a leader reads. The band and rollout checks do not apply to them (they
offer cards, not calls), so those flags change nothing for leads.

Usage:
    python3 scripts/audit_pool.py --firestore [--key K] [--band] [--remove]
    python3 scripts/audit_pool.py --firestore --rollout --suspects-only
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

from bridge_trainer.engine.explain_check import (answer_insensitive_violations,
                                                 band_violations,
                                                 lead_record_violations,
                                                 point_mass_suspects,
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


ROLLOUT_SAMPLES = 128   # R1 is structural (argmax on a fixed hero hand), so
                        # the screen-size pool shows it as clearly as 512 and
                        # costs a quarter as much


def rollout_violations(rec: dict, engine) -> list[str]:
    """R1 for a stored record: re-roll the board's own candidates on freshly
    sampled layouts and run ``answer_insensitive_violations`` on the result.

    The record keeps only the contract counts, so the rollout has to be redone
    to see partner's replies. Ben's sampler reseeds deterministically off the
    hero's hand, so this is a faithful re-run of the same board rather than a
    fresh experiment."""
    spot = spot_from_record(rec)
    bot = engine.bot(spot.hands[spot.hero_i], spot.hero_i, spot.dealer_i,
                     spot.vul)
    cands = [c for c, _p in spot.candidates]
    padded, hands_np, hands_pbn, quality = engine.sample_for_auction(
        bot, spot.dealer_i, spot.stem, n_samples=ROLLOUT_SAMPLES)
    ev = engine.rollout_eval(bot, padded, cands, hands_np, hands_pbn, quality,
                             dd_memo={})
    return answer_insensitive_violations(ev, spot.stem)


def audit_record(rec: dict, engine=None, rollout: bool = False,
                 band: bool = True) -> list[str]:
    """Every violation the current gates find in *rec*. With *engine*, the
    engine-level halves run too: the band check (unless *band* is off) and,
    with *rollout*, the R1 re-roll (bidding boards only — a lead board has no
    candidate calls whose measured meaning could be sampled).

    *band* is separate from ``engine is None`` so that --rollout alone reports
    R1 without the band check's findings mixed in; both flags create the
    engine, and each check answers for itself."""
    if rec.get("kind") == "lead":
        return lead_record_violations(rec)
    fatal, _soft = record_violations(rec)
    if engine is None:
        return fatal
    ex = rec.get("explanations") or {}
    option_cards = {o["bid"]: o.get("card") for o in (ex.get("options") or [])
                    if o.get("bid")}
    if band:
        fatal = fatal + band_violations(engine, spot_from_record(rec),
                                        ex.get("stem") or [], option_cards)
    if rollout:
        fatal += rollout_violations(rec, engine)
    return fatal


def record_suspects(rec: dict) -> list[str]:
    """R1's record-only pre-filter — reported, never removed."""
    if rec.get("kind") == "lead":
        return []
    return point_mass_suspects((rec.get("verdict") or {}).get("table") or [],
                               (rec.get("quality") or {}).get("n_samples") or 0)


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
                    help="also run the engine band check on bidding boards "
                         "(needs Ben)")
    ap.add_argument("--rollout", action="store_true",
                    help="also re-roll each bidding board and run R1, the "
                         "answer-insensitive-ask check (needs Ben; ~40s/board)")
    ap.add_argument("--suspects-only", action="store_true",
                    help="audit only the boards R1's cheap pre-filter flags "
                         "(a point-mass projection past the candidate) — the "
                         "shortlist --rollout is worth paying for")
    ap.add_argument("--remove", action="store_true",
                    help="delete the offenders from Firestore (index first)")
    ap.add_argument("--limit", type=int, default=0,
                    help="audit at most N records (smoke runs)")
    ap.add_argument("--kind", choices=("bidding", "lead"), default=None,
                    help="audit only this problem kind (default: both)")
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
    if args.kind:
        records = [r for r in records
                   if (r.get("kind") or "bidding") == args.kind]
    if args.ids:
        want = {i.strip() for i in args.ids.split(",") if i.strip()}
        records = [r for r in records if r["id"] in want]
        missing = want - {r["id"] for r in records}
        if missing:
            print(f"not in the pool: {', '.join(sorted(missing))}")
    suspects = {}
    for rec in records:
        s = record_suspects(rec)
        if s:
            suspects[rec["id"]] = s
    if args.suspects_only:
        records = [r for r in records if r["id"] in suspects]
        print(f"auditing the {len(records)} point-mass suspect(s) only")
    if args.limit:
        records = records[:args.limit]

    engine = None
    if args.band or args.rollout:
        from bridge_trainer.engine.ben import get_engine
        engine = get_engine()

    findings = {}
    for i, rec in enumerate(records, 1):
        try:
            bad = audit_record(rec, engine, rollout=args.rollout,
                               band=args.band)
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

    level = "cheap only"
    if engine:
        level = "cheap + " + " + ".join(
            k for k, on in (("band", args.band), ("rollout", args.rollout))
            if on)
    print(f"\n{len(findings)} of {len(records)} problems violate the "
          f"current gates ({level})")
    # R1's pre-filter is reported, never acted on: 5 of the 11 rows it flagged
    # on the published pool were legitimate (partner had one action on every
    # layout). --rollout is what decides.
    unconfirmed = {p: s for p, s in suspects.items() if p not in findings}
    if unconfirmed and not args.rollout:
        print(f"\n{len(unconfirmed)} point-mass SUSPECT(S) — re-roll with "
              f"--rollout to confirm or clear (never removed on this "
              f"evidence):")
        for pid, s in sorted(unconfirmed.items()):
            print(f"  {pid}: {s[0]}")
    if args.out:
        Path(args.out).write_text(
            json.dumps({"findings": findings, "suspects": suspects},
                       indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"findings written to {args.out}")
    if findings and args.remove:
        gone = sum(bool(remote.remove(pid)) for pid in findings)
        print(f"deleted {gone} problem(s) from Firestore")
        return 0
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
