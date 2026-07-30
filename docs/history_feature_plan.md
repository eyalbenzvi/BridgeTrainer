# יומן התרגול — practice-history feature plan

Brief (user): *"there is no way to see all the recent workouts the user did. I
want to add that, in the personal area."*

Scope: the personal area is `dashboard.html` ("ההתקדמות שלי"). Everything below
is computable from attempt fields **already written** by
`bridge_trainer/web/bt-firebase.js` and already allow-listed in
`firestore.rules`. No schema change, no rules change, no dependency, no build
step.

Written from the plan's first draft plus a UX/information-design review and a
staff-engineering review of that draft. Where the two disagreed, the ruling and
its reason are recorded inline (`R#`), matching
`docs/dashboard_redesign_plan.md`'s convention.

---

## 1. What exists today, and why it isn't this

| view | what it shows | why it is not a history |
|---|---|---|
| hero (`heroHtml`) | mean score over the last 50 first attempts | an aggregate; no per-problem rows |
| "החלטות לחזור אליהן" | 3 worst rows **inside** the hero window | filtered to misses, ordered by score |
| "כל ההחלטות לשיפור" | up to 30 rows, `score < 85` | filtered to misses, ordered by score, capped |
| session ribbon / summary | the *current* 10-problem run | `localStorage` only, per-device, 6 h TTL |

A user who answered 40 problems and got 34 of them right has **no view that
shows those 34 at all**, and no view ordered by *when*. Every existing list is
ordered by *how bad*. That is the gap.

> **R1 — the log and the miss list are not redundant.** They are the same rows
> under two different questions ("what should I fix" vs "what did I do"), so
> both stay — and each says so in copy, or they read as one list shipped twice.

## 2. The data we actually have

`users/{uid}/attempts/{problemId}` — **one doc per problem** (deliberate: it
bounds the collection to distinct problems answered). Fields this feature
reads: `problemId`, `kind`, `type`, `difficultyLevel`, `score`, `outcomeClass`,
`gradedCost`, `chosenCall`, `acceptedSet`, `trainingMode`, `attemptCount`,
`isFirstAttempt`, `firstTs` (immutable first-answer time), `ts` (bumped by a
re-answer), `lastTs` (written on a re-answer since DB-M-9).

The map is already in memory (`BT.allAttempts()` serves the cache preloaded at
sign-in), so the rows themselves cost **no** Firestore reads.

## 3. What the feature can and cannot do

### Can

* every problem the user has answered, newest activity first;
* grouped by calendar day (device timezone), each day naming its count, how
  many are below the review line, and the span of times;
* per row: panel score, time, scenario (+ lead training mode) + type,
  difficulty, the call you chose (and the accepted one when it differs),
  replay count;
* tap a row to practise the same problem again (`retry=1`);
* filter by scenario and by "misses only"; deep-link both;
* work offline from the local cache, and refresh in place when the sync lands.

### Cannot — and the page must say so, not imply otherwise

1. **One row per problem, not per attempt.** The server keeps one doc per
   problem, so a re-answer bumps `attemptCount`/`ts` and does *not* create a
   second entry, and does *not* change the row's grade (the stored grade is the
   first attempt's, by design — `docs/scoring_scale.md`). Per-attempt history
   would need a subcollection per problem: unbounded doc count, a read
   multiplier. Out of scope, and stated in the footnotes.
2. **No duration.** Nothing records when a problem was opened.
3. **No "session" grouping.** A practice run lives in `bt_session`
   (localStorage, one device, 6 h TTL) and never reaches an attempt. Days are
   factual; sessions would be a guess from timestamp gaps. → **R2**: group by
   **day**, and print each day's **time span** (`14:08–15:51`) so one sitting
   versus three is visible without asserting a boundary.
4. **No hand / auction preview in a row.** That lives in `problems/{id}` — one
   read per row. Rows link out instead.
5. **Removed problems stay in the log but are not tappable.** Their verdict is
   gone, so they can be neither replayed nor re-graded (DB-M-9).
6. **A pre-scale attempt shows a reconstructed score**, several points harsher
   (`btHasStoredScore`); and a recorded mistake with no measured cost has no
   score at all — `btScoreOfAttempt` returns exactly `ERROR_MIN` for it.
   → **R3**: the log shows those rows (a log that hides history is not a log)
   but marks them: `~72` for a reconstruction, a muted `ללא ציון` chip for the
   fallback. A footnote count alone cannot tell you *which* row is affected.
7. **A score can change between visits without the row moving**:
   `trainer pool regrade-attempts` rewrites grading fields server-side (never
   the guess, never `firstTs`). One footnote sentence, since a log is exactly
   where a user would notice.
