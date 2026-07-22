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
| `formal-rule` | **Not available** | No formal per-call constraint rules exist in this repo (meanings come from GIB, which is descriptive, not a sampler). Not faked. |
| `uniform` (offline baseline) | **Ships, Ben-free** | `UniformSampler`: unconstrained card-conserving completions. Honest `not_a_posterior` label. Runs the whole audit on real DDS without Ben and acts as a deliberate sampler-sensitivity counterpoint. |
| `fixture` / `synthetic` | Ships | Load/inject layouts (capture-once fixtures; test scenarios). |

**Environment note:** in the container that produced this document Ben was not
installed (`/home/user/ben` absent, no trained models), so the `current` /
`ben-replay` / `ben-likelihood` runs are marked `unavailable` in audit output
and their **live numbers must be produced under the Ben venv**
(`scripts/setup_ben.sh`). The acceptance/weighting math for all three is
implemented and unit-tested here, and the DDS + all diagnostics run live.

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

## 8. Quality flags (requirement 7) — never tuned to outcome

Thresholds are preconfigured and swept; the winner is **never** chosen after
seeing which lead wins. `quality_flag` (`engine/lead_posterior.py`) returns:

* `robust` — same winner across valid samplers/thresholds, adequate N/ESS,
  CI clear of 0, not tail-dominated;
* `sampler_sensitive` — winner changes or the gap collapses (min mean < ¼ max);
* `insufficient_evidence` — inadequate ESS or CI straddles 0 (fix by **more
  samples at the same threshold**, never by moving the threshold);
* `tail_dominated` — a tiny fraction of layouts drives the signed delta mass
  and the trimmed mean disagrees with / flips the raw mean.

A single "correct" lead is published only when `quality_flag == "robust"`
(`publishable_single_lead`).

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

**HA vs H4 tail/threshold result:** the owner's observation — HA−H4 falling
from **+0.371 @ τ=.70** to **+0.124 @ τ=.90** with occasional **+7** per-deal
deltas — has the signature of a **tail-dominated, threshold-sensitive** gap
under the neural-consistency filter `Q_τ`, *not* a DDS error. The audit's tail
diagnostics (`is_tail_dominated`, trimmed/winsorized means, top-k contribution)
and the score-bin / bridge strata (§ below) are built to quantify precisely
this, and the `--compare HA,H4` path reports it. **Producing the live per-layout
HA/H4 deltas requires the `current` sampler under the Ben venv**; in this
container that run is marked `unavailable`, so the numbers above are the owner's
reported values, and the reproduction command is:

```
trainer lead-posterior-audit --id lead1-0284459a \
  --auction "1S P 2C P 3D P 3NT P P P" --contract 3NTW \
  --samplers current --thresholds .70,.75,.80,.85,.90 \
  --compare HA,H4 --samples 512 --seed 1 --out output/lead1-0284459a.json
```

**Strata (requirement 5)** reported per sampler run (`strata_report`): score
bins .70–.75/.75–.80/.80–.85/.85–.90/.90+; partner/declarer/dummy length in the
led suit; location+length of the missing key honor; declarer HCP bins;
declarer balanced/semi/unbalanced shape. Each stratum reports count, weight
share, mean score, mean delta, total contribution, and win/loss/tie; then each
stratum is removed in turn (leave-one-out) and the new best / top gap /
best-minus-runner is reported. Diagnostic only — the headline ranking stays the
full-set mean DD.

**Board status:** because the live `current` run is unavailable here and the
reported gap is threshold-sensitive with a heavy tail, the board is currently
**`insufficient_evidence` / likely `tail_dominated`** pending a Ben-venv run; a
single "correct" lead should **not** be published for it until a robust
cross-threshold, adequately-sized run says so.

---

## 10. Findings summary

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
