# Ben Execution Plan (detailed) — v1 for bridge review

Date: 2026-07-17. Parent: `docs/ben_plan.md` (approved direction).
Scope: everything needed to generate 20 real problems with explanations
in this session, plus the permanent CI home.

## 1. Deliverables (in order)

1. Dead-path deletion (the fired directions), tests kept green.
2. Ben installed in-session + committed `scripts/setup_ben.sh` (pinned)
   for any future session/CI.
3. `bridge_trainer/engine/` — the Ben adapter + generator.
4. Calibration: the owner's flagged non-problems must fail the scanner.
5. **20 generated deals with given-bidding + option explanations**,
   timed, in a fresh pool.
6. Old-deal deletion (b1/b2/b3 batches + legacy pool artifacts).
7. CI workflow: cached Ben, scheduled generation.
8. Report: wall clock, yield, learnings, plus the 20 stem auctions for
   the owner's 2/1-flavor acceptance judgment (the P0 gate folded into
   the deliverable review, since execution was ordered now).

## 2. Dead-path deletion (deliverable 1)

Delete: `bridge_trainer/bot/` (SimpleBidder — fired v2 generator),
`bridge_trainer/generate/` (bot-based producer), `bridge_trainer/
finalize/` (LLM finalizer — fired v5 generator), `bridge_trainer/
forge/` (recipe compiler — fired yesterday), the era scripts
(`finish_b2.py`, `judge_docs.py`, `attach_notes.py`, `m0_spike.py`,
`spike_finalize.py`), their tests, and the `trainer produce` CLI
command. Keep: `harvest/` (future field-oracle prior), `validate/`
(hard shell — reused), the evidence stack (`dd/`, `scoring/`,
`dealing/`, `semantics/`, `projection/` — used by the legacy authored
`trainer run` path and future cross-checks). The five recipe YAMLs move
`problems/ → tests/fixtures/` : retired as product, retained only so the
evidence-stack golden tests keep protecting `dd/scoring/dealing`.
`batches/` is deleted in deliverable 6 (it IS the old deals).

## 3. The generator (`bridge_trainer/engine/`)

```
engine/
  ben.py       # adapter: load models once; bid(auction, hand) -> policy;
               # sample_hands(auction) -> layouts; candidate search
  scanner.py   # random deal -> Ben bids 4 seats -> qualifying decision point
  verdict.py   # candidate evaluation + gate (closeness, stakes, honesty)
  explain.py   # given-bidding + option explanations (templated, computed)
  records.py   # pool record; provenance
CLI: trainer ben-forge --count N --pool pool_ben --seed S
     [--max-seconds T] [--scan-log]
```

### 3.1 Scanner

Deal random board (existing seeded dealer), random dealer/vul. Ben bids
all four seats call-by-call. At every turn of every seat, read the
policy distribution *before* committing Ben's chosen call:

- **Dilemma signal**: `p(top) < 0.70 AND p(second) >= 0.15` (tunable;
  calibrated in deliverable 4).
- **Candidates**: calls with policy ≥ 0.03, union the top call, capped
  at 6; if fewer than 2 → not a problem. The distribution is read from
  the raw bidder softmax (`BenEngine.policy_full`), NOT
  `get_bid_candidates`, whose own 0.10 search_threshold would otherwise
  hide legitimate lower-probability calls (a simple raise, a jump to
  game) below its cutoff.
- **Stem sanity**: every committed stem call must itself carry policy
  mass ≥ 0.05 at the moment it was chosen (an auction Ben itself finds
  bizarre is discarded — no weird stems); auction length cap (12 calls
  before the decision point) to keep explanations and sampling sane.
- **Hero** = the seat holding the qualifying turn (first qualifying turn
  wins; later turns of the same board may be revisited in future runs
  via different seeds).
- Hard shell V1 (existing `validate/auction_state.py`) replays the stem
  and checks every candidate's legality — mechanical, zero trust.

### 3.2 Verdict

Use **Ben's native candidate evaluation** (its production bidding-table
machinery): for the qualifying turn, Ben samples concealed-hand layouts
consistent with the auction, rolls out each candidate to auction
completion with its own models for all seats, double-dummy scores the
final contracts per layout, and returns per-candidate expected scores.
The adapter extracts per-sample scores and computes:

