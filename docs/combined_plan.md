# The Combined Plan: Forge — compiler + empirical gate + oracle-ready (v1)

Status: unified implementation plan combining R2-5 (problem compiler,
the frame), R2-1 (empirical mining metrics, the gate), R2-3 (field
oracle, a later prior). For dual review: bridge + engineering.
Date: 2026-07-16. Parents: `docs/plan_r2_5_problem_compiler.md`,
`docs/plan_r2_1_empirical_mining.md`, `docs/plan_r2_3_field_oracle.md`,
panel records in `docs/panel/`.

## 0. How the three methods compose

- **R2-5 is the chassis**: problems come from *families* — an
  expert-reviewed recipe (hero hand-class + fixed auction stem + option
  menu + meanings + projections) that deals unlimited fresh instances.
  Families solve stem plausibility (reviewed once), option-menu
  correctness (reviewed once), and system-safety (owner's card only).
- **R2-1 is the gate**: every compiled instance is accepted or rejected
  by *measurement* on its own full simulation — is the choice genuinely
  close, material, and statistically honest for THIS hand? This solves
  per-instance degeneracy (auto-bid instances, stakeless coin-flips)
  that no family review can see.
- **R2-3 is a deferred prior**: when a harvested corpus exists, the
  oracle's human-split score attaches to instances as publish priority.
  v1 ships with `oracle: none` provenance on every record and a single
  integration point — nothing else in the design depends on it.

Division of labor, restated: **the family answers "is this a real
decision?" once; the gate answers "is it a real decision on THESE 13
cards?" every time.** R2-1's standalone mining loop (random deals over
context catalogues) is deferred to P2 — the compiler reaches volume
first because stems and menus are already trusted.

## 1. What exists today (verified in code, tests green: 443 passed)

- `run_problem(path, seed, my_hand_override=…)` — the full trusted
  pipeline per instance: semantics → constrained deals (INV2/3) →
  projections (INV1) → DD + correction (INV5) → paired comparison with
  CIs/ESS/toss-ups (INV7). ~30 s at n=800; deal-set + DD caches keyed by
  hand (INV4), so fresh hands are compute-cold by design.
- `sample_my_hand(hand_class, rng)` — deals a hero hand from a class
  (`dealing/myhand.py`); already used by the publish "next deal" path.
- Five authored families in `problems/*.yaml`, all with `my_hand_class`
  and 3-candidate menus — the P0 catalogue.
- `ComparisonResult` — per candidate: `ev_vs_best_alt`, `ci_half_width`,
  `p_gain/p_loss/p_push`, `p_big_gain/p_big_loss`, verdict + toss-up set,
  raw AND corrected (fog flag).
- `ProblemPool` (`pool/store.py`) — JSON pool + index, database-shaped.
- Hard-shell validators (`validate/`), batch-era finalize schema — reused
  where applicable; the LLM finalizer is NOT in this loop (constraint F:
  offline, free).

## 2. The new component: `bridge_trainer/forge/`

```
forge/
  family.py    # family = existing problem YAML + optional `family:` block
  gate.py      # the instance gate (G1–G5 below)
  maker.py     # the generation loop (staged sims, seeding, logging)
  records.py   # pool record v2 + provenance
CLI: trainer forge --families problems/ --count 20 --pool pool_v2
                   --seed S [--n 800] [--probe 150] [--report]
```

### 2.1 Family schema (backward compatible)

An ordinary problem YAML is a valid family. Optional `family:` block:

```yaml
family:
  principle: >-        # the lesson, one paragraph (shown post-answer)
  gate:                # per-family overrides of gate defaults
    delta_imps: 3.0    # dilemma band (top-2 corrected EV gap)
    stakes_min: 0.5    # min E|top-2 per-deal IMP swing|
    push_max: 0.85     # max weighted push probability
  audit:               # missing-option guards, family-declared (v0)
    - when: "me_hcp >= 11"        # predicate over hero features
      reason: "limit-raise+ strength — 4S/cue family, not this menu"
  live_when:           # optional conditional menu (P1; v0 menus constant)
    "2NT": "me_hearts_hcp >= 4"
```

v0 honesty note (from the R2-5 round-2 note): the *generic-tree
off-menu screen* is P1; v0's missing-option audit is the
family-declared `audit` predicates — the family author states where the
class leaks into other decisions, and instances there are rejected with
a logged reason. The five P0 classes are tight (e.g. exactly 3 spades,
6–10 HCP), which is what makes this honest at v0.

### 2.2 The instance gate (order matters; each rejection logged + tagged)

- **G1 hero-stem conformance** — the sampled hand must be one that bids
  hero's own stem calls under the card: check `my_hand` against the
  rule bands the semantics engine assigns to hero's calls (the b1 #5
  validator, per instance). Kills fictional auctions.
- **G2 family audit** — the `audit` predicates (§2.1). Kills
  out-of-family hands whose best call is off-menu.
