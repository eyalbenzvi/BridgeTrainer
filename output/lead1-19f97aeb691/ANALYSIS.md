# lead1-19f97aeb691 — multi-method opening-lead analysis

**Board** (reproduced exactly from the id seed with the pinned Ben commit —
matches the stored `full_deal` byte-for-byte):

- Auction: `1S P 2H P 4S P P P`, dealer W, vul None → **4S by W**
- Leader: **N**, hand `T4.K82.J863.AQ97`
- Actual hidden hands: W `AKJ87532.J3.K42.` (club **void**), E (dummy)
  `9.AT754.AQ7.KJT8`, S `Q6.Q96.T95.65432`
- Published verdict (512 samples, target MP): **♣A**, gap +0.40 tricks over
  ♦-spot, recommended in BOTH MP and IMP modes.

## Methods run (independent axes: sampler family, DD engine, constraint
## model, seed, sample size, metric)

| # | Method | Posterior | DD engine | Winner (tricks) | CA−♦3 (tricks) |
|---|--------|-----------|-----------|-----------------|----------------|
| 1 | Stored production verdict (512) | Ben current@0.70 | Ben DDS | ♣A | +0.40 |
| 2 | `lead-posterior-audit` current@0.70/0.80/0.90, seed 1 | Ben neural filter | Ben DDS | ♣A / ♣A / ♣A | +0.37 / +0.37 / +0.31 (all CI>0) |
| 3 | Same, seed 2 (replication) | Ben neural filter | Ben DDS | ♣A ×3 | same, `quality_flag=robust` |
| 4 | ben-replay sampler | Ben auction replay | Ben DDS | ♣A | +0.33 [0.25,0.41] |
| 5 | ben-likelihood sampler | Ben likelihood weights | Ben DDS | ♣A | +0.36 [0.32,0.41] |
| 6 | Ben native `lead_evaluate` (300 & 600 samples) | Ben's own production path | Ben's own DDS+averaging | ♣A / ♣A | +0.35 / +0.39 |
| 7 | Independent MC, "tight" 2/1 constraints, seeds 11/22/33, 800 layouts | hand-rolled NumPy rejection (no Ben code) | endplay DDS (separate binary) | ♣A ×3 | +0.14/+0.22/+0.20 (all CI>0, 0% bootstrap flips) |
| 8 | Independent MC, "loose" constraints, seeds 11/22 | hand-rolled | endplay | ♣A ×2 | +0.09/+0.13 (CI>0) |
| 9 | Repo `constraint` sampler (rule engine, Ben-free) | YAML rule bands | Ben DDS | **♦6** | −0.09 [−0.17,−0.02] |
| 10 | Uniform baselines (repo + independent) | none (contrast only) | both | ♠T (noise) | −0.10 / −0.17 |

**Metric cross-check (independent MC, all 5 constrained runs):**

| Metric | Winner | CA−♦3 | Significant? |
|--------|--------|-------|--------------|
| Avg DD defensive tricks (MP proxy) | **♣A** | +0.09..+0.22 | yes, 5/5 |
| Butler-datum expected IMPs | **♦ spot** | −0.24..−0.46 | yes 4/5 (5th borderline) |
| P(set 4S) | **♦ spot** | −3.4..−5.0 pp | yes, 5/5 |

Production's own stored table agrees on the set-probability direction
(♦ 3.3% vs ♣A 2.3%) even while ranking CA first on exp_imps — under Ben's
posterior the contract almost never fails, so IMP differences are driven by
overtricks there.

**Mechanism (strata by declarer club length, both pipelines agree):**
- W holds 1–3 clubs (~vast majority of layouts): ♣A cashes and often sets up
  ♣Q behind dummy — biggest single contributor to its edge
  (audit `declarer_led_len C=1/C=2` strata; independent MC identical).
- W club **void** (~2.6% of tight-model layouts): ♣A is the *worst* card.
  The actual deal is exactly this rare stratum: double-dummy on the real
  layout gives defense 1 trick on any lead **except a club (0 tricks)** —
  the published recommendation loses a trick at the table on this deal.

**Posterior realism check** (400 layouts/sampler, `posterior_check.json`):

| Sampler | W spade lengths | W HCP mean | W club void | P(4S makes vs best defense) |
|---------|-----------------|-----------|-------------|------------------------------|
| Ben current@0.70 | 7–10 (mode 7–8) | 11.8 | 3.1% | **0.95** |
| repo `constraint` (rules) | **5–7 (mode 5!)** | 13.3 | 5.2% | **0.40** |
| independent tight/loose | 6–8 | ~12 | ~2.6% | ~0.85 |
| uniform | 0–7 | 9.6 | 2.2% | 0.19 |

The rule-based `constraint` sampler models 1S→4S as plain "5+ spades" — a
declarer who fails 60% of the time after unilaterally jumping to game is not
a credible posterior, so its ♦6 vote (the source of `sampler_sensitive`) is
discounted. Ben's posterior (7–10 spades, 95% make) matches the fast-arrival
meaning of 4S, and the actual W hand (8 spades, 11 HCP, 95%-make profile)
sits squarely inside it.

## Conclusions

1. **Under the project's official metric (expected DD defensive tricks = MP
   mode), ♣A is confirmed as the best lead** by 16 independent runs across
   two disjoint codebases, two DDS builds, three sampler families, two
   constraint models, multiple seeds and sample sizes. The margin
   (+0.1..+0.4 tricks vs the best diamond) is outside every bootstrap CI and
   is not tail-dominated.
2. **Under IMP scoring the answer flips**: low-diamond leads set the
   contract significantly more often, and the independent-MC Butler-IMP
   ranking prefers ♦3/♦6/♦8 in 5/5 runs. The published verdict marks CA as
   the IMP recommendation too — that is the one part of the stored record
   this analysis does NOT robustly support: it holds only under Ben's
   (make-heavy) posterior and reverses under independent constraint models.
3. The project's own multi-sampler gate agrees the board is contested: the
   seed-1 audit returns `quality_flag=sampler_sensitive`,
   `publishable_single_lead=false` (the Ben-free constraint sampler votes
   ♦6). Seed 2 (Ben-family only) is `robust` for CA.
4. On the actual hidden deal (declarer void in clubs) ♣A concedes the 13th
   trick — a legitimate "unlucky stratum" outcome, not a grading bug: the
   correctness gate passes, the board reproduces deterministically, and
   candidate-to-index mapping is 13-distinct.

Files: `audit_seed1.json`, `audit_seed2.json` (repo pipeline),
`ben_native.json` (Ben's own evaluator), `independent_mc.json` (endplay-based
independent Monte-Carlo), `posterior_check.json` (sampler realism).
