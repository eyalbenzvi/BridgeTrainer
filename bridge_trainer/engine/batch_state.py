"""Shared batch aggregation for the forge loops (ARCH-7).

maker._BatchState and lead_maker._LeadBatchState had nearly identical bodies —
dedup against the existing pool, add + rebuild the index, tally rejections and
per-stage timings, and emit a run summary. They differed only in the quota
axes tracked, the logging cadence (maker logs every board; leads log every N
accepts), and a few summary key names. That core lives here now; each domain
subclasses and fills the hooks, so a fix to the batch loop is made once.

Both the sequential loops (maker.forge_batch / lead_maker.forge_lead_batch) and
the parallel collector (engine/parallel.py) drive this through the same
``absorb(outcome, tag=...)`` / ``summary(wall)`` interface.
"""
from __future__ import annotations

from collections import Counter

from ..pool.store import ProblemPool


class BatchState:
    """Common accept/reject bookkeeping. Subclasses provide the per-domain
    quota tracking, logging, and summary shape via the hooks below."""

    boards_key = "boards_scanned"       # summary key for the scan count

    def __init__(self, pool_dir: str, count: int, log):
        self.pool = ProblemPool(pool_dir)
        self.existing = set(self.pool.ids())
        self.count = count
        self.log = log
        self.made: list[str] = []
        self.rejections = Counter()
        self.stage_totals = Counter()
        self.boards = 0
        self._init_quotas()

    # ---- hooks (override as needed) ------------------------------------
    def _init_quotas(self) -> None:
        """Set up any per-domain quota counters (self.quotas, timers, ...)."""

    def _absorb_extra(self, out) -> None:
        """Per-board work that runs for EVERY outcome, before the accept/reject
        split (maker uses it for prescreen-audit accounting)."""

    def _on_reject(self, out, tag: str) -> None:
        """Called after a rejection is counted (maker logs a detail line)."""

    def _on_accept(self, out, rec, tag: str) -> None:
        """Called after an accepted record is added to the pool and self.made
        (record quotas here, and any per-accept logging/progress)."""

    def _mix(self) -> dict:
        """The 'mix' block of the summary (per-domain quota axes)."""
        return {}

    def _summary_extra(self, summary: dict) -> None:
        """Add any domain-specific summary keys (maker adds prescreen_audit)."""

    # ---- shared core ----------------------------------------------------
    def absorb(self, out, tag: str = "") -> None:
        self.boards += 1
        for k, x in out.timings.items():
            self.stage_totals[k] += x
        self._absorb_extra(out)
        if out.status in ("rejected", "error"):
            self.rejections[out.reason] += 1
            self._on_reject(out, tag)
            return
        rec = out.rec
        if rec["id"] in self.existing:
            self.rejections["duplicate"] += 1
            return
        self.pool.add(rec)
        self.pool.rebuild_index()
        self.existing.add(rec["id"])
        self.made.append(rec["id"])
        self._on_accept(out, rec, tag)

    def summary(self, wall: float) -> dict:
        summary = {
            "made": self.made, "count": len(self.made),
            "wall_s": round(wall, 1), self.boards_key: self.boards,
            "rejections": dict(self.rejections),
            "stage_totals_s": {k: round(x, 1)
                               for k, x in self.stage_totals.items()},
            "per_accepted_s": round(wall / len(self.made), 1)
            if self.made else None,
            "mix": self._mix(),
        }
        self._summary_extra(summary)
        return summary
