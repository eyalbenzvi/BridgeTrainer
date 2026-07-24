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
        doubled_apply_obvious=args.doubled_obvious,
        target_mode=args.mode)
    import json as _json
    print(_json.dumps(summary, indent=1))
    return 0 if summary["count"] == args.count else 1


def cmd_lead_posterior_audit(args: argparse.Namespace) -> int:
    from .lead_audit import cmd_lead_posterior_audit as _run
    return _run(args)


def cmd_lead_corpus(args: argparse.Namespace) -> int:
    """Run the blind-labelled validation corpus and print the report."""
    import json as _json
    from ..engine.lead_corpus import run_corpus
    r = run_corpus(seed=args.seed, n_boot=args.n_boot)
    if args.out:
        with open(args.out, "w") as f:
            _json.dump(r, f, indent=2)
    print(f"label_agreement_rate={r['label_agreement_rate']} "
          f"robustness_rate={r['robustness_rate']} "
          f"ace_win_rate={r['ace_win_rate']} "
          f"mapping_failures={r['mapping_failures']} "
          f"source_leak_failures={r['source_leak_failures']}")
    for c in r["cases"]:
        print(f"  {c['id']:24s} {c['category']:20s} agree={c['agree']} "
              f"state={c['observed']['state']} winner={c['observed']['winner']}")
    return 0 if (r["label_agreement_rate"] == 1.0
                 and r["mapping_failures"] == 0
                 and r["source_leak_failures"] == 0) else 1


def cmd_lead_calibration(args: argparse.Namespace) -> int:
    """Calibrate a sampler's hidden-hand distribution against REAL deals.

    Reads a JSON list of complete deals (each: {"hands": {seat: pbn}, "auction":
    [...], "contract": "3NTW", optional "dealer"/"vul"}), groups them by auction
    family, and reports per-feature real-vs-sampled total-variation divergence.
    Ben-free samplers only (uniform, constraint); 'current' would need Ben.
    """
    import json as _json
    from ..engine.lead_calibration import calibrate_corpus
    from ..engine.lead_samplers import UniformSampler

    with open(args.deals) as f:
        deals = _json.load(f)

    if args.sampler == "uniform":
        sampler = UniformSampler()
    elif args.sampler == "constraint":
        # derive constraints from each board's own auction lazily (ARCH-10:
        # the adapter now lives in engine/lead_samplers.py).
        from ..engine.lead_samplers import PerBoardConstraintSampler
        sampler = PerBoardConstraintSampler()
    else:
        print(f"unknown sampler {args.sampler!r} (use uniform|constraint)")
        return 2

    out = calibrate_corpus(deals, sampler, requested=args.samples,
                           seed=args.seed, tol=args.tol,
                           min_boards=args.min_boards)
    if args.out:
        with open(args.out, "w") as f:
            _json.dump(out, f, indent=2)
    s = out["summary"]
    print(f"families={s['n_families']} calibrated={s['calibrated']} "
          f"miscalibrated={s['miscalibrated']} insufficient={s['insufficient']}")
    for feat, cnt in s["most_off_features"][:12]:
        print(f"  off x{cnt:<3d} {feat}")
    return 0


def cmd_pool_ls(args: argparse.Namespace) -> int:
    from ..pool.store import ProblemPool
    pool = ProblemPool(args.pool)
    for pid in pool.ids():
        r = pool.get(pid)
        print(f"{pid}  {r.get('seat')} after "
              f"{' '.join(r.get('auction', [])) or '(opening)'}  "
              f"verdict={r.get('verdict', {}).get('accepted', '?')}")
    print(f"{len(pool.ids())} problems in {args.pool}")
    return 0


def cmd_pool_rm(args: argparse.Namespace) -> int:
    from ..pool.store import ProblemPool
    pool = ProblemPool(args.pool)
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


def cmd_pool_add(args: argparse.Namespace) -> int:
    from ..engine.maker import forge_batch
    import time as _time
    seed = args.seed if args.seed is not None else int(_time.time())
    summary = forge_batch(pool_dir=args.pool, count=args.count,
                          base_seed=seed, max_seconds=args.max_seconds,
                          workers=args.workers)
    return 0 if summary["count"] == args.count else 1