- **G3 dilemma test** (corrected comparison): accept iff the best
  candidate's `ev_vs_best_alt ≤ delta_imps` OR the verdict is a
  toss-up. Gap > delta ⇒ reject "one-sided" (loggable as a calibration
  hand, not published as a dilemma).
- **G4 stakes floor**: reject if `p_push ≥ push_max` on the top-2 pair
  or E|per-deal top-2 IMP swing| < `stakes_min` — the "close because
  nothing ever differs" spots.
- **G5 anti-lottery**: ≥4 candidates all mutually inside their CIs with
  near-uniform per-deal winners ⇒ reject "pure guess" (moot at v0's
  3-candidate menus, implemented for P1 families).
- Fog honesty: `in_dd_fog` instances publish only as toss-ups with the
  fog label (existing INV5 discipline), never as single winners.

### 2.3 The generation loop (staged for wall clock)

```
for family round-robin, instance seed s = f(base_seed, family, k):
  hand  = sample_my_hand(class, rng(s))
  G1/G2 (microseconds; no sim)
  probe = run_problem(…, n=PROBE≈150, my_hand_override=hand)   # ~5–8 s
     early G3/G4 with CI widened by probe size — reject only clear cases
  full  = run_problem(…, n=N≈800)                              # ~30 s
     final gate G3–G5 on corrected comparison
  emit record v2 + per-instance provenance
```

Expected cost per *accepted* deal: one probe + one full sim for
acceptances, one probe for most rejections. At a 40–60% post-G2
acceptance rate: ~45–70 s per accepted deal single-threaded; a 20-deal
batch ≈ 20–35 min. (Numbers to be measured and reported in the P0 run —
this is a plan estimate from the ~13 ms/deal DD floor and 2 denoms.)
Parallelism knob: instances are embarrassingly parallel
(`--jobs`, process pool) — P1 if the measured single-thread time
annoys.

### 2.4 Record v2 (pool JSON)

Existing pool record shape + `family_id`, `instance_seed`, `verdict`
(call or toss-up set + fog flag), `evidence` (per-candidate table:
EV-vs-best-alt, CI, p_gain/p_push, big-swing rates), `gate` (thresholds
+ measured values + probe/full ns), `explanation` = family `principle` +
**templated instance delta** (top hero-feature breakdown rows: "your
♥QJ = 4 wasted points sits under the raise"), `provenance`
(`bot: none, llm: none, oracle: none`, versions, seeds — INV6).
No LLM in the loop (constraint F); prose upgrades are additive later.

## 3. What is deliberately NOT in v1

- **R2-1 standalone mining** (random-deal context catalogues, EVPI
  de-biasing, per-context candidate trees): P2. The gate uses only
  metrics computable from the existing per-instance comparison.
- **R2-3 oracle**: P2+, needs the harvest census first. Hook = one
  provenance field + publish-priority sort key, already in the schema.
- **LLM explanations, generic-tree audit, live_when menus, subfamily
  splitting, SRS surfaces**: P1+, additive.
- **Genre quarantine note carried over**: none of the five P0 families
  is in R2-1's DD-bias exclusion genres except `five_level_over_save`
  (5-level/sac genre) — its instances publish **only as toss-up/flagged
  unless the corrected and raw verdicts agree** (stricter fog rule), per
  the R2-5 sequencing note.

## 4. Deliverables & sequence (this iteration)

1. `forge/` module + CLI as specified; unit tests for gate logic and
   family parsing (fast, no DD); one slow integration test (probe-sized).
2. **Calibration mini-run**: authored variant 0 of each of the five
   families through the gate — the five originals were expert-authored
   dilemmas and must pass G3–G5 (they are the labeled positives; gate
   thresholds must not reject them). Any failure → threshold review
   before the batch run.
3. **The 20-deal run**: `trainer forge --count 20`, wall-clock and
   per-stage timing logged, acceptance/rejection reasons tabulated.
   Report: total time, time per accepted deal, rejection breakdown,
   gate-threshold observations, and what to change before scaling.
4. **Old-pool deletion**: remove b1/b2/b3-era batch artifacts and their
   pool documents from the repo (the deployed gh-pages data is replaced
   on next publish); the five family YAMLs and all docs/panel records
   stay.

## 5. Risks (v1-specific)

1. **Gate thresholds are guesses until the calibration mini-run** — the
   five authored positives are few; expect one tuning pass, report it.
2. **G1 depends on rule coverage for hero's stem calls** — where the
   ruleset lacks a rule for hero's call, G1 degrades to "class bands
   only"; logged so coverage gaps are visible, never silent.
3. **Fresh hands are cache-cold by design** (INV4) — per-deal cost is
   real compute; the probe stage is the mitigation, `--jobs` the escape.
4. **Five families ⇒ variety ceiling for the first batch** — 20 deals
   over 5 families = 4 per family; acceptable for a shakedown run,
   stated so the batch isn't judged as a catalogue.
5. **Templated explanations are thin** relative to the b3 prose bar —
   accepted trade under constraint F; principle text carries the lesson.
