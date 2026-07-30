# יומן התרגול — practice-history feature plan

Brief (user): *"there is no way to see all the recent workouts the user did. I
want to add that, in the personal area."*

Scope: the personal area is `dashboard.html` ("ההתקדמות שלי"). Everything below
is computable from attempt fields **already written** by
`bridge_trainer/web/bt-firebase.js` and already allow-listed in
`firestore.rules`. No schema change, no new Firestore reads, no dependency, no
build step.

---

## 1. What exists today, and why it isn't this

| view | what it shows | why it is not a history |
|---|---|---|
| hero (`heroHtml`) | mean score over the last 50 first attempts | an aggregate; no per-problem rows |
| "החלטות לחזור אליהן" | 3 worst rows **inside** the hero window | filtered to misses, ordered by score |
| "כל ההחלטות לשיפור" | up to 30 rows, `score < 85` | filtered to misses, ordered by score, capped |
| session ribbon / summary | the *current* 10-problem run | `localStorage` only, per-device, 6 h TTL |

So a user who answered 40 problems and got 34 of them right has **no view that
shows those 34 at all**, and no view ordered by *when*. Every existing list is
ordered by *how bad*. That is the gap.

## 2. The data we actually have

`users/{uid}/attempts/{problemId}` — **one doc per problem** (deliberate: it
bounds the collection to distinct problems answered). Per doc, the fields this
feature reads:

`problemId`, `kind` (`bidding`/`lead`), `type`, `difficultyLevel`, `score`,
`outcomeClass`, `gradedCost`, `chosenCall`, `acceptedSet`, `trainingMode`,
`scoringForm`, `attemptCount`, `isFirstAttempt`, `firstTs` (immutable
first-answer time), `ts`/`lastTs` (bumped by a re-answer).

The whole map is already in memory (`BT.allAttempts()` serves the cache
preloaded at sign-in, refreshed by `bt-attempts-synced`), so the list costs
**zero** extra Firestore reads.

## 3. What the feature can and cannot do

### Can

* every problem the user has answered, newest first, ordered by `firstTs`;
* grouped by calendar day (device timezone), with a per-day count;
* per row: panel score, scenario + type, difficulty, the call you chose vs the
  accepted set, outcome, cost with its unit, time of day, replay count;
* tap a row to practise the same problem again (`retry=1`, the existing route);
* filter by scenario (all / bidding / lead) and by "misses only" (`< 85`);
* work offline from the local cache, and refresh in place when the background
  sync lands.

### Cannot — and the page must say so, not imply otherwise

1. **One row per problem, not per attempt.** The server keeps one doc per
   problem, so a re-answer bumps `attemptCount` and *does not* create a second
   entry, does not move the row's position, and does not change its grade (the
   stored grade is the first attempt's, by design — `docs/scoring_scale.md`).
   Per-attempt history would need a subcollection per problem: an unbounded
   doc count and a read multiplier. Out of scope, and stated as a footnote.
2. **No duration.** Nothing records when a problem was opened, so "you spent
   2 min on this" is unavailable.
3. **No "session" grouping.** A practice run lives in `bt_session`
   (localStorage, one device, 6 h TTL) and is never written to an attempt. Days
   are factual; sessions would be a guess from timestamp gaps. Grouping is by
   **day**.
4. **No hand / auction preview in a row.** That lives in `problems/{id}` — one
   Firestore read per row. Rows link out instead.
5. **Removed problems stay in the log but are not tappable.** Their verdict is
   gone, so they cannot be replayed or re-graded (same rule as the miss list,
   DB-M-9).
6. **A pre-scale attempt shows a reconstructed score.** `btScoreOfAttempt`
   rebuilds it from the base curve only, so it reads a few points harsher.
   The dashboard excludes those from aggregates; the log **shows** them (a log
   that hides history is not a log) and marks the count in the footnote.
7. **No search, no export, no per-row delete.** The only free text is the call
   and the type, both already covered by the filters; export/delete are their
   own features. Not in this change.

## 4. Shape of the feature

A **new page, `history.html`**, not a sixth dashboard section:

* the dashboard is an aggregate instrument — five fixed sections, each a
  statistic; a raw chronological log is a different object, and the page's own
  design rule ("one hero, everything else a statistic behind a heading") would
  be broken by a 300-row list inside it;
* it can be deep-linked and it can hold its own filter state;
* the dashboard keeps its pinned five-section structure
  (`test_five_fixed_sections_in_a_stable_order`).

### Layout (RTL, mobile-first, same chrome as every other page)

```
→ ההתקדמות שלי                                    יומן התרגול
יומן התרגול
─────────────────────────────────────────────────────────────
34 בעיות · מ-12.6 עד היום                     ← summary line
[ הכל ] [ הכרזה ] [ הובלה ]   [ רק לשיפור ]    ← filters (chips)
─────────────────────────────────────────────────────────────
היום · 6 בעיות · ציון 82                       ← day header
 [92]  הכרזה · תחרותי ★★★☆☆   בחרת 3S — מיטבי 3S · מנצחת   14:20 →
 [61]  הובלה · חוזה חלקי ★★★★☆ בחרת ♦4 — מיטבי ♥7 · עלות ≈ 0.7 לקיחה  14:08 →
 …
אתמול · 4 בעיות
 …
[ הצג עוד 50 ]                                 ← paging
─────────────────────────────────────────────────────────────
footnotes: one row per problem · replays · legacy · removed · pending
```

