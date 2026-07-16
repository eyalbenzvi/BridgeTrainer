# Plan R2-1 — Empirical Dilemma Mining (high-level, v2 — post panel round 1)

Status: v2, revised per expert review (`docs/panel/plans_round1.md`).
Date: 2026-07-16. Parent: `docs/problem_quality_concepts_round2.md` §R2-1.

## What it is, in plain language

Deal random boards and let **measurement**, not anyone's opinion, decide
whether a spot is a problem. A hero hand at a decision point qualifies
when the simulation says the choice is genuinely close between real
candidate calls, the stakes are material, and the closeness survives
statistical scrutiny.

v1 of this plan proposed "no dominant call + high value of hidden
information" as the dilemma definition. The expert panel showed both
metrics keep **automatic** bids: a routine 4♠ game acceptance fails on
25% of layouts, so nothing dominates and clairvoyance is worth ~2 IMPs —
yet no player thinks for a second. What actually separates auto-bids from
dilemmas is the **gap between the top candidates' expected scores**. v2
reassigns the metric roles accordingly.

## The metrics, with their corrected roles

Over layouts `L` consistent with the context, `S(c, l)` = corrected
IMP-scored outcome of candidate `c` on layout `l` (continuations + DD,
existing stack):

1. **Dilemma detector — top-2 EV gap**: the spot is a candidate problem
   iff the two best calls' expected scores are within a per-context
   closeness band AND the gap's CI makes the ranking genuinely uncertain
   or small (the existing ≤3-IMP closeness filter + INV7 discipline,
   promoted from publish-gate to *the detector*).
2. **Materiality floor — EVPI**: `E_l[max_c S(c,l)] − max_c E_l[S(c,l)]`
   must exceed a per-context, stake-normalized floor — this only filters
   out decisions where nothing is at stake; it never *keeps* a spot by
   itself. Because a max over noisy estimates is biased upward
   (winner's curse, growing with candidate count), EVPI is used only
   with: (a) per-context noise-floor subtraction calibrated on known
   auto-bids, (b) split-half estimation (pick per-layout winners on one
   half of rollouts, score them on the other), (c) a mandatory
   fresh-seed confirmation re-sim before any spot is kept (cheap under
   INV4/INV6).
3. **Discard rules — dominance**: one call ε-dominating on ≥`D_hi` of
   layouts discards the spot as one-sided; near-identical outcome vectors
   between two calls collapse them as route-equivalent (transpositions).
   ε and all thresholds are **stake-normalized per context** — partscore
   IMP quanta and game-swing quanta cannot share one ε.
4. **Anti-lottery rule**: a close top-2 gap with 4+ mutually non-dominated
   candidates and near-uniform per-layout winners — defined as no call
   being clairvoyantly best on even 40% of layouts — is a *pure guess*
   (the b2-0135277e "teaches nothing" class) → discard, per rubric Q3.
   (This 40% uniformity threshold is distributional, sits outside the
   stake-normalization rule, and is pre-registered in P0 like the rest.)

Honest knob count: δ, ε, `D_hi`, `V_lo`, x%, the closeness band, the
uniformity threshold, the EVPI noise floor — **eight**, of which five
derive from the single stake-normalization rule and three (x%,
uniformity, noise floor) are pre-registered independently in P0.

## Candidate universe and continuations — the honest system statement

v1 claimed "no system vocabulary is ever consulted." Retracted: system
enters through the semantics rules that define consistent layouts and
through every continuation tree. The honest formulation of the
system-safety constraint is **one system — the owner's card** — a
closed world with no cross-table ambiguity, which is what the owner's
constraint actually requires.

Consequence made explicit: each mined context needs a **per-context
candidate list and continuation trees authored on the owner's card,
once, reviewed once** — including the conventional calls the old bot
lacked (Stayman, transfers, 2♣) wherever a context can involve them.
Without a continuation model for 2♣, `S(2♣, l)` does not exist and the
missing-Stayman failure is untestable, let alone fixed. Budget: ~10
contexts × up to ~8 candidates; this is the plan's main authoring cost
and is T-compatible (once, versioned, reviewable).

## Option derivation (v2 rule)

- **Base**: all candidates within δ (per-context) of the EV-best call in
  expectation — the calls a result-oriented expert is actually choosing
  among. The EV-best call is always included.
- **Union**: calls strictly best (within ε) on ≥ x% of layouts — the
  clairvoyant's picks — *filtered by card legality/forcing status*: Pass
  is never offered in a forcing auction; no call is offered that the card
  marks unavailable. (v1's pure x% rule both resurrected absurd
  clairvoyant Passes and excluded flexible "master bids" like negative
  doubles that tie rather than win — the δ-EV base catches those.)
- Cap per schema (2–5); overflow → collapse route-equivalents, else
  discard the spot as too wide.

## Context catalogue (v2 — trimmed and exclusion-listed)

**In scope (v1.0)**: direct-seat actions over openings and preempts;
responder's decisions after interference (negative-double territory);
raise decisions after partner's opening + overcall; balancing over weak
twos.

Two boundary rules (round-2 verification notes), stated precisely:

- **The invite quarantine applies to candidates, not just contexts.**
  Inside kept raise contexts, any spot whose top-2 comparison is
  invite-vs-game (3♠ vs 4♠) is quarantined under the same rule as
  invitational sequences until the correction table is validated for it;
  the P0 calibration set includes a labeled invite-in-competition spot to
  measure exactly this.
- **Doubled continuations are never pruned from trees** (a censored
  outcome space would undervalue every X). The penalty-bias exclusion is
  a *context* filter, applied empirically: if more than a threshold share
  of a context's layouts terminate in doubled contracts (e.g., reopening
  doubles with frequent penalty-pass conversions), the context is dropped
  and reported — measured by the sim itself, not guessed.

