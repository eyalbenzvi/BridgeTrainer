"""Queue worker: process pending analysis requests from Firestore.

Runs inside GitHub Actions (.github/workflows/analyze-requests.yml) with the
Admin SDK (bypasses security rules — the rules only constrain the browser
client). The site files request docs; this worker claims each one with a
status CAS transaction (pending -> running), re-validates the payload, runs
the same pipeline the local tool uses, and writes the finished report back:

    analysis_requests/{id}: status pending|running|done|error, summary, ...
    analysis_reports/{id}:  {uid, html, facts, createdAt}

Operational rules:
  * the repo is PUBLIC, so Actions logs are public — never log hand,
    auction or report content; ids, counts and timings only;
  * per-user daily cap (DAILY_LIMIT) so one account cannot monopolize the
    runner or the Firestore free tier;
  * max_deals is clamped; a request can lower it, never raise it past cap;
  * every failure lands as status="error" with a short reason — a request
    is never left dangling in "running" by a crash we can catch.
"""
from __future__ import annotations

import time
import traceback

from .llm_narrator import llm_narrate
from .pipeline import AnalysisRequest, run_analysis
from .report import build_facts, facts_to_json, narrate_all, render_report

REQUESTS = "analysis_requests"
REPORTS = "analysis_reports"
DAILY_LIMIT = 20            # analyses per user per UTC day
MAX_DEALS_CAP = 2000
DEFAULT_DEALS = 1500        # CI runners are slower than a dev machine
MAX_HTML_BYTES = 900_000    # Firestore doc limit is 1 MiB


def get_db(key_path: str | None = None):
    from ..pool.firestore_store import _client  # same creds resolution
    return _client(key_path)


def _server_ts():
    try:
        from firebase_admin import firestore
        return firestore.SERVER_TIMESTAMP
    except ImportError:                      # unit tests with a fake db
        return time.time()


def _run_transaction(txn, body):
    try:
        from firebase_admin import firestore
        return firestore.transactional(body)(txn)
    except ImportError:                      # fake transaction in tests
        return body(txn)


def claim(db, ref, run_id: str) -> bool:
    """CAS pending -> running; False if someone else got there first."""
    def body(t):
        snap = ref.get(transaction=t)
        data = snap.to_dict() or {}
        if data.get("status") != "pending":
            return False
        t.update(ref, {"status": "running", "startedAt": _server_ts(),
                       "runId": run_id})
        return True
    return _run_transaction(db.transaction(), body)


def _created_seconds(data: dict) -> float:
    ts = data.get("createdAt")
    if ts is None:
        return 0.0
    if hasattr(ts, "timestamp"):
        return float(ts.timestamp())
    if isinstance(ts, dict) and "seconds" in ts:
        return float(ts["seconds"])
    return float(ts) if isinstance(ts, (int, float)) else 0.0


def over_daily_limit(db, uid: str, now: float | None = None) -> bool:
    """Count the user's requests filed since UTC midnight (single-field
    uid query — no composite index; the per-user collection stays small)."""
    now = now or time.time()
    day_start = now - (now % 86400)
    docs = db.collection(REQUESTS).where("uid", "==", uid).stream()
    n_today = sum(1 for d in docs
                  if _created_seconds(d.to_dict() or {}) >= day_start)
    return n_today > DAILY_LIMIT


def process_request(req: dict, narration_available: bool = False) -> tuple:
    """Validate + run one analysis. Returns (summary, html, facts_json).
    Raises on any invalid payload — the caller records status=error."""
    overrides = {int(k): v for k, v in (req.get("overrides") or {}).items()}
    max_deals = min(int(req.get("max_deals", DEFAULT_DEALS)), MAX_DEALS_CAP)
    areq = AnalysisRequest(
        dealer=str(req["dealer"]), vul=str(req["vul"]),
        my_seat=str(req["my_seat"]), my_hand=str(req["my_hand"]),
        auction=[str(t) for t in req["auction"]],
        decision_index=int(req["decision_index"]),
        system=str(req.get("system", "two_over_one")),
        scoring=str(req.get("scoring", "IMP")),
        candidates=[str(c) for c in req["candidates"]]
        if req.get("candidates") else None,
        overrides=overrides,
        seed=int(req.get("seed", 1)),
        max_deals=max(100, max_deals),
    )
    result = run_analysis(areq)
    facts = build_facts(result)
    use_llm = narration_available and req.get("narration") == "llm"
    prose = llm_narrate(facts) if use_llm else narrate_all(facts)
    html = render_report(facts, prose)
    if len(html.encode("utf-8")) > MAX_HTML_BYTES:
        raise RuntimeError("report too large for a Firestore document")
    summary = {
        "recommended": result.recommended,
        "actual": result.actual_call,
        "n_deals": result.n_deals,
        "mean_imp": round(result.top_pair_mean_imp, 2),
        "ci": round(result.top_pair_ci, 2),
        "stable": result.stable,
        "scoring": areq.scoring,
        "narrator": prose.get("narrator", "template"),
    }
    return summary, html, facts_to_json(facts)


def _short_error(exc: Exception) -> str:
    msg = f"{type(exc).__name__}: {exc}"
    return msg[:400]


def run_queue(db, run_id: str = "local", max_requests: int = 6,
              narration_available: bool = False, log=print) -> dict:
    """Process up to max_requests pending docs, oldest first.

    Returns {"processed": n, "done": n, "errors": n, "skipped": n}.
    """
    snaps = list(db.collection(REQUESTS)
                 .where("status", "==", "pending").limit(25).stream())
    snaps.sort(key=lambda s: _created_seconds(s.to_dict() or {}))
    stats = {"processed": 0, "done": 0, "errors": 0, "skipped": 0}

    for snap in snaps:
        if stats["processed"] >= max_requests:
            break
        ref = snap.reference
        if not claim(db, ref, run_id):
            stats["skipped"] += 1
            continue
        stats["processed"] += 1
        data = snap.to_dict() or {}
        uid = data.get("uid", "")
        t0 = time.time()
        try:
            if over_daily_limit(db, uid):
                raise RuntimeError(
                    f"חריגה מהמכסה היומית ({DAILY_LIMIT} ניתוחים ביום)")
            summary, html, facts_json = process_request(
                data.get("req") or {}, narration_available)
            db.collection(REPORTS).document(snap.id).set({
                "uid": uid, "html": html, "facts": facts_json,
                "createdAt": _server_ts(),
            })
            ref.update({"status": "done", "summary": summary,
                        "finishedAt": _server_ts()})
            stats["done"] += 1
            # public logs: id + timing only, never content
            log(f"[worker] {snap.id[:10]} done "
                f"({summary['n_deals']} deals, {time.time() - t0:.0f}s)")
        except Exception as exc:
            stats["errors"] += 1
            ref.update({"status": "error", "error": _short_error(exc),
                        "finishedAt": _server_ts()})
            log(f"[worker] {snap.id[:10]} error "
                f"({type(exc).__name__}, {time.time() - t0:.0f}s)")
            traceback.print_exc()
    log(f"[worker] queue pass: {stats}")
    return stats


def main(key_path: str | None = None, max_requests: int = 6,
         run_id: str = "manual") -> int:
    import os
    db = get_db(key_path)
    narration_available = bool(os.environ.get("ANTHROPIC_API_KEY"))
    run_queue(db, run_id=run_id, max_requests=max_requests,
              narration_available=narration_available)
    return 0
