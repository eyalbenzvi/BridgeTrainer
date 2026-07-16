# Dual review — combined plan v1, round 1 (2026-07-16)

Bridge expert (bridge-wise) + software engineer (runtime/structure/
feasibility), independent, over `docs/combined_plan.md` v1.
Both verdicts: **APPROVED WITH CHANGES**. All changes applied in v2 +
the YAML repairs below.

## Bridge review (10 recommendations, all applied)

1. Calibration needs labeled auto-bid **negatives** (concrete hands
   supplied per family) — positives-only tuning is no tuning. → plan §4.
2. `five_level_over_save` excluded from publishing in v0 (raw/corrected
   agreement cannot remove a directional bias present in both); Pass
   never crowned (forcing-pass violation ≠ verdict). → `publish: false`,
   `never_verdict: [P]`.
3. G4 changed OR→AND: high-push/high-tail penalty-conversion spots are
   the catalogue's best content; stakes_min is the only hard floor.
4. Cross-option consistency lint (b1 #6) — **two live YAML hits found**:
   comp_3s X tree lacked the 3S tree's opener-push-to-4H branch
   (flattering X on every instance); bal_reopen's opposing 3S-competition
   predicates differed between the X and 3H trees. Both fixed; lint at
   family load. Tests: 443 still green (goldens unaffected).
5. Family audit predicates written now (supplied per family; see the
   `family:` blocks in problems/*.yaml) + per-instance doubled-outcome
   share flag (b1 #12 applied at the gate).
6. Explanation honesty minimums (margin-calibrated vocabulary; numeric
   gap+CI; computed-breakdown-only feature claims; X verdicts carry the
   DD-defense caveat; fog in plain words; principle framed as lesson).
7. Corner hands (3–4/family) added to calibration.
8. `delta_imps` stake-normalized per family (fraction of measured
   E|swing|, frozen post-calibration) — 3.0 flat was wrong across genres.
9. Menu-display honesty: dead-option post-answer annotation in records.
10. G1 documented as structurally vacuous for the three families where
    hero has no stem call.

## Engineering review (7 recommendations, all applied)

1. **G1 as v1-specified contradicted by code**: `RuleEngine.extract`
   skips the hero seat; hero-call rule coverage is zero across all five
   families. → G1 rebuilt on `validate/trees.py:check_hero_stem` +
   coverage logging; class-bands-by-construction stated as the real
   guarantee.
2. Probe stage cut (default off): cache key includes `n`, so probe work
   is discarded on acceptance — break-even at expected acceptance rates,
   plus a second threshold set to maintain. Measured: n=150 ≈ 5.8 s,
   n=800 ≈ 18.1 s cache-cold; 20-deal batch ≈ 12–16 min single-threaded.
3. Pool schema collision: `ProblemPool.add` asserts `schema == 1` →
   forge data ships as additive `forge:` sub-object; `difficulty` and
   `created_at` populated for the index.
4. Reuse `generate/producer.py:produce_batch` loop shape; `--max-seconds`
   + per-family attempt caps (no stalled round-robin); wire into cli.py.
5. Per-instance try/except (`generation_failed`), `rebuild_index` after
   each accept (crash ⇒ valid partial pool); record + threshold
   shortfall/ci_widen (widened CIs manufacture toss-ups G3 would accept).
6. Seeding pinned: sorted-file family index (no salted `hash()`), plain
   int seeds (cache key JSON), `default_rng([seed, 777])` convention,
   record id from (family_id, seed) for idempotent re-runs.
7. Same-day cuts: G5 stubbed (all menus are 3 candidates), probe off,
   explanation = principle + serialized computed breakdowns; audit
   predicates via existing `compile_predicate` + `dealing/features.py`.
