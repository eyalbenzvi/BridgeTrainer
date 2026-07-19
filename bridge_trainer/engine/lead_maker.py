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
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..pool.store import ProblemPool
from .conventions import (SEATS, contract_str, final_contract,
                          opening_leader)
from .lead_verdict import P_OBVIOUS, judge_lead, prejudge_lead
from .scanner import VUL_NAMES, bid_out

SCREEN_SAMPLES = 128    # full screen sample pool
CONFIRM_SAMPLES = 512   # published evidence
PRESCREEN_STEPS = (32, 64)   # decisive rule-out checkpoints before full screen


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


@dataclass
class LeadOutcome:
    """Everything the batch loop needs to know about one board."""
    seed: int
    status: str                    # accepted | rejected | error
    reason: str = ""
    rec: dict | None = None
    timings: dict = field(default_factory=dict)
    detail: str = ""               # preformatted log tail (no [i/count])


def forge_lead_one(engine, seed: int, audit_prescreen: bool = False
                   ) -> LeadOutcome:
    """The whole per-board pipeline: bid out -> final contract -> screening
    cascade (32/64/128) -> 512-sample confirm -> explanations. Self-contained
    so the sequential loop and the parallel workers share one implementation.

    `audit_prescreen` is accepted for signature parity with maker.forge_one
    (the parallel harness passes it uniformly); leads have no prescreen audit.
    """
    from .lead_explain import auction_meanings, card_notes

    t = {}
    t_board = time.perf_counter()
    try:
        hands, dealer_i, vul, full_auction = bid_out(engine, seed)
    except Exception as e:
        return LeadOutcome(seed, "error", "bid_error",
                           detail=f"bid error ({type(e).__name__}: {e})")
    t["bid_out_s"] = time.perf_counter() - t_board

    fc = final_contract(full_auction, dealer_i)
    if fc is None:
        return LeadOutcome(seed, "rejected", "passed_out", timings=t)
    if fc["doubled"]:
        return LeadOutcome(seed, "rejected", "doubled_excluded", timings=t)
    leader_i = opening_leader(fc["declarer_i"])
    hand = hands[leader_i]
    if not _hand_ok(hand):
        return LeadOutcome(seed, "rejected", "round_trip", timings=t)
    contract = contract_str(fc)
    dbl = bool(fc["doubled"])

    def evaluate(n):
        return engine.lead_evaluate(
            hand, leader_i, dealer_i, vul, full_auction,
            fc["denom"], contract, dbl, n_samples=n)

    # ---- screening cascade: sample the layouts once, double-dummy them
    # 32 -> 64 -> 128, and bail as soon as the board is a confident
    # rule-out. Most boards die at 32/64, so most DD runs are saved.
    ts = time.perf_counter()
    try:
        grade, navail, top_soft = engine.lead_open(
            hand, leader_i, dealer_i, vul, full_auction, contract, dbl,
            pool_n=SCREEN_SAMPLES)
    except Exception as e:
        t["screen_s"] = time.perf_counter() - ts
        return LeadOutcome(seed, "error", "evaluate_error", timings=t,
                           detail=f"sample error ({type(e).__name__}: {e})")
    if top_soft > P_OBVIOUS:            # obvious: no DD needed at all
        t["screen_s"] = time.perf_counter() - ts
        return LeadOutcome(seed, "rejected", "pre_obvious", timings=t)
    ruled = None
    for n in PRESCREEN_STEPS:
        pv = prejudge_lead(grade(n))
        if pv:
            ruled = pv
            break
    le = grade(SCREEN_SAMPLES) if not ruled else None
    t["screen_s"] = time.perf_counter() - ts
    if ruled:
        return LeadOutcome(seed, "rejected", "pre_" + ruled, timings=t,
                           detail=f"pre_{ruled} contract={contract}")
    v = judge_lead(le)
    if not v.accepted:
        return LeadOutcome(
            seed, "rejected", v.reason, timings=t,
            detail=f"{v.reason} gap={v.measured.get('gap')} "
                   f"contract={contract}")

    tc = time.perf_counter()
    try:
        le = evaluate(CONFIRM_SAMPLES)
    except Exception as e:
        return LeadOutcome(seed, "error", "confirm_error", timings=t,
                           detail=f"confirm error ({type(e).__name__}: {e})")
    t["confirm_s"] = time.perf_counter() - tc
    v = judge_lead(le)
    if not v.accepted:
        return LeadOutcome(
            seed, "rejected", "confirm_" + v.reason, timings=t,
            detail=f"confirm_{v.reason} gap={v.measured.get('gap')}")

    te = time.perf_counter()
    auc = auction_meanings(engine, hand, leader_i, dealer_i, vul, full_auction)
    notes = card_notes(v)
    t["explain_s"] = time.perf_counter() - te
    elapsed = time.perf_counter() - t_board
    rec = build_lead_record(seed, hands, dealer_i, vul, fc, leader_i,
                            hand, full_auction, le, v, auc, notes, elapsed)
    detail = (f"ACCEPTED {rec['id']} lead {SEATS[leader_i]} vs {contract} "
              f"best={'/'.join(v.best)} gap={v.measured.get('gap')} "
              f"diff={v.difficulty} [{elapsed:.1f}s]")
    return LeadOutcome(seed, "accepted", "accepted", rec=rec, timings=t,
                       detail=detail)


