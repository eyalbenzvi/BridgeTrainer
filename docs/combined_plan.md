# The Combined Plan: Forge — compiler + empirical gate + oracle-ready (v2)

Status: v2 — dual review applied (bridge expert + software engineer,
both APPROVED WITH CHANGES; round-1 reports in
`docs/panel/combined_round1.md`). Date: 2026-07-16.
Parents: `docs/plan_r2_5_problem_compiler.md`,
`docs/plan_r2_1_empirical_mining.md`, `docs/plan_r2_3_field_oracle.md`.

## 0. How the three methods compose

- **R2-5 is the chassis**: problems come from *families* — an
  expert-reviewed recipe (hero hand-class + fixed auction stem + option
  menu + meanings + projections) that deals unlimited fresh instances.
  Families carry stem plausibility, menu correctness, system-safety.
- **R2-1 is the gate**: every compiled instance is accepted or rejected
  by *measurement* on its own full simulation — genuinely close,
  material, statistically honest for THIS hand.
- **R2-3 is a deferred prior**: `oracle: none` provenance on every v1
  record; one publish-priority integration point; nothing else depends
  on it.

**The family answers "is this a real decision?" once; the gate answers
"is it a real decision on THESE 13 cards?" every time.** R2-1's
standalone random-deal miner is P2.

## 1. Verified ground truth (code + measurements)

- `run_problem(path, seed, my_hand_override=…)`: full trusted pipeline.
  **Measured on this machine, cache-cold fresh hands**: n=150 ≈ 5.8 s,
  n=800 ≈ 18.1 s (DD ≈ 11 ms/deal-denom). 20-deal batch estimate:
  **~12–16 min** single-threaded at 40–60% acceptance.
- `sample_my_hand(hand_class, rng)` exists; publish.py's variant loop is
  the pattern (rng = `np.random.default_rng([instance_seed, 777])`).
- Five families in `problems/*.yaml`, all with `my_hand_class`, all
  exactly 3 candidates.
- `ComparisonResult` exposes every gate metric; `RunResult` exposes
  `in_dd_fog`, `diagnostics.shortfall`, `ci_widen`, `_breakdowns` rows.
- `ProblemPool.add` hard-asserts `schema == 1` — forge data therefore
  ships as **additive fields under `schema: 1`** (a `forge:` sub-object),
  never a version bump; records must populate `difficulty` and
  `created_at` (the index sorts on them).
- `generate/producer.py:produce_batch` already implements the loop
  skeleton (timing, rejection log, duplicate-id skip, `max_seconds`
  budget, `rebuild_index`) — maker.py extends that pattern, not new code.
- **G1 as v1 specified is unimplementable**: `RuleEngine.extract` skips
  the hero seat by design, and hero-stem rule coverage is zero across
  the P0 catalogue (three families have no hero stem call at all).

## 2. `bridge_trainer/forge/` (v2 spec)

```
forge/
  family.py    # family: block parsing (plain problem YAML = valid family)
  gate.py      # G1–G4 (+G5 stub) below
  maker.py     # produce_batch-style loop; CLI: trainer forge
records: pool JSON, schema 1 + `forge:` sub-object
CLI: trainer forge --families problems/ --count 20 --pool pool_v2
     --seed S [--n 800] [--max-seconds T] [--max-attempts-per-family K]
```

### 2.1 Family block (v2)

```yaml
family:
  principle: >-        # the lesson (framed as lesson, never as verdict)
  publish: true        # false = calibration-only (five_level in v0)
  gate:
    delta_imps: null   # null = derive from calibration (fraction of E|swing|)
    stakes_min: 0.5    # E|top-2 per-deal IMP swing| hard floor
    push_max: 0.85     # advisory unless stakes also low (G4 is AND)
  audit:               # family-declared off-menu leak guards
    - when: "me_diamonds >= 6 or me_clubs >= 6"
      reason: "long-minor hand — fit-jump/preempt family, not this menu"
```

