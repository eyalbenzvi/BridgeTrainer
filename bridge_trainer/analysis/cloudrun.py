"""Cloud Run entry point for the Ben-powered analysis engine.

Replaces the old Cloud Functions gen2 function (which could not carry the
Ben checkout + TensorFlow). An Eventarc trigger delivers a CloudEvent HTTP
POST for every created analysis_requests document; only the document id is
needed, and it arrives in the `ce-subject` header
("documents/analysis_requests/{id}") — no protobuf parsing. The worker
then re-reads the document with the Admin SDK and runs the shared
claim/process path (worker.handle_request), so the CAS keeps this service,
the Actions fallback and Eventarc's at-least-once delivery from ever
double-processing a request.

Responses are always 200 once the request doc reflects the outcome
(done/error) — a non-200 would only trigger redelivery of work that is
already recorded.
"""
from __future__ import annotations

import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_DB = None


def _db():
    global _DB
    if _DB is None:
        import firebase_admin
        from firebase_admin import firestore
        if not firebase_admin._apps:
            firebase_admin.initialize_app()   # ADC on Cloud Run
        _DB = firestore.client()
    return _DB


def _request_id(subject: str | None) -> str | None:
    # "documents/analysis_requests/{id}"
    if not subject:
        return None
    parts = subject.strip("/").split("/")
    if len(parts) >= 2 and parts[-2] == "analysis_requests":
        return parts[-1]
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "BridgeAnalysis/1.0"

    def _reply(self, code: int, text: str = "") -> None:
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:              # health checks
        self._reply(200, "ok")

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length:
            self.rfile.read(length)        # drain; the id is in the header
        req_id = _request_id(self.headers.get("ce-subject"))
        if not req_id:
            self._reply(200, "ignored: no analysis_requests subject")
            return
        try:
            from ..analysis.worker import handle_request
            db = _db()
            ref = db.collection("analysis_requests").document(req_id)
            outcome = handle_request(
                db, ref, run_id=f"run-{os.environ.get('K_REVISION', 'x')}",
                narration_available=bool(os.environ.get("ANTHROPIC_API_KEY")))
            self._reply(200, outcome)
        except Exception:
            # outcome not recorded on the doc — let Eventarc redeliver once
            # the stale-running janitor or a retry can pick it up
            traceback.print_exc()
            self._reply(500, "error")

    def log_message(self, fmt, *args):     # ids/timings only (public repo
        print(f"[cloudrun] {fmt % args}")  # discipline kept out of habit)


def main() -> None:
    port = int(os.environ.get("PORT", 8080))
    print(f"[cloudrun] analysis service listening on :{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