8. **No search, no export, no per-row delete, no `?type=` filter.** The only
   free text is the call and the type; export/delete are their own features.
   Deep-linking the dashboard's category rows into a type-filtered log is a
   real gap but a separate change.

## 4. Shape of the feature

A **new page, `history.html`**, not a sixth dashboard section:

* `render()` on the dashboard is one `el.innerHTML = …` rebuild, fired again on
  `bt-attempts-synced`; it already needs `loadOpen`/`saveOpen` just to keep
  `<details>` open across that. Paging offset + filter + scroll would be three
  more pieces of state to reconstruct inside somebody else's rebuild;
* tabs are already ruled out house-wide (`dashboard_redesign_plan.md` §2.8);
* the dashboard's five-section structure is pinned
  (`test_five_fixed_sections_in_a_stable_order`), and a permanent sixth slot
  whose payoff value is a row count would be the weakest heading on the page.

### 4.1 Ordering — by last activity, not by first answer

> **R4 (the review's most important finding).** Ordering by `firstTs` alone
> makes a whole workout **invisible**: a session spent re-answering eight old
> problems produces zero new rows and no visible change anywhere. That is not a
> disclosed limitation, it is the feature failing its own brief.

So the sort/group key is `actMs(a) = max(firstMs, tsMillis, lastTsMs)` — `ts`
is bumped on every re-answer, `firstTs` never moves. A row that surfaced
because of a replay is marked `· חזרה ×N`, and when its first answer fell on a
different day it also says `נפתרה לראשונה ב-…`, so the first-attempt grade in
its chip is never mistaken for today's work. Tiebreak on `problemId`
(descending activity, then id) — `Object.values(ATTEMPTS)` order changes across
a full reconcile and `firstTs` is second-granular for queued rows, so without a
deterministic tiebreak paging can duplicate or skip a row.

### 4.2 Layout (RTL, mobile-first, same chrome as every page)

```
→ דף הבית                                       יומן התרגול ←   ← dashboard topbar
─────────────────────────────────────────────────────────────
34 בעיות · מ-12 ביוני עד היום                  ← summary line
[ הכל | הכרזה | הובלה ]   [ רק לשיפור ]         ← .segctl, from app.css
─────────────────────────────────────────────────────────────
היום · 6 בעיות · 2 לשיפור · 14:08–15:51          ← <h2>, sticky
 [92] 14:20  הכרזה · קרב חוזה חלקי ★4   3S                    ←
 [61] 14:08  הובלה · MP · חוזה חלקי ★4  ♦4 · מיטבי ♥7          ←
 [~55] 09:04 הכרזה · סלם ★5  4NT · חזרה ×2 · נפתרה לראשונה ב-3 ביולי ←
אתמול · בעיה אחת · 20:14
 …
[ הצג עוד 100 (נותרו 214) ]
─────────────────────────────────────────────────────────────
footnotes: one row per problem · replays · legacy · removed · pending · regrade
```

Rulings behind that:

* **R5 — no per-day mean.** A 6-problem mean mixes three scoring scales
  (bidding τ=2.0, lead·MP τ=0.6 + rank blend, lead·IMP τ=1.75) and possibly two
  calibrations (legacy), and `MIN_CI = 12` means the app refuses to print even a
  *range* at that n. The day header gets facts only: count, misses, time span.
  A day header is a free-to-read group label, not a `<summary>` that owes the
  reader a payoff for a tap.
* **R6 — the row is a grid, not `.mrow`'s flex.** Over hundreds of rows nothing
  aligns under flex, so no column can be scanned. Cells, in RTL reading order:
  score chip → time → text → `←`.
* **R7 — cut from the row**: the outcome label (derivable from the chip plus
  chosen-vs-accepted, and for leads `gradeLead` only ever writes
  `winner`/`suboptimal`), the cost + unit (duplicates the score, and its unit
  differs by scenario — it belongs in the miss list, where severity *is* the
  subject), the word `בחרת`, and `— מיטבי X` whenever the chosen call is
  already accepted (~45% of rows would print the same call twice).
* **R8 — a lead row names its training mode** (`הובלה · MP`): two lead rows
  graded MP and IMP are two different scales sitting in one aligned column.
* **R9 — paging never splits a day.** Chunk target 100 rows, extended to the
  end of the day it lands in, so a day header can never sit above a truncated
  day. A real `<button>` labelled with the remainder; it appends (keeping
  scroll), resets on a filter change, and moves focus to the first newly
  revealed day heading.
* **R10 — filters: persist the scenario, never the "misses only" toggle.** A
  log that silently opens filtered is a log lying about being a log. Whatever
  is active is stated in the summary line with a one-tap escape. Controls are
  `.segctl` from `app.css` — already accent-styled, already contrast-checked,
  and it keeps `--accent` out of the dashboard CSS guard.
* **R11 — undated rows** (docs predating `ts`) group last under `ללא תאריך`,
  with the reason, never silently dated today.
* **R12 — no "no history" before the first sync.** `BT.allAttempts()` serves a
  localStorage cache that is empty on a new device; on a page whose whole
  promise is your history, `עוד אין נתונים` for a user with 400 attempts is the
  worst possible first impression. Show a loading state until either rows exist
  or `bt-attempts-synced` has fired once.
* **R13 — day keys and times are local and hand-formatted.**
  `toISOString().slice(0,10)` buckets by UTC (every answer between 00:00 and
  03:00 Israel time lands on the previous day) and `± 86400000` breaks across
  DST; use `getFullYear/getMonth/getDate` and compare day keys.
  `toLocaleTimeString()` would print `2:20 PM` on an en-US phone — English the
  Hebrew-UI test cannot see, because it only scans static markup. Every
  numeral, time and call is wrapped in `.ltr` (bidi isolation).
* **R14 — a11y**: day headers are real `<h2>`s (heading navigation is how a
  screen-reader user survives 300 rows), stars and the arrow are
  `aria-hidden`, each row carries a full-sentence `aria-label`, rows and
  controls are ≥44 px, and **no `glossHtml` buttons inside a row `<a>`** (the
  miss list already nests a `<button>` in an `<a>`; don't propagate that into
  hundreds of rows). Glosses live in the summary line and footnotes.

### 4.3 Entry points

> **R15.** The dashboard topbar currently prints the page title twice —
> `<span class="muted">ההתקדמות שלי</span>` directly above the `<h1>`. That
> span is ink without data: replace it with the log link. Above the fold, no
> new chrome, zero net ink — and better than the standalone link card the first
> draft proposed, which would have sat a screen and a half down.

Plus one contextual link inside the miss section (`אותן החלטות לפי תאריך ←`),
which is also what stops the two lists reading as one list shipped twice (R1),
and one in the "revisit" card, which already admits it is showing a subset.
The bottom nav stays two items + account; `history.html` sets **no**
`data-nav`, because stamping `progress` would put `aria-current="page"` on a
link to a different URL.

## 5. Implementation

### 5.1 Where the shared code goes

> **R16.** The first draft proposed `_ATTEMPT_JS` as a prefix of both
> `_DASHBOARD_JS` and `_HISTORY_JS`. Both reviews rejected it: it ships the same
> ~150 lines twice over the wire (inverting the T2/PERF-F-4 rationale) and it
> silently guts `test_db_m9_sec_c8.py`'s escaping test, whose slice
> (`index("function missRowHtml") … index("function section(")`) would widen
> from 22 lines to ~600 and stop localising anything.

The vocabulary moves into **`_SCORE_JS`** instead — the block that is already
documented DOM-free, already the source of `btScoreOfAttempt` /
`btScoreChipHtml`, already shipped inside `bt-shared.js` (so it is cached once
and downloaded by neither page twice), and already the only block the node test
harness loads:

`tsMillis`, `firstMs`, `actMs`, `attKind`, `scenHe`, `unitOf`, `accOf`,
`typeLabel`, `mean`, `median`, `nProblems`, `nDecisions`, `MIN_N`,
`OUTCOME_HE`, `badge`, `LIVE_IDS`/`btOrphan`, `btScoreIsFallback`, and one row
builder. They are **deleted** from `_DASHBOARD_JS` in the same commit — two
copies of `MIN_N = 5` is the drift this refactor exists to prevent, and a
duplicated top-level `let LIVE_IDS` in one global scope is a hard
`SyntaxError`.

> **R17 — one row builder, not two.** `attemptRowHtml(a, opts)` serves both
> pages (`opts`: row class, whether to print time / cost / outcome / replays),
> and `missRowHtml` becomes a thin wrapper. One escaping path, one orphan path,
> one cost-unit path — otherwise the plan's own risk table ("duplicated row code
> drifts from the miss list") is re-introduced by the plan itself.

### 5.2 The rest

1. **`_HISTORY_JS`** → `history.js`: `dayKey`/`dayLabel`/`groupByDay`,
   `filtered`, `render`, `appendMore`, plus the dashboard's bootstrap shape
   (`BT.start(init)`, re-render on `bt-attempts-synced`). Module state holds the
   filter **and** the paging limit, so a sync that lands after two `הצג עוד`
   taps cannot reset the page to one chunk. Listeners are bound with `onclick`
   / delegated from a container `render()` never replaces — the dashboard's
   `addEventListener` inside `render()` re-binds per render, which is harmless
   only for an idempotent handler and would double-advance paging.
2. **No `fetchIndex()` before first paint.** `fetchIndex` starts with a
   server-first `getDoc(meta/index)`, i.e. a billed read and a network await;
   the first draft's "zero extra reads" claim was wrong. The page paints from
   the cache with every row tappable, then fetches the index at idle and
   *patches* the few orphaned rows in place (no re-render, no flicker).
3. **`_HISTORY_CSS`** → its own `history.css`, **not** appended to
   `_DASHBOARD_CSS`: that constant is guarded against `--accent` fills and
   `direction: ltr`, and shipping history-only rules to the dashboard for no
   reason is exactly what the guard's neighbours were written to prevent. It
   carries the felt-tone scoping for `#hist` (loose text on this page rides on
   the green felt — the UI-1 bug, which is id-scoped to `#dash` today), the day
   header, the row grid, and nothing else.
4. **`_history_html()`** + `write_app` registration, with `_asset_ver`
   versioning (`_HIST_CSS_HREF`, `_HIST_SRC`), `_theme_head_script()` before
   `app.css`, `_head_preloads()`, `_taxonomy_script()` exactly once before
   `bt-shared.js`, and `<main id="main" tabindex="-1">` for the skip link.
5. **`bt-firebase.js`**: expose `pendingIds()` (one line) so a queued row can be
   marked in place instead of only counted; every call site guards it, as the
   dashboard already guards `pendingCount` (the preview harness's stub lacks
   both).
6. **Hardening while we are in the row builder**: coerce `attemptCount`
   numerically, clamp `difficultyLevel` before `"★".repeat(d)` (the rules file
   does not type-check it), and keep `problemId` going through `routeFor`'s
   `encodeURIComponent`.
7. **`scripts/dash_preview.py`**: a `--page history` flag, or there is no way to
   eyeball a 300-row list offline.

### 5.3 Tests

New `tests/test_history_page.py`, importing the generalised `run_js` helper
rather than adding a third copy of it (the repo's cross-module-import pattern),
with `glossHtml`/`routeFor` stubs alongside the existing `TYPE_NAMES`
injection:

* ordering is by last activity, so a replayed problem surfaces, and a bumped
  `ts` moves the row it belongs to;
* the tiebreak makes the order deterministic under an insertion-order change;
* `groupByDay` buckets by **local** day, newest first, undated last, and
  `היום`/`אתמול` are day-key comparisons (survive a 23/25-hour day);
* day headers print count + misses + span and **never** a mean;
* the misses filter is exactly `score < REVIEW_MIN`; a `kind`-less legacy
  attempt counts as bidding; `isFirstAttempt !== false` is applied;
* paging: first chunk ≥ 100 extended to a day boundary, remainder reported,
  reset on filter change;
* a reconstructed score prints `~`, the no-cost fallback prints `ללא ציון`;
* replay marker appears iff `attemptCount > 1`;
* an orphaned attempt renders a non-link row; user text is `esc()`d — asserted
  against the shared row builder, so the assertion covers **both** pages;
* Hebrew number agreement over `_HISTORY_JS` (the `${n} בעיות` guard the
  dashboard already has), `glossHtml` keys resolve, `node --check` of
  `_SHARED_JS + _HISTORY_JS`, and a `bt-attempts-synced` listener exists.

Existing suites that must gain the new page: `test_asset_split`,
`test_head_preloads`, `test_hebrew_ui` (×4 lists), `test_signin_ux`,
`test_taxonomy_single_source`, `test_ux_round3`, `test_scoring_scale`,
`test_lead_modes`, `test_dashboard_redesign` (emitted assets); plus the pinned
assertions that move with the code (`test_db_m9_sec_c8` on `firstMs`/`accOf`/
`missRowHtml`, `test_dashboard_redesign` on `MIN_N = 5`, `test_ui_fixes_round2`
on the felt-tone selectors).

## 6. Risks

| risk | mitigation |
|---|---|
| a replay-only session shows nothing | order/group by last activity (R4) |
| the log implies it holds every *attempt* | replay marker on the row + footnote |
| a fabricated `40` reads as a measurement | `ללא ציון` chip, exact predicate (R3) |
| a sync resets paging/filters | both in module state, patch-not-rebuild (5.2) |
| loose text unreadable on the felt | `#hist` felt scoping shipped with the page |
| duplicated row code drifts | one builder in `_SCORE_JS` (R17) |
| a new page misses a global invariant | added to the 12 parametrized page lists |