- top-2 expected-IMP gap + bootstrap CI over samples;
- **accept** iff gap ≤ 2.5 IMPs or honest toss-up (gap inside CI);
- **stakes floor**: E|per-sample top-2 IMP swing| ≥ 0.5 (drop
  nothing-at-stake spots);
- **anti-lottery**: ≥4 candidates mutually inside CIs with near-uniform
  per-sample winners → discard as a pure guess;
- degenerate-option annotation: candidate best on <0.5% of samples is
  marked *dead* in the record (menu shown, annotated post-answer).

Rationale for Ben-native rather than the INV1–8 stack at v0: it is the
identical pipeline shape (constrained layouts → continuations → DD →
compare), already engineered and battle-tested inside Ben, and it fits
the <60 s budget. The INV stack remains in-repo; a later cross-check
harness can replay Ben's layouts through it (out of scope today).

### 3.3 Explanations (the new requirement, no LLM — computed + templated)

**Given-bidding explanations** — for each non-pass stem call, an
*empirical meaning band*: Ben's sampler is run at that call's auction
prefix (small sample, 50–100 layouts) and the caller's sampled hands
are summarized — HCP 10th–90th percentile, dominant suit lengths,
balance share. Rendered:

> `1♠ (West): in hands consistent with this auction, West holds 5+
> spades (avg 5.3) and 11–16 HCP; balanced 18% of the time.`

Passes get a band only when informative (e.g. a limited pass over an
opening); otherwise "nothing yet shown." Every band is **computed from
samples, never asserted** — the record stores the numbers behind every
sentence. Label shown once per problem: "meanings are empirical — what
the engine's 2/1 style implies, measured over consistent layouts."

**Option explanations** — per candidate:
1. what it is (call + systemic category from mechanical context:
   raise/new suit/NT/double/pass — derived from auction state, not
   guessed);
2. Ben's policy weight ("a strong engine chooses this 34% of the time
   here");
3. where it leads: top 3 final contracts from its rollouts with shares;
4. how it scores: expected IMPs vs best alternative ± CI, p(gain),
   p(push);
5. verdict framing rules (inherited from the reviewed gate): toss-ups
   say "the panel would split"; sub-CI margins never say "clearly";
   doubled-contract-heavy margins carry the DD-defense caveat.

### 3.4 Record (pool JSON, schema 1 + `ben:` block)

Standard fields (id `ben1-{seed:08x}`, created_at, difficulty=gap,
dealer/vul/seat/hand/auction/candidates) + `ben:` {model id + hash,
policy distribution at the decision point, per-candidate evaluation
table, stem policy-mass trail, samples used, explanations {stem: [...],
options: [...]}, gate measurements, `oracle: none`, seeds}.

## 4. Calibration (before the 20-deal run)

- **Negative controls** (must NOT qualify): e50006-19's hand
  (♠AQ6♥K74♦AQJ42♣K3-type 17 bal → its 1NT turn must show p(top) ≥
  0.85), b2-000273ee's Stayman hand type, plus 3 hand-built auto-bids
  (routine game acceptance, textbook preempt, clear 1NT response).
  Fed through the scanner at the right decision points.
- **Positive sanity**: scanner yield on random boards (expected: a few
  % of turns qualify); 5 sample problems eyeballed for stem sanity
  before the batch.
- Thresholds are frozen after calibration and stamped into provenance.

## 5. Budget (measured before the batch, reported after)

| Stage | Target |
|---|---|
| model load (once per process) | ≤ 60 s, amortized |
| scan per board (4 seats, full auction) | ≤ 5 s |
| verdict (sampling + rollouts + DD) | ≤ 35 s |
| explanations (per-prefix sampling) | ≤ 10 s |
| record + pool | < 1 s |
| **per accepted deal (excl. scan misses)** | **< 60 s** |

Dials if over: samples per candidate ↓ (CI widens honestly), candidate
cap 5→4→3, explanation prefix-samples 100→50, batch NN inference.

## 6. CI home (deliverable 7)

`.github/workflows/generate.yml`: nightly cron + manual dispatch;
restores `~/ben-cache` (models + venv) via actions/cache; runs
`scripts/setup_ben.sh` (no-op when cached); `trainer ben-forge --count
K --pool data/`; commits/deploys pool with the existing publish flow.
Committed but necessarily untested in-session (no Actions runner here);
first real run may need one babysit.