**Out of scope, pre-declared**:
- **Opening decisions** — dropped entirely: the metric is blind to
  descriptive/systemic value (the panel showed e50006-19's clear 1NT
  plausibly lands *in* the keep band: per-layout winners flip constantly
  on small margins), and the Pass continuation is the whole board's
  auction — the projection burden is maximal exactly where the metric is
  weakest.
- **Penalty/doubled-terminal contexts and sacrifice/5-level decisions** —
  DD's perfect defense biases these *directionally* (phantom +500s,
  systematic Pass bias), not noisily; the INV5 scalar correction cannot
  fix a comparative bias between a doubled contract and a partscore.
- **Invitational sequences** — quarantined until validated against the
  correction table (DD never misguesses thin games and information
  transfer is free, so blast systematically beats invite under DD).

**Coverage statement (owner-acknowledged trade)**: this catalogue reaches
roughly **a quarter to a third** of a serious 2/1 player's real dilemma
space. Deep competitive battles, game tries, sit-or-pull, forcing-pass
positions and slam auctions are deep-stem by nature and belong to R2-5
authored families. The miner is a scout, not the whole army.

## Pipeline

```
context catalogue (owner's card; per-context candidates + trees, authored once)
   → random deal → cheap prefilter → low-n probe sim (~100 layouts)
   → full sim (n≈800, INV1–8) → detector: top-2 EV gap in closeness band
   → floors: EVPI (de-biased) ≥ V_lo; anti-lottery; dominance discards
   → fresh-seed confirmation re-sim
   → finalization: meanings from card; explanation = bridge rationale per
     option (card meanings, why each wins/loses) + the dominance/EVPI
     table as supporting evidence — never the frequency table alone
   → hard shell V1–V7 → pool
     (publish priority = the R2-3 oracle's human-split score where one
      exists; spots without a score publish neutrally — absence of a
      score is never treated as a low score)
```

## P0 — the redesigned calibration gate

v1's gate (a handful of spots, thresholds free to move) could pass by
tuning. v2:

- **Pre-registered thresholds**: δ, ε, `D_hi`, `V_lo`, per-context
  normalizations fixed *before* scoring the calibration set.
- **≥20 labeled spots** spanning genres: owner-flagged non-problems;
  b1-panel-endorsed problems (e50006-24, e50018-10); routine game
  acceptances and textbook preempts (labeled auto-bid); hand-built
  card-legal genuine dilemmas; known pure guesses; and one
  flexible-double spot *expected to stress the blind spot* — measured,
  not hidden.
- **Held-out half**: thresholds tuned on one half must separate the other.
- **Rank correlation** with labels required, not just binary separation.
- **Re-simulation, not re-scoring**: b2-000273ee and f50022-21 are re-run
  with corrected candidate sets and the new continuation trees — scoring
  stale outputs over the wrong candidates proves nothing.
- Expected result stated up front: e50006-19 *fails* the naive v1 metrics;
  the v2 detector must reject it via the opening-context exclusion and
  the auto-bid labels. If the detector cannot rank the labeled set, the
  concept dies in P0 at census cost.

## Phases

- **P0 — Metric spike + calibration (~1 week).** Detector/floors/discards
  over the sim stack; candidate lists + trees for the 3–4 contexts the
  calibration set needs; the gate above.
- **P1 — Miner (~1–1.5 weeks).** Catalogue contexts + remaining trees;
  staged sims; yield + CPU-per-keep instrumentation. Gate: owner rubric
  Q1–Q5 on a 10-problem batch.
- **P2 — Options + explanations (~1 week).** v2 option rule; explanation
  contract (bridge rationale + evidence table). Gate: owner rubric.
- **P3 — Breadth + handoff.** Additional contexts inside the exclusion
  rules; high-scoring spots proposed to R2-5 as family candidates.

## Risks

1. **Continuation realism bounds everything** (inherited): contained by
   shallow contexts, the exclusion list, and trees-reviewed-once; the
   fresh-seed re-sim kills the noisiest survivors.
2. **Winner's-curse EVPI**: addressed structurally (noise floor,
   split-half, confirmation re-sim) — kept in the risk list because the
   floor calibration itself can drift.
3. **Compute per kept problem**: staged sims; measure in P1; R2-4
   breeding is the designed escape hatch.
4. **Threshold sprawl** (now ~6 knobs): all pre-registered in P0, all
   per-context values derived from one stake-normalization rule, not
   hand-set per context.
5. **Catalogue narrowness**: stated coverage fraction; R2-5 carries the
   deep-stem genres.

## What the owner gets

A generator whose "is this a problem?" judgment is a measurement he can
audit, computed entirely inside his own system's closed world, with a
falsifiable pre-registered P0 experiment — and an honest statement of
which third of the dilemma space it covers.
