"""Regenerate every problem's explanations from GIB, in place.

Explanations depend only on the auction — GIB's meaning per call, rendered
by ``terse_meaning`` — never on the sampled evidence, so they can be rebuilt
at any time without touching verdicts or re-running the engine. Use this
after improving the meaning parser/renderer (or when GIB fetches failed at
generation time and left calls without a note): it re-FETCHES the meaning of
every call and re-renders the stored texts.

What is rebuilt per record kind:
  bidding — ``explanations.stem`` wholesale (cards + texts), and each
      option's meaning head; the evidence tail of the option text
      ("Leads to ...") is preserved verbatim since it comes from the
      rollout, not from GIB.
  lead — ``explanations.auction`` wholesale (the full-auction call
      meanings). ``explanations.cards`` is trick-derived and untouched.

Usage:
    python3 scripts/reexplain_pool.py <pool_dir>            # local pool
    python3 scripts/reexplain_pool.py --firestore [--key K] # the live DB

Idempotent and resumable: each record is written as soon as it is rebuilt;
re-running redoes the (cached, throttled) GIB fetches but loses nothing.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bridge_trainer.engine.conventions import SEATS, seat_of
from bridge_trainer.engine.explain import _call_name, terse_meaning
from bridge_trainer.engine.gib_explain import card_for_auction

EVIDENCE_SEP = " Leads to "


def _same(a, b) -> bool:
    """Equality up to JSON round-trip (stored docs hold lists where fresh
    cards hold tuples)."""
    return json.loads(json.dumps(a)) == json.loads(json.dumps(b))


def rebuild_bidding(rec: dict) -> bool:
    ex = rec.get("explanations") or {}
    auction = rec.get("auction") or []
    dealer_i = SEATS.index(rec["dealer"])
    changed = False

    stem = []
    for j, tok in enumerate(auction):
        card = card_for_auction(auction[: j + 1])
        meaning = terse_meaning(card, call=tok)
        seat = SEATS[seat_of(dealer_i, j)]
        stem.append({"idx": j, "seat": seat, "call": tok, "card": card,
                     "text": (f"{_call_name(tok)} ({seat}): {meaning}"
                              if meaning else "")})
    if not _same(stem, ex.get("stem") or []):
        ex["stem"] = stem
        changed = True

    for o in ex.get("options") or []:
        card = card_for_auction(auction + [o["bid"]])
        meaning = terse_meaning(card, call=o["bid"])
        text = o.get("text") or ""
        if EVIDENCE_SEP in text:
            head = (f"{_call_name(o['bid'])} — {meaning}." if meaning
                    else f"{_call_name(o['bid'])}.")
            new_text = head + EVIDENCE_SEP + text.split(EVIDENCE_SEP, 1)[1]
        else:
            new_text = text
        if new_text != text or not _same(card, o.get("card")):
            o["card"], o["text"] = card, new_text
            changed = True
    rec["explanations"] = ex
    return changed


def rebuild_lead(rec: dict) -> bool:
    from bridge_trainer.engine.lead_explain import auction_meanings
    ex = rec.get("explanations") or {}
    auction = rec.get("auction") or rec.get("engine_auction_complete") or []
    if not auction or "dealer" not in rec:
        return False
    meanings = auction_meanings(SEATS.index(rec["dealer"]), auction)
    if not _same(meanings, ex.get("auction") or []):
        ex["auction"] = meanings
        rec["explanations"] = ex
        return True
    return False


def rebuild(rec: dict) -> bool:
    if rec.get("kind") == "lead":
        return rebuild_lead(rec)
    return rebuild_bidding(rec)


def run_local(pool_dir: str) -> None:
    from bridge_trainer.pool.store import ProblemPool
    pool = ProblemPool(pool_dir)
    n = 0
    for path in sorted(pool.problems_dir.glob("*.json")):
        rec = json.loads(path.read_text())
        if rebuild(rec):
            path.write_text(json.dumps(rec, separators=(",", ":")))
            n += 1
            print(f"reexplained {rec['id']}", file=sys.stderr, flush=True)
    print(f"{n} record(s) updated in {pool_dir}")


def run_firestore(key_path: str | None) -> None:
    from bridge_trainer.pool.firestore_store import (
        FirestorePool, _firestore_safe, _retry_transient)
    pool = FirestorePool(key_path)
    recs = pool.stream_records(
        fields=["kind", "dealer", "auction", "engine_auction_complete",
                "explanations"])
    n = 0
    for rec in recs:
        if rebuild(rec):
            _retry_transient(lambda r=rec: pool._col.document(r["id"]).set(
                {"explanations": _firestore_safe(r["explanations"])},
                merge=True))
            n += 1
            print(f"reexplained {rec['id']}", file=sys.stderr, flush=True)
    print(f"{n} record(s) updated in Firestore")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("pool_dir", nargs="?",
                    help="local pool directory (omit with --firestore)")
    ap.add_argument("--firestore", action="store_true",
                    help="rewrite the live Firestore pool instead")
    ap.add_argument("--key", default=None,
                    help="service-account JSON (else GOOGLE_APPLICATION_"
                         "CREDENTIALS)")
    args = ap.parse_args()
    if args.firestore:
        run_firestore(args.key)
    elif args.pool_dir:
        run_local(args.pool_dir)
    else:
        ap.error("give a pool_dir or --firestore")
