"""The practice log (history.html) — docs/history_feature_plan.md.

Two kinds of assertion, matching the convention of test_dashboard_redesign.py:

* behavioural — the ordering, day bucketing, filtering, paging and row markers
  run under node against the cases that motivated them (a replay-only session,
  a tie in the sort key, local midnight vs UTC, a day the paging cut lands in,
  a legacy attempt with no measured cost);
* structural — the page is emitted and wired like every other page, the copy
  that carries the feature's honesty is present, and the decisions the reviews
  bought (no day mean, no persisted miss filter, no index read before first
  paint, no gloss target inside a row link) cannot be silently undone.

The harness comes from test_dashboard_redesign (the repo's cross-module import
pattern) rather than a third copy of the same node runner.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile

import pytest

from bridge_trainer.app.webapp import (_CSS, _DASHBOARD_JS, _HISTORY_CSS,
                                       _HISTORY_JS, _LEAD_JS, _SCORE_JS,
                                       _SHARED_JS, _dashboard_html,
                                       _history_html, _index_html, _lead_html,
                                       _problem_html)
from test_dashboard_redesign import needs_node, run_js as _run_js

CUT = "// The authoritative sync lands after first paint"


def run_js(exprs: list[str]) -> list:
    return _run_js(exprs, block=_HISTORY_JS, cut_at=CUT)


DAY = 24 * 60 * 60 * 1000


def att(pid: str, *, first_ms: int | None = None, ts_ms: int | None = None,
        last_ms: int | None = None, score: int | None = 100,
        kind: str = "bidding", **extra) -> str:
    """One stored attempt, as the client caches it (seconds-keyed stamps)."""
    rec: dict = {"problemId": pid, "kind": kind, "isFirstAttempt": True,
                 "attemptCount": 1, "chosenCall": "3S", "acceptedSet": ["3S"],
                 "outcomeClass": "winner", "correct": True, "gradedCost": 0,
                 # a REAL taxonomy key, or badge()/rowLabel()'s label path is
                 # never exercised and a raw snake_case id could ship unnoticed
                 "type": "compete_or_sell", "difficultyLevel": 3}
    if score is not None:
        rec["score"] = score
    if first_ms is not None:
        rec["firstTs"] = {"seconds": first_ms // 1000}
    if ts_ms is not None:
        rec["ts"] = {"seconds": ts_ms // 1000}
    if last_ms is not None:
        rec["lastTs"] = {"seconds": last_ms // 1000}
    rec.update(extra)
    return json.dumps(rec, ensure_ascii=False)


# ---- ordering ---------------------------------------------------------------

@needs_node
def test_order_is_by_last_activity_so_a_replay_is_not_invisible():
    """The finding that reshaped the feature: one doc per problem means a
    session spent re-answering old problems bumps no firstTs at all. Ordered by
    firstMs that whole workout renders zero rows; ordered by last activity the
    replayed problem surfaces where the user did the work."""
    old_replay = att("A", first_ms=1000 * DAY, ts_ms=1900 * DAY,
                     last_ms=1900 * DAY, attemptCount=2)
    newer_first = att("B", first_ms=1500 * DAY, ts_ms=1500 * DAY)
    got = run_js([f"sortRows([{old_replay}, {newer_first}]).map(a => a.problemId)",
                  f"[...[{old_replay}, {newer_first}]]"
                  f".sort((x, y) => firstMs(y) - firstMs(x)).map(a => a.problemId)"])
    assert got[0] == ["A", "B"], "the replayed problem must come first"
    assert got[1] == ["B", "A"], "a firstMs order would have buried it"


@needs_node
def test_order_is_deterministic_when_the_activity_key_ties():
    """Object.values(ATTEMPTS) is in map-insertion order, which changes across a
    full reconcile, and a queued row's stamp is second-granular — so without a
    tiebreak two rows sharing a key swap places between renders and paging can
    show one twice or skip it."""
    a, b, c = (att(x, first_ms=100 * DAY, ts_ms=100 * DAY) for x in "abc")
    got = run_js([f"sortRows([{a}, {b}, {c}]).map(a => a.problemId)",
                  f"sortRows([{c}, {a}, {b}]).map(a => a.problemId)"])
    assert got[0] == got[1]


# ---- day bucketing ---------------------------------------------------------

@needs_node
def test_days_bucket_on_the_LOCAL_day_not_utc():
    """toISOString().slice(0,10) would put everything answered between 00:00
    and 03:00 Israel time on the previous day."""
    got = run_js(["dayKey(new Date(2026, 6, 30, 0, 30).getTime())",
                  "dayKey(new Date(2026, 6, 29, 23, 30).getTime())",
                  "hhmm(new Date(2026, 6, 30, 9, 4).getTime())"])
    assert got[0] == 20260730
    assert got[1] == 20260729
    assert got[2] == "09:04"


def _code(src: str) -> str:
    """The script with its comments removed: the prose explains what is banned,
    so a naive substring check would fail on the explanation itself."""
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("//"))


def test_no_utc_or_locale_formatting_reaches_the_page():
    # toLocaleTimeString() honours the DEVICE locale, so an en-US phone would
    # print "2:20 PM" — English in a Hebrew UI, in a string the localisation
    # test cannot see because it only scans static markup.
    code = _code(_HISTORY_JS)
    for banned in ("toISOString", "toLocaleTimeString", "toLocaleDateString",
                   "86400000"):
        assert banned not in code, banned
    # local getters instead
    assert "getFullYear()" in code and "getDate()" in code


@needs_node
def test_today_and_yesterday_are_day_key_comparisons():
    """Israel observes DST, so a day is sometimes 23 or 25 hours long and
    millisecond arithmetic lands in the wrong one."""
    got = run_js(["dayLabel(dayKey(Date.now()), Date.now())",
                  "dayLabel(daysAgoKey(1), Date.now() - 86400000)",
                  "dayLabel(0, 0)"])
    assert got[0] == "היום"
    assert got[1] == "אתמול"
    assert got[2] == "ללא תאריך"


@needs_node
def test_undated_rows_group_last_and_are_never_dated_today():
    dated = att("A", first_ms=100 * DAY, ts_ms=100 * DAY)
    undated = json.dumps({"problemId": "B", "score": 90, "kind": "bidding",
                          "chosenCall": "4H", "attemptCount": 1},
                         ensure_ascii=False)
    got = run_js([f"groupByDay(sortRows([{undated}, {dated}]))"
                  f".map(g => [g.key, g.rows.length])"])
    assert got[0][-1][0] == 0, "the undated group comes last"
    assert [g[0] for g in got[0]].count(0) == 1


# ---- the day heading -------------------------------------------------------

@needs_node
def test_day_heading_states_facts_and_never_a_mean():
    """A handful of problems mixes three scoring scales (bidding, lead MP, lead
    IMP) and possibly two calibrations, and the app refuses to print even an
    interval below 12 decisions — so a daily mean would be the least defensible
    number in the app. Count, misses and the time span are all facts."""
    t = 100 * DAY
    rows = ", ".join([
        att("a", first_ms=t + 3600000, ts_ms=t + 3600000, score=92),
        att("b", first_ms=t + 7200000, ts_ms=t + 7200000, score=61),
        att("c", first_ms=t + 9000000, ts_ms=t + 9000000, score=40),
    ])
    got = run_js([f"dayHtml(groupByDay(sortRows([{rows}]))[0])"])[0]
    head = got[:got.index("</h2>")]              # the heading, not its rows
    assert "3 בעיות" in head
    assert "2 לשיפור" in head                    # 61 and 40 are below 85
    assert re.search(r"\d\d:\d\d–\d\d:\d\d", head), head
    assert "ציון" not in head, "a day heading must not print a mean"
    # and the section that builds it computes no mean at all
    seg = _HISTORY_JS[_HISTORY_JS.index("function dayHtml("):
                      _HISTORY_JS.index("function firstAttempts(")]
    assert "mean(" not in seg and "meanCI" not in seg


@needs_node
def test_day_heading_counts_use_hebrew_number_agreement():
    t = 100 * DAY
    one = att("a", first_ms=t + 3600000, ts_ms=t + 3600000, score=92)
    got = run_js([f"dayHtml(groupByDay(sortRows([{one}]))[0])"])[0]
    assert "בעיה אחת" in got and "1 בעיות" not in got


def test_counts_go_through_the_agreement_helpers():
    """Same guard the dashboard carries: any count printed next to בעיות /
    החלטות must go through nProblems/nDecisions, or a one-problem day reads
    "1 בעיות" -- broken Hebrew. Forward-looking: the log builds its strings by
    concatenation today, so both spellings are banned."""
    # a fixed constant that can never be 1 is the one legitimate exception (the
    # dashboard's guard allows MIN_N the same way)
    FIXED = {"MIN_N", "SESSION_SIZE", "CHUNK"}
    for pat in (r"\$\{([^}]+)\} (?:בעיות|החלטות)",
                r'\+ ([A-Za-z_$][\w$]*) \+\s*\n?\s*\' (?:בעיות|החלטות)',
                r'(\d+) (?:בעיות|החלטות)'):
        for m in re.finditer(pat, _HISTORY_JS):
            assert m.group(1).strip() in FIXED, m.group(0)
    for m in re.finditer(r'\+ " (?:בעיות|החלטות)"', _HISTORY_JS):
        raise AssertionError(m.group(0))
    # ...and the helpers really are used
    assert "nProblems(" in _HISTORY_JS and "nDecisions(" in _HISTORY_JS


# ---- filters ---------------------------------------------------------------

@needs_node
def test_filters_are_the_review_line_and_the_scenario():
    t = 100 * DAY
    rows = ", ".join([
        att("a", first_ms=t, ts_ms=t, score=92),
        att("b", first_ms=t, ts_ms=t, score=84),                  # below 85
        att("c", first_ms=t, ts_ms=t, score=90, kind="lead"),
        # a record with no `kind` at all predates the lead trainer
        json.dumps({"problemId": "d", "score": 70, "chosenCall": "P",
                    "attemptCount": 1, "isFirstAttempt": True},
                   ensure_ascii=False),   # no `kind` at all
    ])
    got = run_js([
        f"(FILTER.kind = 'all', FILTER.miss = true, filterRows([{rows}]))"
        f".map(a => a.problemId)",
        f"(FILTER.kind = 'lead', FILTER.miss = false, filterRows([{rows}]))"
        f".map(a => a.problemId)",
        f"(FILTER.kind = 'bidding', FILTER.miss = false, filterRows([{rows}]))"
        f".map(a => a.problemId)",
    ])
    assert got[0] == ["b", "d"], "exactly the rows below REVIEW_MIN"
    assert got[1] == ["c"]
    assert got[2] == ["a", "b", "d"], "a kind-less legacy attempt is bidding"


def test_only_the_scenario_filter_persists():
    """A log that silently opens filtered is a log lying about being a log."""
    assert 'KIND_KEY = "bt_hist_kind"' in _HISTORY_JS
    assert _HISTORY_JS.count("localStorage.setItem") == 1
    seg = _HISTORY_JS[_HISTORY_JS.index("function setFilter("):
                      _HISTORY_JS.index("function markRemoved(")]
    assert 'if ("kind" in patch)' in seg
    assert "localStorage.setItem(KIND_KEY" in seg
    assert "miss" not in seg.split("localStorage.setItem")[1][:200]
    # a narrowed view says so, with a one-tap escape
    assert 'id="clearf"' in _HISTORY_JS and "הצג את הכל" in _HISTORY_JS


def test_a_new_selection_starts_at_the_first_chunk():
    seg = _HISTORY_JS[_HISTORY_JS.index("function setFilter("):
                      _HISTORY_JS.index("function markRemoved(")]
    assert "LIMIT = CHUNK" in seg
    # ...but a re-render (e.g. the background sync) must NOT reset it
    render = _HISTORY_JS[_HISTORY_JS.index("function render(list)"):
                         _HISTORY_JS.index("function moreHtml(")]
    assert "LIMIT =" not in render


@needs_node
def test_first_attempts_only_like_the_dashboard():
    keep = att("a", first_ms=DAY, ts_ms=DAY)
    drop = att("b", first_ms=DAY, ts_ms=DAY, isFirstAttempt=False)
    got = run_js([f"firstAttempts([{keep}, {drop}]).map(a => a.problemId)"])
    assert got[0] == ["a"]


# ---- paging ----------------------------------------------------------------

@needs_node
def test_paging_extends_to_a_day_boundary():
    """A fixed row cut would leave a heading claiming 60 problems above 40
    visible rows."""
    days = []
    for d in range(3):
        base = (200 - d) * DAY
        for i in range(60):
            days.append(att(f"p{d}_{i}", first_ms=base + i * 60000,
                            ts_ms=base + i * 60000))
    rows = ", ".join(days)
    got = run_js([f"visibleGroups(groupByDay(sortRows([{rows}])), CHUNK)"
                  f".map(g => g.rows.length)",
                  "CHUNK"])
    assert got[1] == 100
    assert got[0] == [60, 60], "whole days only, never a partial one"


@needs_node
def test_the_more_button_names_the_remainder_and_yields_to_a_cta():
    got = run_js(["moreHtml(214)", "moreHtml(0)"])
    assert "נותרו 214" in got[0] and "הצג עוד 100" in got[0]
    assert got[0].startswith("<button type=\"button\"")   # not an <a href="#">
    assert "index.html" in got[1] and "בעיות חדשות" in got[1]


def test_more_appends_and_moves_focus():
    seg = _HISTORY_JS[_HISTORY_JS.index("function showMore()"):
                      _HISTORY_JS.index("function setFilter(")]
    assert 'insertAdjacentHTML("beforeend"' in seg   # scroll position survives
    assert "head.focus()" in seg                     # keyboard/SR user lands there
    assert "markRemoved()" in seg


# ---- the row ---------------------------------------------------------------

@needs_node
def test_a_reconstructed_grade_is_marked_and_a_fallback_has_no_number():
    """btScoreOfAttempt hands back exactly ERROR_MIN for a recorded mistake with
    no measured cost. Inside an aggregate that is invisible; in a log a column
    of 40s reads as a measurement and is not one."""
    t = 100 * DAY
    measured = att("a", first_ms=t, ts_ms=t, score=92)
    legacy = att("b", first_ms=t, ts_ms=t, score=None, correct=False,
                 outcomeClass="suboptimal", gradedCost=1.4)
    nocost = att("c", first_ms=t, ts_ms=t, score=None, correct=False,
                 outcomeClass="suboptimal", gradedCost=0)
    got = run_js([f"chipHtml({measured})", f"chipHtml({legacy})",
                  f"chipHtml({nocost})", f"btScoreOfAttempt({nocost})"])
    assert ">92<" in got[0] and "~" not in got[0]
    assert "~" in got[1], "a reconstructed score must not look measured"
    assert got[3] == 40 and "ללא ציון" in got[2] and "40" not in got[2]


@needs_node
def test_a_replay_is_counted_and_dated_only_when_it_needs_to_be():
    t = 200 * DAY
    once = att("a", first_ms=t, ts_ms=t)
    # answered 3 days ago, re-answered today: the row sits under today while its
    # grade is still the first attempt's, so it says when it was first solved
    twice = att("b", first_ms=t - 3 * DAY, ts_ms=t, last_ms=t, attemptCount=3)
    # a replay inside the same day needs no date
    same = att("c", first_ms=t + 60000, ts_ms=t + 120000, last_ms=t + 120000,
               attemptCount=2)
    got = run_js([f"logRowHtml({once}, dayKey({t}))",
                  f"logRowHtml({twice}, dayKey({t}))",
                  f"logRowHtml({same}, dayKey({t}))"])
    assert "חזרה" not in got[0]
    assert "חזרה" in got[1] and "3" in got[1] and "נפתרה לראשונה" in got[1]
    assert "חזרה" in got[2] and "נפתרה לראשונה" not in got[2]


@needs_node
def test_a_removed_problem_is_a_row_but_not_a_link():
    t = 100 * DAY
    a = att("gone", first_ms=t, ts_ms=t)
    got = run_js([f"(LIVE_IDS = new Set(['other']), logRowHtml({a}, dayKey({t})))"])
    assert got[0].startswith("<div"), got[0]
    assert "בעיה שהוסרה" in got[0] and "href=" not in got[0]


@needs_node
def test_row_text_from_the_document_is_escaped():
    """SEC-A-6: the fields below are user-owned — a doctored client write must
    not become markup in a list that renders hundreds of them."""
    t = 100 * DAY
    evil = att("x<y", first_ms=t, ts_ms=t, score=50,
               chosenCall='<img src=x onerror="alert(1)">',
               acceptedSet=['<b>4H</b>'], correct=False,
               outcomeClass="suboptimal", gradedCost=1.0)
    got = run_js([f"logRowHtml({evil}, dayKey({t}))"])[0]
    # nothing user-owned survives as markup: no raw tag, no attribute break-out
    assert "<img" not in got
    assert 'onerror="' not in got
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in got
    assert "&lt;b&gt;4H&lt;/b&gt;" in got
    # ...including inside the row's data attribute, and in the href -- which is
    # URL-encoded, not HTML-escaped. The href here comes from the harness stub,
    # so the SHIPPED routeFor is pinned separately below.
    assert 'data-pid="x&lt;y"' in got
    assert "id=x%3Cy" in got and "id=x<y" not in got


def test_the_shipped_route_builder_url_encodes_the_id():
    """esc() is the wrong tool for a URL, and the log puts a link on EVERY row
    rather than the miss list's ≤30."""
    seg = _SHARED_JS[_SHARED_JS.index("function routeFor("):]
    seg = seg[:seg.index("\n}")]
    assert "encodeURIComponent(id)" in seg
    assert "esc(m.problemId)" in _SCORE_JS      # the data attribute, in contrast