def cmd_pool_push(args: argparse.Namespace) -> int:
    from ..pool.firestore_store import push_local_pool
    summary = push_local_pool(args.pool, key_path=args.key,
                              overwrite=args.overwrite)
    print(f"uploaded {summary['uploaded']}, skipped {summary['skipped']} "
          f"(pool has {summary['total']}); meta/index refreshed")
    failed = summary.get("failed") or []
    if failed:
        # DB-O-5: real write failures must fail the run (redden CI), not be
        # reported as success; those docs were excluded from the index.
        print(f"ERROR: {len(failed)} doc(s) failed to upload and were left "
              f"out of the index: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


def cmd_pool_backfill_training(args: argparse.Namespace) -> int:
    from ..pool.firestore_store import backfill_lead_training
    summary = backfill_lead_training(key_path=args.key, dry_run=args.dry_run)
    verb = "would stamp" if args.dry_run else "stamped"
    print(f"{verb} legacy training metadata on {summary['updated']} of "
          f"{summary['lead_total']} lead problems in Firestore "
          f"({summary['total']} total); meta/index "
          f"{'unchanged (dry run)' if args.dry_run else 'refreshed with mode flags'}")
    return 0


def cmd_pool_backfill_leads(args: argparse.Namespace) -> int:
    from ..pool.firestore_store import backfill_lead_types
    summary = backfill_lead_types(key_path=args.key, dry_run=args.dry_run)
    verb = "would update" if args.dry_run else "updated"
    print(f"{verb} {summary['updated']} of {summary['lead_total']} lead "
          f"problems in Firestore ({summary['total']} total); "
          f"meta/index {'unchanged (dry run)' if args.dry_run else 'refreshed'}")
    return 0


def _run_pool_script(filename: str, argv: list[str]) -> int:
    """Delegate a `trainer pool <cmd>` to a stable maintenance script under
    scripts/ (ARCH-11). The script is executed as __main__ with *argv* so it
    is discoverable through `trainer pool -h` — a single operational interface
    for the whole pool lifecycle — without duplicating its (LLM/GIB/Firestore-
    heavy) body here. The script's own arg parser handles *argv*."""
    import runpy
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts" / filename
    if not script.exists():
        print(f"error: maintenance script not found: {script}\n"
              f"(run from a source checkout — scripts/ ships with the repo, "
              f"not the installed wheel)", file=sys.stderr)
        return 2
    saved = sys.argv
    sys.argv = [str(script), *argv]
    try:
        runpy.run_path(str(script), run_name="__main__")
        return 0
    except SystemExit as e:      # the script called sys.exit()/argparse error
        return int(e.code) if isinstance(e.code, int) else (0 if not e.code else 1)
    finally:
        sys.argv = saved


# ARCH-11: pool subcommands that forward their args verbatim to a stable
# maintenance script under scripts/. Intercepted before argparse because
# argparse.REMAINDER cannot reliably capture a leading option (bpo-17050).
_POOL_SCRIPTS = {
    "classify": "classify_pool.py",
    "reexplain": "reexplain_pool.py",
    "backfill-notes": "backfill_bot_notes.py",
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) >= 2 and argv[0] == "pool" and argv[1] in _POOL_SCRIPTS:
        return _run_pool_script(_POOL_SCRIPTS[argv[1]], argv[2:])

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
    lf_p.add_argument("--mode", choices=["MP", "IMP"], default="MP",
                      help="target training mode: MP selects boards whose "
                           "suit choice matters in DD tricks; IMP selects "
                           "boards whose suit choice matters in expected "
                           "IMPs from the final score (records are stamped "
                           "with the mode they were forged for)")
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

    lpa = sub.add_parser(
        "lead-posterior-audit",
        help="audit one opening-lead board: samplers x thresholds, all lead "
             "EVs, delta/tail/strata diagnostics, card-level correctness, "
             "quality flag (Ben-free for uniform/fixture; 'current' needs Ben)")
    lpa.add_argument("--id", default=None,
                     help="board id like lead1-0284459a; regenerates the deal "
                          "from its seed (also pass --auction and --contract)")
    lpa.add_argument("--hand", default=None,
                     help="leader hand PBN 'S.H.D.C', e.g. 874.AQ94.T.97642")
    lpa.add_argument("--auction", default=None,
                     help="space-separated tokens from dealer, e.g. "
                          "'1S P 2C P 3D P 3NT P P P'")
    lpa.add_argument("--dealer", default="N")
    lpa.add_argument("--vul", default="None")
    lpa.add_argument("--contract", default=None,
                     help="e.g. 3NTW, 4HEx")
    lpa.add_argument("--samplers", default="uniform",
                     help="comma list: uniform,constraint,current,fixture,"
                          "ben-replay,ben-likelihood")
    lpa.add_argument("--thresholds", default="0.70",
                     help="comma list of 'current' acceptance thresholds")
    lpa.add_argument("--samples", type=int, default=512,
                     help="requested accepted samples per run")
    lpa.add_argument("--proposals", type=int, default=0,
                     help="proposal budget hint (recorded; Ben caps its own)")
    lpa.add_argument("--compare", default=None,
                     help="explicit pair, e.g. HA,H4")
    lpa.add_argument("--seed", type=int, default=1)
    lpa.add_argument("--n-boot", type=int, default=2000)
    lpa.add_argument("--fixture", default=None,
                     help="JSON layout fixture for the 'fixture' sampler")
    lpa.add_argument("--card-trace-layouts", type=int, default=0,
                     help="emit per-card DDS traces for the first N layouts "
                          "(audit/debug only)")
    lpa.add_argument("--out", default=None, help="write JSON here")
    lpa.set_defaults(func=cmd_lead_posterior_audit)

    lc = sub.add_parser(
        "lead-corpus",
        help="run the blind-labelled opening-lead validation corpus "
             "(synthetic ground-truth cases; Ben-free)")
    lc.add_argument("--seed", type=int, default=1)
    lc.add_argument("--n-boot", type=int, default=500)
    lc.add_argument("--out", default=None, help="write JSON report here")
    lc.set_defaults(func=cmd_lead_corpus)

    cal = sub.add_parser(
        "lead-calibration",
        help="calibrate a sampler's hidden-hand distribution against REAL "
             "complete deals grouped by auction family (HCP, shape, announced-"
             "suit lengths, fits, controls, honor locations); Ben-free")
    cal.add_argument("--deals", required=True,
                     help="JSON list of complete deals: {hands:{seat:pbn}, "
                          "auction:[...], contract:'3NTW', dealer, vul}")
    cal.add_argument("--sampler", default="uniform",
                     help="uniform | constraint (Ben-free)")
    cal.add_argument("--samples", type=int, default=256,
                     help="sampled layouts per board")
    cal.add_argument("--seed", type=int, default=1)
    cal.add_argument("--tol", type=float, default=0.20,
                     help="total-variation tolerance for 'calibrated'")
    cal.add_argument("--min-boards", type=int, default=5,
                     help="min real boards per family to attempt calibration")
    cal.add_argument("--out", default=None, help="write JSON report here")
    cal.set_defaults(func=cmd_lead_calibration)

    pool_p = sub.add_parser("pool", help="add/remove/list pool problems")
    pool_sub = pool_p.add_subparsers(dest="pool_cmd", required=True)
    pl = pool_sub.add_parser("ls", help="list problems")
    pl.add_argument("--pool", default="data")
    pl.set_defaults(func=cmd_pool_ls)
    pr = pool_sub.add_parser("rm", help="remove problems by id")
    pr.add_argument("ids", nargs="+")
    pr.add_argument("--pool", default="data")
    pr.set_defaults(func=cmd_pool_rm)
    pa = pool_sub.add_parser(
        "add", help="generate new problems into the pool (needs Ben env)")
    pa.add_argument("--count", type=int, default=1)
    pa.add_argument("--seed", type=int, default=None)
    pa.add_argument("--pool", default="data")
    pa.add_argument("--max-seconds", type=float, default=1800.0)
    pa.add_argument("--workers", type=int, default=1,
                    help="parallel forge workers; 0 = auto")
    pa.set_defaults(func=cmd_pool_add)
    pp = pool_sub.add_parser(
        "push", help="upload the local JSON pool + index to Firestore")
    pp.add_argument("--pool", default="data")
    pp.add_argument("--key", default=None,
                    help="service-account JSON (or set "
                         "GOOGLE_APPLICATION_CREDENTIALS)")
    pp.add_argument("--overwrite", action="store_true",
                    help="replace documents that already exist")
    pp.set_defaults(func=cmd_pool_push)

    pt = pool_sub.add_parser(
        "backfill-training",
        help="migration: stamp legacy lead problems in Firestore as MP-only "
             "(tricks-only evidence) and rebuild the index with mode flags")
    pt.add_argument("--key", default=None,
                    help="service-account JSON (or set "
                         "GOOGLE_APPLICATION_CREDENTIALS)")
    pt.add_argument("--dry-run", action="store_true",
                    help="report counts without writing")
    pt.set_defaults(func=cmd_pool_backfill_training)

    pb = pool_sub.add_parser(
        "backfill-leads",
        help="assign lead categories to existing lead problems in Firestore")
    pb.add_argument("--key", default=None,
                    help="service-account JSON (or set "
                         "GOOGLE_APPLICATION_CREDENTIALS)")
    pb.add_argument("--dry-run", action="store_true",
                    help="report counts without writing")
    pb.set_defaults(func=cmd_pool_backfill_leads)

    # ARCH-11: stable pool-maintenance scripts, surfaced as discoverable pool
    # subcommands. The actual dispatch is intercepted in main() (before
    # argparse), so these registrations exist only to document them under
    # `trainer pool -h`; all args after the name are forwarded to the script.
    _POOL_SCRIPT_HELP = {
        "classify": "classify pool records (difficulty + type)",
        "reexplain": "regenerate every problem's explanations from GIB",
        "backfill-notes": "backfill engine notes on pool records",
    }
    for name, filename in _POOL_SCRIPTS.items():
        pool_sub.add_parser(
            name, help=_POOL_SCRIPT_HELP[name], add_help=False,
            description=f"Delegates to scripts/{filename}; every argument after "
                        f"'pool {name}' is forwarded to it (use "
                        f"'trainer pool {name} -h' to see the script's own "
                        f"options).")

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
