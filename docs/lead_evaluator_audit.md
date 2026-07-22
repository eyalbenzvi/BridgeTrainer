# Opening-lead evaluator: audit and correction

Implementation-level audit of the opening-lead problem generator/evaluator,
tracing the real data path and fixing verified defects. Nothing here relies on
the source deal, hidden cards, or the source board's double-dummy result: the
grade depends only on the opening leader's 13 cards, the public auction,
contract/declarer, vulnerability, dealer, and the sampler seed/config.

> Scope note: seat order is **absolute NESW = 0,1,2,3** everywhere in the
> application. This was verified, not assumed (see §1.1).

---

## 1. Traced data path

### 1.1 Compass-seat encoding (verified, not assumed)

| Stage | File / symbol | Seat encoding |
|---|---|---|
| Deal generation | `engine/scanner.py::deal_board` | `hands[i]`, `i = 0..3 = N,E,S,W` (`rng.permutation(52)` sliced 13/13/13/13; `dealer_i`, `vul` follow) |
| Auction | `engine/scanner.py::bid_out`, `conventions.seat_of(dealer_i, idx)` | tokens run from the dealer; `seat_of = (dealer_i + idx) % 4` |
| Contract / declarer | `conventions.final_contract` | `declarer_i` absolute 0..3; declarer = first of the winning side to name the strain |
| Opening leader | `conventions.opening_leader(declarer_i)` | `(declarer_i + 1) % 4` (declarer's LHO) |
| Ben adapter | `engine/ben.py` (`SEATS = "NESW"`) | same absolute indices; `pad(dealer_i, auction)` prepends `dealer_i` PAD tokens for Ben's N-first convention |
| Layout sampler (Ben) | Ben `translate_hands` | **hero-first**: PBN row position `p` is absolute seat `(bot.seat + p) % 4`. Confirmed from the working bidding DD `engine/ben.py::_tricks_dd_memo`, which rotates `leader = (leader + 4 - bot.seat) % 4`. |
| DDS adapter (endplay) | `engine/lead_evaluate.py::_deal_for` | `Deal("N:<N> <E> <S> <W>")` (absolute), `deal.first = leader_i` |
| UI record | `engine/lead_maker.py::build_lead_record` | `SEATS[i]` names |

The one place the sampler's hero-first order becomes absolute is
`engine/lead_cards.py::hero_first_to_absolute` — the **single seat-conversion
layer** (§2). No ad-hoc rotations elsewhere.

### 1.2 Card representations

* **Physical / display / DDS card** — the exact card, e.g. `"S7"`
  (`engine/lead_cards.py::physical_cards`, matching `engine/ben.py::cards_of`).
  These three are always the identical string.
* **Policy action** — Ben's abstract 32-card lead action
  (`engine/lead_cards.py::policy_action` / `lead_code32`): honors and 8/9 keep
  their rank; spots **7..2 fold to `"<suit>-low"`** / code slot 7. Used only to
  look up Ben's neural policy probability.

### 1.3 Which physical card reaches DDS

After the fix: every one of the **13 physical cards** is double-dummied
separately by endplay `solve_all_boards` in
`engine/lead_evaluate.py::score_layouts`. The returned `(Card, tricks)` pairs
are the *leader's-side* (defensive) tricks per card; the DDS candidate token is
the exact physical card (`token_from_endplay_card`).

### 1.4 Source-deal influence on sampling / scoring

None. The sampler is invoked through
`evaluate_leads_from_public_state(..., sampler=…, source_deal=…)`, where
`source_deal` is `del`-eted on the first line and never reaches the sampler,
the scorer, or the policy. The Ben-backed sampler
(`engine/ben.py::lead_evaluate`'s inner `sampler`/`policy`) builds its bot from
the **displayed leader hand + public auction + dealer + vul only**. See §5 and
`tests/test_lead_purity.py`.

---

## 2. Verified defect #1 — spot folding *before* DDS (fixed)

**Before.** `engine/ben.py::lead_evaluate` and `lead_open` built the DDS
candidate set as `codes = sorted({lead_code32(t) for t in held})` — the
**folded 32-code set** — and asked Ben to double-dummy those codes. Every low
spot of a suit therefore shared a single DD value (whatever card Ben's code→card
map led), and the candidate set passed to DDS was *not* the 13 physical cards.
This directly violates the requirement that DDS evaluate each legal physical
card separately, and it is exactly the kind of abstraction that can move which
card is reported as "best."

**Evidence it matters.** endplay distinguishes physical cards routinely: for the
audit fixture (South vs 3NT-E) `♥T/♥J → 3` defensive tricks but `♥6/♥8 → 2`;
folding those into one heart-low action loses the distinction. `deal_board(1)`'s
North hand collapses from 13 physical cards to **9** Ben codes.

**Fix.** `score_layouts` double-dummies all 13 physical cards via endplay (the
DDS the rest of the project already uses). The 32-code fold survives **only** in
`lead_softmax` / `answer_policy_mass` for the C1 policy gate. Tests:
`tests/test_lead_evaluate.py::test_all_13_physical_cards_scored_separately`,
`::test_spot_cards_resolved_independently_not_folded`,
`::test_display_card_equals_dds_card`;
`tests/test_lead_cards.py::test_policy_action_never_changes_physical_card_identity`.

---

## 3. Physical vs policy separation (new module)

`engine/lead_cards.py` is the single home of the suit/rank ordering and of the
four card concepts:

```
physical_card  exact legal card  "S7"   -> DDS evaluates this
display_card   UI card                  == physical_card
dds_card       card sent to DDS         == physical_card
policy_action  Ben 32-card action "S-low" for 7..2 (policy lookup ONLY)
```

Rules enforced by code + tests:

* DDS scores each physical card separately; no 7..2 folding before/at DDS.
* Folding is permitted **only** for Ben's policy probability.
* `physical_card == display_card == dds_card` for every candidate
  (`lead_debug` records all four side by side).
* Rank order cannot invert 2..A (`RANKS = "AKQJT98765432"`, one definition;
  `tests/test_lead_cards.py::test_rank_index_cannot_invert_2_to_A`).
* Candidate enumeration is exactly the 13 physical cards, once each
  (`physical_cards`; invariant + DDS-result checks in §4).

The stored record schema is unchanged and back-compatible; the richer
per-candidate `physical_card`/`policy_action`/`dds_card` breakdown is added in
the **debug artifact** (§7), not by rewriting historical records.

---

## 4. DDS semantics and sign convention (verified)

* **Solver**: endplay `solve_all_boards` on `Deal("N:…")` with `deal.trump`
  set to the contract strain and `deal.first = leader_i` (declarer's LHO).
* **Return**: for the player on lead, `(card, tricks)` where `tricks` is the
  number of tricks **that player's side (the defence)** takes with best play
  after leading `card`. So it *is* defensive tricks directly.
* **Conversion**: `declarer_tricks = 13 - defensive_tricks`. Cross-checked
  against `calc_all_tables`: audit fixture defence max = 3 ⇒ declarer 10 =
  `calc_all_tables[NT, E]`.

Objective implemented: `defensive_tricks(card) = leader_side_tricks(card)`;
equivalently `13 - declarer_max_tricks_after_that_exact_card`.

**Golden-board test** (`tests/test_lead_evaluate.py`, runs in normal CI because
endplay is a hard dependency):
`test_golden_board_matches_direct_dds_and_ranking` scores all 13 cards through
the production `score_layouts` path and, independently, through a bare
`solve_all_boards` call, and asserts the same card list, the same per-card
values, and the same ranking. `test_sign_convention_is_defensive_not_declarer`
fails if the sign is reversed (`x` vs `13 - x`).

> If an environment lacks endplay, mark these as integration tests. Run locally
> with `pip install -e .[dev] && pytest tests/test_lead_evaluate.py`. All
> mapping/conversion logic (`tests/test_lead_cards.py`,
> `tests/test_lead_invariants.py`) is DDS-free and always runs.

### Runtime invariants (new module `engine/lead_invariants.py`)

Before every DDS solve, `check_layout` asserts (with the problem id, sample
index, sample seed, offending card and compass seats in the message):

* four hands, 13 cards each, all 52 unique = the full deck;
* `leader_i == (contract.declarer_i + 1) % 4` (declarer's LHO);
* the sampled hand at `leader_i` equals the displayed leader hand;
* candidates are exactly the 13 physical cards of the displayed hand;
* every candidate is physically present at the leader seat (not already
  removed from the DDS position).

After the solve, `check_dds_result` asserts the returned card map is exactly the
candidate set (catches any collapse/illegality). Active always in tests; in
production only when `BT_LEAD_CHECK` is set (or `check=True`), so normal runs
stay quiet.

---

## 5. Private-information leakage (testable boundary)

`engine/lead_evaluate.py::evaluate_leads_from_public_state(leader_hand,
public_auction, contract, dealer_i, vul, sampler_seed, config, *, sampler,
policy, source_deal)` is the purity boundary. It:

* deletes `source_deal` immediately (audit-only);
* passes the injected `sampler` a `PublicState` whose only fields are
  `leader_hand, auction, contract, dealer_i, vul`.

Regression tests (`tests/test_lead_purity.py`):

* `test_two_different_source_deals_same_public_state_identical` — two different
  full deals, identical public state + sampler seed ⇒ identical per-card
  results.
* `test_sampler_never_receives_source_deal` — a spy sampler proves the source
  deal is never in its arguments; `PublicState` has exactly the allowed fields.
* `test_deterministic_same_public_state_and_seed` — repeatability.

No module-level mutable state, cached source deal, or captured hidden-hand
closure exists in the lead path; the Ben sampler/policy closures in
`engine/ben.py::lead_evaluate` capture only `engine` (models) and are handed the
public state at call time.

---

## 6. The sampling distribution Q(layout | info) — NOT a proven posterior

The DD means are averaged over a distribution **Q(layout | public info)**, which
is **not** proven equal to the bridge posterior **P(layout | public info)**. Do
not call it a posterior. Traced mechanism (`engine/ben.py::sample_lead_layouts`
→ Ben `sample.py`):

1. **Prior.** A neural `binfo_model` predicts each hidden seat's HCP + shape from
   the auction *as seen from the leader's seat* (`Sample.get_bidding_info`).
   Candidate deals are drawn from that prior with the leader's hand fixed
   (`sample_cards_vec`).
2. **Acceptance = neural bidding-consistency, thresholded.** For each hidden seat,
   Ben's bidder model (partner) / opponent model (LHO, RHO) gives, at each of that
   seat's turns, the softmax probability of the **observed** bid given the
   candidate hand. `process_bidding` takes the **min over that seat's turns**
   (`min_scores_X`). `sample_cards_auction` combines them into
   `biddingScore = (Σ_X w_X·min_score_X) / (Σ_X w_X)`, `w_X = bid_count_X`
   (partner ×2). A hand is accepted iff `biddingScore ≥ bidding_threshold_sampling`
   (0.70; floor 0.40 only if starved). A hard per-seat floor `exclude_samples`
   (0.01) is applied first.
3. **Weighting.** `engine/ben.py` shuffles the accepted set and truncates —
   i.e. **uniform weights over accepted layouts**. The scores are recorded but
   not used as weights.

So Q is a **truncated, uniformly-weighted neural-consistency distribution**. It is
**not** exact-auction replay, **not** GIB semantic constraints, and **not** a
calibrated posterior.

**`biddingScore` is uncalibrated.** It is a weighted mean of per-seat *minimum
per-bid softmax probabilities* — a heuristic consistency score in [0,1], not a
likelihood (a likelihood would be a product over turns, not a min) and not a
calibrated probability. A score of 0.90 has **no defined probabilistic relation**
to 0.70; there is no isotonic/Platt/temperature calibration step in the code.
Code: `Sample.process_bidding`, `Sample.sample_cards_auction` (the
`use_distance=True` branch), `Sample.get_bidding_info` (prior).

**Ben-argmax caveat.** The auction was produced by Ben's argmax bid-out, but the
sampler does **not** require argmax-reproduction of the exact auction; it uses the
soft per-seat consistency score above. So Q estimates *"deals whose observed bids
Ben's neural models rate ≥0.70 consistent, from the leader's seat"* — explicitly a
**Ben-model distribution**, not automatically a human-auction posterior.

**No model mixing / no leakage.** Auction and sampling both use the same Ben
config (`BEN-21GF`, BBA/EPBot off). GIB is used only for auction-meaning *text* in
explanations, never in sampling. The source full deal is not used in sampler
setup, constraints, cache, seed, or weights (the bot is built from leader hand +
auction + dealer + vul only; `sampler_seed` is a hash of public state).

**Provenance is now recorded** on every problem (`build_lead_record` → `sampling`)
and in the debug artifact: `requested_samples`, `accepted_samples`,
`proposal_count`, `acceptance_rate`, `sampling_model`, `weighting_method`,
`score_threshold`, `effective_sample_size` (= n under uniform weights),
`posterior_calibration_status` (`"uncalibrated_neural_consistency"`), and
`complete` (whether `accepted_samples ≥ requested_samples`).

**Empirical audit (board `lead1-0284459a`).** At threshold 0.70 the sampler found
only **246** accepted deals from ~10 000 proposals (~2.5% acceptance) — it could
**not** reach the 512 requested, so that board's grade is an incomplete sample,
not a 512-sample confirmation. A multi-threshold report
(`output/lead_threshold_diag_*.json`) records n, ESS, all-13-card ranking, heart
distributions, honor locations, and bootstrap CIs at thresholds 0.70–0.90. See §9
for the finding.

**Known quality flag.** Doubled contracts (`lead_doubled`) keep the least
realistic double-dummy defence (a Lightner/lead-directing double asks for a
specific lead the bare `X` token cannot convey); this is surfaced as
`measured["doubled"] = True` and the `lead_doubled` category deliberately
bypasses the C1/C2 gates (`engine/lead_maker.py`).

---

## 7. Diagnostic artifact — `trainer lead-debug`

```bash
trainer lead-debug --id lead1-XXXXXXXX --out output/lead_debug.json
trainer lead-debug --seed 42 --n 512 --out output/lead_debug.json
```

Writes JSON (`engine/lead_debug.py::build_lead_debug_artifact`) with: problem id
/ source seed / sampler seed / config; seat mapping incl. compass names;
auction, contract, declarer, leader, dealer, vulnerability; displayed leader
hand; all 13 physical candidates; per candidate `physical_card`, `display_card`,
`policy_action`, `dds_card`, Ben softmax, mean defensive tricks, std, stderr,
95% CI; per sampled layout the four hands (debug-only), acceptance info, and the
per-candidate raw DDS output with declarer/defender conversion; and the summary
ranking / gate outcome. The full source deal appears **only** under
`audit_only` and is never read by evaluation. Needs the Ben env for
sampling/policy; the per-card DDS is endplay. The builder is unit-tested without
Ben (`tests/test_lead_debug.py`).

---

## 8. Tests added

`tests/test_lead_cards.py`, `tests/test_lead_invariants.py`,
`tests/test_lead_evaluate.py`, `tests/test_lead_purity.py`,
`tests/test_lead_seat_mapping.py`, `tests/test_lead_debug.py`. Coverage:
seat/rotation mapping across deal→auction→contract→leader→DDS; declarer's-LHO
leader for all four declarers; physical-card enumeration; policy fold cannot
change the DDS card; no duplicate/missing cards; fixed leader hand across
samples; candidate legality; direct-DDS vs production path; purity/no leakage;
deterministic repeatability; and a reversed-sign catch. All DDS-free tests run
anywhere; the endplay tests run wherever endplay is installed (CI installs it).

---

## 9. Acceptance-gate review (recommendations only — separate from correctness)

Reviewed after the correctness fixes; **not** the primary fix.

* **`best` set is card-level.** `judge_lead` selects every card within
  `TIE_EPS` of the max average (`engine/lead_verdict.py`), so touching honors
  *and* now the individually-scored spots can all tie.
* **C2 is cross-suit.** `gap = best_avg − best_different_suit_avg` compares the
  best card to the best card of a *different suit*
  (`_best_different_suit`). Within-suit card choices (e.g. which spot) are not
  treated as the suit-choice question C2 gates on — so a pure carding problem
  can pass or fail C2 for reasons unrelated to the actual decision.
* **`TIE_EPS = 0.05` vs estimator resolution.** Per-sample DD defensive tricks
  are integers; the standard error of a card's mean is `std/√N`. With
  `std ≈ 1–2`, that is ≈ 0.04–0.09 at N=512 and ≈ 0.09–0.18 at N=128. So a
  0.05-trick "tie" is **at or below** the noise floor at confirm size and below
  it at screen size: cards separated by less than the estimator can resolve are
  sometimes split and sometimes merged. `GAP_MIN = 0.25` sits comfortably above
  the noise; `TIE_EPS` does not.
* **`pre_obvious` / `suit_indifferent`** early rule-outs are conservative
  (upper-confidence-bound on the gap) and unaffected by the fix.

**Proposed future design separation (not implemented):**
1. *Suit-choice* lead problems — graded at suit granularity (best card per
   suit), where C2 and a coarser tie epsilon (≥ the noise floor, e.g. one
   standard error) are meaningful.
2. *Exact-card / carding* lead problems — graded at physical-card granularity
   with a within-suit gate, since the now-correct per-card DDS makes these
   well-defined for the first time.

This separation is a curriculum change and should not be bundled with the
correctness fix.
