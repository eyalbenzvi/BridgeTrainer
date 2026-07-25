# Progress dashboard redesign — plan

Scope: `dashboard.html` only — `_DASHBOARD_CSS` + `_DASHBOARD_JS` in
`bridge_trainer/app/webapp.py`, plus the small shared-layer fixes they depend
on (`meanCI`'s variance floor, a `bidHeight` helper, two `_CSS` bugs). No new
dependencies, no build step, no framework, no schema change: everything below
is computable from attempt fields already written by `bridge_trainer/web/
bt-firebase.js` and already allow-listed in `firestore.rules`.

The brief: *"much clearer, with the score made prominent; all the abundant and
hard-to-understand information hidden by default behind a clear heading with an
option to expand."*

Written from a dashboard/information-design review and a bridge-teaching
review, reconciled against each other. Where they disagreed the ruling and its
reason are recorded inline, so a later reader can see which constraint bought
which decision.

---

## 1. Why the current dashboard fails

Not a matter of taste; six specific defects, five of which are bugs.

1. **No hero.** Four co-equal 26px numbers in a 2x2 grid (`ציון ממוצע`,
   `רצף מיטבי`, `בעיות שנענו`, `סה"כ ניסיונות`). Four heroes is none. The score
   the whole app exists to produce has the same visual weight as a replay
   counter.
2. **Nothing is hidden.** On the overview every card is expanded: stat grid,
   weak area, trend, by-scenario, a 10-row miss list, a 5-sentence footnote.
   The only collapsibles are *inside* the lead tab, one level too deep to help.
3. **Wasted dynamic range.** `row()` draws `width: ${mean}%` from zero, but a
   *mean* panel score essentially never leaves ~60–95 (about 45% of answers
   are exactly 100 and misses cluster 60–90). A 78-player and a 90-player
   render nearly identically. This is the main reason the page feels
   uninformative.
4. **The emphasised trend series is the uninformative one.** Of the two paths,
   the solid `--accent` 2px line is the *cumulative* mean — which by
   construction converges and flattens, so it shows less and less change the
   more the user practises. The *rolling* window, the only series that can
   show change, is the de-emphasised grey dashed one. The code already
   half-admits this in a comment.
5. **A wall of empty rows.** The per-card lead drilldown renders one row per
   card per suit; n per individual card is 1–3 essentially forever, so almost
   every row reads `אין מספיק נתונים · n=1`. Screenshotting the lead tab
   expanded produces ~60 such rows. This is the single largest block of code
   producing the least value.
6. **Bugs.**
   - `meanCI` has no variance floor, so five straight 100s give `sd = 0` and
     the dashboard prints `100 (100–100, n=5)` — infinite confidence from five
     easy boards.
   - `.catrow .dbar { direction: ltr; }` makes every magnitude bar grow
     **left-to-right on an RTL page**, i.e. away from the reading origin.
   - `.bseg` prints its `%` label *inside* the segment under
     `min-width: 0` + `overflow: hidden`, so a small segment clips its own
     text.
   - The miss list renders `עלות ≈ 1.4` with **no unit** — and that number is
     IMPs for bidding but *tricks* for MP leads.
   - `.stars .on` / `.off` colours are scoped to `.diffline .stars` in `_CSS`,
     so the dashboard's difficulty stars render all-five-dark.

### Two semantic errors, which matter more than the layout

7. **`BAND_HE` is used to label a mean.** `BAND_HE` grades *one decision*
   against *one optimum*. A mean of 86 can be 100/100/100/44 — calling that
   `כמעט מיטבי` is a category error. Aggregates need their own vocabulary.
8. **`רצף מיטבי` reintroduces binary correct/incorrect** — the exact regime
   `docs/scoring_scale.md` was written to abolish. An 84 (`סטייה קלה`, a call a
   real panel would print with votes) resets it to zero identically to a 12.
   It also rewards answering easy problems, which is the opposite of the
   incentive a coach wants, and it spends most of its life displaying 0 or 1.

---

## 2. Metric decisions

### 2.1 The hero number

**Mean panel score over the last `min(50, n)` first attempts.**

- **First-attempt-only stays.** A second answer to a problem whose verdict you
  have already seen is recall, not judgment; bridge judgment is one-shot. The
  existing `isFirstAttempt !== false` filter is correct.
- **Recent form, not lifetime.** Nobody is judged by their career average.
  After 200 problems a brilliant week moves the lifetime mean by ~0.4 points,
  so a lifetime hero freezes and gets ignored.
- **Window = 50** (reviewers proposed 40 and 50; taking the tighter interval).
  At SD≈21 the 95% half-width is ~±6 at n=50 vs ~±7.5 at n=30. It is also
  5 × `SESSION_SIZE`, a unit the user recognises.
- **`min(50, n)`, so there is exactly one hero at every stage of a user's
  life.** Below 50 the window *is* everything, so the number silently starts
  as the lifetime mean and becomes recent form as the user grows — no dual
  headline, no discontinuity, nothing to explain.
- **The lifetime number is dropped from the hero card entirely.** Nothing
  competes with the hero. What replaces it is the honest disclosure that
  pre-empts the wobble: state the interval *before* the user can notice
  movement. A user who has been told `טווח סביר 77–89` does not read 83→86
  as news.

### 2.2 Aggregate vocabulary (`AGG_HE`) — never `BAND_HE`

Four buckets. The bridge review derived five ~7-point buckets mechanically
from the scoring curve; the design review objected that at SD≈21 a 7-point
bucket flips between visits with no behaviour change, and a label that moves
when nothing moved is worse than no label. Resolution: the design review's
bucket **count/width** (~10 points ≈ the noise floor) with the bridge review's
**vocabulary**, including its own correction of its top label.

| mean | label | one-line meaning |
|---|---|---|
| ≥ 88 | `שיפוט מדויק` | ברוב הבעיות בחרת בדיוק את הפעולה המיטבית. |
| 78–87 | `שיפוט טוב` | בכמחצית הבעיות בחרת את המיטבית, ובשאר היית קרוב. |
| 68–77 | `שיפוט סביר` | כמעט תמיד אפשרות הגיונית, אך לא לרוב את המיטבית. |
| < 68 | `יש מה לחזק` | לצד בחירות קרובות יש גם טעויות של ממש. |

Why these numbers are defensible rather than invented — read off
`btScoreBidding` / `btScoreLead`: a player who *never* finds the top action but
*always* picks a defensible second choice scores ~74–80 mechanically
(bidding, 1 IMP gap, `tau=2.0`: `95/(1+0.5^1.6) ≈ 72` plus leniency). A player
who finds the best half the time and is second the rest lands ~87–89. So
"always sensible, never best" ≈ 75 and "best half the time" ≈ 88 are the two
real anchors, and the bucket edges sit on them.

`BAND_HE` survives in exactly two places, both per-answer: the `.scorechip` on
miss rows, and the reference table inside `איך מחושב הציון`. `AGG_HE` never
labels a single answer.

**`רצף מיטבי` is retired** and replaced by the **blunder-free run**: how many
consecutive first attempts without a score below `ERROR_MIN` (40). At IMPs and
in teams, avoiding disasters is what wins matches; near-misses are recoverable.
It does not punish an 84, it is far harder to game by picking easy boards, and
it maps to a real coaching instruction ("stop having accidents"). The
`GLOSS.streak` entry is replaced by a `blunderfree` entry.

### 2.3 Honesty constraints

These are copy constraints, not suggestions.

- **One disclosure sentence under the hero, always:**
  `הציון מודד את בחירותיך מול פתרון המנוע על הבעיות שפתרת — לא מול שחקנים אחרים.`
- **No comparative word anywhere on the page.** No `ברמת מועדון`, no
  `מעל הממוצע`, no `טוב מהרוב`, no percentile, no letter grade. The app has
  never observed another human, and `docs/scoring_scale.md` itself calls the
  taus provisional. The only comparison the data licenses is the player
  against their own other categories, and it must be phrased that way
  (`לעומת 82 בשאר`).
- **Print the window's difficulty mix beside the hero.** The panel score
  normalises for board volatility (stakes stretch) and field size (MP rank
  blend) but **not** for how hard the winner is to find, so a level-5 diet
  genuinely scores lower. Do not attempt a difficulty adjustment — any such
  adjustment would be uncalibrated. Disclose instead: `ממוצע קושי 3.2`.
- **Never assert a move that isn't significant.** Render a direction arrow
  only when the recent window's CI and the prior window's CI do not overlap;
  otherwise the caption reads `ללא שינוי מובהק` in `--muted`, with no arrow,
  no number and no colour. The *value* is never softened — full precision in
  the numeral, humility in the narrative.
- A genuine benchmark is possible later and is the highest-value future item:
  the engine already stores BEN's policy, so `Σ policy(c) · score(c)` per
  problem is the field's expected score. Precomputed at forge time into
  `index.json` it would give `הממוצע שלך: 83 · השדה על אותן בעיות: 74` — an
  honest comparative claim, difficulty-normalised by construction. **Out of
  scope here** (needs forge/schema changes). Its absence is a capability gap,
  not an honesty gap.

### 2.4 Statistics fixes

In `meanCI` (shared, also used by the hero):

```js
const SD_FLOOR = 8;   // a homogeneous sample of 5 has not proven sd = 0
const H_FLOOR  = 4;   // never print "76-76"
```

A homogeneous sample of five has not proven `sd = 0`; it has proven "sd is
probably below population". The floor keeps the whisker from collapsing
(±4.5 minimum at n=12) without materially inflating a genuinely tight estimate
at n=200. Because the hero uses the same floored function, a lucky 50-window
cannot claim ±2.

**Tiered thresholds — the stronger the claim, the more evidence it needs.**
The two reviews split here (5 vs 12); the resolution is that they were
answering different questions, so each threshold gets a stated job:

| n | mark | numeral | `AGG_HE` label / named "weakest" | drives the CTA |
|---|---|---|---|---|
| 0 | — | — | `לא תרגלת · N בעיות זמינות` | coverage fallback only |
| 1–4 | — | — | folded into the `.rmore` aggregate line | coverage fallback only |
| 5–11 | hollow dot, no whisker | yes | no | no |
| 12–19 | dot + whisker | yes | no (`הנמוך עד כה:`, not `החלש ביותר:`) | yes |
| ≥ 20 | dot + whisker | yes | yes (`החלש ביותר:`) | yes |

Hero: n ≥ 5 for a numeral (below that, `--muted` numeral, no `AGG_HE` chip,
caption `מדגם קטן`); sparkline needs n ≥ 12 per window or it is absent.
Hiding sparse rows entirely was rejected — coverage is exactly what the low-n
rows show, and §3's merged section depends on them being visible.

### 2.5 Cost, and the MP unit

The cost line is meaningful in principle and broken as computed. It averages
`gradedCost` over *all* attempts including the zeros from correct answers, so
it mixes "how often" with "how much" — the two things the panel score already
combines properly. Its only remaining job is **"when I do err, what does it
cost?"**, so:

- **Condition on `score < 100`.** Unconditionally, the median is 0.0 forever
  once the hit rate passes 50%, which reads as a bug.
- **Prefer the median plus a worst case, not the mean.** The distribution is
  right-skewed; one 6-IMP disaster owns the mean of 30 answers.
- **Never print a cost without its unit**, and never sum across scenarios.
- **MP leads switch from tricks to rank.** Matchpoints is frequency scoring —
  `MP_RANK_WEIGHT = 0.35` already knows this. "0.35 tricks below best" is not
  how a pairs player thinks; "your lead ranked 2nd" is. `chosenRank` is
  already stored on every lead attempt and currently unused. This also makes
  the tricks/IMP unit collision disappear.
  Caveat found while verifying: **the candidate count is not stored**, so
  `acceptedSet.length` is the accepted count, not the denominator. Do **not**
  print "2.3 מתוך 5". The rank-1 rate needs no denominator and is the real
  matchpoint statistic.

### 2.6 What to practise next

The current `weakArea` has six defects: it takes a min over a *mixed*
population (bidding types against lead difficulty levels), it recommends
practice **by difficulty**, it uses `MIN_N = 5` with no CI, and it has no
recency, no cooldown and no pool guard. With n=5 the SE is ~10 points; across
~15 candidate buckets the argmin is essentially always the noisiest bucket,
not the weakest — a textbook winner's curse, so it names a false weakness
nearly every time.

Recommending by difficulty is the worst of these. `docs/classification.md`
defines level 5 as P(competent club player gets it wrong) — so scoring low
there is what "level 5" *means*. It is not a weakness and not a study topic.

**Eligible units: skill-named only** — the 10 bidding types, the 5 lead
contract types, and `lead·MP` / `lead·IMP`. Never difficulty, never suit,
never card.

**Guardrails, in order:**

1. **Sample gate:** n ≥ 12 (≥ 20 to use the word `החלש ביותר`).
2. **Significance, not argmin:**
   `weakness = (overall_mean − cat_mean) − 1.0 · SE(cat)`, require
   `weakness > 3`. A one-sided "genuinely below *your own* standard" test.
3. **Recency:** category mean over its last 20 attempts. Untouched for 60+
   days → still offered, but framed `רענון`, not `נקודה חלשה`.
4. **Cooldown:** if ≥ 8 of the last 20 first attempts were already in this
   category, take the runner-up.
5. **Pool guard:** require ≥ `SESSION_SIZE` unanswered live problems in the
   category (`LIVE_IDS` minus answered `problemId`s gives this).

**Fallback ladder — this matters as much as the main rule:**

- **(a) Coverage.** If any eligible category has n < 8, recommend the
  least-practised one. Coverage is a legitimate coaching goal and is a true
  statement at low n.
- **(b) Review.** Otherwise recommend revisiting the worst decisions — the
  highest-yield activity anyway and always defensible.
- **(c) Never invent a weakness.**

**Always show the evidence.** A player accepts a diagnosis with numbers and
rejects a bare label:

```
מה הכי כדאי לחזק
קרב חוזה חלקי — ציון ממוצע 71 על 14 בעיות, לעומת 82 בשאר.
[ תרגל 10 כאלה ← ]

מה הכי כדאי לחזק
כמעט לא תרגלת הובלה נגד סלם (3 בעיות בלבד).
[ תרגל 10 כאלה ← ]

מה הכי כדאי לחזק
אין נושא שבולט לרעה — ההבדלים בין הנושאים בתוך תחום הרעש.
הכי משתלם עכשיו: חזרה על 8 ההחלטות החמורות.
[ חזור עליהן ← ]
```

### 2.7 Pattern detectors

The highest-value new content, because a pattern is a *diagnosis* rather than
a measurement — it is what a teacher actually says. Three ship (a fourth,
"lead passivity", was proposed and dropped: it needs the player's hand, which
is not on the attempt doc).

| detector | expression | gate |
|---|---|---|
| **Pass bias** — exact, build first | `passiveMiss = kind!=="lead" && chosenCall==="P" && !acceptedSet.includes("P")`; `pushyMiss = kind!=="lead" && chosenCall!=="P" && acceptedSet.includes("P")` | combined n ≥ 8, skew ≥ 2:1 |
| **Wrong suit vs wrong card** | `kind==="lead" && score<100`, then `sameSuit = acceptedSet.some(c => c[0] === chosenCall[0])` | ≥ 12 lead misses |
| **Over/under-bid** | needs a new `bidHeight` helper (below) | eligible n ≥ 15, skew ≥ 70/30 |
| **Difficulty cliff** | mean drops > 12 points from level ≤3 to level ≥4 | both sides n ≥ 12 |

Two correctness notes found while verifying these against the source:

- **There is no `callRank` helper.** The nearest thing, `candOrder`
  (`webapp.py:1592`), sorts `P`/`X`/`XX` to **100/101/102 — above 7NT**, so
  using it as a height would classify every Pass as an overbid. A new helper
  is required, and it must return `null` for the non-contract calls:
  ```js
  function bidHeight(c) {
    if (!c || c === "P" || c === "X" || c === "XX") return null;
    return +c[0] * 10 + ["C", "D", "H", "S", "NT"].indexOf(c.slice(1));
  }
  ```
  Because the `P`/`X`/`XX` exclusions drop a large share of attempts, this
  counter lags; **fallback is to omit the line**, never to render "no
  tendency found".
- **"Wrong suit" must be tested against `acceptedSet`, not
  `recommendedLead[0]`.** `acceptedSet` can hold several cards across several
  suits, so "any accepted lead in my suit" is the honest test. Comparing to a
  single recommended card misfiles right-suit-wrong-card as a judgment error,
  which **inverts the finding**. (`recommendedLead` is also only present on
  lead attempts, and only on newer ones.)

### 2.8 Cut, with reasons

- **Per-card lead drilldown** — n per card is 1–3 forever; renders as ~60 rows
  of `אין מספיק נתונים`.
- **By-lead-suit breakdown** — the suit you led is a property of the *deal*,
  not a skill, and it is endogenous: you led a heart *because* the hand said
  heart. Unactionable and confounded.
- **Cumulative trend line** — guaranteed by construction to hide the change
  being looked for.
- **`סה"כ ניסיונות`** — vanity, and it contradicts the "first attempt only"
  framing printed beside it.
- **`רצף מיטבי`** — §2.2.
- **By-difficulty as five bars** — collapsed to one sanity line. Its only
  diagnostic use is a monotonicity check: if levels 1–2 are not clearly the
  best, that is carelessness or a fundamentals hole, and that is worth one
  sentence: `על בעיות קלות (1–2) הציון שלך 91, על קשות (4–5) 71 — פער תקין.`
- **The three tabs** — tabs hide content *sideways* behind a word that carries
  no summary value. A `<details>` reading `הכרזה — ציון 78 · 62 החלטות` hides
  the same content *and* pays the user for the tap.
- **`(lo–hi, n=)` on every row** — 30 numbers nobody reads; CI becomes a
  whisker, printed numerically only in the hero.

### 2.9 Explicitly deferred (needs a schema change)

**Improvement-on-repeats is not computable and was cut.** Worth recording
precisely, because it looks computable: there is one doc per problem keyed by
`problemId`, and the re-answer path patches **only** `attemptCount`, `lastTs`
and `ts` — *"re-answer: keep the first-attempt grading, just count it."* The
replay's score is never written. So `attemptCount` tells you *that* you
replayed, never *how you did*. It needs a new field (`lastScore` /
`bestScore`).

Silver lining from the same finding: every doc's `score` **is** the
first-attempt score and `isFirstAttempt` is never flipped to `false`, so the
dashboard's filter is a correct no-op and its semantics are sound.

Consequently **"leeches" are reframed**: `attemptCount >= 2 && score <
REVIEW_MIN` is revisit *intent*, not evidence of failure to learn. Render it
as `בעיות שחזרת אליהן וטעית בהן בפעם הראשונה` — **not** "still unsolved".

Also deferred: vulnerability and seat (not stored). Costs resolution, not
honesty — but do not imply vulnerability awareness anywhere.

---

## 3. Information architecture

**Tier 1 — always visible, no interaction, ~one phone screen.** Three cards.

1. **`.card.hero`** — hero numeral, `AGG_HE` chip, rail (0–100, ticks at
   0/40/85/100, CI whisker, marker), the interval and difficulty-mix subline,
   the disclosure sentence, the mix bar with its key line, blunder-free run,
   and a bare sparkline of the rolling window with a significance-gated
   caption.
2. **`.card.nextup`** — the merged weak-area + CTA, three lines and exactly
   one action: the what (15px `--fg`), the why (13px `--muted`, one mined
   pattern sentence), and the gold `a.big` button. Two competing calls to
   action is the hierarchy failure being removed, so the pattern gets no
   button of its own.
3. **`.card.tocheck`** — `3 החלטות לחזור אליהן`, one line each: score chip,
   type badge, `בחרת 3♠ — מיטבי 4♥`, `←`.

**Tier 2 — five collapsed `<details class="dsec">`, all closed on first
visit.** The reviews proposed 4 and 5; taking 5. The disputed section was
`איך מחושב הציון`, which the bridge review wanted replaced by a `GLOSS`
tooltip — rejected because the design review's accessibility rule is that this
dashboard ships **no tooltips at all** (touch-first), and a tooltip cannot hold
the 5-band reference table.

| # | `<summary>` | `.dsum` (the payoff) |
|---|---|---|
| 1 | `הכרזה` | `ציון 78 · 62 החלטות` |
| 2 | `הובלה` | `ציון 71 · 40 החלטות` |
| 3 | `נטיות שחוזרות` | `3 דפוסים` |
| 4 | `כל ההחלטות לשיפור` | `23 מתחת ל־85` |
| 5 | `איך מחושב הציון` | `0–100 · 5 רמות` |

Section 5 stays a section (rather than collapsing into a gloss entry) because
the 5-band reference table is tabular content a `.glosscard` cannot hold. It is
the *long-form* explainer; the per-term glosses of §4.9 are the *inline* ones,
and both ship — a user who wants one term tapped answers it in place, a user
who wants the whole model opens section 5.

**Tier 3 — nested `<details class="dsub">` inside a scenario section**, max 3
each. Within a scenario, **the breakdown whose worst qualifying cell is lowest
renders `open`** — that buys the reachability of a flat 8-header list at a
header count of 5, which is what the two reviews were really arguing about.

- `לפי סוג בעיה` → `החלש ביותר: קרב חוזה חלקי 71`
- `לפי סוג חוזה` (lead) → `החלש ביותר: סלם 58`
- `מאצ'פוינטס מול IMP` (lead) → two rows
- `המספרים המלאים` → conditional cost line, the by-difficulty sanity line

**No tier 4, ever.** Hard caps: 5 at tier 2, 3 at tier 3, exactly one
auto-open at tier 3.

**The summary contract.** The title names the subject; the end-aligned `.dsum`
says what you would learn by opening it. A summary that only names its subject
has failed. **Never ship a header whose payoff is `אין מספיק נתונים`** — omit
the section instead.

Open/closed state persists in `localStorage` (`bt_dash_open`), and the
`bt-attempts-synced` re-render must read the open-set *before* re-rendering and
restore it after, or a background sync silently collapses whatever the user
opened.

---

## 4. Encodings

### 4.1 Category rows — dot + whisker on a 40–100 domain

The core disagreement, and the most consequential decision in the plan. The
bridge review wanted the bars rescaled to start at 50 to recover the wasted
range (§1.3). The design review agreed the complaint was empirically right but
refused the fix: bar *length* is the encoding, so a 50 baseline renders 60 vs
90 as 1:4 for a true ratio of 1:1.5. The bridge review then conceded, noting
the distortion runs the wrong way *for this dataset specifically* — it would
make normal, non-significant category scatter look like a diagnosis, which is
exactly what §2.6's significance test exists to prevent.

**Resolution: change the mark, not the axis.** A position mark on a non-zero
domain is legitimate where a truncated bar is a lie, and it lets the CI ride
as a range mark on the same row — which both reviews wanted anyway. One mark
solves both problems.

- **Mark:** filled dot, r=5, `--data`, with a 2px `--card` ring (it overlaps
  the whisker and the 85 tick).
- **Domain: 40 → 100.** Not 50. 40 is `ERROR_MIN` — an existing threshold,
  already the mix bar's lower bin edge, so the whole dashboard stays on one
  landmark set (**40 / 85 / 100**); inventing 50 adds a fourth number nobody
  can anchor, and a 50 floor would clamp real values (a weak category at n=12
  can print ~45).
- **The track stays**, 10px `--data-weak`, **uniform full width on every
  row**. It is now the *axis*, not a bar: because every track is the same
  length, no length comparison is possible and no ratio can be misread.
- **No stem.** A lollipop stem to the domain floor re-imports the length lie.
- **Clipping is disclosed**, not implied: axis ticks `100 ⋯ 85 ⋯ 40` in the
  `.dcap` caption row over the track column, plus one muted line at the top of
  the first breakdown in each scenario: `הסולם מתחיל ב־40.`
- **Out-of-domain values clamp to the inline-start edge with a `◂` in
  `--loss`, and the numeral still renders** — the number carries the truth
  when the mark cannot. Never silently pinned.
- **Colour:** one neutral data ink (`--data`), *not* `--accent` — in this app
  blue means "tappable" (links, CTAs, `.typebadge`). Only rows below
  `NEAR_MIN` (65) take `--loss`, so one thing is coloured and the eye finds
  the actionable row. Banding every row by score would double-encode position
  as hue and turn a 10-row list into a traffic light.
- **Sort by n descending** (stable across visits — a list that reorders is
  unlearnable); surface the worst in the `.dsum` instead.
- **Low-n rows** fold into one trailing muted line:
  `עוד 4 קטגוריות עם פחות מ־5 החלטות — עדיין ללא ציון.` If no cell qualifies,
  the whole tier-3 `<details>` is not rendered.

### 4.2 Hero rail — keeps 0–100

The hero's precision is carried by a 62px numeral (78 vs 90 is unmistakable as
text), so the rail's job is *orientation*, not discrimination — and it is the
one place the full scale gets taught. Labelled at **0 / 40 / 85 / 100** so the
row axis reads visibly as a zoom of its upper portion, plus a `--muted`
lifetime tick.

