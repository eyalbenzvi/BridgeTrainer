"""Cheap pending-count gate for the analyze-requests workflow.

Runs BEFORE the heavy install (endplay/numpy compile + package): with only
firebase-admin available it counts pending analysis requests and writes
`pending=<n>` to GITHUB_OUTPUT, so the workflow can skip the expensive
steps on the (common) empty-queue tick. Deliberately does NOT import
bridge_trainer — that would pull numpy.

Usage: python scripts/analysis_queue_gate.py --key sa-key.json
"""
from __future__ import annotations

import argparse
import os
import sys


def pending_count(key_path: str | None) -> int:
    import firebase_admin
    from firebase_admin import credentials, firestore
    if not firebase_admin._apps:
        cred = (credentials.Certificate(key_path) if key_path
                else credentials.ApplicationDefault())
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    docs = (db.collection("analysis_requests")
            .where("status", "==", "pending").limit(25).stream())
    return sum(1 for _ in docs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=None)
    args = ap.parse_args()
    n = pending_count(args.key)
    print(f"pending analysis requests: {n}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"pending={n}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
