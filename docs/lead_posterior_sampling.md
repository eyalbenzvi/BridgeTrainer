# Opening-lead posterior sampling — audit

Status: audit of the **actual** implementation on the pinned Ben commit
`2b534146415dcacb2f783bd9015b36df44dcf2bb` (see `scripts/setup_ben.sh`) plus
this repo's `bridge_trainer/engine/{ben,lead_maker,lead_verdict}.py`. Every
formula below is quoted from source; nothing is invented. Line references are
to the files as of this branch.

The objective is fixed and correct, and this audit does **not** change it:

```
best lead = argmax over legal PHYSICAL cards of
            E[ DD defensive tricks | leader hand, public auction, contract ]
```

The suspicion the owner raised — *a sampling/weighting bias that overvalues
ace leads, not a DDS problem* — is **confirmed as plausible and precisely
located**: the production estimator is a **thresholded uniform average over a
neural bidding-consistency filter**, i.e. it estimates a distribution `Q`, not
the intended posterior `P(deal | public information)`. The filter score is an
**uncalibrated heuristic in [0,1]**, not a likelihood. Details below.

---

## 1. What the production pipeline actually does

### 1.1 Entry points (this repo)

`engine/lead_maker.forge_lead_one` bids a board out, then grades leads through
two engine calls:

* **screen cascade (32 → 64 → 128):** `engine.lead_open(...)`
  (`engine/ben.py:300`) — samples layouts once, DD-solves incremental slices.
* **confirm (512) and the `lead_doubled` path:** `engine.lead_evaluate(...)`
  (`engine/ben.py:249`) — calls Ben's
  `BotLead.simulate_outcomes_opening_lead`.

Both ultimately call Ben's sampler
`Sample.generate_samples_iterative` (`src/sample.py:174` in Ben), whose
per-block workhorse is `sample_cards_auction` (`src/sample.py:567`). **That
function is where the proposal, the score, and the acceptance threshold live.**

### 1.2 Proposal generation

`sample_cards_auction` (Ben `src/sample.py:567`):

1. `get_bidding_info` (`:501`) runs Ben's neural `binfo_model` on the auction
   to get, for each of the three unseen seats, an estimated HCP mean
   (`c_hcp = 4x+10`) and a per-suit length mean (`c_shp = 1.75x+3.25`).
2. `sample_cards_vec` (`:264`) deals the **39 unseen cards** into LHO / partner
   / RHO (13 each) at random, lightly rejection-filtered so seats with a high
   estimated HCP/suit length tend to satisfy a loose bound (`accept_hcp`,
   `accept_shp`, `:432`–`:450`). The leader's 13 cards are fixed. **Proposals
   are complete, card-conserving deals consistent with the leader's hand.**

Inputs that are fixed / public: the leader hand (`hand_str`), the full auction
(`auction`), vulnerability, dealer. The **source hidden deal is never passed
in** (see §4).

### 1.3 `biddingScore` — exact formula and meaning

For each unseen seat that made calls, `process_bidding` (Ben `src/sample.py:519`)
runs the seat's neural bidder/opponent model **forward on the sampled hand**
and reads the softmax probability it assigns to the **actual call made** at each
of that seat's turns. The seat's raw score is the **minimum over its turns**
(`:543`–`:545`):

```
s_seat = min over that seat's turns t of  P_NN(actual_call_t | sampled hand, auction)
```

A hard per-turn pre-filter drops any deal where the model gives the actual call
below `exclude_samples = 0.01` at any turn (`:548`).

The three seat scores are aggregated. With `use_distance = True` (the shipped
**BEN-21GF** default), it is a **bid-count-weighted average with partner
double-weighted**, rescaled to `[0,1]` (`:652`–`:669`):

```
distance     = (1-s_lho)·n_lho + 2·(1-s_partner)·n_partner + (1-s_rho)·n_rho
max_distance = n_lho + 2·n_partner + n_rho
biddingScore = (max_distance − distance) / max_distance        (clamped ≥ 0)
```

With `use_distance = False` it is instead the **single worst seat**:
`min(s_lho, s_partner, s_rho)` (`:675`–`:681`).

**Meaning:** `biddingScore ∈ [0,1]` measures *how confidently Ben's own neural
bidder would have reproduced the observed calls if the unseen hands were the
sampled ones*. It is **not** a probability of the deal, **not** normalized over
deals, and **not** calibrated. It is a consistency heuristic. Re-implemented
Ben-free and unit-tested in `engine.lead_posterior.bidding_consistency_scores`.

### 1.4 Acceptance and weighting

* **Acceptance (the swept knob):** keep deals with
  `biddingScore ≥ bidding_threshold_sampling` (Ben `src/sample.py:693`).
  Shipped value **0.70** (`BEN-21GF.conf [sampling]`). This is exactly the
  threshold the owner's sweep varies (.70 → .90).
