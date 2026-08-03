# Panel score: the 0–100 graded answer scale

Replaces the binary correct/incorrect verdict with a Master-Solvers-Club
style 0–100 "panel score" per answer. The score measures the ANSWER, not
the question (difficulty stays a property of the problem), is continuous
in the middle, and is differentiated per training scenario.

## Why binary failed

* A 0.4 IMP miss counted the same as a 4 IMP blunder.
* A gap smaller than the sample CI counted as a full failure (punishing
  double-dummy noise, not judgment).
* A part-score nudge and a slam swing were scored on the same scale.
* A dead option (never won a single simulated layout) counted the same
  as a reasonable alternative.

## The shared skeleton

For a chosen option that is neither accepted-best nor dead:

```
score = clamp( 95 / (1 + (c_eff / tau)^1.6) + leniency , 1, 94 )
```

* **100** is reserved for the accepted set (the winner, plus statistical
  ties the verdict machinery itself could not separate: legacy toss-up
  sets, equal-trick lead groups). What the engine cannot distinguish, the
  score must not distinguish. This holds BELOW the accepted set too: two
  leads the active mode ranks identically (same leading metric to display
  precision) always get the same score — see the tie invariant below.
* **0** is reserved for dead bidding options (`best_share < 0.5%`, where
  "winning a layout" INCLUDES tying the per-layout best result — a call
  that reaches the same winning contract as another option won those
  layouts too, even if it is never the unique winner). Records published
  under the old strictly-unique rule carried stale flags (an option that
  merely tied another call's winning result scored 0); those were removed
  from Firestore by the one-off `trainer pool backfill-dead` migration
  (2026-07-25), so the client trusts `verdict.dead_options` as stored.
* **95 cap** — a mistake inside the noise band never quite equals best.
* **tau** — the cost at which the base score crosses ~47. This is the
  per-scenario knob (below).
* **exponent 1.6** — a soft shoulder: small deviations are nearly free,
  then the curve drops fast.
* **leniency** — up to +6 x the engine policy weight of the chosen
  action: the trap the whole field falls into loses a few points less
  than the call nobody considers (the MSC "popular but wrong gets 60"
  tradition). Never lifts a score above 94. For leads the policy weight
  is the tie-GROUP's total (see the tie invariant below), not a single
  card's, so interchangeable leads share it.

## Per-scenario differentiation

### Bidding (unit: IMP)

* **Uncertainty haircut**: `c_eff = max(0, cost - ci/2)` using the
  option's stored 95% CI. Half the noise margin is forgiven; a gap that
  is mostly CI is mostly forgiven.
* **Stakes stretch** — this is where the 10 problem types differentiate
  automatically. Every record carries `quality.stakes` (mean absolute
  per-layout IMP swing between the top-2 calls). The scale stretches
  with it:

  ```
  tau = 2.0 IMP x clamp(stakes / 2.5, 0.8, 1.8)
  ```

  Slam tries / game decisions (high stakes) are judged on a wide scale —
  2 IMP there is a light deviation; part-score battles and preempts (low
  stakes) are judged on a tight one — 2 IMP there is the whole battle.
  The score measures judgment quality relative to what was on the table.
* Dead option → 0. Legacy authored records with `toss_up_set` → the
  whole set scores 100.

### Opening leads, MP mode (unit: defensive tricks)

* Much tighter base scale: `tau = 0.6 tricks` — at matchpoints one trick
  flips a board from 30% to 70%.
* **Rank blend**: matchpoints is frequency scoring, so the final base is
  `0.65 x cost curve + 0.35 x rank curve`, where the rank curve is
  `95 x (distinct-value groups worse than yours) / (groups - 1)`. The
  second-best lead of five keeps its dignity even when the trick gap is
  wide — in a matchpoint field it still beats most of the room.
* No CI haircut (per-card CIs are not published; ties already collapse
  into the accepted set at forge time via TIE_EPS).
* **The score-domain test** (below) — the average trick count alone never
  certifies a tie, and never sets the charged gap on its own.

### The MP score-domain test

The average number of defensive tricks cannot see WHERE those tricks
fall. Two leads can average the same number and still produce very
different results: one takes its tricks while the contract is going down,
the other only after it is home. So an average-trick tie is not by itself
proof that two leads are interchangeable — and grading it as one handed
100 to a materially worse lead:

> `lead1-19fa8ed5599` (3NT-E, MP): ♥K averages 3.480 defensive tricks
> against a spade spot's 3.482 — a 0.002 "tie", well inside TIE_EPS —
> yet beats the contract on 28% of the layouts instead of 37%, averages
> 37 duplicate points less, and is **0.90 IMP** behind on the same
> evidence. It scored 100; it now scores 75.

Every mode-aware lead record already carries the score domain per card
(`exp_imps`, against the board's own Butler datum), so MP consults it:

* **Accepted (100)** = tied on the trick average **and** within
  `TIE_EPS_MP_SCORE` (0.05 IMP — the IMP mode's own "indistinguishable"
  line, reused rather than reinvented) of the MP **recommendation** in the
  score domain. The recommendation is the anchor, so it is always in its
  own accepted set, and a lead that is *better* than it in the score
  domain is never dropped for being different.
* **Interchangeable** — the tie key behind the rank blend and the field
  leniency group — is equality on **both** metrics at display precision.
  The tie invariant below is unchanged in spirit and gains its converse:
  what the engine *can* distinguish, the score must not merge.
* **The charged gap** is the worse of the two yardsticks: the trick gap,
  and the score-domain gap put on the trick scale by the two modes' taus
  (`x 0.6/1.75`). Otherwise a lead that costs most of an IMP would be
  charged 0.00 tricks. When the score domain is the binding one, the
  Hebrew breakdown line says so (`פער 0.90 IMP בתוצאה (0.00 לקיחות)`)
  rather than claiming a trick gap that isn't there.

IMP mode already ranks and grades in the score domain, so none of this
touches it — measured over the whole published pool, not one IMP-mode
score moves.

One policy, three call sites, all reading the same stored aggregates:
`scoring/lead_metrics.mp_score_domain_tie` (forge-time accepted set, and
the `trainer pool backfill-mp-ties` migration), and `btLeadAccepted`
(`_SCORE_JS`), which every client path — the scorer, `gradeLead`, the lead
page's green cards — now shares, so `correct` can never disagree with
`score`.

Measured effect on the published pool (2794 lead problems, all 13 cards
each, MP mode):

| | before | after |
|---|---|---|
| cards accepted (score 100) | 7123 | 6168 (-955, in 453 problems) |
| mean score, all cards | 65.2 | 61.7 |
| mean score, non-accepted | 56.7 | 53.9 |
| field-weighted¹ share scoring >= 65 | 72.9% | 67.7% |
| field-weighted¹ share scoring < 40 | 5.1% | 7.8% |

¹ weighted by BEN's opening-lead policy — i.e. over the leads a human
plausibly makes, which is the population the 50-85 calibration target
talks about.

**Production run (2026-08-03).** `trainer pool backfill-mp-ties` dropped
955 leads from the MP accepted set of 453 of the 2794 published lead
problems (4493 docs); a second run reports 0, and the Python migration and
the client's `btLeadAccepted` agree on all 2794 records. `trainer pool
regrade-attempts` then rewrote 37 of 380 stored attempts (314 already
current, 29 on deleted problems left as-is), and likewise re-reports 0.
The reference board `lead1-19fa8ed5599` now accepts only the five spade
spots; ♥K/♥Q/♥J score 75 with the breakdown line
`פער 0.90 IMP בתוצאה (0.00 לקיחות) · מדורגת 2 מתוך 6 · +3 הקלת שדה`.

Deliberately NOT migrated: each affected board's stored `difficulty` /
`quality.trap`, which the narrowed accepted set would also move (BEN's
favourite is now outside the answer on some of them, i.e. a trap). That is
a property of the PROBLEM, not of the answer, it feeds the index and the
user's difficulty filters, and re-levelling the pool is its own change.
New boards get it right at forge time. `explanations.cards` is likewise
left alone — producer-side data the client never reads.

### Opening leads, IMP mode (unit: IMPs)

* `tau = 1.75 IMP` — slightly tighter than bidding: a lead is final,
  there is no later auction to recover.
* Pure magnitude, no rank blend — at IMPs distance is everything.
* Vulnerability is already priced into `exp_imps`, so the score inherits
  it for free.
* Legacy tricks-only records are graded as MP (matching gradeLead).

### Tie invariant (both lead modes)

Cards the active mode ranks identically — same leading metric (expected
IMPs / defensive tricks) to display precision — are interchangeable leads
and MUST receive the same panel score. Every score input is therefore a
property of the tie-GROUP, not the individual card:

* the gap is charged on the *rounded* leading metric, so equal-ranked
  cards share one cost and hence one base (and, in MP, one rank);
* field leniency uses the group's TOTAL policy weight (the sum of the
  interchangeable cards' BEN softmax — the field's probability of finding
  that single idea) rather than the per-card softmax, which previously
  split otherwise-identical cards by a few points (e.g. two spades tied at
  +0.27 IMP scoring 86 vs 83).

## Display bands

| score | band key | Hebrew label |
|---|---|---|
| 100 | best | מיטבי |
| 85–99 | near | כמעט מיטבי |
| 65–84 | minor | סטייה קלה |
| 40–64 | error | טעות |
| 1–39 | blunder | טעות חמורה |
| 0 | dead | אפשרות מתה |

Colors: best/near ride the win green, minor the gold, error/blunder/dead
the loss red.

## UX plan (per screen)

* **Verdict (bidding + lead)**: headline leads with a score chip
  (`ציון 82`) + band label; the old ✓/✗ line becomes the second clause
  ("עדיף היה ..."). A transparency line under the headline decomposes
  the score in Hebrew: measured gap, proven gap after the haircut, the
  board's stakes stretch, field leniency. The chosen candidate button
  colors by band (green ≥85 via accepted, gold 65–84, red below).
* **Session ribbon**: average score ("ממוצע 78") instead of a correct
  count; the per-problem trail stores each score.
* **Session summary (home)**: average score + review links for every
  answer under 85, each with its score.
* **Home stats**: average score bar over answered problems in the
  current selection.
* **Dashboard**: overall average score (95% CI on the mean) replaces
  first-attempt accuracy; the trend chart plots mean score over time;
  the per-type / per-difficulty / per-suit rows become mean-score bars;
  the distribution band groups score ≥85 / 40–84 / <40; "recent
  mistakes" lists everything under 85 with its score. Streak stays
  "consecutive best answers" (score 100).

## Storage & backward compatibility

* New attempts store `score` (int 0–100) next to the existing fields
  (`correct`, `gradedCost`, `outcomeClass` are unchanged — dashboards
  and Firestore rules keep working, and `correct` still means "in the
  accepted set").
* Old attempts carry no score: `btScoreOfAttempt` recomputes an
  approximate score client-side from `gradedCost` + `outcomeClass`
  (base curve only, default tau — no haircut / stakes / leniency, which
  need the problem doc). The dashboard therefore never resets.
* Replays recompute the full score + breakdown from the problem doc
  (`btScoreBidding` / `btScoreLead` are pure functions of it).

## Code layout

* `_SCORE_JS` (webapp.py): the pure scoring module — constants, curve,
  `btScoreBidding`, `btScoreLead`, `btScoreOfAttempt`, `btBandOf`,
  Hebrew band labels, breakdown-line builder. Embedded at the top of
  `_SHARED_JS`, so every page (and the classic-script → module boundary)
  sees it; unit-tested by running the extracted string under node
  (tests/test_scoring_scale.py).
* `web/bt-firebase.js`: `gradeBidding` / `gradeLead` attach
  `score` via `window.btScoreBidding` / `window.btScoreLead` (inline
  classic scripts run before the deferred module, so the functions exist
  by grade time; guarded anyway).
* Calibration: base taus follow the forge gates (GAP_MAX 2.5,
  STAKES_MIN 0.5, CI_MAX 1.5); revisit against the live pool's cost
  distribution if bands skew (most plausible human errors should land
  50–85).
