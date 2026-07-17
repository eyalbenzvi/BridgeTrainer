"""The batch maker: scan → verdict → explanations → pool, with quotas,
time budget and per-attempt logging (docs/ben_execution_plan.md §3 + v2
amendments 8, 13).

Run under the Ben venv (scripts/setup_ben.sh):
    trainer ben-forge --count 20 --pool pool_ben --seed 1
"""
from __future__ import annotations

import time
from collections import Counter
from datetime import datetime, timezone

from ..pool.store import ProblemPool
from .conventions import hero_role
from .scanner import SEATS, VUL_NAMES, scan_board
from .verdict import judge

MAX_OPENING_DECISIONS = 3
MAX_PER_THEME = 2
MAX_TRAP = 3          # trap-class boards per batch (selectivity review)


def _theme_key(spot) -> str:
    tail = [t for t in spot.stem if t != "P"][-3:]
    cands = ",".join(sorted(b for b, _ in spot.candidates))
    return f"{'-'.join(tail)}|{cands}"


def _round_trip_ok(spot) -> bool:
    """Rec 13d: the hand we publish is the hand Ben bid for that seat."""
    return spot.hands[spot.hero_i].count(".") == 3 and \
        sum(len(p) for p in spot.hands[spot.hero_i].split(".")) == 13


def build_record(spot, verdict, stem_expl, opt_expl, elapsed) -> dict:
    policy_map = dict(spot.candidates)
    rec = {
        "schema": 1,
        "id": f"ben1-{spot.seed:08x}",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": {"engine": "ben BEN-21GF", "seed": spot.seed,
                      "samples": verdict.measured["n_samples"],
                      "oracle": "none", "elapsed_s": round(elapsed, 1)},
        "scoring_form": "IMPs",
        "dealer": SEATS[spot.dealer_i],
        "vul": VUL_NAMES[spot.vul],
        "seat": SEATS[spot.hero_i],
        "hand": spot.hands[spot.hero_i],
        "auction": list(spot.stem),
        "candidates": [{"call": b, "policy": round(p, 3)}
                       for b, p in spot.candidates],
        "verdict": {
            "accepted": "" if verdict.toss_up else verdict.best,
            "toss_up": verdict.toss_up,
            "toss_up_set": ([verdict.best] + verdict.toss_up_with)
            if verdict.toss_up else [],
            "flags": verdict.flags,
            "table": verdict.table,
            "dead_options": verdict.dead,
        },
        "difficulty": verdict.measured["gap_imps"],
        "quality": verdict.measured,
        "explanations": {
            "note": "call meanings follow standard 2/1 Game Force",
            "stem": stem_expl,
            "options": opt_expl,
        },
        "hero_role": hero_role(spot.stem, spot.dealer_i, spot.hero_i),
        "full_deal": {SEATS[i]: h for i, h in enumerate(spot.hands)},
        "engine_auction_complete": list(spot.full_auction),
        "policy_trail": [
            {"idx": t.idx, "seat": SEATS[t.seat_i], "chosen": t.chosen,
             "policy": [(b, round(p, 3)) for b, p in t.policy[:4]]}
            for t in spot.turns],
    }
    return rec