* **Fallback:** if fewer than `min_sample_hands_auction = 15` survive, take the
  top-N by score regardless of threshold (`:698`–`:705`).
* **Trick averaging:** DD defensive tricks are averaged **uniformly** over the
  accepted deals. In this repo, `lead_verdict._averages` is a plain
  `np.mean` over the per-sample array (`engine/lead_verdict.py:67`). **The
  scores are used only for the accept/reject cut, not as averaging weights.**
* **One non-uniform wrinkle:** when Ben's sampler returns *more* accepted deals
  than requested, `simulate_outcomes_opening_lead`
  (Ben `src/botopeninglead.py:401`–`:415`) sub-selects the requested count
  **with probability ∝ score** (`np.random.choice(..., p=scores/Σscores)`), then
  averages DD uniformly over the sub-sample. So in the oversampled regime the
  *selection* is score-weighted even though the *average* is uniform. This repo's
  `lead_open` screen path instead **shuffles uniformly and truncates**
  (`engine/ben.py:366`–`:371`), ignoring scores. **Screen and confirm therefore
  use different selection rules within the accepted set** — documented here as a
  real inconsistency, not a bug we silently "fixed".

### 1.5 The distribution actually estimated

Let `Q_τ` be the distribution of complete deals that (a) fix the leader's hand,
(b) are drawn from the binfo-guided proposal of §1.2, and (c) pass
`biddingScore ≥ τ`. The production system estimates

```
Ê_Q_τ[ DD defensive tricks(lead) ]   (uniform average over accepted deals)
```

with `τ = 0.70`. This is **not** `E_P[·]` for the intended posterior `P`. Honest
labels (persisted with every audit, requirement 3):

```
sampling_model               = "thresholded_uniform_neural_consistency"
posterior_calibration_status = "uncalibrated"
weighting_method             = "uniform_over_accepted"
score_threshold              = 0.70 (swept)
```

Because `biddingScore` is uncalibrated and the accept/reject cut is hard, `Q_τ`
can be **skewed relative to `P`** in ways that are *systematic in the auction*,
which is exactly the mechanism that can make one candidate (e.g. an ace) look
better or worse than under `P` — without DDS ever being wrong. Raising `τ`
keeps only the deals Ben is most sure reproduce the auction; if those deals are
disproportionately ones where the ace lead is good/bad, the gap moves with `τ`
(the observed .70→.90 drift for HA−H4). **DDS is exonerated; the estimator's
target distribution is the issue.**

### 1.6 Card space — a genuine low-card correctness concern

Ben grades leads in a **32-card space**: `lead_code32` folds ranks 7,6,5,4,3,2
into a single "low card per suit" slot (`engine/ben.py:57`, `:279`). Two
consequences in the **production** path:

* Distinct low spots in the same suit **share one grade** (`by_code`,
  `engine/ben.py:291`). 8 and 9 stay distinct; 7..2 collapse.
* When DD-solving a folded "low" lead, Ben's `double_dummy_estimates` leads a
  **randomly chosen** low pip (Ben `src/botopeninglead.py:445`–`:450`), not a
  specific physical card.

This does not corrupt honor leads and, on the reference board, the only low
heart is `H4` (so `HA/HQ/H9/H4` are already four distinct codes), but the
*mechanism* is exactly the "low card blurred into a representative" pattern the
owner asked to rule out. **The audit engine avoids it entirely:** it grades all
**13 physical cards** with endplay's `solve_board`, one DDS row per physical
card, no folding, no random substitution (`engine.lead_posterior._dd_defensive_
tricks`, `card_level_trace`). Touching cards then tie *because DDS says so*, not
because of dedup. See §6.

---

## 2. Enforced invariants (tests)

All in `tests/test_lead_posterior.py`, Ben-free, run in normal CI:

| Invariant | Test |
|---|---|
| Correct contract/declarer/dummy/leader mapping | `test_contract_mapping_reference_board` |
| DDS mapping correct (known board = 2 def tricks) | `test_dds_mapping_matches_known_result` |
| Rank encoding 2..A round-trips through DDS | `test_card_token_rank_encoding_all_ranks` |
| Card-conserving sampled deals | `test_uniform_layouts_card_conserving`, `test_malformed_layout_rejected` |
| Every physical lead evaluated exactly once, shared layouts | `test_every_physical_lead_evaluated_once_on_shared_layouts` |
| Deterministic sampling from seed | `test_uniform_deterministic_in_seed` |
| Source-deal independence (identical public state+seed ⇒ identical result) | `test_source_deal_independence_identical_public_state`, `test_source_deal_cannot_enter_signature` |
| Ben score formula (distance & min modes, exclude) | `test_bidding_consistency_*` |
| Threshold acceptance | `test_accept_thresholded` |
| Ben exact-replay rejects any mismatch | `test_replay_exact_mask_rejects_any_mismatch` |
| Likelihood log-sum-exp weights + ESS stability | `test_likelihood_weights_normalize_and_ess` |
| Tail-dominated / sampler-sensitive / insufficient / robust flags | `test_tail_dominated_detection`, `test_quality_flag_*` |
| Low-card correctness (see §6) | `test_low_cards_*`, `test_card_trace_*`, `test_candidate_sorting_*` |
| Explicit auction-constraint sampler honours HCP/suit-length bands, importance-weights, source-independent (§11) | `test_constraint_sampler_*` (`tests/test_lead_constraint_calibration.py`) |
| Calibration vs real deals detects miscalibration on announced-suit lengths (§12) | `test_calibration_*` |