Audit predicates are compiled with the existing AST-whitelisted
`compile_predicate` (projection/tree.py) over `me_*` features from
`dealing/features.py` — no new predicate language.

**Audit predicates shipped with the five P0 families** (bridge review):
comp_3s `me_diamonds >= 6 or me_clubs >= 6`; ovc `me_spades_hcp >= 7`
(auto-1♠) and `me_spades_hcp <= 1` (degenerate suit); comp_over_weak
`me_hearts_hcp <= 3`; bal_reopen `me_diamonds >= 5 or me_clubs >= 5`
(two-suiter live) and the fictional-pass guard (near-max HCP with
`me_hearts_hcp` high would have overcalled 2♥ directly).

### 2.2 The instance gate (v2)

- **G1 hero-stem sanity** — implemented with the existing
  `check_hero_stem` (validate/trees.py) gross checks on hero's non-pass
  stem calls, plus a per-instance coverage log
  (`G1: N hero-call rules found`). Honesty note in every record: for
  the three families where hero has no stem call, G1 is structurally
  vacuous and the real stem guarantee is the hand class itself
  (enforced by construction in `sample_my_hand`) + G2.
- **G2 family audit** — the `audit` predicates. With G1's limits, G2 +
  class tightness carry the stem/menu burden at v0.
- **G3 dilemma test** (corrected comparison): accept iff best
  candidate's `ev_vs_best_alt ≤ delta_imps` OR verdict is a toss-up;
  reject "one-sided" otherwise. `delta_imps` is **per-family,
  stake-normalized**: derived in calibration as a fraction of the
  family's measured E|top-2 swing|, then frozen.
- **G4 stakes floor (AND rule)**: reject only if stakes are low
  (E|top-2 swing| < `stakes_min`) — `push_max` alone never rejects:
  high-push/high-tail penalty-conversion spots (X-vs-3♠ pushing 85%
  into the same contract with the +800/−730 tail as the lesson) are
  exactly the catalogue's best instances.
- **G5 anti-lottery** — stub at v0 (all menus are 3 candidates);
  implemented when a 4+-option family ships.
- **Shortfall honesty**: `diagnostics.shortfall`/`ci_widen` recorded;
  instances above a shortfall threshold are flagged and cannot be
  accepted *via the toss-up branch* (widened CIs manufacture toss-ups,
  which G3 would otherwise accept — slow families would be
  systematically over-accepted).
