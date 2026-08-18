"""Firebase Cloud Functions (2nd gen / Cloud Run): the fast analysis path.

Fires on CREATION of an analysis_requests document (the site's submit),
claims it with the same CAS the Actions worker uses, runs the analysis
pipeline and writes the report back — typically ~30-90s after the user
taps "נתח", instead of waiting for the 5-minute Actions cron. The Actions
workflow stays deployed as fallback + janitor: it heals requests stuck in
"running" (a crashed instance consumes the creation event forever) and
processes anything filed while the function was broken or undeployed.

Cost: within the Cloud Run free tier at personal volume (~180k
vCPU-seconds/month ≈ thousands of analyses); max_instances bounds the
worst case. Requires the Firebase project on the Blaze plan.

REGION must match the Firestore database location family. nam5 (the
default multi-region) pairs with us-central1; if your database lives
elsewhere (e.g. eur3 -> europe-west4, me-west1 -> me-west1), change the
constant — a mismatch fails at deploy time with a location error.
"""
from firebase_admin import firestore, initialize_app
from firebase_functions import firestore_fn, options

initialize_app()

REGION = "us-central1"

# Firestore triggers do NOT retry by default (and FirestoreOptions exposes
# no retry knob in this SDK) — a failed analysis lands as status=error via
# handle_request, never as an endless re-run.
_LIMITS = dict(
    region=REGION,
    memory=options.MemoryOption.GB_1,
    cpu=1,
    timeout_sec=540,          # analyses cap out well under this
    max_instances=2,          # cost bound; the queue tolerates waiting
    concurrency=1,            # CPU-bound work — one analysis per instance
)


@firestore_fn.on_document_created(document="analysis_requests/{req_id}",
                                  **_LIMITS)
def analyze_request(event: firestore_fn.Event) -> None:
    # heavy imports stay inside the handler so the CLI's deploy-time
    # discovery of this module needs only firebase_functions itself
    import os

    from bridge_trainer.analysis.worker import handle_request

    db = firestore.client()
    ref = db.collection("analysis_requests").document(
        event.params["req_id"])
    handle_request(
        db, ref,
        run_id=f"cf-{event.id[:12]}",
        narration_available=bool(os.environ.get("ANTHROPIC_API_KEY")),
    )