---

## 3. Persisted audit fields (requirement 3)

Every audit run records, per sampler run
(`LayoutSet.provenance()` in `engine/lead_posterior.py`):

```
sampling_model, sampler_version, posterior_calibration_status,
weighting_method, score_threshold, proposal_count, requested_samples,
accepted_samples, ess, seed, auction_replay_mode, semantic_constraint_mode,
source_deal_independent
```

Honest label examples are baked into the samplers (`engine/lead_samplers.py`):
the production adapter reports
`thresholded_uniform_neural_consistency` / `uncalibrated` /
`uniform_over_accepted`; the offline baseline reports
`uniform_unconstrained` / `not_a_posterior`.

---

## 4. Source-deal independence — proof

The lead sampler's RNG seed is `calculate_seed(hand_str)` =
`sha256(leader_hand)[:4] mod (2³²−1)` (Ben `src/util.py:136`, used at
`src/botopeninglead.py:32`). It is a function of **the leader's hand only** —
not the source deal, not an external `--seed`. And `lead_evaluate` /
`lead_open` receive only `(hand, seat, dealer, vul, auction, contract)`; the
other three source hands are never arguments. Therefore:

* **Given identical public state, the accepted sample set is identical
  regardless of what the true hidden deal was.** Two boards that happen to
  produce the same auction + leader hand get identical lead evaluations.
* Consequence for `--seed`: for a *fixed* board the lead sampling is fully
  deterministic but **not** externally reseedable (Ben ignores an outer seed
  here). The audit records the effective seed and proves reproducibility via
  `result_signature`.

The audit engine makes this structural: samplers take only `(LeadProblem,
seed)`; `LeadProblem` has no source-deal field. `problem_fingerprint` hashes
public state + seed; `result_signature` hashes the graded layouts + per-card
trick vectors. Equal fingerprints ⇒ equal signatures is asserted in tests.

---

## 5. Sampler modes (requirement 6)

`engine/lead_samplers.py`. All modes share the same public state, fixed leader
hand, physical-card candidate set, endplay DDS, and comparable accepted-sample
counts.

| Mode | Status | Notes |
|---|---|---|
| `current` (thresholded-uniform neural) | **Requires Ben venv** | `BenCurrentSampler`; extracts accepted deals + scores from Ben's opening-lead sampler; honest uncalibrated labels; threshold is the swept knob. |
| `ben-replay` (exact auction reproduction) | **Requires Ben venv**; math implemented+tested | Accept only deals where the bidder's argmax reproduces **every** observed call. Pure logic: `replay_exact_mask`. |
| `ben-likelihood` (log-sum-exp weights) | **Only if valid per-legal-call probabilities exist**; math implemented+tested | `policy_full` (`engine/ben.py:144`) exposes the full per-call softmax, so a genuine per-call likelihood is available. Weighting + ESS: `likelihood_log_weights`. Still uncalibrated as a *deal* posterior; use with ESS reported. |
| `constraint` (explicit auction constraints) | **Ships, Ben-free** | `ConstraintSampler` (requirement 3, first bullet): applies the accumulated auction constraints — per concealed seat, weighted HCP / suit-length / suit-quality bands, conditional denials, and named exclusion predicates (shape/convention meaning) — via the existing `RuleEngine` + YAML rulesets and the vectorised `RejectionDealSource`. Soft margin bands become **importance weights** (ESS reported). Constraints can be derived from the auction (`from_auction`, unrecognised calls surfaced, not dropped) or supplied explicitly. Honest label: `auction_constraint_bands` / **`modelled_prior_uncalibrated`** — a per-seat modelled prior, *not* a calibrated deal posterior, and it does not encode cross-hand partnership fits. `semantic_constraint_mode` is finally set (`explicit` or `rule_engine:<system>`), never `none`. It **votes** as an independent auction-aware sampler, but only when at least one concealed seat was actually constrained (an all-unrecognised auction leaves it equivalent to uniform, so it abstains). |
| `formal-rule` | **Partially available** | The `constraint` sampler above *is* the formal per-call constraint path where rulesets match; coverage is limited to the shipped rulesets (`our_2over1`, `opps_sound`, `opps_light_preempts`) and unmatched calls degrade gracefully. Not faked; the gap is reported in `constraint_diagnostics.unrecognized_calls`. |
| `uniform` (offline baseline) | **Ships, Ben-free** | `UniformSampler`: unconstrained card-conserving completions. Honest `not_a_posterior` label. Runs the whole audit on real DDS without Ben and acts as a deliberate sampler-sensitivity counterpoint. |
| `fixture` / `synthetic` | Ships | Load/inject layouts (capture-once fixtures; test scenarios). |