class _LeadBatchState:
    """Aggregation shared by the sequential and parallel lead paths
    (mirrors maker._BatchState)."""

    def __init__(self, pool_dir: str, count: int, log):
        self.pool = ProblemPool(pool_dir)
        self.existing = set(self.pool.ids())
        self.count = count
        self.log = log
        self.made: list[str] = []
        self.rejections = Counter()
        self.stage_totals = Counter()
        self.quotas = {"vuls": Counter(), "difficulty": Counter()}
        self.boards = 0

    def absorb(self, out: LeadOutcome, tag: str = "") -> None:
        self.boards += 1
        for k, x in out.timings.items():
            self.stage_totals[k] += x
        if out.status in ("rejected", "error"):
            self.rejections[out.reason] += 1
            if out.detail:
                self.log(f"  {tag}seed {out.seed}: {out.detail}")
            return
        rec = out.rec
        if rec["id"] in self.existing:
            self.rejections["duplicate"] += 1
            return
        self.pool.add(rec)
        self.pool.rebuild_index()
        self.existing.add(rec["id"])
        self.made.append(rec["id"])
        self.quotas["vuls"][rec["vul"]] += 1
        self.quotas["difficulty"][rec["difficulty"]] += 1
        self.log(f"  {tag}seed {out.seed}: "
                 + out.detail.replace(
                     "ACCEPTED " + rec["id"],
                     f"ACCEPTED {rec['id']} [{len(self.made)}/{self.count}]",
                     1))

    def summary(self, wall: float) -> dict:
        return {
            "made": self.made, "count": len(self.made),
            "wall_s": round(wall, 1), "boards_bid": self.boards,
            "rejections": dict(self.rejections),
            "stage_totals_s": {s: round(x, 1)
                               for s, x in self.stage_totals.items()},
            "per_accepted_s": round(wall / len(self.made), 1)
            if self.made else None,
            "mix": {"vuls": dict(self.quotas["vuls"]),
                    "difficulty": dict(self.quotas["difficulty"])},
        }


def forge_lead_batch(pool_dir: str, count: int, base_seed: int,
                     max_seconds: float = 3600.0, log=print,
                     workers: int = 1) -> dict:
    pool_dir = os.path.abspath(pool_dir)   # before engine chdir's into ben

    if workers == 0:
        # auto: each worker holds a ~1.2 GB engine — stay conservative
        workers = max(1, min(3, os.cpu_count() or 1))
    if workers > 1:
        from .parallel import forge_batch_parallel
        return forge_batch_parallel(pool_dir, count, base_seed, max_seconds,
                                    log, workers, False, domain="lead")

    from .ben import get_engine

    t_load = time.perf_counter()
    engine = get_engine()
    log(f"engine loaded in {time.perf_counter() - t_load:.1f}s")

    state = _LeadBatchState(pool_dir, count, log)
    t0 = time.perf_counter()
    k = 0
    while len(state.made) < count and time.perf_counter() - t0 < max_seconds:
        state.absorb(forge_lead_one(engine, base_seed + k))
        k += 1

    wall = time.perf_counter() - t0
    summary = state.summary(wall)
    log(f"\nDone: {len(state.made)}/{count} in {wall / 60:.1f} min; "
        f"bid {state.boards} boards; rejections: {summary['rejections']}")
    return summary
