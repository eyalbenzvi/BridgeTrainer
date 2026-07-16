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


def cmd_produce(args: argparse.Namespace) -> int:
    import time as _time
    from ..generate.producer import produce_batch
    seed = args.seed if args.seed is not None else int(_time.time())
    made = produce_batch(
        pool_dir=args.pool,
        count=args.count,
        max_seconds=args.max_seconds,
        base_seed=seed,
        n_deals=args.n,
        jobs=args.jobs,
    )
    print(f"\n{len(made)} problems added to {args.pool} (base seed {seed})")
    return 0


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

    prod_p = sub.add_parser(
        "produce", help="generate random problems into the pool")
    prod_p.add_argument("--pool", default="pool_data")
    prod_p.add_argument("--count", type=int, default=10)
    prod_p.add_argument("--max-seconds", type=float, default=3600.0)
    prod_p.add_argument("--seed", type=int, default=None,
                        help="base seed (default: derived from time)")
    prod_p.add_argument("--n", type=int, default=600,
                        help="simulated layouts per problem")
    prod_p.add_argument("--jobs", type=int, default=1,
                        help="parallel worker processes (each DD solve "
                             "already uses ~4 cores; raise this on "
                             "many-core machines)")
    prod_p.set_defaults(func=cmd_produce)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
