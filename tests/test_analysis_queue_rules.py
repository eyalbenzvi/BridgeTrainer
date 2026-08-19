"""Static guards for the analysis-queue Firestore rules + client API.

Same approach as test_firestore_rules.py (no emulator in this repo): the
rule text is checked structurally, and the client/worker field contracts
are cross-checked against the rule allowlists so they cannot drift apart.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
RULES = (ROOT / "firestore.rules").read_text(encoding="utf-8")
FB = (ROOT / "bridge_trainer" / "web" / "bt-firebase.js").read_text(
    encoding="utf-8")
PAGE_SRC = (ROOT / "bridge_trainer" / "app" / "webapp.py").read_text(
    encoding="utf-8")

# `system` and `overrides` were removed from the product (the Ben engine
# defines the meanings) but stay ALLOWED in the rules so cached old clients
# don't break; the page no longer sends them.
REQ_REQUIRED = ["dealer", "vul", "my_seat", "my_hand", "auction",
                "decision_index", "scoring"]
REQ_OPTIONAL = ["system", "overrides", "narration", "candidates",
                "extra_candidates", "plans", "seed", "max_deals"]


def _block(name: str) -> str:
    i = RULES.index(name)
    return RULES[i:i + 2500]


def test_requests_create_requires_owner_uid_and_pending():
    b = _block("function validAnalysisReq()")
    assert "d.uid == request.auth.uid" in b
    assert "d.status == 'pending'" in b


def test_requests_keys_are_locked_down():
    b = _block("function validAnalysisReq()")
    assert "hasOnly(['uid', 'status', 'createdAt', 'req'])" in b
    for k in REQ_REQUIRED:
        assert f"'{k}'" in b, k
    # bounded payloads: hand length, auction length, overrides map size
    assert "r.my_hand.size() <= 20" in b
    assert "r.auction.size() <= 40" in b
    assert "r.overrides.size() <= 40" in b
    assert "r.max_deals <= 2000" in b
    for k in REQ_OPTIONAL:
        assert f"'{k}'" in b, k
    assert "r.extra_candidates.size() <= 4" in b
    assert "r.plans.size() <= 6" in b


def test_requests_client_may_not_update_status():
    b = _block("match /analysis_requests/{id}")
    assert "allow update: if false" in b
    assert "resource.data.uid == request.auth.uid" in b


def test_reports_are_worker_written_and_owner_read():
    b = _block("match /analysis_reports/{id}")
    assert "allow create, update: if false" in b
    assert "allow list: if false" in b
    assert "resource.data.uid == request.auth.uid" in b


def test_client_submits_exactly_the_rule_shape():
    m = re.search(r"async submitAnalysis[\s\S]{0,400}?setDoc\(reqRef, \{"
                  r"([\s\S]*?)\}\);", FB)
    assert m, "submitAnalysis setDoc payload not found"
    payload = m.group(1)
    for field in ("uid: USER.uid", 'status: "pending"',
                  "createdAt: serverTimestamp()", "req"):
        assert field in payload, field


def test_client_watch_filters_on_own_uid():
    m = re.search(r"watchAnalyses[\s\S]{0,300}?where\(\"uid\", \"==\", "
                  r"USER\.uid\)", FB)
    assert m, "watchAnalyses must filter uid == mine (rules reject otherwise)"


def test_page_request_fields_match_rule_allowlist():
    """The analyze page builds `req` with only rule-allowed keys."""
    m = re.search(r"const req = \{([\s\S]*?)\};", PAGE_SRC)
    assert m, "analyze page req literal not found"
    keys = set(re.findall(r"(\w+):", m.group(1)))
    allowed = set(REQ_REQUIRED) | set(REQ_OPTIONAL)
    assert keys <= allowed, keys - allowed
    assert set(REQ_REQUIRED) <= keys
