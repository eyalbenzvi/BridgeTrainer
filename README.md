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

## Random problems (the app)

The deployed app serves RANDOM problems generated with the **Ben engine**
(github.com/lorserker/ben, GPL-3.0 — external checkout, never vendored;
`scripts/setup_ben.sh` installs it pinned). `trainer ben-forge` deals a
random board, Ben (BEN-21GF, a dedicated 2/1 Game Force model) bids all
four seats to a decision point, and a turn qualifies only when Ben's own
policy distribution genuinely splits AND the paired rollout evaluation
(shared samples, per-candidate expected IMPs, CI floors) confirms the
choice is close, material and statistically honest. Options are the calls
carrying real policy mass (2–5); every problem ships with computed
explanations — empirical meaning bands per stem call ("1♥ (N): overcall —
7–10 HCP, 5.0♥ avg, n=128, measured"), convention names from a mechanical
2/1 table (Stayman, transfers, RKC, cue bids, double types), and
per-option evidence (policy weight, contract distributions, IMP margins).
Design + review history: `docs/ben_execution_plan.md`, `docs/panel/`.

### Managing the pool without Claude

Generation needs no Claude session — only the Ben environment:

- **GitHub UI (no install)**: Actions → *generate* → Run workflow —
  set `count` to add problems and/or list ids in `remove` to delete;
  the site redeploys automatically.
- **Any machine**: `scripts/setup_ben.sh` once, then
  `trainer pool add --count N` / `trainer pool rm <id> ...` /
  `trainer pool ls` (removal and listing need no Ben install).

Problems land in a JSON pool (`data/`) read by the static app
(`trainer webapp`); `.github/workflows/generate.yml` grows the pool
nightly with the engine cached between CI runs.

## Authored problems (legacy drill, still available for dev)

## Phone / cloud usage

`trainer publish` builds a static, mobile-friendly quiz site for the whole
problem bank (`site/index.html`): each problem page shows the hand and
auction, you tap a call, and the verdict reveals. Answers are stored in the
browser's localStorage (per device), so no server is needed.

**Next deal**: a problem with `my_hand_class` (HCP + suit-length bounds for
your seat) and `variants: N` publishes N seeded deals of the same decision —
variant 0 is the authored hand, the rest are freshly dealt from the class and
fully re-simulated. The quiz's "Next deal" button jumps to your first
unanswered variant; the per-problem URL redirects there too.

**Continuous generation**: the deploy workflow also runs on a daily cron with
`--grow-per-day K --grow-anchor <date>`, so every problem family gains K
fresh deals per day, forever — deterministic within a day, and only the new
deals are ever computed (deal sets and DD tables are content-addressed in the
cache). The site's "Deal me a hand" button serves a random deal you haven't
answered, across all families. True tap-time generation would need a compute
server or an in-browser DD engine; the daily pool + random unseen serving
gives the same experience on free static hosting.

`.github/workflows/publish.yml` runs the tests, rebuilds the site and deploys
it to **GitHub Pages** on every push to `main` (deal sets and DD trick tables
are cached between CI runs, so unchanged problems republish in seconds). One-
time setup: repo → Settings → Pages → Source: **GitHub Actions**, then
bookmark the published URL on your phone.

Note: GitHub Pages sites are public (even for private repos, outside
Enterprise). The content is just bridge problems, but if that bothers you,
Cloudflare Pages + Access gives the same static hosting behind a free email
login.

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
- **M2 (done, pulled forward)**: correction layer, deal-set + DD-result disk
  caches, sample audit, schema validation.
- **Cloud publishing (added)**: `trainer publish` static quiz site + GitHub
  Pages workflow; per-device answer tracking via localStorage.
- **M3+**: SQLite session store (or localStorage export), more problems,
  generation-diagnostics publishing gate, spaced repetition, matchpoints via
  FieldModel.

Note: DD solving (~13 ms/deal for two denominations) dominates wall clock,
which is why problems default to `n_deals: 800` (< 30 s per run, CI half-width
≈ ±0.3 IMPs). Acceptance rate is logged on every run; if a future problem
measures < 0.1% AND minutes-scale wall clock, promote the reserve dealers
(HCP-partitioned dealing / shape-vector enumeration with combinatorial
weighting per INV3).
