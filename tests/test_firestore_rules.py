"""Static checks for firestore.rules attempt validation (task T6).

There is no Firestore emulator in this repo (see docs/infra_fixes_plan.md), so
rule *semantics* are verified manually; CI keeps these static guards:
  * the broken request.resource.size() API never returns,
  * the attempt key allowlist stays in lock-step with the fields the web
    client actually writes (web/bt-firebase.js), so a new stored field can't be
    silently rejected by the rule, and no phantom field lingers in the rule.
"""
from __future__ import annotations

import pathlib
import re

_RULES_PATH = pathlib.Path(__file__).resolve().parent.parent / "firestore.rules"
_FB_PATH = (pathlib.Path(__file__).resolve().parent.parent / "bridge_trainer"
            / "web" / "bt-firebase.js")

# The fields the client writes, from meta()+gradeBidding()+gradeLead() and the
# record() first-attempt payload + re-answer merge. Kept here as the contract.
EXPECTED = {
    "problemId", "problemVersion", "scoringForm", "kind", "type",
    "difficultyLevel", "answer", "chosenCall", "correct", "outcomeClass",
    "gradedCost", "score", "acceptedSet", "trainingMode", "rankingMetric",
    "chosenRank", "recommendedLead", "primaryValue", "isFirstAttempt",
    "attemptCount", "ts", "firstTs", "lastTs",
}


def _rules() -> str:
    return _RULES_PATH.read_text(encoding="utf-8")


def _allowlist() -> set[str]:
    src = _rules()
    fn = src[src.index("function attemptKeys()"):]
    block = fn[fn.index("["):fn.index("]")]
    return set(re.findall(r"'([A-Za-z]+)'", block))


def _code() -> str:
    # rules text with // line comments stripped (prose mentions the old API)
    return "\n".join(ln.split("//", 1)[0] for ln in _rules().splitlines())


def test_broken_size_api_is_gone():
    code = _code()
    # request.resource.size() is not a valid rules API (it silently failed to
    # evaluate); the field-count form must be used instead. attemptBounds(d) is
    # called with request.resource.data and applies the count cap via d.size().
    assert "request.resource.size()" not in code
    assert "let d = request.resource.data" in code
    assert "d.size() < 25" in code


def test_no_recursive_user_write_wildcard():
    # the old match /users/{uid}/{doc=**} let a client create arbitrary
    # subcollections; validation is now scoped to attempts.
    assert "/users/{uid}/{doc=**}" not in _rules()
    assert "match /attempts/{pid}" in _rules()


def test_top_level_user_doc_is_not_writable():
    """SEC-A-6/DB-M-9: the 'profile' doc is never written by any client, so the
    only writable location is the attempts subtree. The /users/{uid} match must
    grant read only — no `allow write` on the user doc itself."""
    code = _code()
    users = code[code.index("match /users/{uid}"):code.index("match /attempts")]
    assert "allow read: if owner(uid)" in users
    assert "allow write" not in users        # no profile write rule


def test_allowlist_matches_the_contract():
    assert _allowlist() == EXPECTED


def test_allowlist_fields_are_real_client_fields():
    """No phantom field in the rule: every allowlisted key appears as a written
    field in bt-firebase.js (drift guard against the rule and client diverging)."""
    fb = _FB_PATH.read_text(encoding="utf-8")
    # a field may be written as `k: v` or as an ES6 shorthand (`k,`/`k }`), so
    # check plain word membership — a phantom field wouldn't appear at all.
    missing = {f for f in _allowlist()
               if not re.search(r"\b" + re.escape(f) + r"\b", fb)}
    assert not missing, f"rule allowlists fields the client never writes: {missing}"


def test_critical_fields_present():
    for f in ("answer", "score", "correct", "attemptCount", "problemId", "ts"):
        assert f in _allowlist()


