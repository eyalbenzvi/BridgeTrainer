# Expert panel — R2-1 / R2-3 / R2-5 plans v1, round 1 (2026-07-16)

Three independent bridge-expert reviewers (one per plan) over the v1
plans (commit c47e315). All three verdicts: **FLAWED** — each with a
concrete repair path, applied in the v2 plans.

## R2-1 Empirical dilemma mining — FLAWED

- **Metric roles reversed (blocker).** EVPI + no-dominance keeps
  *automatic* bids: a routine 4♠ acceptance over a limit raise fails on
  ~25% of layouts → no dominance, EVPI ≈ 2 IMPs → keep-band. The real
  auto-bid/dilemma separator is the top-2 *expected-score* gap (the
  existing ≤3-IMP + INV7 machinery). The plan's own calibration list
  mis-predicted itself: a 9-trick 4♠ preempt would NOT be rejected by
  dominance.
- **Poster-child contradicted by the repo (blocker).** b3's own record of
  e50006-19 shows 1NT-vs-1♦ as a half-IMP toss-up with flipping
  per-layout winners — the clear 1NT plausibly lands *inside* the v1
  keep band. Cause: the metric is blind to descriptive/systemic value;
  opening decisions also make the Pass-continuation the whole board.
  → opening contexts dropped from v1 scope.
- **Candidate universe unspecified (blocker).** Without authored
  Stayman/transfer/2♣ continuation trees, `S(2♣,l)` does not exist — the
  missing-2♣ kill-claim was untestable. "No system vocabulary" retracted;
  honest form: one system, the owner's card.
- **Option rule backwards at both ends (major).** "Strictly best on ≥x%"
  resurrects clairvoyant Passes (incl. passes of forcing bids) and
  excludes never-strictly-best master bids (negative doubles). → δ-EV
  band ∪ x%-rule, EV-best always included, forcing/legality filter.
- **EVPI winner's curse (major)** — max over noisy estimates selects
  where the projection machinery is confused → noise-floor subtraction,
  split-half, fresh-seed confirmation re-sim.
- **Invisible dilemmas (major)** — ε-dominance kills "small edge vs rare
  disaster" classics (3NT vs 5♦: ties count as dominance); global
  thresholds kill partscore genres → stake-normalized per context;
  anti-lottery rule added for 4-way guesses.
- **DD directional bias (major)** — penalty/doubled, sacrifice/5-level,
  invitational genres distorted, not noisy → pre-declared exclusions.
- **P0 too weak (major)** — few points, free thresholds → pre-registered
  thresholds, ≥20 labeled spots, held-out half, rank correlation,
  re-simulation of flagged problems with corrected candidates.
- Coverage statement required: shallow catalogue ≈ 25–35% of real
  dilemma space; deep stems belong to R2-5.

## R2-3 Distilled field oracle — FLAWED

- **Feature-lift separator refuted (blocker).** Most system splits ARE
  feature-driven (strong-NT vs weak-NT flips p(1NT) exactly at the
  14/15-HCP boundary; Landy vs natural 2♣ swings with shape; strong club
  tracks HCP). A mixture of feature-deterministic policies is maximally
  feature-dependent — the test admits the disease it was built to
  exclude, including the plan's own cited b1 example. → population-aware
  separator: parse `pn|` pair identities (currently discarded), cluster
  pairs by policy; systemic = explained by cluster membership; judgment =
  entropy survives within same-method clusters. Alert data (`!`, `an|`)
  currently stripped by `_norm_call` must be retained.
- **Top-k options resurrect the token/meaning disease (blocker).** Drury
  2♣ read as natural clubs = e50012-13 generated at scale; owner-correct
  calls field-rare in mixed corpora vanish from top-k. → oracle never
  authors options.
- **Demotion (the principal change):** standalone generator → human-
  hardness *prior* for R2-1's nominations ("would strong players actually
  split here?" — the one signal DD cannot compute). In that role the
  remaining leakage misranks rather than fabricates.
