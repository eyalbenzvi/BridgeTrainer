"""Ensemble batch assembly (approach F, in-session).

A batch is produced in four stages, the first two by Claude Code
subagents inside an interactive session (no API key, no scheduler):

  1. PROPOSER   drafts one finalization document per spot
                (scratchpad/proposals.json, keyed "<lin>-<board>")
  2. VERIFIER   independently audits every proposal: verdict
                "accept" | "patch" (with a full patched_doc) | "reject"
                (scratchpad/reviews.json, same keys)
  3. THIS MODULE merges the verdicts, runs every surviving document
                through the hard shell + DD judge (build_record), and
                keeps the `keep` closest genuine dilemmas
  4. DEPLOY     the pool directory replaces data/ on gh-pages

Stage 3 is deterministic and unit-tested; stages 1-2 are judgment and
are deliberately NOT trusted — build_record re-validates everything.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..pool.store import ProblemPool
from .schema import FinalizationError, build_record


def resolve_reviews(proposals: dict, reviews: dict) -> dict:
    """Merge proposer + verifier output into the surviving documents.

    accept -> the original proposal; patch -> the verifier's patched_doc;
    reject (by either stage) -> dropped.
    """
    docs = {}
    for key, proposal in proposals.items():
        review = reviews.get(key) or {}
        verdict = review.get("verdict")
        if not proposal.get("dilemma") or verdict == "reject":
            continue
        if verdict == "patch":
            docs[key] = review["patched_doc"]
        elif verdict == "accept":
            docs[key] = proposal
        # no review -> not audited -> not trusted -> dropped
    return docs


def judge_spot(spot: dict, doc: dict, *, n_deals: int = 600) -> dict:
    """Run one surviving document through the shell + DD judge."""
    lin, board = str(spot["lin"]), int(spot["board"])
    return build_record(
        problem_id=f"e{lin}-{board}",
        dealer=spot["dealer"], vul=spot["vul"], hero=spot["hero"],
        hands=spot["hands"], stem=spot["stem"], doc=doc,
        n_deals=n_deals, seed=int(lin) * 100 + board,
        source={
            "kind": "vugraph",
            "event": spot.get("event", ""),
            "teams": spot.get("teams", ""),
            "board": board,
            "room_calls": spot.get("room_calls", {}),
            "room_contracts": spot.get("room_contracts", {}),
        })


def dedupe_deals(records: list[dict]) -> tuple[list[dict], list[str]]:
    """F25: one problem per physical deal. When the same board appears
    from two perspectives, keep the closer decision; the other is spoiled
    the moment the first one shows its full deal."""
    best: dict[str, dict] = {}
    dropped = []
    for rec in records:
        key = rec.get("deal_hash") or rec["id"]
        cur = best.get(key)
        if cur is None:
            best[key] = rec
        elif abs(rec["difficulty"]) < abs(cur["difficulty"]):
            dropped.append(cur["id"])
            best[key] = rec
        else:
            dropped.append(rec["id"])
    return list(best.values()), dropped


def select_batch(records: list[dict], keep: int) -> list[dict]:
    """Keep the `keep` best problems: genuine dilemmas first.

    Ranking: smaller DD margin = closer decision = better training
    value. Equivalence-collapsed toss-ups rank after true close calls
    at the same margin (the options genuinely differ there). Spread
    across source matches (lin file) and problem categories (F26)
    before taking more from one bucket.
    """
    def margin(rec):
        return abs(rec["difficulty"])

    cat_cap = max(2, -(-keep // 2))  # no category may exceed half the batch
    ranked = sorted(records, key=lambda r: (margin(r),
                                            bool(r["quality"]["equivalent_pairs"])))
    picked, per_lin, per_cat, backlog = [], {}, {}, []
    for rec in ranked:
        lin = rec["id"].split("-")[0]
        cat = rec.get("category", "other")
        if per_lin.get(lin, 0) >= 2 or per_cat.get(cat, 0) >= cat_cap:
            backlog.append(rec)
            continue
        picked.append(rec)
        per_lin[lin] = per_lin.get(lin, 0) + 1
        per_cat[cat] = per_cat.get(cat, 0) + 1
        if len(picked) == keep:
            return picked
    return (picked + backlog)[:keep]


def assemble(spots_path: str | Path, proposals_path: str | Path,
             reviews_path: str | Path, pool_root: str | Path,
             *, keep: int = 8, n_deals: int = 600) -> dict:
    """Full stage-3 run: judge every survivor, keep the best, write pool.

    Returns a report dict: kept ids, per-spot outcomes, failures.
    """
    spots = {f"{s['lin']}-{s['board']}": s
             for s in json.loads(Path(spots_path).read_text())}
    proposals = json.loads(Path(proposals_path).read_text())
    reviews = json.loads(Path(reviews_path).read_text())

    docs = resolve_reviews(proposals, reviews)
    records, failures = [], {}
    for key, doc in docs.items():
        try:
            records.append(judge_spot(spots[key], doc, n_deals=n_deals))
        except FinalizationError as exc:  # hard shell or gates
            failures[key] = str(exc)

    records, duplicates = dedupe_deals(records)
    batch = select_batch(records, keep)
    pool = ProblemPool(pool_root)
    for rec in batch:
        pool.add(rec)
    pool.rebuild_index()
    return {
        "kept": [r["id"] for r in batch],
        "judged": len(records),
        "rejected": sorted(set(proposals) - set(docs)),
        "failures": failures,
        "duplicates_dropped": duplicates,
        "spare": sorted({r["id"] for r in records} -
                        {r["id"] for r in batch}),
    }