**Environment note:** Ben (pinned commit, trained models) was installed via
`scripts/setup_ben.sh` and the `current` sampler was **run live** — see §9 for
real reference-board numbers. `ben-replay` / `ben-likelihood` expose their
acceptance/weighting **math** (unit-tested: `replay_exact_mask`,
`likelihood_log_weights`), but their Ben-backed *proposal scorer* (per-seat,
per-turn call probabilities extracted from Ben's bidder) is not yet wired, so
those two modes report `unavailable` until that adapter lands. The `current` and
`uniform` samplers, DDS, and every diagnostic run live.

---

## 6. Low-card correctness audit (follow-up)

Verified **end-to-end, card level**, in the audit engine and tests:

1. **Exact physical card to DDS.** `card_level_trace` logs, per candidate, the
   DDS input suit/rank/leader/strain and the token echoed back from the DDS
   result. On the reference board `HA/HQ/H9/H4` each map to their own row with
   `matched=True` (`test_card_trace_maps_each_physical_card_to_its_own_dds_result`).
   No 2/3/4→"low" conversion, no lowest/highest/representative substitution
   (endplay returns one row per physical card).
2. **Low cards are distinct candidates.** `H4` and `H9` are separate
   candidates with separate aggregation slots even when DDS returns equal
   values; equality comes from DDS, not dedup
   (`test_two_low_cards_dds_equal_stay_separate_candidates`).
3. **Complete enumeration.** Exactly 13 candidates, all distinct, one per card,
   suit-then-rank; the candidate list equals the cards sent to DDS
   (`test_every_physical_lead_evaluated_once_on_shared_layouts`,
   `card_level_audit.all_distinct`).
4. **Card-correct extraction.** Result read for a lead corresponds to the
   requested suit/rank (`_card_token`: suit `card.suit.name[0]`, rank
   `card.rank.name[1]`, covering 2..9,T,J,Q,K,A —
   `test_card_token_rank_encoding_all_ranks`). endplay returns physical cards,
   not equivalence masks, so no grouped-rank mapping is needed; the audit never
   reuses an honor's result for a low-card request
   (`test_low_cards_are_distinct_candidates_with_distinct_values`).
5. **Card-correct aggregation.** Each card's mean/delta/CI/rank use that card's
   own per-layout vector, keyed by the card token (not a positional index), so
   sorting cannot detach a card from its result
   (`test_candidate_sorting_cannot_detach_card_from_result`).
6. **Explicit per-card output.** `card_level_audit` (candidate→index, mean,
   rank, min/max, focus-pair difference counts) and `card_level_trace` (per
   layout) are emitted in the audit JSON (`--card-trace-layouts N`).

**Production caveat (real finding):** the *shipped* Ben path folds 7..2 into one
"low" code and DD-solves a random low pip (§1.6). That is a genuine low-card
blurring in production; the audit engine does **not** inherit it and grades
physical cards. No index-alignment, dedup, or rank-mapping *defect* was found in
the audit engine; the production 32-code folding is a documented modelling
choice to be aware of when comparing audit numbers to shipped verdicts.

---

## 7. CLI

```
trainer lead-posterior-audit --id lead1-0284459a \
  --auction "1S P 2C P 3D P 3NT P P P" --contract 3NTW \
  --samplers current,uniform,ben-replay,ben-likelihood \
  --thresholds .70,.75,.80,.85,.90 \
  --compare HA,H4 --samples 512 --seed 1 --out output/audit.json
```

Emits one JSON record: per-sampler provenance, proposal/acceptance/ESS, all 13
lead EVs, best-vs-runner-up and `--compare` delta/tail metrics, strata +
leave-one-stratum-out, card-level audit (+ optional per-layout traces),
cross-sampler agreement, and a quality flag. **Sampled full deals appear only
in this audit/debug output, never in normal UI.** `--id` regenerates the deal's
public state from its seed (Ben-free); the auction must be supplied because
reproducing the bidding needs the engine.

---

## 8. Quality flags + publication gate — never tuned to outcome

Thresholds are preconfigured and swept; the winner is **never** chosen after
seeing which lead wins.

**Hard correctness gate (blocks publication).** `correctness_gate` runs every
hard check — exactly 13 distinct physical leads, all on the same layouts, card
conservation, correct declarer/dummy/leader mapping, fixed-seed reproducibility
(identical `result_signature` on a repeat), and source-deal independence — and
`publication_verdict` blocks publication on ANY failure, independent of the
robustness state (requirement 1).

**Robustness state — three canonical values** (`quality_flag`, requirement 4):
* `sampler_sensitive` — the winner changes across preconfigured thresholds or
  **valid** samplers. Only auction-aware posterior samplers vote (`current`,
  `ben-replay`, `ben-likelihood`); the `uniform`/`fixture` baselines are
  not-a-posterior contrasts and do **not** vote.
* `insufficient_evidence` — inadequate ESS, a CI straddling 0, or a
  tail-dominated mean. Fix by **more samples at the same threshold**, never by
  moving the threshold.
* `robust` — otherwise.

**Threshold decay is a warning, not a rejection (requirement 5).**
`margin_decay_ratio = strict-τ gap / primary-τ gap`. A ratio below 1 is
reported but does **not** by itself downgrade the verdict — `quality_flag`
deliberately does not flag on gap decay alone. It downgrades only on real
instability (winner change, CI including 0, low ESS, tail domination, or
independent-sampler disagreement), which `margin_decay` surfaces as explicit
`instability_signals`.

A single "correct" lead is published only when the correctness gate passes AND
the state is `robust` (`publishable_single_lead`).

## 8a. Independent audit samplers (requirement 2) — implemented & live

Both are wired to Ben's public API (`engine/lead_samplers.py`) and run live:
* **`ben-replay`** (`ben_exact_auction_replay`): proposes Ben's binfo pool, then
  keeps a deal ONLY if Ben's bidder reproduces **every observed call as its
  argmax** (`_ben_auction_scores` → `replay_exact_mask`). Uniform over the
  exact-replay set. An independent cross-check of the production consistency
  score.
* **`ben-likelihood`** (`ben_auction_likelihood_weighted`): weights each
  proposal by the observed auction's log-likelihood under Ben's per-legal-call
  softmax (`policy_full` → `likelihood_log_weights`, stable log-sum-exp), with
  **ESS reported**. Honestly labelled `importance_weighted_uncalibrated` — the
  proposal is binfo-guided, so the weights are auction-likelihood importance
  weights, not a calibrated posterior; ESS states usability.

## 8b. Adaptive sample size + validation corpus (requirements 3 & 6)

* `adaptive_sample` starts at 256 accepted deals and escalates to 512/1024 only
  when the CI includes 0, ESS is inadequate, or the mean is tail-dominated —
  spending runtime only where robustness demands it.
* `engine/lead_corpus.py` + `trainer lead-corpus`: a blind-labelled validation
  corpus (stable control, ace-overpreference control, low-card mapping,
  source-leak probe, tail-dominated, sampler-sensitive) with a runner reporting
  label agreement, ace-win rate, robustness rate, and mapping/leak failures.
  Current synthetic result: **100% label agreement, 0 mapping failures, 0
  source-leak failures**; the ace-overpreference control correctly picks a
  passive club, confirming neither a pro- nor anti-ace pull. Expert-suspect real
  boards are registered with recorded labels and run when Ben is present.

---

## 9. Reference board `lead1-0284459a`

Regenerated Ben-free from seed `0x0284459a` (`engine.scanner.deal_board`):

```
N 874.AQ94.T.97642   (= S874 HAQ94 DT C97642, the leader)
E AKJT96.K3.9832.K    dealer E, vul Both
S 53.J872.J654.AJT
W Q2.T65.AKQ7.Q853
auction 1S P 2C P 3D P 3NT P P P  →  3NT by W, N on lead   ✓ matches the brief
```

Mapping (leader N, declarer W, strain NT) and the North hand match the brief
**exactly** — verified without Ben (`test_contract_mapping_reference_board`).
The actual deal's DD is 3NT+2 (defence 2 tricks); this is the *hidden truth*
and is deliberately **not** used in ranking (source-deal independence).

**HA vs H4 — measured live** under the production `current` sampler (Ben
installed at the pinned commit; `--samples 300 --seed 1`,
`output/lead1-0284459a.json`):

| τ | accepted n / ESS | HA mean | H4 mean | HA−H4 delta | boot 95% CI | tail-dominated? | top-1% contrib |
|---|---|---|---|---|---|---|---|
| .70 | 206 | 2.175 | 1.723 | **+0.452** | [0.32, 0.60] | no | 0.18 |
| .75 | 172 | 2.116 | 1.657 | +0.459 | [0.31, 0.62] | no | 0.15 |
| .80 | 128 | 2.172 | 1.781 | +0.391 | [0.24, 0.54] | no | 0.22 |
| .85 |  53 | 2.189 | 1.849 | +0.340 | [0.09, 0.64] | no | 0.28 |
| .90 |  34 | 2.412 | 2.235 | **+0.176** | [−0.09, 0.47] | no | 0.50 |

This **reproduces the owner's decay** (+0.371 → +0.124 reported; +0.452 → +0.176
measured, same direction and rough magnitude at a different seed/N) and lets us
answer the actual question:

