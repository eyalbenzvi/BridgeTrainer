"""Deploy firestore.rules to the live project, idempotently.

Why this exists: nothing deployed the file. `firestore.rules` lived in the repo
and was published to Firestore by hand, once — so the moment the client started
writing a new attempt field (`firstTs`, DB-M-9), the deployed allowlist stopped
matching what the client sends. `attemptBounds` requires
`keys().hasOnly(attemptKeys())`, so EVERY first-attempt create was rejected with
permission-denied, queued in the browser's PENDING list, and retried for ever.
The measurable symptom: 66 stored attempts, not one with a firstTs field, and
nothing created by a client since the field shipped — while the user's dashboard
kept showing answers (and their pre-fix grades) that Firestore had never seen.

Rules are code; they ship with the code. This is the deploy step, run from
publish.yml on every push to main.

Auth: --key FILE, or $GOOGLE_APPLICATION_CREDENTIALS, or the JSON content in
$FIREBASE_SERVICE_ACCOUNT (what CI holds). The service account needs
firebaserules.rulesets.create + firebaserules.releases.update; the Firebase
Admin SDK service agent has them.

Usage:
    python3 scripts/deploy_rules.py [--key sa.json] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

API = "https://firebaserules.googleapis.com/v1"
RULES_FILE = "firestore.rules"
RELEASE = "cloud.firestore"


def _credentials(key_path: str | None):
    """(token, project_id) from an explicit key, the ADC env var, or the raw
    JSON in $FIREBASE_SERVICE_ACCOUNT."""
    from google.oauth2 import service_account          # provided by firebase-admin
    import google.auth.transport.requests

    tmp = None
    if not key_path:
        key_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not key_path and os.environ.get("FIREBASE_SERVICE_ACCOUNT"):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        tmp.write(os.environ["FIREBASE_SERVICE_ACCOUNT"])
        tmp.close()
        key_path = tmp.name
    if not key_path:
        raise SystemExit("no credentials: pass --key, or set "
                         "GOOGLE_APPLICATION_CREDENTIALS / "
                         "FIREBASE_SERVICE_ACCOUNT")
    try:
        creds = service_account.Credentials.from_service_account_file(
            key_path, scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token, creds.project_id
    finally:
        if tmp:
            os.unlink(tmp.name)


def _call(method: str, url: str, token: str, body: dict | None = None):
    req = urllib.request.Request(
        url, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise SystemExit(f"{method} {url} -> HTTP {e.code}: {detail[:500]}")


def live_source(token: str, project: str) -> tuple[str, str]:
    """(ruleset name, source text) currently serving reads and writes."""
    rel = _call("GET", f"{API}/projects/{project}/releases/{RELEASE}", token)
    name = rel["rulesetName"]
    rs = _call("GET", f"{API}/{name}", token)
    return name, rs["source"]["files"][0]["content"]


def _same(a: str, b: str) -> bool:
    """Rules equality for the idempotency check, ignoring trailing newlines.

    Observed in production: the same file deployed from two places came back
    once with and once without its final newline, so a byte comparison called
    every run a change and published a fresh (identical) ruleset each time.
    Trailing whitespace cannot alter what the rules DO."""
    return a.rstrip() == b.rstrip()


def deploy(local: str, token: str, project: str, dry_run: bool = False) -> dict:
    """Publish *local* unless it is already live. Returns a summary dict."""
    prev_name, prev_src = live_source(token, project)
    if _same(prev_src, local):
        return {"changed": False, "ruleset": prev_name, "previous": prev_name}
    if dry_run:
        return {"changed": True, "ruleset": None, "previous": prev_name}
    rs = _call("POST", f"{API}/projects/{project}/rulesets", token,
               {"source": {"files": [{"name": RULES_FILE, "content": local}]}})
    _call("PATCH", f"{API}/projects/{project}/releases/{RELEASE}", token,
          {"release": {"name": f"projects/{project}/releases/{RELEASE}",
                       "rulesetName": rs["name"]}})
    now_name, now_src = live_source(token, project)
    if not _same(now_src, local):
        raise SystemExit("release did not take effect — rules NOT deployed")
    return {"changed": True, "ruleset": now_name, "previous": prev_name}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--key", default=None,
                    help="service-account JSON (or set "
                         "GOOGLE_APPLICATION_CREDENTIALS / "
                         "FIREBASE_SERVICE_ACCOUNT)")
    ap.add_argument("--rules", default=None,
                    help=f"rules file (default: {RULES_FILE} at the repo root)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report whether a deploy is needed, without deploying")
    args = ap.parse_args(argv)

    path = Path(args.rules or (Path(__file__).parent.parent / RULES_FILE))
    local = path.read_text(encoding="utf-8")
    token, project = _credentials(args.key)
    out = deploy(local, token, project, dry_run=args.dry_run)
    if not out["changed"]:
        print(f"firestore.rules already live ({out['ruleset'].split('/')[-1]})")
    elif args.dry_run:
        print(f"firestore.rules DIFFERS from the live ruleset "
              f"({out['previous'].split('/')[-1]}) — a deploy is needed")
    else:
        print(f"deployed firestore.rules: "
              f"{out['previous'].split('/')[-1]} -> "
              f"{out['ruleset'].split('/')[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