def test_create_is_strict_but_update_is_legacy_tolerant():
    """A first-attempt create requires the full grading; a re-answer update
    must NOT require score (legacy docs predate it) or it would reject the
    merge that only bumps attemptCount/lastTs."""
    code = _code()
    assert "allow create: if owner(uid) && validCreate();" in code
    assert "allow update: if owner(uid) && validUpdate();" in code
    # create demands score/answer/correct outright
    create = code[code.index("function validCreate()"):code.index("function validUpdate()")]
    assert "d.score is number" in create and "d.answer is string" in create
    # update only enforces the shared, presence-conditional bounds
    update = code[code.index("function validUpdate()"):code.index("match /users")]
    assert "attemptBounds(request.resource.data)" in update
    # the shared bounds guard score by presence, not unconditionally
    bounds = code[code.index("function attemptBounds"):code.index("function validCreate")]
    assert "!('score' in d) || d.score is number" in bounds


# ---- the rules must actually BE deployed ------------------------------------
#
# Every test above checks the FILE. The file was right and production was two
# commits behind: nothing ever deployed it. `firstTs` shipped in the client
# (DB-M-9) but not in the live allowlist, and since attemptBounds requires
# keys().hasOnly(attemptKeys()), every first-attempt create was rejected with
# permission-denied and sat in the browser's PENDING queue for ever — 66 stored
# attempts, not one with a firstTs, nothing created by a client since. The user
# saw answers (and their pre-fix grades) that Firestore had never received.

def _workflow(name: str) -> str:
    return (pathlib.Path(__file__).resolve().parent.parent / ".github"
            / "workflows" / name).read_text(encoding="utf-8")


def test_rules_are_deployed_by_the_app_deploy():
    wf = _workflow("publish.yml")
    assert "scripts/deploy_rules.py" in wf
    assert "FIREBASE_SERVICE_ACCOUNT" in wf
    # a missing secret must fail the job, not skip the deploy silently
    assert "rules not deployed" in wf
    assert "branches: [main]" in wf


def test_deploy_is_a_noop_when_the_live_rules_already_match(monkeypatch):
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent
                           / "scripts"))
    import deploy_rules

    calls = []
    monkeypatch.setattr(deploy_rules, "live_source",
                        lambda t, p: ("projects/x/rulesets/same", "RULES"))
    monkeypatch.setattr(deploy_rules, "_call",
                        lambda *a, **k: calls.append(a) or {})
    out = deploy_rules.deploy("RULES", "tok", "x")
    assert out["changed"] is False and calls == []


def test_deploy_publishes_and_verifies_the_release(monkeypatch):
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent
                           / "scripts"))
    import deploy_rules

    state = {"live": "OLD"}
    monkeypatch.setattr(deploy_rules, "live_source",
                        lambda t, p: (f"projects/x/rulesets/{state['live']}",
                                      state["live"]))

    def fake_call(method, url, token, body=None):
        if method == "POST":
            return {"name": "projects/x/rulesets/new"}
        if method == "PATCH":
            state["live"] = "NEW"        # the release takes effect
            return {}
        raise AssertionError(method)

    monkeypatch.setattr(deploy_rules, "_call", fake_call)
    out = deploy_rules.deploy("NEW", "tok", "x")
    assert out["changed"] is True
    assert out["ruleset"].endswith("NEW") and out["previous"].endswith("OLD")

    # ... and a release that does NOT take effect is an error, never a success
    state["live"] = "OLD"
    monkeypatch.setattr(deploy_rules, "_call",
                        lambda *a, **k: {"name": "projects/x/rulesets/new"})
    try:
        deploy_rules.deploy("NEW", "tok", "x")
    except SystemExit as e:
        assert "NOT deployed" in str(e)
    else:
        raise AssertionError("a failed release must raise")


def test_stored_history_is_repaired_on_a_schedule():
    """The dashboard may not fix a grade at display time, so the repair has to
    run on its own: a client write that lands carries whatever grade it computed
    when it was answered."""
    wf = _workflow("data-hygiene.yml")
    assert "schedule:" in wf and "cron:" in wf
    assert "pool regrade-attempts" in wf
    # the audit reports; it must not delete problems unattended
    assert "audit_pool.py" in wf
    audit = wf[wf.index("- name: Audit published problems"):
               wf.index("- name: Job summary")]
    assert "--remove" not in audit