@needs_node
def test_the_log_row_drops_the_severity_vocabulary_the_miss_list_owns():
    """Same builder, different question: the log says what happened, the miss
    list ranks how bad it was. Cost has a per-scenario unit and duplicates the
    score, so it belongs to the list whose subject IS severity."""
    t = 100 * DAY
    a = att("a", first_ms=t, ts_ms=t, score=61, correct=False,
            outcomeClass="suboptimal", gradedCost=2.4, acceptedSet=["4H"],
            chosenCall="3S")
    got = run_js([f"logRowHtml({a}, dayKey({t}))"])[0]
    vis = got[got.index('<span class="mtxt">'):]   # the visible cell only: the
    # aria-label is a sentence and legitimately says "בחרת 3S"
    assert "עלות" not in vis and "נחותה מהמיטבית" not in vis
    assert "מיטבי" in vis and "4H" in vis     # ...but the better call is named
    assert "בחרת" not in vis                  # 300 repetitions of a label
    # the dashboard's rows keep both, through the same builder
    assert "attemptRowHtml(m, {cost: !compact, outcome: !compact})" \
        in _DASHBOARD_JS


@needs_node
def test_a_lead_row_names_its_training_mode():
    """MP and IMP leads are graded on different scales; in a list with one
    aligned score column, two such rows would otherwise look comparable."""
    mp = att("a", kind="lead", trainingMode="MP", type="lead_3nt")
    imp = att("b", kind="lead", trainingMode="IMP", type="lead_3nt")
    bid = att("c")
    got = run_js([f"badge({mp})", f"badge({imp})", f"badge({bid})"])
    assert "הובלה · MP" in got[0]
    assert "הובלה · IMP" in got[1]
    assert "הכרזה" in got[2] and "MP" not in got[2] and "IMP" not in got[2]