* **Is HA−H4 tail-dominated?** **No, not at the production threshold.** At τ=.70
  the split is win 43% / loss 9% / tie 48% (median delta 0), conditional
  win/loss ±1.2 tricks, trimmed-5% mean +0.321, winsorised(cap 2) +0.388, and
  the top 1% of layouts supply only ~18% of the mass. HA's edge is a **broad,
  real double-dummy plurality**, not one freak layout. The **+7 deltas the owner
  saw are located**: the `HK@declarer(len1)` stratum (a stiff heart king) —
  mean delta **+6.0** but only **2 layouts** (13% of the gap); plus
  `HK@dummy(len1)` (+2.5, 6 layouts). Real but not dominant.
* **Why does the gap decay .70 → .90?** The **score-bin strata** show HA's edge
  is present in every bin (+0.41 / +0.66 / +0.43 / +0.63) **except the `.90+`
  bin, where it collapses to +0.176**. Raising τ preferentially keeps exactly
  those highest-consistency deals where the ace barely wins, while N/ESS
  collapse 206 → 34 and the CI crosses 0. This is the **thresholded-neural-
  consistency bias made concrete** — `Q_τ` reweighting toward low-edge layouts,
  not DDS error and not tail-trimming.

Reproduce with:

```
BEN_HOME=/path/to/ben  trainer lead-posterior-audit --id lead1-0284459a \
  --auction "1S P 2C P 3D P 3NT P P P" --contract 3NTW \
  --samplers current,uniform --thresholds .70,.75,.80,.85,.90 \
  --compare HA,H4 --samples 300 --seed 1 --card-trace-layouts 2 \
  --out /abs/path/output/lead1-0284459a.json
```