- **Doubled-outcome flag (b1 #12 at the gate)**: log the share of the
  top-2 EV gap carried by doubled-terminal layouts; when it dominates,
  the instance publishes flagged/toss-up-only (DD's perfect defense
  overpays penalties).
- **Fog**: `in_dd_fog` ⇒ toss-up with fog label, never a single winner.

### 2.3 The loop (v2 — probe cut)

Single-stage full sims (`n=800`, ~18 s): the probe is **off by
default** — the cache key includes `n`, so probe work is discarded on
acceptance; at expected acceptance rates it is break-even while adding
a second threshold set. (Future: prefix-reuse cache path would make it
a true win; not now.) `produce_batch`-style loop with `--max-seconds`,
per-family attempt caps (a never-passing family cannot stall the
round-robin), per-instance try/except (`generation_failed` reject on
`RuntimeError`, batch continues), `rebuild_index` after every accept
(crash ⇒ valid partial pool).

**Seeding (pinned)**: family key = index in sorted file list (not
Python `hash()` — process-salted); instance seed = plain Python int
`base_seed + 1000*family_index + k`; hand rng =
`np.random.default_rng([instance_seed, 777])`; record id =
`{family_id}-{instance_seed:x}` so re-runs resume via the pool's
`FileExistsError` skip.

### 2.4 Record (schema 1 + `forge:` sub-object)

Standard pool fields (`id`, `difficulty`, `created_at`, hand, auction,
options, verdict) + `forge: {family_id, instance_seed, gate:
{thresholds, measured, shortfall, ci_widen, doubled_share}, evidence:
per-candidate table (EV-vs-best-alt, CI, p_gain/p_push, big-swing
rates), dead_options: [...] (post-answer annotation: "X best on 0 of
800 layouts"), explanation: {principle, breakdown_rows (serialized from
run_problem's computed breakdowns — no free-text feature claims),
caveats}, provenance: {bot: none, llm: none, oracle: none, versions,
seeds}}`.

**Explanation honesty rules** (bridge review, binding): verdict
vocabulary margin-calibrated (toss-ups say "the panel would split",
never "the answer was"); numeric gap + CI always printed; feature-delta
rows only from computed breakdowns; any X verdict carries the
DD-defense caveat; fog explained in plain words; `principle` framed as
lesson, not verdict.

## 3. Pre-run repairs to the P0 catalogue (bridge review, binding)

1. **Cross-option consistency fixes + lint (b1 #6)** — two live hits
   found in shipped YAMLs: `comp_3s_over_3h`'s X tree lacks the 3♠
   tree's opener-pushes-to-4♥ branch (`west_hearts >= 7 and
   west_hcp >= 14`) though both reach the identical 3♠ contract — X is
   flattered on every instance; `bal_reopen_after_2s`'s opposing
   3♠-competition predicates differ between the X and 3♥ trees. Fix
   both YAMLs; add a mechanical lint (same opposing decision ⇒ same
   predicate) that runs at family load.
2. **`five_level_over_save`: `publish: false`** (calibration/shakedown
   only) — the 5-level/sac genre carries directional DD bias present in
   raw AND corrected numbers; raw/corrected agreement proves nothing.
   Additionally its Pass option is display-only: the gate never crowns
   a forcing-pass violation as the verdict.
3. **Golden tests**: the YAML tree fixes change verdict numbers; golden
   expectations are updated in the same commit with the diff explained.

## 4. Calibration mini-run (v2 — positives, negatives, corners)

- **Positives**: the five authored variant-0 hands (must pass G3–G5).
- **Negatives** (must be rejected as one-sided; bridge review supplied):
  comp_3s ♠J93 ♥QJ7 ♦Q854 ♣J62 (clear Pass) and ♠K93 ♥76 ♦KQT85 ♣962
  (clear 3♠ at favorable); ovc ♠KQJT9 ♥42 ♦A72 ♣853 (auto 1♠) and
  ♠Q7653 ♥KQ ♦QJ3 ♣J52 (clear Pass); comp_over_weak ♠A7 ♥KQJT8 ♦K93
  ♣J52 (auto 3♥); bal_reopen ♠QJ ♥97542 ♦KJ4 ♣Q83 (clear sell-out).
- **Corners**: 3–4 compiled corner hands per family (HCP/shape/wastage
  extremes) — centroid review was the parents' named failure mode.
- Output: per-family measured E|swing| → frozen `delta_imps`; a
  calibration report table committed with the run.

## 5. Deliverables & sequence

1. `forge/` + CLI + lint; fast unit tests (gate, family parsing,
   seeding); YAML repairs + golden updates.
2. Calibration mini-run; freeze thresholds; report.
3. **20-deal run** (`--count 20`), wall clock + per-stage timing,
   acceptance/rejection tabulation, learnings report.
4. **Old-pool deletion** as a separate commit after the run (verified:
   no test references `batches/`).

## 6. Risks (v2)

1. Calibration set is small (5 pos / 6 neg / ~15 corners) — thresholds
   are v0-frozen, not final; report states them as such.
2. G1 vacuity for three families — documented per instance; class
   tightness + G2 carry the burden (that is why the audit predicates
   ship now, not later).
3. Four publishable families ⇒ ~5 deals each in the 20-batch —
   shakedown variety, stated in the report.
4. Templated explanations thinner than b3 prose — accepted under
   constraint F; principle + computed breakdowns only, no invented
   claims.
5. `five_level` excluded from publishing shrinks the catalogue's only
   high-level family — P1 re-admits it behind correction-table
   validation per the parent plans.