@needs_node
def test_a_type_with_no_taxonomy_entry_is_dropped_not_read_aloud():
    """typeLabel falls back to the raw key (the dashboard's rows need SOMETHING
    to name a group), but a row must not announce "compete_or_sell" inside a
    Hebrew sentence, and "constructor" must not print "· undefined"."""
    t = 100 * DAY
    known = att("a", first_ms=t, ts_ms=t)
    renamed = att("b", first_ms=t, ts_ms=t, type="retired_type_x")
    proto = att("c", first_ms=t, ts_ms=t, type="constructor")
    got = run_js([f"badge({known})", f"logRowHtml({known}, dayKey({t}))",
                  f"badge({renamed})", f"logRowHtml({renamed}, dayKey({t}))",
                  f"badge({proto})", "typeLabel('retired_type_x')"])
    assert "קרב חוזה חלקי" in got[0] and "קרב חוזה חלקי" in got[1]
    assert "retired_type_x" not in got[2] and "retired_type_x" not in got[3]
    assert "undefined" not in got[4]
    assert got[5] == "retired_type_x"   # the fallback the dashboard relies on


@needs_node
def test_an_undated_row_still_emits_the_time_cell():
    """The row is a 4-track grid: dropping the empty time cell shifted every
    later cell one track left, crushing the whole text into the 3.2em time
    column -- exactly for the undated population the log groups apart."""
    undated = json.dumps({"problemId": "u", "score": 90, "kind": "bidding",
                          "chosenCall": "4H", "acceptedSet": ["4H"],
                          "attemptCount": 1, "isFirstAttempt": True,
                          "type": "compete_or_sell", "difficultyLevel": 2},
                         ensure_ascii=False)
    dated = att("d", first_ms=100 * DAY, ts_ms=100 * DAY)
    got = run_js([f"logRowHtml({undated}, 0)",
                  f"logRowHtml({dated}, dayKey({100 * DAY}))"])
    for row in got:
        assert row.count('class="rtime ltr"') == 1, row
    assert '<span class="rtime ltr"></span>' in got[0]
    # the miss list has no time column at all, so it must NOT gain an empty cell
    miss = _run_js([f"missRowHtml({dated}, true)"])   # the dashboard's block
    assert "rtime" not in miss[0]
    # and a screen reader is told the row is undated rather than nothing
    assert "ללא תאריך" in got[0]


