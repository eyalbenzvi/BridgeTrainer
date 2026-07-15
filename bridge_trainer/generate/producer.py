"""Batch producer: generate random problems into the pool.

Runs generate_problem over successive seeds, keeping only problems that
survive the interestingness filter, until `count` are stored or the time
budget runs out. Every attempt is logged with its outcome so acceptance
tuning is measurable.
"""
from __future__ import annotations

import time

from ..pool.store import ProblemPool
from .random_problem import generate_problem


def produce_batch(
    pool_dir: str,
    count: int,
    max_seconds: float,
    base_seed: int,
    n_deals: int = 600,
) -> list[str]:
    pool = ProblemPool(pool_dir)
    existing = set(pool.ids())
    made: list[str] = []
    t0 = time.perf_counter()
    k = 0
    while len(made) < count and time.perf_counter() - t0 < max_seconds:
        seed = base_seed + k
        k += 1
        t_one = time.perf_counter()
        record, reason = generate_problem(seed=seed, n_deals=n_deals)
        dt = time.perf_counter() - t_one
        if record is None:
            print(f"  seed {seed}: rejected ({reason}) [{dt:.1f}s]")
            continue
        if record["id"] in existing:
            print(f"  seed {seed}: duplicate id, skipped")
            continue
        pool.add(record)
        existing.add(record["id"])
        made.append(record["id"])
        print(f"  seed {seed}: ACCEPTED {record['id']} "
              f"difficulty={record['difficulty']:.2f} "
              f"auction='{' '.join(record['auction'])}' [{dt:.1f}s]")
    pool.rebuild_index()
    return made