**Low-card correctness on the real Ben layouts** (`card_level_audit`): all 13
candidates distinct; HA/HQ/H9/H4 occupy separate aggregation slots (indices
3/4/5/6); HA and H4 return **different** DD values on 107 of 206 layouts and
equal on 99 — i.e. they are genuinely solved separately (traces: `HA→HA`,
`H4→H4`, matched). **No dedup / index / rank defect.**

**Strata (requirement 5)** reported per run (`strata_report`): score bins;
partner/declarer/dummy length in the led (heart) suit; location+length of the
missing key honor (**HK** here); declarer HCP bins; declarer shape class. Each
stratum reports count, share, mean score, mean delta, contribution, win/loss/
tie; then leave-one-stratum-out reports the new best / top gap / best-minus-
runner. Diagnostic only.

**Cross-sampler — all four samplers, live** (`output/lead1-0284459a.allsamplers.json`,
`--samples 200`): every **valid auction-aware** sampler agrees on **HA** —
`current` at τ=.70/.80/.90, `ben-replay` (57 exact-replay deals), and
`ben-likelihood` (ESS 94). Only the `uniform` *not-a-posterior* baseline picks a
passive club (C7), reported as a contrast, not a vote. So HA is **not** a
production-sampler artefact — it survives an independent exact auction replay
and auction-likelihood weighting.

**Board status — measured:** correctness gate **passes** (all six checks). HA is
best under the **production τ=0.70** (delta +0.45, CI [0.32, 0.60], not
tail-dominated, broad win plurality) and under both independent samplers. But
the verdict is **`insufficient_evidence`, not robust**: the margin decays sharply
(`margin_decay_ratio = 0.21`) and at the strict τ=0.90 the CI includes 0 with
ESS 34 — real instability (not decay alone), so `decay_is_warning_only = False`.
`publishable_single_lead = False`. The ace here is a **genuine DD winner that all
valid posterior samplers favour** — the audit found no mechanism inflating it —
but the evidence is not strong enough across a stricter audit to publish it as
THE single answer. Increase samples at τ=.70 (not by moving τ) to firm it up.

---

## 9a. Before/after low-card audit — suspect boards

`scripts/lead_before_after.py` reconstructs a board with Ben (bid-out), then on
the SAME sampled layouts grades every lead two ways: **legacy** = Ben's 32-code
folding (ranks 7..2 share one code, DD of a random low pip;
`legacy_folded_eval`) and **fixed** = physical per-card endplay. Both share
layouts, weights, and DDS, so the only variable is the low-card handling. It
sweeps τ, checks determinism + source independence, cross-checks Ben's own
`lead_evaluate`, and computes ace-vs-best-non-ace tail/strata. JSON:
`output/lead1-*.before_after.json` (`--samples 300 --seed 1`).