@needs_node
def test_the_row_label_repeats_every_marker_the_row_shows():
    """aria-label REPLACES the accessible name, so a marker missing from it is
    a disclosure that exists for sighted users only."""
    t = 200 * DAY
    replay = att("b", first_ms=t - 3 * DAY, ts_ms=t, last_ms=t, attemptCount=3,
                 score=61, correct=False, outcomeClass="suboptimal",
                 gradedCost=2.0, acceptedSet=["4H"], chosenCall="3S")
    got = run_js([f"logRowHtml({replay}, dayKey({t}))"])[0]
    lbl = re.search(r'aria-label="([^"]*)"', got).group(1)
    assert "חזרה 3 פעמים" in lbl
    assert "נפתרה לראשונה" in lbl
    assert "מיטבי 4H" in lbl and "ציון 61" in lbl and "קושי 3" in lbl
    # a removed row keeps a label too -- it is still a row, just not a link
    gone = run_js([f"(LIVE_IDS = new Set([]), logRowHtml({replay}, dayKey({t})))"])[0]
    assert gone.startswith("<div") and "aria-label=" in gone


@needs_node
def test_an_exact_legacy_grade_is_not_marked_as_reconstructed():
    """100 for an accepted call and 0 for a dead option are exact by
    definition; only a curve-rebuilt score reads harsher than it should."""
    t = 100 * DAY
    ok = att("a", first_ms=t, ts_ms=t, score=None, correct=True)
    dead = att("b", first_ms=t, ts_ms=t, score=None, correct=False,
               outcomeClass="dead")
    approx = att("c", first_ms=t, ts_ms=t, score=None, correct=False,
                 outcomeClass="suboptimal", gradedCost=1.4)
    got = run_js([f"chipHtml({ok})", f"chipHtml({dead})", f"chipHtml({approx})"])
    assert "~" not in got[0] and ">100<" in got[0]
    assert "~" not in got[1] and ">0<" in got[1]
    assert "~" in got[2]
    # the tilde is bidi-neutral, so without an explicit LTR direction the chip
    # renders "42~" on this RTL page
    assert 'dir="ltr"' in got[2] and 'dir="ltr"' not in got[0]
    # and the chip carries no gloss target: it lives inside the row's <a>
    assert "data-gloss" not in "".join(got)


