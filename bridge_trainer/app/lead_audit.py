"""`trainer lead-posterior-audit` — a reproducible opening-lead audit.

Runs one or more samplers (and thresholds) on ONE opening-lead problem, grades
every physical lead by average double-dummy defensive tricks on a shared
layout set, and emits a single JSON record with: sampler provenance,
proposal/acceptance/ESS, all lead EVs, the best-vs-runner-up delta/tail
metrics, strata + leave-one-stratum-out diagnostics, the card-level
correctness trace, cross-sampler agreement, and a quality flag.

The headline ranking is ALWAYS the mean-DD ranking; every extra metric is a
diagnostic. Sampled full deals live only in this audit output, never in normal
UI. Nothing here consults the hidden source deal.
"""
from __future__ import annotations

import json

import numpy as np

from ..engine.lead_posterior import (
    LeadProblem, build_problem, evaluate_layouts, delta_report, is_tail_dominated,
    strata_report, quality_flag, card_level_audit, card_level_trace,
    result_signature, problem_fingerprint)
from ..engine.lead_samplers import UniformSampler, BenCurrentSampler, FixtureSampler


def _rank_table(ev, ls) -> list:
    m = ev.weighted_mean()
    order = ev.ranking()
    rows = []
    for c in order:
        arr = ev.def_tricks[c]
        rows.append({
            "card": c,
            "avg_def_tricks": round(m[c], 4),
            "min": float(arr.min()), "max": float(arr.max()),
        })
    return rows


def _make_sampler(name: str, threshold, engine, fixture):
    if name == "uniform":
        return UniformSampler()
    if name == "fixture":
        return FixtureSampler.from_json(fixture)
    if name == "current":
        return BenCurrentSampler(engine=engine, threshold=threshold or 0.70)
    if name in ("ben-replay", "ben-likelihood"):
        raise NotImplementedError(
            f"sampler '{name}' requires the Ben venv and per-legal-call "
            f"probabilities; run under BEN_HOME. The acceptance/weighting math "
            f"is implemented and unit-tested in engine.lead_posterior "
            f"(replay_exact_mask / likelihood_log_weights).")
    raise ValueError(f"unknown sampler {name}")


def run_one_sampler(problem: LeadProblem, sampler, requested: int, seed: int,
                    compare, n_boot: int) -> dict:
    ls = sampler.sample(problem, requested, seed)
    ev = evaluate_layouts(ls)
    m = ev.weighted_mean()
    order = ev.ranking()
    best, runner = order[0], order[1]

    dr = delta_report(ev.def_tricks[best], ev.def_tricks[runner],
                      weight=ls.weight, n_boot=n_boot, seed=seed)
    # optional explicit pair (e.g. HA vs H4)
    compare_report = None
    if compare and len(compare) == 2 and all(c in ev.def_tricks for c in compare):
        a, b = compare
        compare_report = {
            "pair": [a, b],
            "mean_a": round(m[a], 4), "mean_b": round(m[b], 4),
            "delta": delta_report(ev.def_tricks[a], ev.def_tricks[b],
                                  weight=ls.weight, n_boot=n_boot, seed=seed),
        }

    strata = strata_report(problem, ls, ev, best, runner)
    focus = list(compare) if compare else [best, runner]
    card_audit = card_level_audit(ls, ev, focus=focus)

    return {
        "provenance": ls.provenance(),
        "winner": best, "runner_up": runner,
        "lead_evs": _rank_table(ev, ls),
        "best_vs_runner_delta": dr,
        "tail_dominated": is_tail_dominated(dr),
        "compare": compare_report,
        "strata": strata,
        "card_level_audit": card_audit,
        "result_signature": result_signature(ev, ls),
        "_ev": ev, "_ls": ls,   # kept for cross-sampler assembly; stripped later
    }