**The rail's zone tints are dropped.** With the mix bar promoted into the hero
card (§4.3), two adjacent tinted horizontal bars would read as duplicates.
Rail = neutral track + ticks + whisker + marker.

### 4.3 Mix bar — promoted into the hero

This is what makes the single `AGG_HE` word honest: `78` + `שיפוט טוב` +
`61% ב־85 ומעלה · 8% מתחת ל־40` discloses the composition a mean hides, which
was the bridge review's objection in §1.7. It also stays in each scenario
section, scoped per scenario.

Fixes to the existing `.band`: height 14px not 22px (a thick saturated
red/gold/green block is currently the loudest object on the page); `gap: 2px`
over a `--card` background as the separator, replacing the
`inset box-shadow` (a border drawn around marks is ink that isn't data); and
**no labels inside the segments** — one key line underneath carries swatch +
label + value together, replacing the 3-line legend and fixing the clipping
bug. A zero-count bin renders no segment at all.

Bins stay `≥85 / 40–84 / <40`, and are named consistently everywhere as
`מיטבי או קרוב` / `סטייה` / `טעות חמורה` (the current legend says `כשל`, which
is vague and collides with `BAND_HE`).

### 4.4 Sparkline — one series

Rolling window only. Padded dynamic domain `[min−5, max+5]` clamped to 0–100
with a **minimum span of 20 points**, so a stable player gets a flat line
rather than amplified noise. Solid 1px `--line` reference at **85** (not the
current dashed 50 — 85 is `REVIEW_MIN`, an actual threshold; 50 is not).
Endpoint dot with a `--card` ring, direct-labelled. No legend (one series
needs none), no `▨` glyph (unreliable on Android). `vector-effect:
non-scaling-stroke` so strokes are true CSS px under `width:100%`. LTR island,
`dir="ltr"` — time reads old→new left→right, matching the codebase's existing
convention for bridge diagrams. Absent below n=12.

### 4.5 Miss list — ordered by score

Sorting by `gradedCost` was proposed and **rejected by both reviews on the
second pass**: units differ by scenario (IMPs for bidding and IMP leads,
*tricks* for MP leads), so a mixed sort ranks 2.4 IMP against 0.7 tricks. The
panel score is the unit-free, stakes-normalised severity measure — it *is* the
intended cost ordering, done correctly.

- **Tier 1: 3 rows, ascending by score, restricted to the same last-50 window
  as the hero.** "Your worst *recent* decisions" is a review target; the
  all-time worst from six months ago is not.
- **Tier 2: full list, ascending by score, all time, cap 30**, with a
  two-button `.segctl` toggle `לפי חומרה | לפי זמן`. Default severity.
  Tie-break newest-first so the order is stable and fresh.
- `gradedCost` renders **with its unit** as row context, fixing the unitless
  `עלות ≈ 1.4`.
- `LIVE_IDS` / `בעיה שהוסרה` handling and `esc()` on every user-owned field
  are preserved exactly.

### 4.6 RTL / theme / a11y invariants

- **Magnitude fills grow from the inline-start** (right, in RTL). Time-series
  SVGs are LTR islands. Never mix the two within one component. This deletes
  `.catrow .dbar { direction: ltr; }`.
- Every Latin/numeric run inside Hebrew prose (`77–89`, `61%`, `IMP`, card
  names) wrapped in the existing `.ltr` class.
- **The hero numeral is `--fg` ink, never the band colour.** `--gold`
  (#EAB84C) on `--card` (#fff) is ~1.9:1 — an unreadable hero. Colour lives in
  the chip beside the number, using the existing contrast-checked
  `--on-win`/`--on-gold`/`--on-loss` pairs.
- Hero numeral sized in **`em`, not `px`**, so the app's existing 3-step text
  scaling works for free.
- Band identity is never colour-alone: the chip carries the Hebrew word, the
  mix bar carries a labelled key line, every row carries its integer.
- `role="img"` + a full-sentence `aria-label` on rail, sparkline and mix bar,
  each matching the visible text word-for-word (the current band's aria-label
  and visible legend use two different vocabularies).
- Every `<summary>` ≥ 44px; `<details>` gives `aria-expanded` free.
- **Every term that needs explaining is tap-to-explain** — see §4.8. The
  design review's original ruling here was "this dashboard ships no tooltips
  at all", justified as touch-first. That ruling is **overridden**: it
  conflated two different things. A *hover* tooltip is indeed unreachable on
  touch and must never gate a value — that part stands. But the app already
  has a touch-native **tap-to-explain** mechanism (`GLOSS` / `glossHtml` /
  `data-glosstext`, opening a `.glosscard` above the bottom nav, closed by a
  second tap, the X, or Escape), used throughout the problem pages for exactly
  this purpose. The dashboard must use it for every piece of professional
  jargon, consistently with those pages. The invariant that survives is
  narrower and still absolute: **no value is ever only available behind an
  interaction** — the gloss explains a term, it never hides a number.
- New colours are `color-mix()` against `--card`/`--fg`, both already themed,
  so **dark mode needs no parallel palette**. One dark-specific rule for
  `.dsec`'s border, mirroring the existing `.card` rule.
- `@media (forced-colors: active)` neutralises the decorative tints.

### 4.7 Terminology fixes

| current | fix | why |
|---|---|---|
| `שקלול מצ'פוינטס` | `שקלול מאצ'פוינטס` | misspelling (missing א) |
| `אפשרות מתה` | `אפשרות ללא סיכוי` | literal calque of "dead option"; means nothing in Hebrew bridge |
| `לא אופטימלית` | `נחותה מהמיטבית` | lone loanword in an otherwise Hebrew set |
| `רווח בר־סמך 95%` (body) | `הטווח הסביר לממוצע` | formally correct, opaque to a club player; keep the formal term in the gloss only |
| `כשל (0–39)` | `טעות חמורה (מתחת ל־40)` | vague, and collides with `BAND_HE` |
| `הנקודה החלשה שלך` | `מה הכי כדאי לחזק` | blunt/judgmental for a training app |
| `בעיות שנענו` | `בעיות שפתרת` | awkward passive |
| `ציון לאורך זמן` | `מגמת הציון` | loose |
| `הקלת שדה (המנוע נתן לבחירתך 34%)` | `רוב השחקנים טועים כאן באותה צורה — הציון מקל בהתאם (+3)` | invented term nobody knows |
| `לוח עתיר תנודה` | `לוח שבו הפערים גדולים ממילא` | stilted |
| `עלות ≈ 1.4` | `עלות ≈ 1.4 IMP` / `≈ 0.35 לקיחה` | **bug** — no unit, and the unit differs by scenario |

`מיטבי` is kept: not what Israeli players say at the table (they would say
*ההכרזה הנכונה*), but it is consistent across the app and already glossed.

### 4.8 Tap-to-explain inventory

Matching the problem pages: anything a club player cannot be assumed to know
is a `.gloss` button (`glossHtml(key, label)`) or an `ⓘ` (`infoHtml(text)`)
that opens the explainer card on tap. The redesign introduces several concepts
the current `GLOSS` table has no entry for, so the table grows.

**Rules.** Gloss the term at its *first* visible occurrence in reading order,
not every occurrence — repeated `.gloss` buttons on one screen turn into
visual noise. The label inside the button is the normal Hebrew label, so a
user who already knows the term sees no jargon and no decoration beyond the
existing dotted affordance. Never gloss a bare number.

**Existing entries reused:** `panel` (the 0–100 score), `imp`, `mp`, `diff`,
`ben`, `dd`, `sd`.

**Entries to remove:** `streak` — the metric it documents is retired (§2.2).

**New entries:**

| key | label shown | explanation (verbatim) |
|---|---|---|
| `form` | `הטופס הנוכחי` | הציון הראשי מחושב על 50 ההחלטות האחרונות שלך בלבד (או על כל ההחלטות, אם פתרת פחות מ-50). כך הוא מגיב לשיפור בתוך שבוע, במקום להיתקע על ממוצע של כל הזמנים. |
| `ci` | `טווח סביר` | הציון מחושב על מדגם של החלטות, ולכן הוא אינו מדויק לחלוטין. הטווח מציין את התחום שבו סביר שנמצא הציון ה"אמיתי" שלך. טווח רחב = פתרת מעט בעיות. |
| `agg` | `דירוג השיפוט` | תיאור מילולי של הציון הממוצע שלך. הוא מתאר את איכות הבחירות שלך מול פתרון המנוע - ולא מול שחקנים אחרים. |
| `sig` | `שינוי מובהק` | הצגת חץ שיפור רק כאשר ההפרש גדול מהתנודה הטבעית של המדידה. הפרש קטן יכול לנבוע מהגרלת הבעיות בלבד, ולא משינוי אמיתי ביכולת. |
| `blunderfree` | `רצף נקי` | כמה בעיות פתרת ברצף בלי טעות חמורה (ציון מתחת ל-40). בקבוצות ובאימפים, הימנעות מתקלות היא מה שמנצח - החמצה קטנה נסלחת. |
| `mix` | `פילוח התשובות` | ממוצע לבדו מסתיר את ההרכב: 85 יכול להיות "תמיד קרוב למיטבי" או "מושלם לרוב, עם כמה תקלות". הפילוח מראה איזה מהשניים. |
| `scale40` | `הסולם מתחיל ב-40` | בגרפים של הפילוח לפי נושא הסולם מתחיל ב-40 ולא ב-0, כדי שההבדלים בין הנושאים יהיו נראים. הנקודה מסמנת את הציון והפס סביבה את הטווח הסביר. |
| `cost` | `מחיר הטעות` | כמה עלתה הבחירה שלך מול המיטבית - ב-IMP בהכרזה ובהובלת IMP, ובלקיחות בהובלת מאצ'פוינטס. מוצג רק על החלטות שבהן טעית. |
| `leadrank` | `דירוג ההובלה` | באיזה מקום דורגה ההובלה שלך מבין ההובלות האפשריות. בתחרות זוגות זה מה שקובע: הובלה שנייה-הכי-טובה עדיין מנצחת חלק מהאולם. |
| `weakspot` | `מה כדאי לחזק` | הנושא נבחר רק אם הציון בו נמוך מהממוצע שלך בשאר הנושאים ביותר ממה שניתן להסביר ברעש המדידה, ורק אם פתרת בו לפחות 12 בעיות. |
| `pattern` | `נטיות שחוזרות` | דפוסים שחוזרים בטעויות שלך - למשל נטייה להכריז גבוה מהמיטבי. מוצגים רק כשהדפוס חוזר על עצמו מספר פעמים ובאופן חד-צדדי. |
| `coverage` | `היקף התרגול` | כמה בעיות פתרת בכל נושא, מול מה שקיים במאגר. נושא שכמעט לא תרגלת אינו "חולשה" - פשוט אין עליו מספיק נתונים. |
| `firstonly` | `ניסיון ראשון` | הלוח מציג רק את התשובה הראשונה שלך לכל בעיה. תשובה שנייה לבעיה שראית את פתרונה היא זכירה, לא שיפוט. |

Placement, so the coverage is deliberate rather than accidental:

| where | glossed |
|---|---|
| hero numeral caption | `form`, `ci`, `firstonly` |
| `AGG_HE` chip | `agg` |
| trend caption | `sig` |
| blunder-free run line | `blunderfree` |
| mix-bar key line | `mix` |
| difficulty-mix clause | `diff` (existing) |
| first breakdown in a scenario | `scale40` |
| `המספרים המלאים` body | `cost`, `imp` / `mp` (existing) |
| lead rank line | `leadrank` |
| `.nextup` heading | `weakspot` |
| `נטיות שחוזרות` summary | `pattern` |
| zero/low-n coverage rows | `coverage` |

### 4.9 Rewritten footnote (body of `איך מחושב הציון`)

> כל החלטה מקבלת ציון 0–100 לפי כמה היא רחוקה מהפעולה המיטבית.
> **100** — הפעולה המיטבית (או שקולה לה). **0** — אפשרות שלא ניצחה באף חלוקה.
> הפער נמדד ב־IMP בהכרזה ובהובלת IMP, ובלקיחות בהובלת MP, בסולם המותאם לתנודת הלוח.
> הלוח מציג **ניסיון ראשון בלבד**. ממוצע מוצג רק מ־5 החלטות ומעלה.

Plus the 5-band reference table with a swatch per row — the one place the full
`BAND_HE` vocabulary lives, and where the `imp` / `panel` glosses move to.

---

## 5. Implementation order

1. Shared-layer fixes: `meanCI` floors, `bidHeight`, `.stars` CSS scope,
   `GLOSS.streak` → `blunderfree`, and the rest of the §4.8 `GLOSS` entries
   (they are shared-layer, so the problem pages can reuse any of them later).
2. Aggregation layer: window/hero stats, `AGG_HE`, blunder-free run,
   coverage map from `fetchIndex()`, difficulty mix (null-guarded — omit the
   line if >20% of the window has no `difficultyLevel`).
3. Pattern detectors in the order the bridge review recommended: pass bias
   (exact) → wrong-suit/card → over-under-bid → difficulty cliff.
4. New `weakArea` per §2.6 with its fallback ladder.
5. Components: hero, nextup, tocheck, `.dsec`/`.dsub`, dot rows, mix bar,
   sparkline, miss list — each wired to its §4.8 gloss as it is built, not in
   a sweep afterwards (a later sweep is how terms get missed).
6. Delete: tabs, statgrid, per-card drilldown, suit rows, cumulative path,
   old `costBand`, dead CSS.
7. Tests, then screenshots in both themes.

## 6. Test impact

Existing assertions that must keep passing: no English in visible text;
`firstMs`/`firstTs` ordering; `LIVE_IDS` + `בעיה שהוסרה`; `esc()` on
`chosenCall`/`acceptedSet`/`outcomeClass` in the miss-list segment; `meanCI`
and `ציון ממוצע` present; `תרגל ${SESSION_SIZE} כאלה`; `{retry: true}`;
`glossHtml`; inline scripts parse under `node --check`.

Assertions that must be **updated** because they pin the old design, with the
intent preserved rather than dropped:

- `test_ui_fixes_round2.py::test_ui1_dashboard_footnote_uses_on_felt_tone`
  pins `#dash .dtab > .footnote` — `.dtab` disappears with the tabs. The
  *intent* (loose text on the felt must use the on-felt tone, or it is
  dark-green-on-green and unreadable in light mode) still holds and gets
  re-pinned against the new selector.
- `test_bug_constants_deadcode.py::test_no_inline_threshold_literals_in_pages`
  — keep deriving thresholds from the named constants; no new bare literals.

New tests to add: `AGG_HE` bucket boundaries; `meanCI` floors (the sd=0 case
explicitly); `bidHeight` returns `null` for `P`/`X`/`XX` and orders contract
bids correctly; wrong-suit uses `acceptedSet` not `recommendedLead`; every
`<details>` has a non-empty `.dsum`; no `--accent` used as a data fill inside
`#dash`; the deleted blocks are actually gone.

Gloss coverage gets its own test, because this is the class of thing that
silently rots: **every key referenced by a `data-gloss` in `_DASHBOARD_JS` must
exist in `GLOSS`**, and every new key in §4.8 must be referenced somewhere in
the dashboard. A `data-gloss` pointing at a missing key fails silently today —
the click handler looks up `GLOSS[key]`, finds nothing, and simply does not
open the card, so a typo is invisible in manual testing. Pin both directions.
