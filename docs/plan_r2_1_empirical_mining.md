# Plan R2-1 — Empirical Dilemma Mining (high-level, v1)

Status: high-level plan for expert review. Date: 2026-07-16.
Parent: `docs/problem_quality_concepts_round2.md` §R2-1.

## What it is, in plain language

Deal random boards and let **measurement**, not anyone's opinion, decide
whether a spot is a problem. A hero hand at a decision point qualifies
when two things are true across the thousands of layouts the concealed
hands could be:

1. **No call dominates** — there is no single call that is at least as
   good as every alternative on (almost) every layout; and
2. **The unseen cards matter a lot** — which call is best genuinely
   changes from layout to layout, with real IMPs at stake.

A clear 1NT opening or an automatic Stayman hand fails test 2 instantly:
one call is best essentially everywhere. The detector computes only in
tricks and IMPs — it has no system vocabulary, so it cannot confuse "a
different system" with "a dilemma."

## The two metrics, precisely

Over layouts `L` consistent with the decision context, with `S(c, l)` =
IMP-scored outcome of call `c` on layout `l` (via continuation projection
+ DD, the existing stack):

- **Dominance score** `dom(c) = fraction of l where S(c,l) ≥ S(c',l) − ε
  for all c'`. If `max_c dom(c) ≥ D_hi` (e.g., 0.90), the spot is an
  auto-bid → discard.
- **Value of hidden information**
  `EVPI = E_l[max_c S(c,l)] − max_c E_l[S(c,l)]`.
  Below `V_lo` (in IMPs) → the decision doesn't matter → discard.
  The kept band is: no dominant call, EVPI above threshold, and the
  existing INV7 CI discipline on the pairwise comparisons.

- **Option derivation**: offer exactly the calls that are strictly best on
  at least `x%` of layouts (e.g., 10%), capped by the schema's 2–5. A call
  best on ~0% of layouts can never be offered — the filler-Pass class dies
  empirically; a call best on 30% of layouts cannot be omitted — the
  missing-2C class dies empirically.

## Pipeline

```
context catalogue (shallow stems, owner's card only)
   → random deal (existing NumPy dealer)
   → cheap prefilter (hand-feature heuristics; skip obvious auto-bids)
   → low-n probe sim (~100 layouts, DD)     — kills 90% cheaply
   → full sim (existing n≈800, INV1–8)      — dominance + EVPI + CI gates
   → finalization (meanings from card rules; explanation from the metric
     evidence: "best call varies: 3S wins on 41% of layouts, X on 33%…")
   → hard shell V1–V7 → pool
```

## The decision context: shallow, standardized, yours

Mining needs an auction to define "consistent layouts." To keep stems
beyond reproach, v1 mines only **shallow contexts** (0–2 non-pass calls
before hero) drawn from a fixed catalogue expressed in the owner's card:
opening decisions, direct-seat actions over an opening, responses to
partner's opening ± overcall, balancing-seat decisions. Concealed-hand
meanings come from the existing semantics rules for those short contexts.
Deep competitive stems are out of scope for the miner (they belong to
R2-5 families, where the stem is authored and reviewed).

## The honest weak layer: continuations

`S(c, l)` requires deciding what happens *after* each candidate call on
each layout — the projection trees. This plan inherits the existing
projection machinery + V6 realism validation, and the known limitation
that projection quality bounds verdict quality. Two mitigations:
1. shallow contexts have short, well-understood continuations (the trees
   are small and reviewable);
2. the dominance/EVPI *detection* decision is more robust to projection
   error than a 0.3-IMP verdict is — detection needs only "does the best
   call vary materially," not a precise margin. Verdict publication keeps
   the full INV5/INV7 discipline as today.

## Calibration gate before anything ships (P0)

Run the two metrics on the existing corpus **before** mining anything:

- owner-flagged non-problems (e50006-19, b2-000273ee) must score below
  the keep-band;
- the b1 problems the panel rated SOUND (e50006-24, e50018-10) must score
  inside it;
- a hand-picked set of known auto-bids (routine 1NT openings, textbook
  Stayman, a 9-playing-trick 4♠ preempt) must be rejected by dominance.

This is a falsifiable, cheap experiment on machinery that already exists.
If the metrics cannot separate these, the concept dies in P0 for the cost
of a week — that is the point of the gate.

## Phases

- **P0 — Metric spike (~3–5 days).** Implement dominance + EVPI over the
  existing sim outputs; run the calibration gate above. No new dealing, no
  new contexts. Gate: clean separation on the calibration set.
- **P1 — Shallow-context miner (~1 week).** Context catalogue (≈10
  shallow contexts), prefilter, staged probe/full sim, mining loop.
  Gate: owner rubric Q1–Q5 (`core_problem_method.md` §6) on a 10-problem
  batch; track yield (problems kept per 1000 deals) and CPU per keep.
- **P2 — Option derivation + explanations from evidence (~1 week).**
  The x%-of-layouts option rule; explanation template quoting the
  variability evidence; publishing path through the hard shell.
  Gate: owner rubric, Phase-2 targets.
- **P3 — Breadth.** More contexts, balancing/competitive families where
  semantics rules exist; feed high-scoring spots to R2-5 as family
  candidates.

## Risks

1. **Projection realism bounds everything** (inherited, §above) —
   shallow-context restriction is the containment.
2. **DD fog on penalty/doubled partscores** — existing correction table +
   fog labels; contexts whose keep-band spots are mostly fog-flagged get
   dropped from the catalogue.
3. **Compute per kept problem** — staged sims + prefilters; measure in P1;
   if yield is poor, R2-4's breeding is the designed escape hatch (same
   metrics as fitness terms).
4. **EVPI threshold tuning** — one global `V_lo` may not fit all contexts
   (game decisions swing more than partscore ones); per-context thresholds
   normalized by stake size, set during P1.
5. **Metric gaming by artifacts** — a projection bug that randomizes
   outcomes *looks* like high EVPI; the V6 tree validation and the P0
   calibration set are the guards.

## What the owner gets

A generator whose "is this a problem?" judgment is a measurement he can
audit (every published problem carries its dominance table and EVPI), no
external dependencies, and a P0 experiment that proves or kills the idea
against his own past flags before any new infrastructure is built.
