# Bridge Bidding Trainer

A personal training tool for borderline/competitive bidding decisions under a
2/1 system. Flow: present a bidding problem → pick an action → simulate
thousands of constrained deals → double-dummy solve → show a statistically
honest comparison of the candidate actions.

## Quick start

```bash
pip install -e .
trainer run problems/comp_3s_over_3h.yaml --seed 42
```

Prints the verdict to stdout and writes a self-contained HTML report to
`reports/`. Add `--answer 3S` to record your call non-interactively, `--n` to
override the deal count, `--no-cache` to force regeneration.

## Architecture

```
bridge_trainer/
  domain/        # pure dataclasses + frozen Protocol interfaces
  semantics/     # rule engine: auction -> ConstraintProfile (YAML rulesets)
  dealing/       # vectorized NumPy rejection DealSource + diagnostics
  projection/    # conditional-tree ContractProjector (per-deal, YAML)
  dd/            # chunked DDS wrapper, single-dummy correction, deal-set cache
  scoring/       # score/IMP tables, weighted statistics, paired comparison
  bank/          # problem YAML schema validation + loader
  app/           # CLI, HTML report renderer
problems/        # problem bank
tests/           # golden + invariant tests
```

The frozen boundary interfaces (`DealSource`, `ContractProjector`,
`Evaluator`) live in `bridge_trainer/domain/interfaces.py`.

## Core invariants

- **INV1** all candidates are scored on the identical deal set;
- **INV2** every statistic uses importance weights; CIs use effective sample size;
- **INV3** dealing is combinatorially honest (chi-square test vs the
  hypergeometric distribution in `tests/test_dealing.py`);
- **INV4** deal-set cache key hashes hand, constraints, systems, dealer,
  vulnerability, seed, schema + library versions;
- **INV5** single-dummy correction is applied symmetrically; reports show raw
  AND corrected verdicts, disagreements are labelled "inside the DD fog";
- **INV6** every run is seeded; reports record seed + versions + constraint hash;
- **INV7** differences within the CI (or < 0.5 IMPs) are a toss-up, never a
  winner; generation shortfall widens CIs and says so;
- **INV8** pass is a first-class call in the semantics engine.

## Authoring a problem

See `problems/comp_3s_over_3h.yaml`. A problem specifies dealer, vul, seat,
hand, auction, two `SystemProfile`s (ours + opponents') pointing at semantics
rulesets, and per-candidate projection trees: ordered `when:` predicates over
the concealed hands ending in an `else:`. Doubles decide partner's sit/pull
per deal via predicates on partner's hand. Semantics rulesets live next to
the problem file or in `bridge_trainer/semantics/rules/`; each rule gives
soft HCP/suit-length bands (core at weight 1.0, margins at reduced weight)
plus named `exclusions` from the predicate library
(`bridge_trainer/semantics/predicates.py`).

The single-dummy correction table is editable:
`bridge_trainer/dd/correction_table.yaml`.

## Status vs roadmap

- **M0 (done)**: feasibility spike — see `docs/m0_results.md`. Gate: tight
  generation is seconds-scale → reserve dealers stay deferred.
- **M1 (done)**: vertical slice end-to-end on `comp_3s_over_3h`; golden tests.
- **M2 (partially pulled forward)**: correction layer, deal-set disk cache and
  sample audit already shipped in M1; remaining: DD-result caching.
- **M3+**: SQLite session store, more problems, generation-diagnostics
  publishing gate, spaced repetition, matchpoints via FieldModel.

Note: DD solving (~13 ms/deal for two denominations) dominates wall clock,
which is why problems default to `n_deals: 800` (< 30 s per run, CI half-width
≈ ±0.3 IMPs). Acceptance rate is logged on every run; if a future problem
measures < 0.1% AND minutes-scale wall clock, promote the reserve dealers
(HCP-partitioned dealing / shape-vector enumeration with combinatorial
weighting per INV3).