def forge_batch(pool_dir: str, count: int, base_seed: int,
                max_seconds: float = 3600.0, log=print) -> dict:
    from .ben import get_engine
    from .explain import option_explanations, stem_explanations

    # Resolve the pool BEFORE engine init: BenEngine chdir's into the ben
    # source tree, so a relative pool path would land there.
    import os
    pool_dir = os.path.abspath(pool_dir)

    t_load = time.perf_counter()
    engine = get_engine()
    log(f"engine loaded in {time.perf_counter() - t_load:.1f}s")

    pool = ProblemPool(pool_dir)
    existing = set(pool.ids())
    made, rejections = [], Counter()
    quotas = {"opening": 0, "themes": Counter(), "vuls": Counter(),
              "roles": Counter(), "contested": 0}
    t0 = time.perf_counter()
    stage_totals = Counter()
    k = 0
    while len(made) < count and time.perf_counter() - t0 < max_seconds:
        seed = base_seed + k
        k += 1
        t_board = time.perf_counter()
        try:
            spot = scan_board(engine, seed)
        except Exception as e:  # engine hiccup: log and move on
            rejections["scan_error"] += 1
            log(f"  seed {seed}: scan error ({type(e).__name__}: {e})")
            continue
        t_scan = time.perf_counter() - t_board
        stage_totals["scan_s"] += t_scan
        if spot is None:
            rejections["no_dilemma"] += 1
            log(f"  seed {seed}: no dilemma [{t_scan:.1f}s]")
            continue

        # quotas (rec 8)
        opening_decision = all(t == "P" for t in spot.stem)
        theme = _theme_key(spot)
        if opening_decision and quotas["opening"] >= MAX_OPENING_DECISIONS:
            rejections["quota_opening"] += 1
            log(f"  seed {seed}: quota (opening decisions) [{t_scan:.1f}s]")
            continue
        if quotas["themes"][theme] >= MAX_PER_THEME:
            rejections["quota_theme"] += 1
            log(f"  seed {seed}: quota (theme {theme}) [{t_scan:.1f}s]")
            continue
        if not _round_trip_ok(spot):
            rejections["round_trip"] += 1
            continue

        hero_bot = engine.bot(spot.hands[spot.hero_i], spot.hero_i,
                              spot.dealer_i, spot.vul)
        t_v = time.perf_counter()
        try:
            ev = engine.evaluate(hero_bot, spot.dealer_i, spot.stem,
                                 [b for b, _ in spot.candidates])
        except Exception as e:
            rejections["evaluate_error"] += 1
            log(f"  seed {seed}: evaluate error ({type(e).__name__}: {e})")
            continue
        t_verdict = time.perf_counter() - t_v
        stage_totals["verdict_s"] += t_verdict
        v = judge(ev, policy_top=spot.candidates[0][0],
                  hero_i=spot.hero_i, policy_map=dict(spot.candidates))
        if v.accepted and v.measured.get("trap") and \
                quotas.get("traps", 0) >= MAX_TRAP:
            rejections["quota_trap"] += 1
            log(f"  seed {seed}: quota (trap class)")
            continue
        if not v.accepted:
            rejections[v.reason] += 1
            log(f"  seed {seed}: {v.reason} gap={v.measured.get('gap_imps')}"
                f" ci={v.measured.get('ci')} [{t_scan:.1f}+{t_verdict:.1f}s]")
            continue

        t_e = time.perf_counter()
        stem_expl = stem_explanations(engine, spot, hero_bot)
        opt_expl = option_explanations(spot, v, dict(spot.candidates),
                               engine=engine, ev=ev, hero_bot=hero_bot)
        t_expl = time.perf_counter() - t_e
        stage_totals["explain_s"] += t_expl

        elapsed = time.perf_counter() - t_board
        rec = build_record(spot, v, stem_expl, opt_expl, elapsed)
        if rec["id"] in existing:
            rejections["duplicate"] += 1
            continue
        pool.add(rec)
        pool.rebuild_index()
        existing.add(rec["id"])
        made.append(rec["id"])
        quotas["traps"] = quotas.get("traps", 0) + (1 if v.measured.get("trap") else 0)
        quotas["opening"] += 1 if opening_decision else 0
        quotas["themes"][theme] += 1
        quotas["vuls"][rec["vul"]] += 1
        quotas["roles"][rec["hero_role"]] += 1
        quotas["contested"] += 1 if any(
            t != "P" for i, t in enumerate(spot.stem)
            if (spot.dealer_i + i) % 4 not in
            (spot.hero_i, (spot.hero_i + 2) % 4)) else 0
        verdict_txt = ("toss-up " + "/".join(rec["verdict"]["toss_up_set"])
                       ) if v.toss_up else v.best
        log(f"  seed {seed}: ACCEPTED {rec['id']} [{len(made)}/{count}] "
            f"hero {rec['seat']} after {' '.join(spot.stem) or '(opening)'} "
            f"cands={[b for b, _ in spot.candidates]} verdict={verdict_txt} "
            f"gap={v.measured['gap_imps']} "
            f"[scan {t_scan:.1f}s verdict {t_verdict:.1f}s expl {t_expl:.1f}s]")

    wall = time.perf_counter() - t0
    summary = {
        "made": made, "count": len(made), "wall_s": round(wall, 1),
        "boards_scanned": k, "rejections": dict(rejections),
        "stage_totals_s": {s: round(x, 1) for s, x in stage_totals.items()},
        "per_accepted_s": round(wall / len(made), 1) if made else None,
        "quotas": {"opening": quotas["opening"],
                   "vuls": dict(quotas["vuls"]),
                   "roles": dict(quotas["roles"]),
                   "contested": quotas["contested"]},
    }
    log(f"\nDone: {len(made)}/{count} in {wall / 60:.1f} min "
        f"({summary['per_accepted_s']}s per accepted deal); "
        f"scanned {k} boards; rejections: {dict(rejections)}")
    return summary