@needs_node
def test_paging_never_dead_taps_when_one_day_overshoots_the_chunk():
    """visibleGroups admits whole days, so a single day can already exceed
    LIMIT + CHUNK -- a plain `LIMIT += CHUNK` then reveals nothing, the tap does
    nothing and focus is dropped."""
    got = run_js([
        # day sizes [250, 5, 5]: the first day alone overshoots two chunks
        "(() => {"
        " const groups = [{key: 3, rows: Array(250).fill(0)},"
        "                 {key: 2, rows: Array(5).fill(0)},"
        "                 {key: 1, rows: Array(5).fill(0)}];"
        " const out = []; LIMIT = CHUNK;"
        " for (let tap = 0; tap < 2; tap++) {"
        "   const before = visibleGroups(groups, LIMIT);"
        "   const shownBefore = before.reduce((s, g) => s + g.rows.length, 0);"
        "   LIMIT = Math.max(LIMIT, shownBefore) + CHUNK;"
        "   let after = visibleGroups(groups, LIMIT);"
        "   while (after.length === before.length && after.length < groups.length) {"
        "     LIMIT += CHUNK; after = visibleGroups(groups, LIMIT); }"
        "   out.push(after.length - before.length);"
        " } return out; })()"])
    # tap 1 must reveal SOMETHING (the bug made it reveal nothing); here it
    # reveals both remaining days, after which there is nothing left to page and
    # the button is replaced by the practice CTA -- hence 0 on the second tap
    assert got[0][0] > 0, "the first tap must reveal at least one more day"
    assert got[0] == [2, 0], got[0]


