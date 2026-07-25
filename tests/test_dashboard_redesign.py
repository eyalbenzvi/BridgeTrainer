"""The progress-dashboard redesign (docs/dashboard_redesign_plan.md).

Two kinds of assertion here:

* behavioural — the new statistics run under node and are checked against the
  cases that motivated them (the sd=0 interval, P/X/XX having no bid height,
  the aggregate buckets, shrinkage collapsing a null category set).
* structural — the deletions actually happened, the disclosure copy is
  present, and every glossed term resolves. The dashboard is a string-built
  page with no DOM test harness, so structure is pinned by source assertions,
  matching the convention already used by the other webapp tests.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile

import pytest

from bridge_trainer.app.webapp import (_CSS, _DASHBOARD_CSS, _DASHBOARD_JS,
                                       _SCORE_JS, _SHARED_JS,
                                       _dashboard_html)

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available")


def run_js(exprs: list[str]) -> list:
    """Evaluate expressions against the score module + the dashboard's own JS.

    _SCORE_JS rather than the whole _SHARED_JS: the shared block installs a
    document-level click handler for the glossary at import time, which a bare
    node run has no DOM for. The score module is deliberately DOM-free (its own
    header says so), and it is where the dashboard's new helpers live.

    The dashboard script's last lines bootstrap against window.BT, so they are
    dropped; everything above them is pure functions.
    """
    cut = _DASHBOARD_JS.index("// refresh the dashboard once the background")
    src = (_SCORE_JS + "\n"
           + "const localStorage = {getItem: () => null, setItem: () => {}};\n"
           + _DASHBOARD_JS[:cut] + "\n"
           + "console.log(JSON.stringify([" + ",".join(exprs) + "]));")
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        os.write(fd, src.encode("utf-8"))
        os.close(fd)
        res = subprocess.run(["node", path], capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
        return json.loads(res.stdout.strip().splitlines()[-1])
    finally:
        os.unlink(path)


# ---- statistics -------------------------------------------------------------

@needs_node
def test_interval_uses_t_not_normal_multiplier():
    """1.96 with an ESTIMATED sd is too narrow at small n: the old dashboard's
    intervals covered ~87% while claiming 95%."""
    got = run_js(["btT95(4)", "btT95(1)", "Math.round(btT95(200) * 100) / 100"])
    assert got[0] == 2.776           # n=5
    assert got[1] == 12.706
    assert abs(got[2] - 1.96) < 0.02   # converges on the normal value


@needs_node
def test_meanCI_never_claims_zero_width():
    """Five straight 100s used to print "100 (100-100, n=5)" -- infinite
    confidence from five easy boards. A homogeneous sample has not proven
    sd=0, so the DISPLAYED half-width is floored."""
    got = run_js(["meanCI([100,100,100,100,100]).h",
                  "meanCI([100,100,100,100,100]).lo",
                  "meanCI([70]).h"])
    assert got[0] >= 2               # floored, not zero
    assert got[1] < 100              # so the interval is not degenerate
    assert got[2] is None            # n=1 has no interval at all


@needs_node
def test_bid_height_excludes_non_contract_calls():
    """candOrder sorts P/X/XX to 100/101/102 -- ABOVE 7NT -- for display
    ordering. Reusing it as a height would have made every Pass an overbid."""
    got = run_js(["bidHeight('P')", "bidHeight('X')", "bidHeight('XX')",
                  "bidHeight('1C') < bidHeight('1NT')",
                  "bidHeight('1NT') < bidHeight('2C')",
                  "bidHeight('7NT') > bidHeight('4S')",
                  "bidHeight('')", "bidHeight(null)"])
    assert got[:3] == [None, None, None]
    assert got[3] and got[4] and got[5]
    assert got[6] is None and got[7] is None


@needs_node
def test_aggregate_buckets_are_distinct_from_per_answer_bands():
    """BAND_HE grades ONE decision; a MEAN of 86 can be 100/100/100/44, so the
    aggregate vocabulary must be its own."""
    got = run_js(["[95, 88, 87, 78, 77, 68, 67, 20].map(btAggOf)",
                  "AGG_HE.map(x => x[0])", "BAND_HE.near"])
    assert got[0] == [0, 0, 1, 1, 2, 2, 3, 3]
    labels = got[1]
    assert labels == ["שיפוט מדויק", "שיפוט טוב", "שיפוט סביר", "יש מה לחזק"]
    # and the two vocabularies share no word
    assert got[2] not in labels


@needs_node
def test_aggregate_wording_matches_its_own_arithmetic():
    """With non-best answers averaging ~75, mean = 100p + 75(1-p), so the share
    of best answers is 0.52 at 88 and 0.28 at 82. "most" would need ~92.5 --
    an earlier draft claimed it at 88."""
    txt = run_js(["AGG_HE.map(x => x[2])"])[0]
    assert "כמחצית" in txt[0]        # >= 88
    assert "כרבע" in txt[1]          # 78-87
    for s in txt:
        assert "ברוב הבעיות בחרת בדיוק" not in s


@needs_node
def test_shrinkage_collapses_a_null_category_set():
    """The old rule (overall - cat - 1.0*SE > 3) named a false weakness on
    ~47% of null category sets at n=12: a one-sided haircut applied once does
    not survive an argmax over 15 candidates. Empirical-Bayes shrinkage pulls
    every cell back to the overall mean when there is no real signal."""
    # 15 categories, same underlying ability, n=12 each -> nothing should look
    # meaningfully weak after shrinkage
    got = run_js(["""(() => {
      let seed = 7;
      const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648)
                        / 2147483648;
      const groups = [];
      for (let g = 0; g < 15; g++) {
        const scores = [];
        for (let i = 0; i < 12; i++)
          scores.push(rnd() < 0.45 ? 100 : 60 + Math.round(rnd() * 30));
        groups.push({key: 'g' + g, label: 'g' + g, scores});
      }
      const all = groups.flatMap(g => g.scores);
      const overall = all.reduce((s, x) => s + x, 0) / all.length;
      const adj = shrink(groups, overall);
      const rawSpread = Math.max(...groups.map(g =>
        g.scores.reduce((s, x) => s + x, 0) / g.scores.length))
        - Math.min(...groups.map(g =>
        g.scores.reduce((s, x) => s + x, 0) / g.scores.length));
      const adjSpread = Math.max(...adj.map(a => a.adj))
                      - Math.min(...adj.map(a => a.adj));
      return {rawSpread, adjSpread,
              fires: adj.some(a => a.adj < overall - 3)};
    })()"""])[0]
    # the raw means scatter widely on noise alone; shrinkage must compress that
    assert got["rawSpread"] > 10, got
    assert got["adjSpread"] < got["rawSpread"] / 2, got
    assert not got["fires"], "named a weakness in a world with no weakness"


@needs_node
def test_shrinkage_keeps_a_real_hole():
    """The flip side: a genuine gap at a decent sample must survive."""
    got = run_js(["""(() => {
      const groups = [];
      for (let g = 0; g < 6; g++)
        groups.push({key: 'g' + g, label: 'g' + g,
                     scores: Array(30).fill(85)});
      groups.push({key: 'bad', label: 'bad', scores: Array(30).fill(55)});
      const all = groups.flatMap(g => g.scores);
      const overall = all.reduce((s, x) => s + x, 0) / all.length;
      const adj = shrink(groups, overall);
      const worst = adj.sort((a, b) => a.adj - b.adj)[0];
      return {key: worst.key, adj: worst.adj, overall};
    })()"""])[0]
    assert got["key"] == "bad"
    assert got["adj"] < got["overall"] - 3


@needs_node
def test_trend_is_a_slope_not_a_window_comparison():
    """Comparing two rolling windows by CI non-overlap is about alpha=0.005, so
    a real 10-point gain would be acknowledged less than half the time while
    the caption asserted flatness. A slope over every point has power and
    reports a rate."""
    got = run_js(["""(() => {
      // a clean +20 points over 100 attempts
      const mk = n => Array.from({length: n}, (_, i) =>
        ({score: 60 + i * 0.2, ts: {seconds: 1000 + i * 3600},
          firstTs: {seconds: 1000 + i * 3600}}));
      const up = trendOf(mk(100));
      const flat = trendOf(Array.from({length: 100}, (_, i) =>
        ({score: 75, ts: {seconds: 1000 + i * 3600},
          firstTs: {seconds: 1000 + i * 3600}})));
      return {upPer100: Math.round(up.per100), upSig: up.sig,
              flatPer100: Math.round(flat.per100), flatSig: flat.sig,
              short: trendOf(mk(5))};
    })()"""])[0]
    assert got["upPer100"] == 20 and got["upSig"] is True
    assert got["flatPer100"] == 0 and got["flatSig"] is False
    assert got["short"] is None          # below MIN_TREND there is no claim


@needs_node
def test_legacy_attempts_are_identified():
    """btScoreOfAttempt rebuilds a scoreless attempt from the base curve alone
    -- no CI haircut, no stakes stretch, no leniency -- so it reads harsher
    than the same decision today. Anything ordered by time must exclude them
    or it drifts upward on its own."""
    got = run_js(["btHasStoredScore({score: 70})",
                  "btHasStoredScore({correct: true})",
                  "btHasStoredScore({score: null})",
                  "btHasStoredScore(null)"])
    assert got == [True, False, False, False]


def test_hero_excludes_legacy_attempts_and_says_so():
    assert "first.filter(btHasStoredScore)" in _DASHBOARD_JS
    assert "עדכון שיטת הציון" in _DASHBOARD_JS


# ---- disclosure copy --------------------------------------------------------

def test_no_comparative_claim_about_other_players():
    """No population data exists, so the page may not rank the user against
    other humans. Claims about what the field chooses belong to the engine."""
    for banned in ("ברמת מועדון", "מעל הממוצע", "טוב מהרוב", "אחוזון"):
        assert banned not in _DASHBOARD_JS, banned
    assert "לא מול שחקנים אחרים" in _DASHBOARD_JS


def test_hero_discloses_scope_difficulty_and_scenario_mix():
    # min(50, n) silently changes what the number MEANS, and the score
    # normalises for neither how hard the winner is to find nor which of the
    # three differently-calibrated scenarios produced it
    assert "על ${HERO_WIN} הבעיות האחרונות" in _DASHBOARD_JS
    assert "על כל ${nProblems(win.length)} שפתרת" in _DASHBOARD_JS
    assert 'glossHtml("diff", "ממוצע קושי")' in _DASHBOARD_JS
    assert "% הכרזה · " in _DASHBOARD_JS


@needs_node
def test_hebrew_number_agreement():
    """These counts genuinely reach 1 on a new account and in sparse
    categories, where "1 בעיות" reads as broken Hebrew."""
    got = run_js(["nProblems(1)", "nProblems(2)",
                  "nDecisions(1)", "nDecisions(14)"])
    assert got == ["בעיה אחת", "2 בעיות", "החלטה אחת", "14 החלטות"]


def test_counts_go_through_the_agreement_helpers():
    # a bare "${count} בעיות" would reintroduce the singular bug. The one
    # legitimate exception is the fixed MIN_N threshold, which is never 1.
    for m in re.finditer(r"\$\{([^}]+)\} (?:בעיות|החלטות)", _DASHBOARD_JS):
        assert m.group(1) == "MIN_N", m.group(0)


def test_trend_never_asserts_flatness():
    assert "עוד לא מספיק נתונים כדי לזהות מגמה" in _DASHBOARD_JS
    assert "ללא שינוי מובהק" not in _DASHBOARD_JS


def test_blunders_reported_as_a_rate_not_a_run():
    # a blunder-free run length is geometric: its sd equals its mean
    assert "מתוך ${win.length}" in _DASHBOARD_JS
    assert "רצף מיטבי" not in _DASHBOARD_JS
    assert "streak" not in _DASHBOARD_JS


def test_cost_is_grouped_by_unit():
    """gradedCost is IMPs for bidding and IMP leads but TRICKS for MP leads, so
    one median over a lead scenario would average the two and label the result
    with whichever unit came first."""
    seg = _DASHBOARD_JS[_DASHBOARD_JS.index("const byUnit"):]
    assert "byUnit.set(u, [])" in seg
    assert "unitOf(errs[0])" not in _DASHBOARD_JS


# ---- deletions --------------------------------------------------------------

def test_deleted_blocks_are_gone():
    # the per-card lead drilldown rendered ~60 rows of "not enough data"
    assert "function suitRows" not in _DASHBOARD_JS
    assert "SUIT_NAME[st]" not in _DASHBOARD_JS
    assert "הקש סדרה כדי לראות את הקלפים" not in _DASHBOARD_JS
    # the tabs, replaced by fixed-slot <details> sections
    assert 'role="tablist"' not in _DASHBOARD_JS
    assert "data-panel" not in _DASHBOARD_JS
    # the four co-equal stat tiles
    assert "statgrid" not in _DASHBOARD_JS and "statgrid" not in _DASHBOARD_CSS
    assert 'סה"כ ניסיונות' not in _DASHBOARD_JS
    # the cumulative trend line, which converges and hides recent change
    assert "מצטבר" not in _DASHBOARD_JS
    # dead CSS from the old design
    for cls in (".catrow", ".dbar", ".bseg", ".blegend", ".dtab", ".drill"):
        assert cls not in _DASHBOARD_CSS, cls


def test_no_accent_used_as_data_fill():
    """--accent is the app's INTERACTION colour (links, CTAs, gloss buttons),
    so an accent-filled mark reads as a control."""
    # no data mark may be FILLED with it -- that is the test that matters
    assert "background: var(--accent)" not in _DASHBOARD_CSS
    # the marks themselves use the neutral data ink
    assert "background: var(--data)" in _DASHBOARD_CSS
    # accent survives only on affordances: the disclosure chevrons and the
    # link arrow on a tappable miss row
    for line in _DASHBOARD_CSS.splitlines():
        if "var(--accent)" in line:
            assert ("summary::before" in line or ".mrow .go" in line), line


def test_rtl_bars_grow_from_the_reading_origin():
    # the old .catrow .dbar { direction: ltr } made every magnitude bar grow
    # left-to-right on an RTL page, i.e. away from the reading origin
    assert "direction: ltr" not in _DASHBOARD_CSS
    assert "inset-inline-start" in _DASHBOARD_CSS


def test_stars_tones_are_not_scoped_to_the_problem_page():
    # while these lived under .diffline the dashboard's stars all inherited the
    # body ink and every rating read as a solid five
    assert ".stars .on { color: var(--gold); }" in _CSS
    assert ".stars .off { color: var(--line); }" in _CSS


def test_mix_segments_carry_no_inline_label():
    # a small segment used to clip its own % text (min-width:0 + overflow:hidden)
    seg = _DASHBOARD_JS[_DASHBOARD_JS.index("function mixHtml"):]
    seg = seg[:seg.index("</div>")]
    assert "%</span>" not in seg
    assert "box-shadow: inset" not in _DASHBOARD_CSS


# ---- structure --------------------------------------------------------------

def test_five_fixed_sections_in_a_stable_order():
    ids = re.findall(r'section\("([a-z]+)", "', _DASHBOARD_JS)
    assert ids == ["bidding", "lead", "pat", "miss", "how"], ids


def test_every_section_carries_a_payoff_value():
    """A summary that only names its subject has failed -- and a header whose
    payoff is "no data" must not ship at all, so an empty slot renders
    disabled with its own copy instead."""
    seg = _DASHBOARD_JS[_DASHBOARD_JS.index("function section("):
                        _DASHBOARD_JS.index("function sub(")]
    assert 'class="dsum"' in seg
    assert "עוד לא" in seg
    # every call site passes a summary expression
    for call in re.findall(r'section\("[a-z]+", "[^"]+", ([^,]+),',
                           _DASHBOARD_JS):
        assert call.strip() not in ('""', "''"), call


def test_open_state_persists_across_renders():
    # a background sync must not collapse a section the user opened
    assert "loadOpen()" in _DASHBOARD_JS
    assert "saveOpen(" in _DASHBOARD_JS
    assert 'OPEN_KEY = "bt_dash_open"' in _DASHBOARD_JS


def test_label_has_hysteresis():
    """A stationary player's label otherwise flips on ~10% of sessions (16%
    near a bucket edge)."""
    seg = _DASHBOARD_JS[_DASHBOARD_JS.index("let idx = btAggOf"):]
    assert "AGG_KEY" in seg
    assert "Math.abs(c.m - edge) < c.h" in seg


def test_category_rows_are_dots_on_a_clipped_domain_and_disclose_it():
    assert "DOM_LO = 40" in _DASHBOARD_JS
    assert "rdot" in _DASHBOARD_JS
    # the clipping is disclosed by printed axis ticks AND a glossed line
    assert "function axisCapHtml" in _DASHBOARD_JS
    assert 'glossHtml("scale40"' in _DASHBOARD_JS
    # a mean below the domain still shows its number rather than being pinned
    assert "runder" in _DASHBOARD_JS


def test_low_sample_rows_are_aggregated_not_repeated():
    # the old page rendered one "not enough data" row per sparse cell
    assert "עדיין ללא ציון" in _DASHBOARD_JS
    assert _DASHBOARD_JS.count("אין מספיק נתונים") == 0


def test_thresholds_scale_with_the_strength_of_the_claim():
    assert "MIN_N = 5" in _DASHBOARD_JS          # a mean appears
    assert "MIN_CI = 12" in _DASHBOARD_JS        # an interval appears
    assert "MIN_LABEL = 20" in _DASHBOARD_JS     # may be NAMED the weakest
    # the wording carries the epistemic status
    assert "החלש ביותר" in _DASHBOARD_JS and "הנמוך עד כה" in _DASHBOARD_JS


def test_recommendation_never_ranks_by_difficulty():
    """docs/classification.md defines level 5 as the probability a competent
    club player gets it wrong, so a low score there is what level 5 MEANS."""
    seg = _DASHBOARD_JS[_DASHBOARD_JS.index("function weakArea"):
                        _DASHBOARD_JS.index("/* ---- render")]
    assert "byDiff" not in seg
    assert "byType" in seg
    # guardrails: sample gate, cooldown, pool guard
    assert "g.n >= MIN_CI" in seg
    assert "cooldown" in seg
    assert "poolLeft(g.key) >= SESSION_SIZE" in seg
    # and it must not invent a weakness when none is significant
    assert 'kind: "coverage"' in seg


def test_wrong_suit_is_tested_against_the_whole_accepted_set():
    """acceptedSet can span several suits. Comparing to a single recommended
    card misfiles right-suit-wrong-card and INVERTS the finding."""
    seg = _DASHBOARD_JS[_DASHBOARD_JS.index("let wrongSuit"):]
    assert "acc.some(c => c[0] === a.chosenCall[0])" in seg
    assert "recommendedLead" not in _DASHBOARD_JS


def test_miss_list_sorted_by_score_not_raw_cost():
    """A cross-scenario cost sort would rank 2.4 IMP against 0.7 tricks."""
    assert "btScoreOfAttempt(a) - btScoreOfAttempt(b)" in _DASHBOARD_JS
    assert "b.gradedCost - a.gradedCost" not in _DASHBOARD_JS


# ---- glossary ---------------------------------------------------------------

def _gloss_keys() -> set[str]:
    seg = _SHARED_JS[_SHARED_JS.index("const GLOSS = {"):]
    seg = seg[:seg.index("\nlet GLOSS_KEY")]
    return set(re.findall(r"^\s{2}([a-z0-9]+): \[", seg, re.M))


def test_every_glossed_key_exists():
    """A data-gloss naming a missing key fails SILENTLY: the handler looks up
    GLOSS[key], finds nothing, and simply does not open the card -- so a typo
    is invisible in manual testing."""
    keys = _gloss_keys()
    used = set(re.findall(r'glossHtml\("([a-z0-9]+)"', _DASHBOARD_JS))
    used |= set(re.findall(r'data-gloss="([a-z0-9]+)"', _DASHBOARD_JS))
    assert used, "the dashboard explains no terms at all"
    assert used <= keys, f"no GLOSS entry for {sorted(used - keys)}"


def test_dashboard_terms_are_explained():
    """The problem pages make every piece of jargon tappable; the progress page
    must match, or its statistics are unexplained."""
    used = set(re.findall(r'glossHtml\("([a-z0-9]+)"', _DASHBOARD_JS))
    used |= set(re.findall(r'data-gloss="([a-z0-9]+)"', _DASHBOARD_JS))
    for key in ("form", "ci", "agg", "sig", "blunders", "mix", "scale40",
                "cost", "leadrank", "weakspot", "pattern", "coverage",
                "firstonly", "legacy", "panel"):
        assert key in used, f"{key} is never explained on the dashboard"


def test_retired_gloss_entry_is_gone():
    assert "streak" not in _gloss_keys()


def test_gloss_entries_have_a_title_and_a_body():
    seg = _SHARED_JS[_SHARED_JS.index("const GLOSS = {"):]
    seg = seg[:seg.index("\nlet GLOSS_KEY")]
    for key in ("form", "ci", "agg", "weakspot", "legacy"):
        m = re.search(r'^\s{2}' + key + r': \["([^"]+)",', seg, re.M)
        assert m and m.group(1).strip(), key


# ---- assets -----------------------------------------------------------------

def test_dashboard_ships_its_css_and_js_as_cacheable_assets():
    page = _dashboard_html()
    assert 'href="dashboard.css?v=' in page
    assert 'src="dashboard.js?v=' in page
    # and no longer inlines them
    assert _DASHBOARD_CSS not in page
    assert _DASHBOARD_JS not in page


def test_emitted_assets_equal_the_constants():
    d = tempfile.mkdtemp()
    try:
        from bridge_trainer.app.webapp import write_app
        write_app(d)
        import pathlib
        root = pathlib.Path(d)
        assert (root / "dashboard.css").read_text(encoding="utf-8") \
            == _DASHBOARD_CSS
        assert (root / "dashboard.js").read_text(encoding="utf-8") \
            == _DASHBOARD_JS
    finally:
        shutil.rmtree(d)