## 7. Risks

1. **System flavor** — GIB-style 2/1; the 20 stem auctions ship in the
   report for the owner's acceptance verdict; BBA fallback documented.
2. **Ben API drift** — the adapter pins the ben commit in
   `setup_ben.sh`; all integration lives in `engine/ben.py`.
3. **Empirical meanings can read oddly** for conventional calls
   (Stayman "showed" varied hands); mitigated by the systemic-category
   line and the "empirical" label; a curated meaning-name table for the
   ~20 most common conventional calls is a fast follow.
4. **In-session wall clock**: 20 deals × <60 s + scan misses ≈ 25–45
   min compute; run in background with progress logging.
5. **Rollout depth**: Ben completes auctions with its own models; a
   pathological never-ending auction is cut by the length cap and
   discarded.

---

## v2 amendments (bridge review, GO WITH CHANGES — all accepted)

Full review: `docs/panel/ben_round1.md`. Binding changes:

1. **Conventional-call name table is a batch prerequisite** (~12
   auction-pattern rules: Stayman, transfers, 2C/2D waiting, Jacoby
   2NT, splinters, Blackwood + step responses, cue bids, negative
   double, fourth-suit). Artificial calls print the convention name and
   the empirical band reframed as *evidence* ("93% held a 4-card
   major; says nothing about clubs"), never a naive length band.
2. **Doubles get a contextual type line** (~8 rules: direct X =
   takeout, X after overcall by opener's side = negative, X of 1NT =
   penalty, balancing X = takeout, X of artificial = lead-directing)
   cross-checked against the measured band; disagreement printed.
3. **Wide-CI back door closed**: minimum effective samples per
   candidate (>=100) and CI half-width cap (~1.5 IMPs); above the cap =
   "insufficient evidence" discard, never a toss-up. Cutting samples
   can never raise acceptance.
4. **Systemically-forced turns excluded** from scanning (responses to
   listed asking/relay calls: Blackwood, Stayman, transfers, 2D
   waiting). A Pass candidate carrying >=0.08 policy in a game-forcing
   auction discards the deal (model artifact).
5. **Equivalence discard**: top-2 candidates with near-identical
   rollout contract distributions (TV distance < 0.15) AND gap < 0.5
   IMP = "distinction without difference", discarded.
6. **Positive calibration controls restored** (limit-raise-vs-game,
   3-over-3 LAW, balancing seat, action-double at 5-level,
   invite-vs-blast) — thresholds too tight is a visible failure;
   negative set extended with a Blackwood response, a transfer
   completion, a 2D waiting turn; verdict calibrated too (routine game
   acceptance must show gap > 2.5).
7. **Doubled-contract honesty (INV5)**: when >40% of decisive samples
   involve doubled contracts, no non-toss-up verdict is published
   (downgrade or discard) — raw-DD penalty flattery contained; piping
   rollout contracts through the correction table is the P1 upgrade.
8. **Best-turn selection + batch diversity quotas**: scan whole
   auction, keep the most-split turn; batch gates: <=3 opening
   decisions, >=15 with 2+ non-pass stem calls, >=8 contested, all
   vulnerabilities, hero roles spread (opener/responder/overcaller/
   advancer >=2 each), theme dedup (last 2-3 calls + candidate set,
   max 2/key), altitude spread.
9. **Meaning bands sample the prefix THROUGH the call**, floor n>=30,
   "n=NN, measured" printed, fallback to category line under the floor.
10. **Verdict evaluates exactly the scanner's candidate set on one
    shared layout set** (INV1 pairing) — no silent internal
    re-derivation of candidates.
11. **Category-line special cases**: opponents'-suit bids = cue bids;
    jump attributes carried (jump raise / jump shift / double-jump =
    splinter).
12. **Stem calls are Ben's searched choices** (mass floor is a
    backstop); auction-length cap counts non-pass calls (~10).
13. **Report honesty**: annotate known GIB-isms in the 20 stems;
    scoring form (IMPs) stated per problem; toss-up scoring accepts
    either member; mechanical round-trip check (displayed hand ==
    hand Ben bid, dealer/vul rotation verified).

Tuning watch-list: alternative 3-way trigger `p(top)<0.60 and
(p2+p3)>=0.25`; stakes floor may rise toward 1.0 if accepted problems
cluster flat.