| Board | Before winner | After winner | Changed? | gap b/a @.70 | Ace mapping bug? | Source leak? | Tail-dominated? | Threshold/sampler-sensitive? | Quality |
|---|---|---|---|---|---|---|---|---|---|
| `lead1-02faf4ff` 4HE, S leads (SA) | SA | SA | no | +0.26 / +0.26 | no | no | no | **yes** (SA→DT→SA over τ; gap 0.0 @.80; CI crosses 0 @.90) | insufficient_evidence |
| `lead1-03473cc7` 4HN, E leads (CA) | CA | CA | no | +0.39 / +0.39 | no | no | no | no (CA at every τ) | **robust** |

Per board:

**`lead1-02faf4ff`** (S holds `A542.Q7.T85.Q643`, leads vs 4HE)
1. **No bug found.** Legacy and fixed give the identical winner and gap at every
   threshold (0 rank shifts here); Ben's own `lead_evaluate` also returns SA
   (1.71) over DT (1.45). The audit maps all 13 physical cards distinctly; the
   ace suit's low spots (S5/S4/S2) each have their own slot.
2. **Does a bug explain the SA recommendation?** No — there is no bug. SA is a
   genuine DD winner at τ=.70 (delta +0.26 vs DT, CI [0.14, 0.36], win/loss/tie
   30/9/61, not tail-dominated).
3. **Robust?** **No.** The fixed winner flips to DT at τ=.80 (gap 0.0) and the
   ace edge's CI crosses 0 at τ=.90 (n=35). Threshold-sensitive / insufficient.
4. **Verdict: FLAG.** Do not publish SA as the settled single answer; re-audit
   with more samples at fixed τ, and keep only if it becomes `robust`.

**`lead1-03473cc7`** (E holds `T83..J87542.AQ74`, leads vs 4HN)
1. **No bug found.** Legacy folding reshuffles 6 low cards' apparent ranks but
   never the winner; the ace (CA, an honor) is folding-invariant. All 13 cards
   map distinctly; no source leak; deterministic repeat.
2. **Does a bug explain CA?** No — CA is robustly best: fixed, legacy, AND Ben's
   own `lead_evaluate` (CA 2.26 over S8) all agree.
3. **Robust?** **Yes.** CA wins at every threshold .70–.90; delta +0.27 to
   +0.39, CI clear of 0, not tail-dominated, broad 42/16 win plurality.
4. **Verdict: KEEP.**

**Cross-board conclusion:** on neither board is the ace recommendation a
low-card / mapping / source-leak artefact — the low-card fix leaves the winner
unchanged because both answers are aces (honors, never folded). The real
discriminator is *threshold robustness*: CA (`03473cc7`) is robust and stays;
SA (`02faf4ff`) is threshold-sensitive and is flagged. Note the general risk the
legacy folding *does* carry — it can misrank a suit's **low cards** among
themselves (6 shifts on `03473cc7`), so any board whose answer is a spot card
must be graded with the physical-card engine, not the 32-code path.

---

## 11. Explicit auction-constraint sampler (requirement 3, first bullet)

Previously the audit's `semantic_constraint_mode` was always `none`: the
production `current` sampler used Ben's neural consistency filter, the
independent samplers used exact-replay / likelihood, and the offline baseline
was unconstrained uniform. **No path applied the auction's *explicit* HCP /
suit-length / shape / convention constraints.** That is now `ConstraintSampler`
(`engine/lead_samplers.py`), wiring the repo's existing constraint stack —
`domain.constraints` (weighted bands), `semantics.engine.RuleEngine` + YAML
rulesets, `semantics.predicates` (shape/convention exclusions), and the
vectorised `dealing.rejection.RejectionDealSource` — into the lead audit.

What it does, precisely:

* **Constraints.** For every concealed seat, the accumulated auction
  constraints are: weighted **HCP** bands, per-suit **length** bands, per-suit
  **quality** (honor-strength) bands, conditional **denials**, and named
  **exclusion predicates** (shape/convention meaning). They are derived from
  the public auction by the rule engine (`from_auction`), walking every
  concealed call — passes included — and merging matched rules (conjunction ⇒
  weights multiply). Unmatched calls **degrade gracefully** and are reported in
  `constraint_diagnostics.unrecognized_calls`; nothing is faked.
* **Proposal + acceptance.** `RejectionDealSource` fixes the leader's 13 cards
  and rejection-samples card-conserving completions for the other three seats
  that satisfy the hard bands; **soft margin bands become per-deal importance
  weights**, so the trick average is weight-aware and **ESS is reported**.