def test_paging_and_focus_wiring():
    seg = _HISTORY_JS[_HISTORY_JS.index("function showMore()"):
                      _HISTORY_JS.index("function setFilter(")]
    assert "Math.max(LIMIT, shownBefore) + CHUNK" in seg
    assert "while (after.length === before.length" in seg
    # a filter tap also replaces the control that was tapped
    fseg = _HISTORY_JS[_HISTORY_JS.index("function setFilter("):
                       _HISTORY_JS.index("function markRemoved(")]
    assert "btn.focus()" in fseg


def test_the_empty_state_fallback_cannot_rebuild_a_populated_page():
    """The 8s guard exists for a sync event that never arrives; firing it while
    400 cached rows are on screen would destroy focus and reflow mid-read."""
    init = _HISTORY_JS[_HISTORY_JS.index("async function init()"):]
    assert "if (!SYNCED && !firstAttempts(ATTEMPTS).length)" in init


def test_the_deep_link_params_are_parsed():
    init = _HISTORY_JS[_HISTORY_JS.index("async function init()"):]
    assert 'q.get("kind")' in init and 'q.get("f") === "miss"' in init
    # ...and the dashboard's own filtered list is what links here
    assert 'href="history.html"' in _DASHBOARD_JS


@needs_node
def test_difficulty_is_clamped_before_it_is_repeated():
    """firestore.rules bounds the field count and the key names, but does not
    type-check difficultyLevel — and this value reaches "★".repeat()."""
    got = run_js([f'badge({att("a", difficultyLevel=99)}).split("★").length - 1',
                  f'badge({att("a", difficultyLevel=-3)})',
                  f'badge({att("a", difficultyLevel=2.7)})'])
    assert got[0] == 5
    assert "★" not in got[1]
    assert got[2].count("★") == 5 and "★★</span>" in got[2]


@needs_node
def test_every_row_carries_a_sentence_label_and_hides_its_decoration():
    """As shipped by the miss list, a row's accessible name would read five star
    glyphs and an arrow."""
    t = 100 * DAY
    a = att("a", first_ms=t, ts_ms=t, score=92)
    got = run_js([f"logRowHtml({a}, dayKey({t}))"])[0]
    assert "aria-label=" in got and "קושי 3 מתוך 5" in got and "ציון 92" in got
    assert 'aria-hidden="true"' in got          # stars + the arrow
    # and no tappable gloss target inside the row <a>: it would fire navigation
    # and the glossary card at once (and a <button> in an <a> is invalid HTML)
    assert "data-gloss" not in got and "<button" not in got


# ---- state, sync and reads -------------------------------------------------

def test_the_page_never_claims_an_empty_history_before_the_first_sync():
    """allAttempts() serves a localStorage cache that is empty on a new device;
    telling a user with 400 answers they have none is the worst possible first
    impression on this page."""
    seg = _HISTORY_JS[_HISTORY_JS.index("function render(list)"):
                      _HISTORY_JS.index("function moreHtml(")]
    assert "SYNCED" in seg
    assert "טוען את היומן שלך" in seg
    assert "עוד לא פתרת בעיות" in seg
    assert 'SYNCED = true' in _HISTORY_JS


def test_the_background_sync_rerenders_from_module_state():
    assert 'addEventListener("bt-attempts-synced"' in _HISTORY_JS
    seg = _HISTORY_JS[_HISTORY_JS.index('addEventListener("bt-attempts-synced"'):]
    assert "render(await window.BT.allAttempts())" in seg
    assert "markRemoved()" in seg


