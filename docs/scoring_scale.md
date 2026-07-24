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
* **0** is reserved for dead bidding options (`best_share < 0.5%`).
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
