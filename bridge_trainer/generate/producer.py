"""Batch producer: generate random problems into the pool.

Runs generate_problem over successive seeds, keeping only problems that
survive the interestingness filter, until `count` are stored or the time
budget runs out. Every attempt is logged with its outcome so acceptance
tuning is measurable.

With jobs > 1 seeds are evaluated in a process pool. Each worker's DD solve
already saturates ~4 cores via DDS's internal threading, so extra jobs pay
off on many-core machines (or to smooth the gaps between DDS calls); on a
4-core box jobs=1 is already near-optimal. Acceptance per seed is unchanged
and deterministic; only WHICH seeds land in the pool when `count` is hit
depends on completion order.
"""
from __future__ import annotations

import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait

from ..pool.store import ProblemPool
from .random_problem import generate_problem


def _generate_timed(seed: int, n_deals: int):
    t0 = time.perf_counter()
    record, reason = generate_problem(seed=seed, n_deals=n_deals)
    return seed, record, reason, time.perf_counter() - t0


def produce_batch(
    pool_dir: str,
    count: int,
    max_seconds: float,
    base_seed: int,
    n_deals: int = 600,
    jobs: int = 1,
) -> list[str]:
    pool = ProblemPool(pool_dir)
    existing = set(pool.ids())
    made: list[str] = []
    t0 = time.perf_counter()

    def handle(seed, record, reason, dt):
        if record is None:
            print(f"  seed {seed}: rejected ({reason}) [{dt:.1f}s]")
            return
        if record["id"] in existing:
            print(f"  seed {seed}: duplicate id, skipped")
            return
        if len(made) >= count:
            return  # parallel tail finished after the bank filled up
        pool.add(record)
        existing.add(record["id"])
        made.append(record["id"])
        print(f"  seed {seed}: ACCEPTED {record['id']} "
              f"difficulty={record['difficulty']:.2f} "
              f"auction='{' '.join(record['auction'])}' [{dt:.1f}s]")

    def keep_going():
        return len(made) < count and time.perf_counter() - t0 < max_seconds

    k = 0
    if jobs <= 1:
        while keep_going():
            handle(*_generate_timed(base_seed + k, n_deals))
            k += 1
    else:
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            pending = set()
            while keep_going() and len(pending) < jobs:
                pending.add(ex.submit(_generate_timed, base_seed + k, n_deals))
                k += 1
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for fut in done:
                    handle(*fut.result())
                while keep_going() and len(pending) < jobs:
                    pending.add(
                        ex.submit(_generate_timed, base_seed + k, n_deals))
                    k += 1
    pool.rebuild_index()
    return made
