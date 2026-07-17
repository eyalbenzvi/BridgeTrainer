"""The opening-lead batch maker: bid a board out, grade all 13 leads by
average double-dummy defensive tricks, judge, explain, pool.

Structurally parallel to maker.py (ben-forge), minus a scanner: the lead
decision point is always the same position (leader on lead after a complete
auction), so there is nothing to search for.

Run under the Ben venv (scripts/setup_ben.sh):
    trainer lead-forge --count 20 --pool data --seed 1
"""
from __future__ import annotations

import os
import time
from collections import Counter
from datetime import datetime, timezone

from ..pool.store import ProblemPool
from .conventions import (SEATS, contract_str, final_contract,
                          opening_leader)
from .lead_verdict import judge_lead
from .scanner import VUL_NAMES, bid_out

SCREEN_SAMPLES = 128    # cheap rejection pass
CONFIRM_SAMPLES = 512   # published evidence


def _hand_ok(hand: str) -> bool:
    return hand.count(".") == 3 and \
        sum(len(p) for p in hand.split(".")) == 13


def build_lead_record(seed, hands, dealer_i, vul, fc, leader_i, hand,
                      full_auction, le, verdict, auc_meanings,
                      card_notes, elapsed) -> dict:
    return {
        "schema": 1,
        "kind": "lead",
        # main's index reads difficulty_level from classification; leads carry
        # their own 1-5 difficulty there so the difficulty filter includes them
        # (no type taxonomy for leads — difficulty is the only lead facet).
        "classification": {"difficulty_level": verdict.difficulty},
        "id": f"lead1-{seed:08x}",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": {"engine": "ben BEN-21GF", "seed": seed,
                      "samples": le.n_samples,
                      "elapsed_s": round(elapsed, 1)},
        "scoring_form": "tricks",
        "dealer": SEATS[dealer_i],
        "vul": VUL_NAMES[vul],
        "declarer": SEATS[fc["declarer_i"]],
        "contract": contract_str(fc),
        "leader": SEATS[leader_i],
        "seat": SEATS[leader_i],          # lets shared UI helpers reuse it
        "hand": hand,
        "auction": list(full_auction),
        "candidates": [{"card": r["card"],
                        "avg_def_tricks": r["avg_def_tricks"],
                        "ben_softmax": r["ben_softmax"]}
                       for r in verdict.table],
        "verdict": {
            "accepted": list(verdict.best),
            "gap": verdict.measured.get("gap"),
            "n_samples": le.n_samples,
            "table": verdict.table,
            "flags": verdict.flags,
        },
        "difficulty": verdict.difficulty,
        "quality": verdict.measured,
        "explanations": {
            "note": "call meanings follow standard 2/1 Game Force",
            "auction": auc_meanings,
            "cards": card_notes,
        },
        "full_deal": {SEATS[i]: h for i, h in enumerate(hands)},
        "engine_auction_complete": list(full_auction),
    }


def forge_lead_batch(pool_dir: str, count: int, base_seed: int,
                     max_seconds: float = 3600.0, log=print) -> dict:
    from .ben import get_engine
    from .lead_explain import auction_meanings, card_notes

    pool_dir = os.path.abspath(pool_dir)   # before engine chdir's into ben
    t_load = time.perf_counter()
    engine = get_engine()
    log(f"engine loaded in {time.perf_counter() - t_load:.1f}s")

    pool = ProblemPool(pool_dir)
    existing = set(pool.ids())
    made, rejections = [], Counter()
    quotas = {"vuls": Counter(), "difficulty": Counter()}
    t0 = time.perf_counter()
    k = 0
    while len(made) < count and time.perf_counter() - t0 < max_seconds:
        seed = base_seed + k
        k += 1
        t_board = time.perf_counter()
        try:
            hands, dealer_i, vul, full_auction = bid_out(engine, seed)
        except Exception as e:
            rejections["bid_error"] += 1
            log(f"  seed {seed}: bid error ({type(e).__name__}: {e})")
            continue

        fc = final_contract(full_auction, dealer_i)
        if fc is None:
            rejections["passed_out"] += 1
            continue
        if fc["doubled"]:
            rejections["doubled_excluded"] += 1
            continue
        leader_i = opening_leader(fc["declarer_i"])
        hand = hands[leader_i]
        if not _hand_ok(hand):
            rejections["round_trip"] += 1
            continue
        contract = contract_str(fc)

        def evaluate(n):
            return engine.lead_evaluate(
                hand, leader_i, dealer_i, vul, full_auction,
                fc["denom"], contract, bool(fc["doubled"]), n_samples=n)

        try:
            le = evaluate(SCREEN_SAMPLES)
        except Exception as e:
            rejections["evaluate_error"] += 1
            log(f"  seed {seed}: evaluate error ({type(e).__name__}: {e})")
            continue
        v = judge_lead(le)
        if not v.accepted:
            rejections[v.reason] += 1
            log(f"  seed {seed}: {v.reason} "
                f"gap={v.measured.get('gap')} contract={contract}")
            continue

        try:
            le = evaluate(CONFIRM_SAMPLES)
        except Exception as e:
            rejections["confirm_error"] += 1
            continue
        v = judge_lead(le)
        if not v.accepted:
            rejections["confirm_" + v.reason] += 1
            log(f"  seed {seed}: confirm_{v.reason} gap={v.measured.get('gap')}")
            continue

        auc = auction_meanings(engine, hand, leader_i, dealer_i, vul,
                               full_auction)
        notes = card_notes(v)
        elapsed = time.perf_counter() - t_board
        rec = build_lead_record(seed, hands, dealer_i, vul, fc, leader_i,
                                hand, full_auction, le, v, auc, notes, elapsed)
        if rec["id"] in existing:
            rejections["duplicate"] += 1
            continue
        pool.add(rec)
        pool.rebuild_index()
        existing.add(rec["id"])
        made.append(rec["id"])
        quotas["vuls"][rec["vul"]] += 1
        quotas["difficulty"][v.difficulty] += 1
        log(f"  seed {seed}: ACCEPTED {rec['id']} [{len(made)}/{count}] "
            f"lead {SEATS[leader_i]} vs {contract} "
            f"best={'/'.join(v.best)} gap={v.measured.get('gap')} "
            f"diff={v.difficulty} [{elapsed:.1f}s]")

    wall = time.perf_counter() - t0
    summary = {
        "made": made, "count": len(made), "wall_s": round(wall, 1),
        "boards_bid": k, "rejections": dict(rejections),
        "per_accepted_s": round(wall / len(made), 1) if made else None,
        "mix": {"vuls": dict(quotas["vuls"]),
                "difficulty": dict(quotas["difficulty"])},
    }
    log(f"\nDone: {len(made)}/{count} in {wall / 60:.1f} min; "
        f"bid {k} boards; rejections: {dict(rejections)}")
    return summary
