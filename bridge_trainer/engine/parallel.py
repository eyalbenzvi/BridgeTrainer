"""Board-level parallelism for the forge: N spawn-context workers, each
owning a full Ben engine (~1.2 GB), a single-threaded parent owning the
pool. Boards are independent, so this scales near-linearly until the
cores are saturated — provided each worker's INTERNAL parallelism is
turned off (DDS alone defaults to one solver thread per core, so four
naive workers on a 4-core box would run 16+ native threads).

Shutdown protocol (review-hardened): the parent never bare-joins after
setting the stop event — a worker blocked on result_q.put() would
deadlock it. Instead it drains the result queue until every worker has
sent its exit sentinel (or a grace timeout passes); workers are daemons,
so anything still alive at interpreter exit is reaped, never joined
while possibly holding a queue feeder lock. Worker death (OOM is a real
possibility) is detected by polling liveness alongside the queue.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import queue as queue_mod
import time

_STOP_GRACE_S = 90.0     # a board in flight can legitimately take ~1 min


def _worker_main(worker_id: int, task_q, result_q, stop, dds_threads: int,
                 audit_prescreen: bool, domain: str = "bidding",
                 require_doubled: bool = False,
                 doubled_min_gap: float = 0.0,
                 doubled_apply_obvious: bool = False,
                 target_mode: str = "MP") -> None:
    # Thread caps BEFORE anything imports TensorFlow: with board-level
    # parallelism as the only parallelism, each worker gets 1 compute
    # thread plus its DDS slice.
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["TF_NUM_INTRAOP_THREADS"] = "1"
    os.environ["TF_NUM_INTEROP_THREADS"] = "1"
    import tensorflow as tf
    try:
        tf.config.threading.set_intra_op_parallelism_threads(1)
        tf.config.threading.set_inter_op_parallelism_threads(1)
    except RuntimeError:
        pass  # already initialized (env vars still apply)

    from .ben import get_engine
    if domain == "lead":
        from .lead_maker import forge_lead_one as forge_one
    else:
        from .maker import forge_one

    try:
        t0 = time.perf_counter()
        engine = get_engine(dds_max_threads=dds_threads)
        engine.models.suppress_warnings = True  # avoid interleaved stderr
        result_q.put(("ready", worker_id,
                      round(time.perf_counter() - t0, 1)))
        while not stop.is_set():
            try:
                seed = task_q.get(timeout=0.5)
            except queue_mod.Empty:
                continue
            if seed is None:
                break
            if domain == "lead":
                out = forge_one(engine, seed, audit_prescreen,
                                require_doubled=require_doubled,
                                doubled_min_gap=doubled_min_gap,
                                doubled_apply_obvious=doubled_apply_obvious,
                                target_mode=target_mode)
            else:
                out = forge_one(engine, seed, audit_prescreen)
            result_q.put(("board", worker_id, out))
    except Exception as e:  # engine failed to load, or a crash between boards
        result_q.put(("fatal", worker_id, f"{type(e).__name__}: {e}"))
    finally:
        result_q.put(("exit", worker_id, None))


def forge_batch_parallel(pool_dir: str, count: int, base_seed: int,
                         max_seconds: float, log, workers: int,
                         audit_prescreen: bool, domain: str = "bidding",
                         require_doubled: bool = False,
                         doubled_min_gap: float = 0.0,
                         doubled_apply_obvious: bool = False,
                         target_mode: str = "MP") -> dict:
    if domain == "lead":
        from .lead_maker import _LeadBatchState as _BatchState
    else:
        from .maker import _BatchState

    ctx = mp.get_context("spawn")   # TF is not fork-safe
    task_q, result_q = ctx.Queue(), ctx.Queue()
    stop = ctx.Event()
    dds_threads = max(1, (os.cpu_count() or workers) // workers)
    procs = [ctx.Process(target=_worker_main,
                         args=(w, task_q, result_q, stop, dds_threads,
                               audit_prescreen, domain, require_doubled,
                               doubled_min_gap, doubled_apply_obvious,
                               target_mode),
                         daemon=True, name=f"forge-w{w}")
             for w in range(workers)]
    for p in procs:
        p.start()
    log(f"spawned {workers} workers (dds {dds_threads} thread(s) each); "
        f"loading engines...")

    next_seed = base_seed
    for _ in range(2 * workers):    # keep ~2 boards buffered per worker
        task_q.put(next_seed)
        next_seed += 1

    state = _BatchState(pool_dir, count, log)
    t0 = time.perf_counter()
    alive = set(range(workers))
    exited: set[int] = set()
    try:
        while len(state.made) < count and alive - exited:
            if time.perf_counter() - t0 >= max_seconds:
                log("time budget reached")
                break
            try:
                msg = result_q.get(timeout=2.0)
            except queue_mod.Empty:
                for w, p in enumerate(procs):   # OOM-killed worker?
                    if w in alive and w not in exited and not p.is_alive():
                        log(f"  [w{w}] worker died (exit code "
                            f"{p.exitcode}) — capacity reduced")
                        alive.discard(w)
                continue
            kind, w, payload = msg
            if kind == "ready":
                log(f"  [w{w}] engine loaded in {payload}s")
            elif kind == "fatal":
                log(f"  [w{w}] fatal: {payload}")
                alive.discard(w)
            elif kind == "exit":
                exited.add(w)
                alive.discard(w)
            elif kind == "board":
                state.absorb(payload, tag=f"[w{w}] ")
                if len(state.made) < count:
                    task_q.put(next_seed)
                    next_seed += 1
    finally:
        stop.set()
        # drain until every started worker reports exit (or grace passes);
        # daemon workers guarantee cleanup even if we give up
        deadline = time.perf_counter() + _STOP_GRACE_S
        while exited != set(range(workers)) and time.perf_counter() < deadline:
            try:
                msg = result_q.get(timeout=1.0)
            except queue_mod.Empty:
                if all(not p.is_alive() for p in procs):
                    break
                continue
            if msg[0] == "exit":
                exited.add(msg[1])
            elif msg[0] == "board":
                # a board finished after the target was hit still counts
                # toward the pool unless that would overshoot the request
                if len(state.made) < count:
                    state.absorb(msg[2], tag=f"[w{msg[1]}] ")
        for p in procs:
            p.join(timeout=1.0)

    wall = time.perf_counter() - t0
    summary = state.summary(wall)
    summary["workers"] = workers
    log(f"\nDone: {len(state.made)}/{count} in {wall / 60:.1f} min "
        f"({summary['per_accepted_s']}s per accepted deal, "
        f"{workers} workers); scanned {state.boards} boards; "
        f"rejections: {summary['rejections']}")
    return summary
