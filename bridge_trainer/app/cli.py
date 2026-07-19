"""CLI entry point: `trainer run problems/foo.yaml --seed 42`."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..bank.schema import load_problem
from ..domain.auction import partner_of
from ..domain.interfaces import GenerationBudget
from .report import write_report
from .runner import run_problem


def _print_problem(problem) -> None:
    p = problem
    print(f"\n=== {p.title} ===")
    if p.description:
        print(p.description.strip())
    print(f"\nDealer {p.dealer}, Vul {p.vul}, IMPs")
    auction = " - ".join(
        f"({c.token})" if seat not in (p.my_seat, partner_of(p.my_seat))
        else c.token
        for seat, c in p.auction.calls_with_seats())
    print(f"Auction: {auction} - ?")
    print(f"You ({p.my_seat}) hold: {p.my_hand}")
    print("\nCandidates:")
    for c in p.candidates:
        print(f"  {c.call:>3}  {c.label}")


def _ask_answer(problem) -> str | None:
    calls = [c.call for c in problem.candidates]
    try:
        raw = input(f"\nYour call {calls}: ").strip()
    except EOFError:
        return None
    matches = [c for c in calls if c.upper() == raw.upper()]
    return matches[0] if matches else None


def cmd_run(args: argparse.Namespace) -> int:
    problem = load_problem(args.problem)
    _print_problem(problem)

    user_answer = args.answer
    if user_answer is None and sys.stdin.isatty() and not args.no_prompt:
        user_answer = _ask_answer(problem)
    if user_answer is not None:
        valid = {c.call for c in problem.candidates}
        if user_answer not in valid:
            print(f"error: --answer must be one of {sorted(valid)}",
                  file=sys.stderr)
            return 2

    print("\nSimulating...", flush=True)
    result = run_problem(
        args.problem,
        seed=args.seed,
        n_override=args.n,
        use_cache=not args.no_cache,
        cache_dir=args.cache_dir,
        budget=GenerationBudget(max_seconds=args.gen_seconds),
    )

    d = result.diagnostics
    print(f"\n{len(result.deals)} deals "
          f"(acceptance {d.acceptance_rate:.3%}, ESS {d.effective_sample_size:.0f}, "
          f"gen {d.elapsed_s:.1f}s, total {result.elapsed_s:.1f}s, "
          f"cache {'hit' if result.cache_hit else 'miss'})")
    if d.unrecognized_calls:
        print("WARNING unrecognized calls: " + "; ".join(d.unrecognized_calls))
    if d.shortfall:
        print(f"WARNING shortfall of {d.shortfall} deals; "
              f"CIs widened x{result.ci_widen:.2f}")

    print("\n--- VERDICT " + "-" * 40)
    print(result.verdict_text())
    if user_answer:
        comp = result.corrected
        accepted = {comp.candidates[0].action, *comp.toss_up_with} \
            if comp.toss_up else {comp.candidates[0].action}
        mark = "✓" if user_answer in accepted else "✗"
        print(f"\nYour answer: {user_answer} {mark}")

    report_path = write_report(result, args.out, user_answer)
    print(f"\nReport: {report_path}")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    from .publish import publish
    entries = publish(
        problems_dir=args.problems,
        out_dir=args.out,
        seed=args.seed,
        n_override=args.n,
        use_cache=not args.no_cache,
        cache_dir=args.cache_dir,
        variants_override=args.variants,
        grow_per_day=args.grow_per_day,
        grow_anchor=args.grow_anchor,
    )
    for e in entries:
        print(f"  {e.id}: {e.variants} deal variants x {e.n_deals} simulations")
    print(f"\nSite: {args.out}/index.html ({len(entries)} problems)")
    return 0


def cmd_webapp(args: argparse.Namespace) -> int:
    from .webapp import write_app
    write_app(args.out)
    print(f"App shell written to {args.out}/")
    return 0



def cmd_ben_forge(args: argparse.Namespace) -> int:
    from ..engine.maker import forge_batch
    summary = forge_batch(
        pool_dir=args.pool, count=args.count, base_seed=args.seed,
        max_seconds=args.max_seconds, workers=args.workers,
        audit_prescreen=args.audit_prescreen)
    import json as _json
    print(_json.dumps(summary, indent=1))
    return 0 if summary["count"] == args.count else 1



def cmd_lead_forge(args: argparse.Namespace) -> int:
    from ..engine.lead_maker import forge_lead_batch
    summary = forge_lead_batch(
        pool_dir=args.pool, count=args.count, base_seed=args.seed,
        max_seconds=args.max_seconds, workers=args.workers,
        require_doubled=args.only_doubled,
        doubled_min_gap=args.doubled_min_gap,
        doubled_apply_obvious=args.doubled_obvious)
    import json as _json
    print(_json.dumps(summary, indent=1))
    return 0 if summary["count"] == args.count else 1


def cmd_pool(args: argparse.Namespace) -> int:
    from ..pool.store import ProblemPool
    # Firestore-only subcommands (push/backfill-leads) don't take --pool.
    pool = ProblemPool(args.pool) if getattr(args, "pool", None) else None
    if args.pool_cmd == "ls":
        import json
        for pid in pool.ids():
            r = pool.get(pid)
            print(f"{pid}  {r.get('seat')} after "
                  f"{' '.join(r.get('auction', [])) or '(opening)'}  "
                  f"verdict={r.get('verdict', {}).get('accepted', '?')}")
        print(f"{len(pool.ids())} problems in {args.pool}")
        return 0
    if args.pool_cmd == "rm":
        removed = 0
        for pid in args.ids:
            path = pool.problems_dir / f"{pid}.json"
            if path.exists():
                path.unlink()
                removed += 1
                print(f"removed {pid}")
            else:
                print(f"not found: {pid}")
        pool.rebuild_index()
        print(f"{removed} removed; index rebuilt "
              f"({len(pool.ids())} problems remain)")
        return 0
    if args.pool_cmd == "add":
        from ..engine.maker import forge_batch
        import time as _time
        seed = args.seed if args.seed is not None else int(_time.time())
        summary = forge_batch(pool_dir=args.pool, count=args.count,
                              base_seed=seed, max_seconds=args.max_seconds,
                              workers=args.workers)
        return 0 if summary["count"] == args.count else 1
    if args.pool_cmd == "push":
        from ..pool.firestore_store import push_local_pool
        summary = push_local_pool(args.pool, key_path=args.key,
                                  overwrite=args.overwrite)
        print(f"uploaded {summary['uploaded']}, skipped {summary['skipped']} "
              f"(pool has {summary['total']}); meta/index refreshed")
        return 0
    if args.pool_cmd == "backfill-leads":
        from ..pool.firestore_store import backfill_lead_types
        summary = backfill_lead_types(key_path=args.key, dry_run=args.dry_run)
        verb = "would update" if args.dry_run else "updated"
        print(f"{verb} {summary['updated']} of {summary['lead_total']} lead "
              f"problems in Firestore ({summary['total']} total); "
              f"meta/index {'unchanged (dry run)' if args.dry_run else 'refreshed'}")
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="trainer",
        description="Bridge bidding trainer: simulate, DD-solve, compare.")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run one problem")
    run_p.add_argument("problem", type=Path)
    run_p.add_argument("--seed", type=int, default=42)
    run_p.add_argument("--n", type=int, default=None,
                       help="override the problem's deal count")
    run_p.add_argument("--answer", default=None,
                       help="your chosen call (skips the interactive prompt)")
    run_p.add_argument("--no-prompt", action="store_true")
    run_p.add_argument("--no-cache", action="store_true")
    run_p.add_argument("--cache-dir", default=".trainer_cache")
    run_p.add_argument("--gen-seconds", type=float, default=15.0,
                       help="generation time budget")
    run_p.add_argument("--out", default="reports")
    run_p.set_defaults(func=cmd_run)

    pub_p = sub.add_parser(
        "publish", help="build the static quiz site for the whole bank")
    pub_p.add_argument("problems", nargs="?", default="problems",
                       help="directory of problem YAML files")
    pub_p.add_argument("--out", default="site")
    pub_p.add_argument("--seed", type=int, default=42)
    pub_p.add_argument("--n", type=int, default=None,
                       help="override every problem's deal count")
    pub_p.add_argument("--no-cache", action="store_true")
    pub_p.add_argument("--cache-dir", default=".trainer_cache")
    pub_p.add_argument("--variants", type=int, default=None,
                       help="cap the number of deal variants per problem")
    pub_p.add_argument("--grow-per-day", type=int, default=0,
                       help="fresh deals added per problem per day")
    pub_p.add_argument("--grow-anchor", default=None,
                       help="UTC date (YYYY-MM-DD) growth counts from")
    pub_p.set_defaults(func=cmd_publish)

    app_p = sub.add_parser("webapp", help="write the static app shell")
    app_p.add_argument("--out", default="_site")
    app_p.set_defaults(func=cmd_webapp)


    bf_p = sub.add_parser(
        "ben-forge", help="generate problems with the Ben engine")
    bf_p.add_argument("--pool", default="pool_ben")
    bf_p.add_argument("--count", type=int, default=20)
    bf_p.add_argument("--seed", type=int, default=1)
    bf_p.add_argument("--max-seconds", type=float, default=3600.0)
    bf_p.add_argument("--workers", type=int, default=1,
                      help="parallel forge workers; 0 = auto "
                           "(each holds a ~1.2 GB engine)")
    bf_p.add_argument("--audit-prescreen", action="store_true",
                      help="run the full screen even on prescreen rejects "
                           "and report the measured false-kill rate")
    bf_p.set_defaults(func=cmd_ben_forge)

    lf_p = sub.add_parser(
        "lead-forge", help="generate opening-lead problems with the Ben engine")
    lf_p.add_argument("--pool", default="data")
    lf_p.add_argument("--count", type=int, default=20)
    lf_p.add_argument("--seed", type=int, default=1)
    lf_p.add_argument("--max-seconds", type=float, default=3600.0)
    lf_p.add_argument("--only-doubled", action="store_true",
                      help="lead_doubled category: keep only doubled final "
                           "contracts and accept every one (skips the C1 "
                           "obvious / 0.25-trick suit-indifferent gates)")
    lf_p.add_argument("--doubled-min-gap", type=float, default=0.0,
                      help="with --only-doubled, require the best lead to beat "
                           "the best different-suit lead by >= this many DD "
                           "tricks (0 = accept every doubled board)")
    lf_p.add_argument("--doubled-obvious", action="store_true",
                      help="with --only-doubled, also apply the C1 obvious rule: "
                           "reject doubled boards where BEN's lead policy puts "
                           "> P_OBVIOUS on the answer set)")
    lf_p.add_argument("--workers", type=int, default=1,
                      help="parallel forge workers; 0 = auto "
                           "(each holds a ~1.2 GB engine)")
    lf_p.set_defaults(func=cmd_lead_forge)

    pool_p = sub.add_parser("pool", help="add/remove/list pool problems")
    pool_sub = pool_p.add_subparsers(dest="pool_cmd", required=True)
    pl = pool_sub.add_parser("ls", help="list problems")
    pl.add_argument("--pool", default="data")
    pl.set_defaults(func=cmd_pool)
    pr = pool_sub.add_parser("rm", help="remove problems by id")
    pr.add_argument("ids", nargs="+")
    pr.add_argument("--pool", default="data")
    pr.set_defaults(func=cmd_pool)
    pa = pool_sub.add_parser(
        "add", help="generate new problems into the pool (needs Ben env)")
    pa.add_argument("--count", type=int, default=1)
    pa.add_argument("--seed", type=int, default=None)
    pa.add_argument("--pool", default="data")
    pa.add_argument("--max-seconds", type=float, default=1800.0)
    pa.add_argument("--workers", type=int, default=1,
                    help="parallel forge workers; 0 = auto")
    pa.set_defaults(func=cmd_pool)
    pp = pool_sub.add_parser(
        "push", help="upload the local JSON pool + index to Firestore")
    pp.add_argument("--pool", default="data")
    pp.add_argument("--key", default=None,
                    help="service-account JSON (or set "
                         "GOOGLE_APPLICATION_CREDENTIALS)")
    pp.add_argument("--overwrite", action="store_true",
                    help="replace documents that already exist")
    pp.set_defaults(func=cmd_pool)

    pb = pool_sub.add_parser(
        "backfill-leads",
        help="assign lead categories to existing lead problems in Firestore")
    pb.add_argument("--key", default=None,
                    help="service-account JSON (or set "
                         "GOOGLE_APPLICATION_CREDENTIALS)")
    pb.add_argument("--dry-run", action="store_true",
                    help="report counts without writing")
    pb.set_defaults(func=cmd_pool)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