def test_one_click_handler_bound_once_outside_render():
    """Binding inside render() adds a listener per render, and paging would
    advance twice per tap."""
    assert _HISTORY_JS.count("addEventListener(\"click\"") == 1
    init = _HISTORY_JS[_HISTORY_JS.index("async function init()"):]
    assert 'el.addEventListener("click"' in init
    render = _HISTORY_JS[_HISTORY_JS.index("function render(list)"):
                         _HISTORY_JS.index("function moreHtml(")]
    assert "addEventListener" not in render


def test_the_pool_index_is_not_on_the_path_to_first_paint():
    """fetchIndex starts with a server-first getDoc: a billed read and a network
    round trip. Rows are tappable until we learn otherwise, and the few removed
    ones are patched in place afterwards."""
    init = _HISTORY_JS[_HISTORY_JS.index("async function init()"):]
    assert "await window.BT.fetchIndex()" not in init
    assert init.index("render(await window.BT.allAttempts())") \
        < init.index("window.BT.fetchIndex()")
    assert "requestIdleCallback" in init
    # the few orphaned rows are swapped in place; the list is never rebuilt
    patch = _HISTORY_JS[_HISTORY_JS.index("function markRemoved()"):
                        _HISTORY_JS.index("async function init()")]
    assert "replaceWith" in patch
    assert 'getElementById("hlist").innerHTML' not in patch
    assert "render(" not in patch


def test_pending_rows_are_marked_and_the_api_is_guarded():
    assert "pendingIds: () => Object.keys(PENDING)," in (
        __import__("pathlib").Path("bridge_trainer/web/bt-firebase.js")
        .read_text(encoding="utf-8"))
    assert "window.BT.pendingIds && window.BT.pendingIds()" in _HISTORY_JS
    assert "window.BT.pendingCount && window.BT.pendingCount()" in _HISTORY_JS
    assert "טרם נשמר בענן" in _HISTORY_JS


def test_the_footnotes_state_every_limit():
    seg = _HISTORY_JS[_HISTORY_JS.index("function noteHtml("):
                      _HISTORY_JS.index("function render(list)")]
    assert "שורה אחת לכל בעיה" in seg          # not one row per attempt
    assert "והציון נשאר של " in seg and 'glossHtml("firstonly"' in seg
    assert "ללא תאריך" in seg                  # why undated rows group apart
    assert "הוסרו מהמאגר" in seg
    assert 'נפתרו לפני ' in seg and 'glossHtml("legacy"' in seg
    assert "ללא ציון" in seg
    assert "טרם נשמרו לענן" in seg
    assert "יכול להתעדכן בין ביקורים" in seg   # a regrade can move a score


# ---- wiring ----------------------------------------------------------------

def test_the_page_is_emitted_and_versions_its_assets():
    page = _history_html()
    assert 'href="history.css?v=' in page
    assert 'src="history.js?v=' in page
    assert _HISTORY_CSS not in page and _HISTORY_JS not in page
    assert 'lang="he"' in page and 'dir="rtl"' in page
    assert '<main id="main" tabindex="-1">' in page      # the skip link's target
    assert page.index("app.css") > page.index("bt_theme")


def test_the_page_claims_no_bottom_nav_slot():
    """data-nav="progress" would put aria-current="page" on a link to a
    different URL."""
    assert "data-nav" not in _history_html()
    assert '{id: "progress", href: "dashboard.html"' in _SHARED_JS


def test_the_dashboard_leads_to_the_log():
    page = _dashboard_html()
    # the topbar slot used to repeat the <h1> directly below it
    assert '<a href="history.html">יומן התרגול' in page
    assert '<span class="muted">ההתקדמות שלי</span>' not in page
    # and both lists of the same rows name each other, so they don't read as
    # one list shipped twice
    assert 'href="history.html">כל התרגולים לפי תאריך' in _DASHBOARD_JS
    assert 'href="history.html">יומן התרגול — אותן החלטות לפי תאריך' \
        in _DASHBOARD_JS


def test_the_log_css_carries_its_own_felt_tones():
    """Everything on this page outside a .card rides on the green felt, where
    the card --muted is unreadable (UI-1). The rule is id-scoped to #dash in
    dashboard.css, so the log ships its own."""
    assert "#hist { color: var(--on-felt); }" in _HISTORY_CSS
    assert "#hist > .footnote { color: var(--on-felt-muted); }" in _HISTORY_CSS
    # the one .alllink in the app that sits on the felt takes an on-felt tone:
    # --accent over the green is 1.16:1 in light mode (invisible), and this is
    # the escape hatch out of a filtered view
    assert "#hist .hsum .alllink { color: var(--on-felt);" in _HISTORY_CSS