* **Honest labels (requirement 3).** `sampling_model =
  auction_constraint_bands`, `posterior_calibration_status =
  modelled_prior_uncalibrated`, `weighting_method =
  constraint_importance_bands`. It is a **per-seat modelled prior, not a
  calibrated deal posterior**, and the per-seat band model does **not** encode
  cross-hand partnership fits — stated plainly, never called a probability.
* **Determinism / independence.** The RNG seed and the constraints both derive
  only from public state, so runs are deterministic in the seed and
  source-deal independent (same tests as the other samplers:
  `test_constraint_sampler_deterministic_and_source_independent`).
* **Voting.** It is an independent auction-aware sampler and therefore **votes**
  in the cross-sampler verdict — but only when at least one concealed seat was
  actually constrained (an all-unrecognised auction leaves it equivalent to
  uniform, so it abstains rather than masquerade as a vote).

CLI: add `constraint` to `--samplers`. Runtime note: rejection acceptance falls
with constraint tightness; the sampler carries a `max_seconds` budget and
reports `shortfall`. Filter-before-DDS still holds — constraints cut the batch
before any board is double-dummied.

## 12. Calibration against real deals (requirement 6)

The blind-labelled corpus (§8b) checks *verdict* agreement; it never asked
whether a sampler's hidden hands *look like real hidden hands*. `engine/
lead_calibration.py` + `trainer lead-calibration` add that posterior-predictive
check, Ben-free and sampler-agnostic:

* **Group by auction family.** `auction_family_key` canonicalises the public
  auction (trailing passes dropped); real complete deals sharing an auction are
  one family.
* **Two distributions, by role.** The **real** distribution pools each board's
  actual hidden hands (declarer / dummy / partner). The **model** distribution
  runs the sampler on each board's public state and pools every sampled hidden
  hand. Both are compared marginally.
* **Features (requirement 6, verbatim):** HCP, shape class, **announced-suit
  lengths**, the declarer+dummy **fit** in each announced suit, **controls**
  (A=2, K=1), and **key-honor locations** (which role holds each suit's A / K).
  Divergence is total-variation distance over the binned marginals, in [0, 1];
  a family is `calibrated` only if no role/feature exceeds the tolerance, else
  `miscalibrated` with the offending `(role, feature)` pairs (or
  `insufficient_real_data`).
* **It actually detects miscalibration.** On a family whose declarer always
  holds six of the announced suit, the `uniform` sampler is flagged
  `miscalibrated` with `declarer.len_S` TV ≈ 0.96 (real mean 6.0 vs sampled
  ≈3.4); a `constraint` sampler that respects the announced suit drives that to
  TV = 0.0 (model mean 6.0). Tests:
  `test_calibration_detects_uniform_miscalibration_on_announced_suit`,
  `test_calibration_constraint_sampler_matches_announced_suit`.

CLI: `trainer lead-calibration --deals real_deals.json --sampler
{uniform|constraint}` prints per-family labels and the most-frequently-off
features. This is the tool to run offline on a real-deal corpus grouped by
auction family before trusting any sampler's posterior on that family.

## 13. Findings summary

* **Added (requirement 3, first bullet):** an explicit auction-constraint
  sampler (§11) — HCP / suit-length / suit-quality / denial / exclusion bands
  from the auction, importance-weighted, ESS-reported, honestly labelled a
  *modelled prior, not a posterior*. `semantic_constraint_mode` is no longer
  always `none`.
* **Added (requirement 6):** a real-deal calibration harness (§12) comparing
  sampled vs real hidden-hand distributions by auction family on HCP, shape,
  announced-suit lengths, fits, controls, and honor locations — and it
  demonstrably flags a uniform sampler as miscalibrated on the announced suit.
* **Confirmed:** the production estimator targets a *thresholded uniform neural
  consistency distribution `Q_τ`*, not the intended posterior `P`; the filter
  `biddingScore` is an **uncalibrated heuristic**, not a likelihood (§1.3–1.5).
  This is the plausible source of ace-lead over/under-valuation and of the
  threshold sensitivity — **not DDS**.
* **Confirmed real:** production folds low cards 7..2 into one code and
  DD-solves a random low pip (§1.6); screen vs confirm use different in-set
  selection (§1.4). Both documented; the audit engine avoids both.
* **Rejected:** no DDS mapping defect (reference board reproduces 3NT+2); no
  candidate dedup / index-misalignment / rank-encoding defect in the audit
  engine (§6).
* **Source-deal independence:** structurally guaranteed (seed = hash(leader
  hand); source hands never passed) and tested (§4).
* **Not changed:** the objective, DDS, the mean-DD ranking. All new numbers are
  diagnostics.
* **Regeneration:** boards whose published single lead rests on a
  threshold-sensitive or tail-dominated gap (candidate: `lead1-0284459a`)
  should be re-audited under the Ben venv and only kept if `robust`.
