"""Ensemble batch assembly: verdict merging + selection policy."""
from bridge_trainer.finalize.batch import resolve_reviews, select_batch

DOC = {"dilemma": True, "options": ["P", "X"]}


def test_resolve_reviews_verdicts():
    proposals = {
        "a": {**DOC, "explanation": "original"},
        "b": {**DOC, "explanation": "flawed"},
        "c": {**DOC, "explanation": "bad"},
        "d": {"dilemma": False, "why": "routine"},
        "e": {**DOC, "explanation": "unaudited"},
    }
    reviews = {
        "a": {"verdict": "accept", "findings": []},
        "b": {"verdict": "patch", "findings": ["hcp off by one"],
              "patched_doc": {**DOC, "explanation": "fixed"}},
        "c": {"verdict": "reject", "findings": ["no dilemma"]},
    }
    docs = resolve_reviews(proposals, reviews)
    # accept keeps the proposal, patch swaps in the verifier's document
    assert docs["a"]["explanation"] == "original"
    assert docs["b"]["explanation"] == "fixed"
    # rejected (either stage) and unaudited proposals are dropped
    assert set(docs) == {"a", "b"}


def _rec(pid, margin, equivalent=(), category=None, deal=None):
    return {"id": pid, "difficulty": margin, "deal_hash": deal or pid,
            "category": category or f"cat-{pid}",
            "quality": {"equivalent_pairs": list(equivalent)}}


def test_select_batch_prefers_close_calls():
    records = [_rec("e1-1", 2.0), _rec("e2-1", 0.1), _rec("e3-1", 0.5)]
    picked = select_batch(records, keep=2)
    assert [r["id"] for r in picked] == ["e2-1", "e3-1"]


def test_select_batch_true_close_call_beats_collapse():
    records = [_rec("e1-1", 0.1, equivalent=[["P", "X"]]), _rec("e2-1", 0.1)]
    assert select_batch(records, keep=1)[0]["id"] == "e2-1"


def test_select_batch_spreads_across_matches():
    records = [_rec("e1-1", 0.1), _rec("e1-2", 0.2), _rec("e1-3", 0.3),
               _rec("e2-1", 5.0)]
    picked = select_batch(records, keep=3)
    # at most two per source match before dipping into the backlog
    assert [r["id"] for r in picked] == ["e1-1", "e1-2", "e2-1"]
    # but the backlog still fills the quota when needed
    assert len(select_batch(records, keep=4)) == 4


def test_select_batch_category_quota():
    records = [_rec("e1-1", 0.1, category="partscore"),
               _rec("e2-1", 0.2, category="partscore"),
               _rec("e3-1", 0.3, category="partscore"),
               _rec("e4-1", 5.0, category="game")]
    picked = select_batch(records, keep=3)
    # no category may exceed half the batch (rounded up)
    assert [r["id"] for r in picked] == ["e1-1", "e2-1", "e4-1"]


def test_dedupe_deals_keeps_closer_margin():
    from bridge_trainer.finalize.batch import dedupe_deals
    records = [_rec("e1-1", 1.5, deal="same"), _rec("e2-1", 0.3, deal="same"),
               _rec("e3-1", 0.9)]
    kept, dropped = dedupe_deals(records)
    assert {r["id"] for r in kept} == {"e2-1", "e3-1"}
    assert dropped == ["e1-1"]