def test_the_row_is_a_grid_and_its_targets_are_reachable():
    row = re.search(r"^\.hrow \{[^}]*\}", _HISTORY_CSS, re.S | re.M).group(0)
    assert "display: grid" in row
    assert "min-height: 44px" in row
    assert ".hfilt .segctl button { min-height: 44px; }" in _HISTORY_CSS
    # the day heading is a real sticky <h2>, for heading navigation
    assert "position: sticky" in _HISTORY_CSS
    assert '<h2 class="dday"' in _HISTORY_JS


def test_the_filters_add_no_new_control_vocabulary():
    """.segctl already exists in app.css, is already accent-styled and is
    already in the contrast test's pair list, so the filter row ships no CSS of
    its own beyond a 44px target."""
    assert ".segctl {" in _CSS
    assert 'class="segctl"' in _HISTORY_JS
    assert ".segctl {" not in _HISTORY_CSS and ".segctl button {" not in \
        _HISTORY_CSS.replace(".hfilt .segctl button {", "")
    # and the accent stays an INK for affordances (the row's arrow, the paging
    # label) -- never a fill, which is how the dashboard's data would start
    # reading as a control
    for line in _HISTORY_CSS.splitlines():
        if "var(--accent)" in line:
            assert "color: var(--accent)" in line, line


def test_history_css_is_not_appended_to_the_dashboard_bundle():
    from bridge_trainer.app.webapp import _DASHBOARD_CSS
    assert "#hist" not in _DASHBOARD_CSS
    assert _HISTORY_CSS not in _DASHBOARD_CSS


def test_every_glossed_key_on_the_log_resolves():
    """A data-gloss naming a missing key fails SILENTLY (the handler looks up
    GLOSS[key], finds nothing, and simply does not open the card)."""
    seg = _SHARED_JS[_SHARED_JS.index("const GLOSS = {"):]
    seg = seg[:seg.index("\nlet GLOSS_KEY")]
    keys = set(re.findall(r"^\s{2}([a-z0-9]+): \[", seg, re.M))
    used = set(re.findall(r'glossHtml\("([a-z0-9]+)"', _HISTORY_JS))
    used |= set(re.findall(r'data-gloss="([a-z0-9]+)"', _HISTORY_JS))
    assert used, "the log explains none of its jargon"
    assert used <= keys, f"no GLOSS entry for {sorted(used - keys)}"
    # and the glosses live in the footnotes, never inside a row <a>: a <button>
    # in an <a> is invalid HTML and one tap would both navigate and open a card
    rows = _HISTORY_JS[_HISTORY_JS.index("function logRowHtml("):
                       _HISTORY_JS.index("function dayHtml(")]
    assert "glossHtml" not in rows


# ---- the shared block the two pages now sit on -----------------------------

def test_the_attempt_vocabulary_is_declared_once():
    """Two copies of MIN_N (or a second top-level `let LIVE_IDS`, which is a
    hard SyntaxError once both scripts share a global scope) is exactly the
    drift the extraction exists to prevent."""
    for name in ("MIN_N", "LIVE_IDS", "OUTCOME_HE"):
        assert re.search(r"^(?:const|let) " + name + r" =", _SCORE_JS, re.M)
        assert not re.search(r"^(?:const|let) " + name + r" =", _DASHBOARD_JS,
                             re.M)
        assert not re.search(r"^(?:const|let) " + name + r" =", _HISTORY_JS,
                             re.M)
    for name in ("function firstMs", "function actMs", "function attKind",
                 "function accOf", "function badge", "function attemptRowHtml",
                 "function typeLabel", "function btScoreIsFallback"):
        assert name in _SCORE_JS
        assert name not in _DASHBOARD_JS and name not in _HISTORY_JS


def test_no_page_script_shadows_a_shared_declaration():
    """A duplicate top-level `function` is legal JS and silently wins over the
    shared one — how the dashboard's pct(score) shadowed bt-shared's pct(x) for
    the whole page. node --check cannot see it, so it is pinned here."""
    def tops(src: str) -> set[str]:
        return set(re.findall(
            r"^(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)",
            src, re.M))
    shared = tops(_SHARED_JS)
    for name, block in (("dashboard", _DASHBOARD_JS), ("history", _HISTORY_JS),
                        ("lead", _LEAD_JS)):
        assert not tops(block) & shared, (name, tops(block) & shared)
    # the inline page bootstraps share the same global scope, and the shared
    # block now exports generic names (badge, mean, median, typeLabel)
    for name, page in (("index", _index_html()), ("p", _problem_html()),
                       ("lead", _lead_html()), ("history", _history_html())):
        inline = "\n".join(re.findall(r"<script>(.*?)</script>", page, re.S))
        assert not tops(inline) & shared, (name, tops(inline) & shared)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_the_history_bundle_parses_next_to_the_shared_one():
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        os.write(fd, (_SHARED_JS + "\n" + _HISTORY_JS).encode("utf-8"))
        os.close(fd)
        res = subprocess.run(["node", "--check", path],
                             capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
    finally:
        os.unlink(path)
