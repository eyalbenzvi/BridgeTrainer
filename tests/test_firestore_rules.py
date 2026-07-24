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
    "attemptCount", "ts", "lastTs",
}


def _rules() -> str:
    return _RULES_PATH.read_text(encoding="utf-8")


def _allowlist() -> set[str]:
    src = _rules()
    block = src[src.index("hasOnly(["):src.index("])", src.index("hasOnly(["))]
    return set(re.findall(r"'([A-Za-z]+)'", block))


def _code() -> str:
    # rules text with // line comments stripped (prose mentions the old API)
    return "\n".join(ln.split("//", 1)[0] for ln in _rules().splitlines())


def test_broken_size_api_is_gone():
    code = _code()
    # request.resource.size() is not a valid rules API (it silently failed to
    # evaluate); the field-count form must be used instead.
    assert "request.resource.size()" not in code
    assert "request.resource.data.size()" in code


def test_no_recursive_user_write_wildcard():
    # the old match /users/{uid}/{doc=**} let a client create arbitrary
    # subcollections; validation is now scoped to attempts.
    assert "/users/{uid}/{doc=**}" not in _rules()
    assert "match /attempts/{pid}" in _rules()


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
