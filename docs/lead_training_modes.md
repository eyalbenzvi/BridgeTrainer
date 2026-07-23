# Opening Lead Trainer: MP and IMP training modes

The Opening Lead Trainer has exactly **two** sections:

1. **Matchpoints (MP)** — *Prioritize maximum defensive tricks.*
   Goal: maximize expected defensive tricks.
2. **IMPs** — *Prioritize score swings.*
   Goal: maximize expected IMP value from the final score.

Both modes share the SAME evidence pipeline — deal generation, the
auction-consistency sampler, and double-dummy analysis
(`engine.lead_evaluate` → per-card, per-sample defensive-trick arrays).
**Only the ranking objective differs.** Every candidate lead always carries
all four aggregate metrics, in both modes:

| metric            | meaning                                                    |
|-------------------|------------------------------------------------------------|
| `avg_def_tricks`  | expected defensive tricks (the MP ranking metric)          |
| `exp_score`       | expected duplicate score, defenders' perspective           |
| `exp_imps`        | expected IMP value vs the baseline (the IMP ranking metric)|
| `set_prob`        | probability the defense beats the contract                 |

The UI shows all metrics in both modes and visually emphasizes the active
mode's primary metric. Ranking is implemented once, centrally, in
`bridge_trainer/scoring/lead_metrics.py`:

* **MP** sorts by `exp_def_tricks` descending;
* **IMP** sorts by `exp_imps` descending — never by the trick average;
* ties break deterministically: expected score, then fixed suit-then-rank
  card order.

## The IMP baseline

Converting a duplicate score to IMPs needs a reference score. No IMP
baseline existed for lead problems before algorithm version 2 (leads were
graded on tricks only; the bidding pipeline's pairwise action comparison has
no analogue for a 13-way lead choice), so one centralized, configurable
baseline was introduced — `scoring.lead_metrics.LEAD_IMP_BASELINE`:

> **`datum_mean_v1`** — a Butler-style datum. On each sampled layout, the
> baseline score is the **mean defender score across all candidate leads on
> that same layout**; a lead's per-sample IMP value is
> `imps(lead_score − datum)` and its expected IMP value is the (weighted)
> mean over samples.

To change it, swap `LEAD_IMP_BASELINE` (bumping its `version`) or pass
`baseline=` to `compute_lead_metrics`. The baseline metadata is persisted in
every record's `training.modes.IMP.imp_baseline`, so stored records are
self-describing. Score→IMP conversion reuses the golden-tested
`scoring.tables` (`contract_score`, `imps_array`).

## Persistence

* **Attempts** (`users/{uid}/attempts/*`) store `trainingMode` (`"MP"` /
  `"IMP"`), `rankingMetric`, `chosenRank`, `recommendedLead`,
  `primaryValue`, and the mode's accepted set (`bt-firebase.js: gradeLead`).
* **Problem records** (schema 2, `engine/lead_maker.py`) store a `training`
  block — algorithm version, sample counts, per-mode ranking metric + goal,
  IMP baseline — plus per-lead aggregates on every candidate/table row:
  `rank_mp`, `rank_imp`, `recommended_mp`, `recommended_imp`,
  `avg_def_tricks`, `exp_score`, `exp_imps`, `set_prob`, and
  `verdict.by_mode.{MP,IMP}.{ranking_metric,recommended,accepted}`.
* **Index entries** for lead problems carry `modes` (`["MP"]` or
  `["MP","IMP"]`); the web app's IMP section only offers problems whose
  index entry includes `"IMP"`.

## The generators: one per mode

The problem generator is **split by training mode**. Both share the whole
pipeline — bid-out, final contract, the 32/64/128 screening cascade, the
512-sample confirm, explanations — and differ ONLY in the unit their
acceptance gates run in (`engine/lead_verdict.py: MP_SCALE / IMP_SCALE`):

| gate | MP generator (tricks) | IMP generator (expected IMPs) |
|------|----------------------|-------------------------------|
| C1 "obvious" | BEN policy mass on the tricks-best answer set > 50% | BEN policy mass on the IMP-best answer set > 50% |
| C2 "suit indifferent" | best vs best-different-suit gap < **0.25 tricks** | gap < **0.5 IMPs** (the bidding verdict's long-standing toss-up line) |
| split-half stability | drift > 0.30 tricks | drift > 0.6 IMPs |
| difficulty scale | trap decisive at 0.5 tricks, live suit within 0.5 | trap decisive at 1.0 IMPs, live suit within 1.0 |

### Running the generators on GitHub (the normal way)

Problem creation runs on GitHub Actions — no local machine or Claude session
needed.

**Hourly schedule** — every hour the workflow forges one MP batch and one
IMP batch (10 problems each by default) and pushes them to Firestore. Seeds
are hour-based, so every firing works fresh boards. Tune it with repository
variables (Settings → Secrets and variables → Actions → Variables), no YAML
edit needed: `FORGE_COUNT` (problems per mode per hour) and
`FORGE_MAX_SECONDS` (per-mode time budget, default 1500 s).

**Manual runs** — open **Actions → "Forge lead problems" → Run workflow**
and choose:

* **mode** — `MP` or `IMP` (which generator's gates select the boards);
* **count** — how many problems to generate;
* optionally a seed and a time budget.

The runner sets up the Ben engine itself (`scripts/setup_ben.sh`, cached
between runs), talks to BBO's GIB service (`gibrest.bridgebase.com`) for the
per-call auction interpretations, and pushes the finished problems straight
to Firestore. One-time setup: add the Firebase service-account key JSON
**content** as the `FIREBASE_SERVICE_ACCOUNT` repository secret
(Settings → Secrets and variables → Actions). Runs are serialized so
concurrent pushes never race the Firestore index.

### Running locally (fallback)

```
trainer lead-forge --mode MP  --count 20 --seed 1   # trick-decision boards
trainer lead-forge --mode IMP --count 20 --seed 1   # score-swing boards
MODE=IMP scripts/generate_and_push_leads.sh 96      # forge + push
```

Records are stamped with the mode they were forged for
(`training.target_mode`, `generator.target_mode`) and get per-mode id
prefixes (`lead1-…` for MP, `lead1i-…` for IMP) so the two generators never
collide on a seed. Every record still carries BOTH modes' metrics; the
target mode only says whose gates selected the board. The web app serves
each section from its own generator's pool (index `target_mode` flag).

## Legacy records (algorithm version 1)

Pre-mode lead records store only per-card trick AVERAGES — no per-sample
evidence — so their IMP metrics cannot be reconstructed and they can serve
**MP only**. The migration `trainer pool backfill-training` stamps them with
`training = {algorithm_version: 1, modes: {MP: …}}` and rebuilds the index
with mode flags. They stay fully readable; opened in IMP mode they fall back
to MP with a visible notice, and the old universal trick ranking never
determines an IMP recommendation. Newly forged problems
(`trainer lead-forge`) carry both modes automatically.