def run_audit(hand, auction, dealer, vul, contract, *, samplers, thresholds,
              requested, proposals, compare, seed, n_boot=2000,
              engine=None, fixture=None, card_trace_layouts=0) -> dict:
    problem = build_problem(hand, auction, dealer, vul, contract)
    runs = {}
    reports_for_flag = {}
    for sname in samplers:
        thr_list = thresholds if sname == "current" else [None]
        for thr in thr_list:
            label = f"{sname}" + (f"@{thr:.2f}" if thr is not None else "")
            ben_family = sname in ("current", "ben-replay", "ben-likelihood")
            try:
                sampler = _make_sampler(sname, thr, engine, fixture)
                r = run_one_sampler(problem, sampler, requested, seed,
                                    compare, n_boot)
            except Exception as e:  # noqa: BLE001
                # Ben-backed samplers may be unavailable (no BEN_HOME); record
                # that and continue. Offline samplers (uniform/fixture) failing
                # is a real bug — let it surface.
                if ben_family:
                    runs[label] = {"unavailable": f"{type(e).__name__}: {e}"}
                    continue
                raise
            reports_for_flag[label] = {
                "winner": r["winner"],
                "delta_report": r["best_vs_runner_delta"],
            }
            # card-level per-layout trace (audit/debug only)
            if card_trace_layouts:
                ls = r["_ls"]
                r["card_level_traces"] = [
                    card_level_trace(problem, ls.hands[i])
                    for i in range(min(card_trace_layouts, ls.n))]
            r.pop("_ev", None)
            r.pop("_ls", None)
            runs[label] = r

    flag = quality_flag(reports_for_flag)
    winners = {r["winner"] for r in runs.values() if "winner" in r}
    publishable = flag == "robust" and len(winners) == 1

    return {
        "schema": "lead-posterior-audit/1",
        "problem": {
            "hand": problem.hand, "auction": list(problem.auction),
            "dealer": problem.dealer, "vul": problem.vul,
            "contract": problem.contract, "strain": problem.strain,
            "declarer": problem.declarer, "leader": problem.leader,
            "legal_leads": problem.legal_leads(),
            "fingerprint": problem_fingerprint(problem, seed),
        },
        "settings": {
            "samplers": samplers, "thresholds": thresholds,
            "requested_samples": requested, "proposals": proposals,
            "compare": compare, "seed": seed, "n_boot": n_boot,
        },
        "runs": runs,
        "cross_sampler": {
            "distinct_winners": sorted(winners),
            "agree_on_winner": len(winners) == 1,
        },
        "quality_flag": flag,
        "publishable_single_lead": publishable,
        "notes": (
            "Ranking is mean double-dummy defensive tricks over the shared "
            "sampled layouts; all other metrics are diagnostics. A single "
            "'correct' lead is withheld unless quality_flag=='robust'."),
    }


def cmd_lead_posterior_audit(args) -> int:
    from ..engine.scanner import deal_board, VUL_NAMES
    from ..engine.conventions import SEATS as _S

    hand, auction, dealer, vul, contract = (
        args.hand, args.auction, args.dealer, args.vul, args.contract)

    # If an id is given and no explicit hand/auction, regenerate the board's
    # PUBLIC state from its seed (Ben-free for the deal; the auction must be
    # supplied or captured, since bidding needs the engine).
    if args.id and not hand:
        seed = int(args.id.split("-")[-1], 16)
        hands, dealer_i, vul_t = deal_board(seed)
        leader_hint = None
        # We can only fill the leader hand once we know the contract/declarer,
        # which requires the auction. Require --auction + --contract with --id.
        if not (args.auction and args.contract):
            print("ERROR: --id needs --auction and --contract (bidding needs "
                  "the Ben engine to reproduce; pass the known auction).")
            return 2
        contract = args.contract
        fc = build_problem(hands[0], args.auction.split(), _S[dealer_i],
                           VUL_NAMES[vul_t], contract)
        hand = hands[_S.index(fc.leader)]
        dealer, vul, auction = _S[dealer_i], VUL_NAMES[vul_t], args.auction

    auction_list = auction.split() if isinstance(auction, str) else auction
    thresholds = [float(x) for x in args.thresholds.split(",")] if args.thresholds else [0.70]
    samplers = args.samplers.split(",") if args.samplers else ["uniform"]
    compare = args.compare.split(",") if args.compare else None

    engine = None
    if "current" in samplers:
        try:
            from ..engine.ben import get_engine
            engine = get_engine()
        except Exception as e:  # noqa: BLE001
            print(f"WARNING: Ben engine unavailable ({type(e).__name__}: {e}); "
                  f"'current' sampler runs will be marked unavailable.")

    result = run_audit(
        hand, auction_list, dealer, vul, contract,
        samplers=samplers, thresholds=thresholds,
        requested=args.samples, proposals=args.proposals,
        compare=compare, seed=args.seed, n_boot=args.n_boot,
        engine=engine, fixture=args.fixture,
        card_trace_layouts=args.card_trace_layouts)

    text = json.dumps(result, indent=2, default=_json_default)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
        print(f"wrote {args.out}  (quality_flag={result['quality_flag']}, "
              f"winners={result['cross_sampler']['distinct_winners']})")
    else:
        print(text)
    return 0


def _json_default(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)