- Other majors: per-instance meaning-conformance filtering of training
  rows (hero + stem calls) with drop-rate as the pollution measure,
  replacing the vacuous token-level guard; support gate on entropy
  (off-distribution predictions are flat → raw entropy maximizes exactly
  off-support); minability bar raised to ~10k conforming rows (2000 =
  census floor only), bootstrap CIs, two-rooms dependence; negative
  controls in P1 (Landy/multi/Drury contexts must be flagged systemic);
  P0 must include the harvest-layer work (`pn|`, alerts, event tier).

## R2-5 Problem compiler — FLAWED

- **Gate blind to off-menu best calls (blocker).** Dominance compares
  offered options only; a heart-void instance inside "10–12, 3 spades"
  makes an un-offered splinter the expert call and the gate passes it.
  → missing-option audit: enumerate legal + card-conventional calls per
  instance; screened-in un-offered call ⇒ reject/re-route.
- **Static option superset bridge-wrong across the class (blocker).**
  Stopper hands make 2NT live; 5-card minors make 3m live; shortness
  moves the hand to the splinter family; heart stacks make penalty
  treatments live. → conditional options (`live_when:` predicates,
  per-option trees) or subfamily splitting.
- **Centroid review ≠ corner validity (major).** Hero-conditional tree
  thresholds (`me_hcp >= 9`) mis-model edge heroes (e50023-20 disease).
  → family review over 8–12 compiled corner instances; cross-option
  consistency linter (b1 #6) and hero-HCP-only-predicate flag at compile
  time.
- **Instance heroes can contradict the stem (major).** A dealt "12–14
  opened 1♦" hand that any expert opens 1NT = fictional auction at
  instance level. → hero-stem validator (b1 #5) per instance;
  suit-quality bands in the class schema (b1 #4).
- **Layout-share gate is the wrong dilemma test (major).** → R2-1's
  corrected metrics (EV gap + stakes + CI); within-CI ⇒ toss-up; dead
  options greyed post-answer, never silently dropped.
- **Verdict-distribution page conflated two distributions (major).**
  Taught distribution must be pre-gate (post-gate understates the
  majority action and teaches a false prior); toss-up bucket; sampling
  caveat; hero-feature breakdowns.
- **Authoring economics understated 2–4× (major).** 1–2 days per family
  end-to-end; constructive/slam families 2–3×; P1 = 3–5 weeks calendar.
- **Suit-swap isomorphs cut (minor).** A legal swap must preserve rank
  order of every mentioned suit ⇒ identity only. Spot shuffles/honor
  jitter are ordinary class dealing.
- **Intra-family contradictions are the point only if attributed
  (minor).** Explanation = principle + instance feature delta;
  margin-calibrated vocabulary (b1 #18); twins presentation; penalty
  discount (b1 #12).

### Panelist's proposed starter catalogue (20 families, quota 60/25/15)

Competitive/raise (12): responder's raise structure after 1♠–(2♥) 10–12
with 3 trumps [conditional options required]; advancer over the
preemptive raise [= comp_3s_over_3h]; 3-over-3 push after both fits
(LAW vs wastage); direct seat over weak 2♠ [exists]; balancing after
1M–P–2M–P–P; 5-level over their save / forcing pass [exists]; marginal
1-level overcall at unfavorable [= ovc_quality]; negative double vs
penalty pass with their-suit length; opener's competitive rebid /
support double after 1m–(P)–1M–(2x); "they push us" 1♠–(2♥)–2♠–(3♥)–?;
action double after we invite and they compete; responder after 1M–(X)
(XX vs Truscott vs blast).

Constructive 2/1 (5, budget 2–3×): 3NT vs 4M with 5-3-3-2 after GF
start; opener's awkward 5-4-3-1 rebid after a 2/1; invite-or-blast after
semi-forcing 1NT; minimum-GF slam try (control-bid vs signoff);
fourth-suit vs 3-card raise.

High-level/preempt (3): second-seat vul preempt with side 4M; sacrifice
at favorable over their confidently-bid game; reopening after 1M–(1NT).

## Endorsed across all three reviews

Measurement-over-opinion and P0-stop-loss discipline (R2-1); the
teacher-not-bank reframe and census-first epistemics (R2-3);
family-level review altitude, SRS-on-fresh-cards, and the feeder trust
order (R2-5); universal reuse of the trusted INV1–8 / hard-shell stack
and the owner's decision record.
