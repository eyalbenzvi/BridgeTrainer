"""DB-M-9 (multi-device re-answer sync + orphan attempts) and SEC-C-8 (clear
local caches on sign-out). No Firestore emulator here, so the client wiring is
pinned with source assertions + a node syntax check on the dashboard JS.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from bridge_trainer.app.webapp import _DASHBOARD_JS, _SHARED_JS

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available")

_FB = (Path(__file__).resolve().parent.parent / "bridge_trainer" / "web"
       / "bt-firebase.js").read_text(encoding="utf-8")


# ---- DB-M-9: re-answer bumps ts (cross-device), first attempt stamps firstTs -
def test_first_attempt_writes_firstTs():
    # both the direct write and the pending-flush write persist firstTs
    assert "firstTs: serverTimestamp()" in _FB
    assert "firstTs: { seconds: nowSec }" in _FB


def test_reanswer_bumps_ts_not_just_lastTs():
    # the merge write for a re-answer must set ts (so incremental sync on
    # another device notices) alongside lastTs/attemptCount
    seg = _FB[_FB.index("re-answer: keep the first-attempt"):
              _FB.index("async resetAll")]
    assert "attemptCount: increment(1)" in seg
    assert "ts: serverTimestamp()" in seg
    assert "lastTs: serverTimestamp()" in seg
    # legacy docs (no firstTs) must be backfilled from the existing first-
    # attempt ts on re-answer, or the bumped ts would reorder them (review fix)
    assert "!existing.firstTs && tsMillis(existing)" in seg
    assert "patch.firstTs = new Date(tsMillis(existing))" in seg


def test_dashboard_orders_by_firstTs_not_bumped_ts():
    # ordering uses firstMs (firstTs || ts), so a re-answer's bumped ts can't
    # reshuffle the streak/trend/recent lists
    assert "function firstMs(a)" in _DASHBOARD_JS
    assert "a.firstTs" in _DASHBOARD_JS
    assert "sort((a, b) => firstMs(b) - firstMs(a))" in _DASHBOARD_JS
    assert "sort((a, b) => firstMs(a) - firstMs(b))" in _DASHBOARD_JS


def test_dashboard_marks_orphan_attempts():
    # deleted-problem attempts render a non-link "removed" row using LIVE_IDS
    assert "let LIVE_IDS = null;" in _DASHBOARD_JS
    assert "LIVE_IDS = new Set(" in _DASHBOARD_JS
    assert "בעיה שהוסרה" in _DASHBOARD_JS
    assert "await window.BT.fetchIndex()" in _DASHBOARD_JS


# ---- SEC-A-6: esc() on user-owned attempt fields in the dashboard -----------
def test_dashboard_escapes_attempt_fields():
    # every miss row on the page is built by this one function, so escaping it
    # here covers both the tier-1 "3 to revisit" card and the full list
    seg = _DASHBOARD_JS[_DASHBOARD_JS.index("function missRowHtml"):
                        _DASHBOARD_JS.index("function section(")]
    assert "esc(m.chosenCall)" in seg
    assert "esc(acc.join" in seg          # accOf()-normalized
    assert "esc(OUTCOME_HE[m.outcomeClass]" in seg


# ---- SEC-C-8: sign-out clears the per-user localStorage caches --------------
def test_signout_clears_local_caches():
    seg = _FB[_FB.index("onAuthStateChanged"):_FB.index('gate("signin")')]
    assert "const prevUid = USER && USER.uid;" in seg
    assert "localStorage.removeItem(cacheKey(prevUid))" in seg
    assert "localStorage.removeItem(pendingKey(prevUid))" in seg


@needs_node
def test_dashboard_js_still_parses():
    script = _SHARED_JS + "\n" + _DASHBOARD_JS
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        os.write(fd, script.encode("utf-8"))
        os.close(fd)
        res = subprocess.run(["node", "--check", path],
                             capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
    finally:
        os.unlink(path)


# ---- orphan attempts must not move the dashboard's numbers ------------------
#
# User report: stored history went stale as problems changed or were deleted
# and the score formula was fixed. `trainer pool regrade-attempts` fixes every
# attempt whose problem still exists, but an attempt on a DELETED problem has
# nothing left to regrade against: its verdict is gone. The hero already
# excludes scoreless legacy attempts for the same reason (their fallback score
# reads harsher — measured up to 27 points on the production account); a grade
# that can never be verified again is excluded too, and counted out loud.

def test_hero_excludes_attempts_on_deleted_problems():
    seg = _DASHBOARD_JS[_DASHBOARD_JS.index("function render(attempts)"):]
    assert "first.filter(btHasStoredScore).filter(a => !btOrphan(a))" in seg
    # legacyN keeps its own meaning (no stored score); the deleted-problem
    # ones are counted separately so the disclosure can name both reasons
    assert "const legacyN = first.filter(a => !btHasStoredScore(a)).length;" \
        in seg
    assert "const goneN = first.length - scored.length - legacyN;" in seg
    assert "heroHtml(heroSet, legacyN, goneN, pendingN)" in seg


def test_orphan_predicate_is_null_safe():
    assert "function btOrphan(a) { return !!LIVE_IDS" in _DASHBOARD_JS


def test_deleted_problem_count_is_shown_not_hidden():
    hero = _DASHBOARD_JS[_DASHBOARD_JS.index("function heroHtml("):
                         _DASHBOARD_JS.index("function mixHtml(")]
    assert "goneN" in hero
    assert "שהוסרו מהמאגר" in hero
    # ... and their rows are still on the page, marked
    assert "בעיה שהוסרה" in _DASHBOARD_JS


# ---- stale grades on the dashboard (user report) -----------------------------
#
# The dashboard showed 0 for a 3S that scores 83 today. An attempt stores a
# grading SNAPSHOT; `trainer pool regrade-attempts` refreshes the stored copy
# when a verdict changes, but two cases escape it: an answer still queued in
# the client's PENDING list has never reached the server at all, and
# problemVersion (the problem's created_at) does not move when a migration
# rewrites a verdict in place, so no version comparison can spot the staleness.

def test_dashboard_shows_only_what_is_stored():
    """Owner direction: the page displays stored data, full stop. No display-time
    re-grading — a wrong score is data to repair (`trainer pool
    regrade-attempts`), not something the renderer works around. An earlier cut
    of this recomputed the low rows from their problem docs on every load, which
    both hid the real defect and made the hero number visibly jump."""
    js = _DASHBOARD_JS
    for banned in ("healLowGrades", "toVerify", "HEAL_MAX", "reScore",
                   "getProblem", "btScoreBidding", "btScoreLead"):
        assert banned not in js, banned
    init = js[js.index("async function init()"):]
    body = init[:init.index("const el = document.getElementById(\"dash\")")]
    assert body.count("render(") == 1          # one paint, of stored data
    assert "await window.BT.allAttempts()" in body


def test_the_client_cannot_rewrite_a_stored_grade():
    # the only writes bt-firebase.js makes to an attempt are the answer itself
    # and the re-answer counter; nothing rewrites a grade behind the user
    assert "reScore" not in _FB
    assert _FB.count("setDoc(") == 3          # create, pending flush, re-answer


def test_unsynced_answers_are_declared_not_presented_as_settled():
    assert "pendingCount: () => Object.keys(PENDING).length," in _FB
    assert "window.BT.pendingCount" in _DASHBOARD_JS
    hero = _DASHBOARD_JS[_DASHBOARD_JS.index("function heroHtml("):
                         _DASHBOARD_JS.index("function mixHtml(")]
    assert "pendingN" in hero
    assert "לא נשמרו לענן" in hero


def test_accepted_set_is_normalized_at_every_read():
    js = _DASHBOARD_JS
    assert "function accOf(a) {" in js
    assert "Array.isArray(s) ? s : (s ? [s] : [])" in js
    # no consumer reads the field raw any more
    assert "a.acceptedSet || []" not in js
    assert "esc(m.acceptedSet" not in js