Details:

* **Day header** carries a payoff value (the page's existing rule for every
  heading): count always; the day's mean score only at `n ≥ MIN_N` (5) —
  below that a daily mean is noise, and the dashboard already refuses to print
  a mean under 5.
* **Row** = the existing miss-row vocabulary (score chip, `badge()`, chosen vs
  accepted, outcome, cost + unit) plus **time of day** and, when
  `attemptCount > 1`, `· נענתה N פעמים`. Rows are `<a>` to
  `routeFor(kind, id, {retry: true})`; a removed problem renders a non-link row
  labelled `בעיה שהוסרה`.
* **Filters**: scenario is a 3-way segmented control; "רק לשיפור" is a toggle
  (`score < REVIEW_MIN`). State persists in `localStorage` (`bt_hist_f`) so
  returning to the page keeps the view. Counts update; an empty result gets its
  own state copy ("אין תרגולים בבחירה הזו"), never a blank page.
* **Paging**: 50 rows per chunk with a "הצג עוד" button that names how many
  remain. A single `innerHTML` of 500+ rows is the one real performance risk
  here, and this removes it.
* **No-timestamp rows** (very old docs that predate `ts`) group last under
  `ללא תאריך` rather than being silently dated today.
* **Ordering is fixed** (newest first). No sort control: "recent" is the
  request, and every other order already exists on the dashboard.

### Entry points

1. Dashboard: a link card after the hero / "what to strengthen" / "revisit"
   cards and before the collapsible sections — one `.mrow` with a payoff
   summary: `יומן התרגול — 34 בעיות · אחרון: היום`.
2. Direct URL (`history.html`), and the topbar links back to the dashboard.
3. Bottom nav stays two items + account. A fourth nav slot for a leaf view
   would cost every page's chrome; the dashboard card is the discoverable
   route, and the dashboard is one tap away from anywhere.

## 5. Implementation

`bridge_trainer/app/webapp.py` (single file, as the rest of the app):

1. **Extract `_ATTEMPT_JS`** — the attempt-row vocabulary the two pages share:
   `tsMillis`, `firstMs`, `attKind`, `scenHe`, `unitOf`, `accOf`, `typeLabel`,
   `badge`, `OUTCOME_HE`, `LIVE_IDS`/`btOrphan`, `missRowHtml`'s row builder,
   `nProblems`/`nDecisions`, `mean`/`median`. Then
   `_DASHBOARD_JS = _ATTEMPT_JS + <dashboard body>` and
   `_HISTORY_JS = _ATTEMPT_JS + <history body>`, so neither page duplicates the
   vocabulary in *source* and the existing `_DASHBOARD_JS` assertions still
   see every symbol they pin.
2. **`_HISTORY_JS`** — pure functions (`dayKey`, `dayLabel`, `groupByDay`,
   `histRowHtml`, `applyFilters`, `render`) + the same bootstrap as the
   dashboard (`BT.start(init)`, re-render on `bt-attempts-synced`, read the
   pool index for `LIVE_IDS`, tolerate its failure).
3. **`_HISTORY_CSS`** — a small block appended to `_DASHBOARD_CSS` (the log
   reuses `.dsec`/`.mrow`/`.patlist`/chips), so `history.html` links
   `app.css` + `dashboard.css` and adds no third stylesheet.
4. **`_history_html()`** + registration in `write_app` (`history.html`,
   `history.js`) with the existing `_asset_ver` cache-busting, `_head_preloads`,
   `_theme_head_script`, `_taxonomy_script`, `data-nav="progress"`.
5. **Dashboard**: the link card in `render()`.

### Tests (`tests/test_history_page.py`, plus additions to existing lists)

Behavioural, under node (the repo's `run_js` pattern):

* ordering is by `firstTs`, descending, and a re-answer's bumped `ts` does not
  reorder;
* `groupByDay` buckets by local day, newest first, undated last;
* a day header prints a mean only at `n ≥ MIN_N`;
* the misses filter is exactly `score < REVIEW_MIN`; the scenario filter treats
  a `kind`-less legacy attempt as bidding;
* paging yields the first 50 and reports the remainder;
* `attemptCount > 1` renders the replay count; `attemptCount = 1` does not;
* an orphaned (removed) attempt renders a non-link row;
* user-owned text (`chosenCall`, `acceptedSet`) is `esc()`d (SEC-A-6).

Structural: the page is emitted, links versioned assets, declares
`lang="he" dir="rtl"`, carries the Hebrew-only chrome, is in the shared-asset /
preload / sign-in-gate parametrizations, every `glossHtml` key resolves, and
the footnotes state the four limits (one row per problem, legacy, removed,
pending).

## 6. Risks

| risk | mitigation |
|---|---|
| a huge log renders slowly | 50-row chunks; one `innerHTML` per chunk |
| the log implies it holds every *attempt* | footnote + the explicit replay count on the row |
| a daily mean over 2 problems reads as a verdict | mean gated at `MIN_N`, count always |
| duplicated row code drifts from the miss list | one shared `_ATTEMPT_JS` source |
| a new page misses a global invariant (RTL, gate, preloads) | added to the existing parametrized page lists |
