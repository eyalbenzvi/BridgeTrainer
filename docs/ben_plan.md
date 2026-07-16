# Plan: Ben-powered deal generation (the owner's six requirements)

Status: proposed. Date: 2026-07-16. Supersedes the Forge/family direction
(docs/combined_plan.md) as the generator; retains its gate and the
evidence stack. Builds on the Ben analysis in docs/core_problem_method.md
§2.1 and docs/bridge_architecture_options.md Approach A.

## 0. The requirements (owner, verbatim intent)

1. Generation of deals — random, full variety, not recipes.
2. Bidding in a 2/1 GF system.
3. 2–5 bidding options per problem.
4. All given bidding accurate; options bridge-correct, no missing options.
5. Real problems — no clear-cut answers.
6. < 1 minute to generate one deal.

## 1. Why an engine, and why Ben

Requirement 4 on random deals means someone competent must bid every
seat of any auction. The repo's own post-mortem proved the in-house bot
can never get there (0.9^10 arithmetic, §1.1) and the LLM finalizer
produced the b1–b3 failures. The remaining candidates were evaluated in
July 2026 (core_problem_method §2):

- **Ben** (github.com/lorserker/ben, GPL-3.0): Python, TensorFlow
  CPU-only, pretrained GIB-flavored **2/1** models shipped in-repo,
  live on BBO, actively maintained. The bidder outputs a **probability
  distribution over calls** — which is simultaneously the auction
  engine (req 2, 4), the candidate generator (req 3), the
  missing-option guard (req 4), and the dilemma detector (req 5).
  Free, local, no API, no credit card.
- EPBot/BBA: free but closed .NET DLL, single-call output (no
  distribution) — retained as fallback if Ben's system flavor fails the
  owner gate.
- LLM: rejected (paid API).

## 2. Pipeline

```
random deal (existing NumPy dealer, seeded)
  → Ben bids all four seats to a hero decision point         [SCAN]
      dilemma signal: p(top call) < P_TOP and p(2nd) > P_2ND
      no qualifying turn → next deal (cheap, seconds)
  → candidates = calls with policy ≥ P_OPT (∪ top call), capped 5   (req 3)
  → hard shell V1: legality of stem + every candidate (existing)
  → Ben samples N concealed-hand layouts consistent with the auction
  → per layout × candidate: Ben bids the auction OUT (all seats)  [VERDICT]
  → our DD + correction + paired IMP comparison (INV1–INV8, unchanged)
  → forge gate (reused): stakes floor, doubled-share flag, fog rule,
      shortfall honesty, dead-option annotation, anti-lottery
  → accept iff genuinely close (top-2 gap ≤ 3 IMPs or honest toss-up)  (req 5)
  → pool record: hand, stem, options, verdict + evidence, Ben policy
      distribution, provenance (model hash, seeds — INV6)
```

How each requirement is met:
1. **Variety**: any random deal, any auction Ben produces — no recipe
   catalogue, no context list.
2. **2/1**: Ben's distributed models play GIB-flavored 2/1 — the
   closest open system to the owner's card. Owner acceptance gate in
   P0 (below); BBA fallback with an explicit 2/1 card if rejected.
3. **2–5 options**: policy threshold + cap; fewer than 2 live calls =
   no problem (skip).
4. **Accuracy/completeness**: stems are bid by a BBO-grade engine, not
   authored; every call carrying real policy mass enters the option
   set — "no missing options" relative to a trained expert policy
   (the honest formulation; no generator can promise more). V1
   legality is mechanical on top.
5. **Real problems**: two independent signals must agree — the policy
   split (Ben is genuinely torn) AND the simulated verdict closeness
   (the outcomes are genuinely close, INV7-honest). Clear-cut hands
   fail the first test in milliseconds; near-miss fakes fail the second.
6. **< 1 min**: budget table below, measured in P0 before anything else.

## 3. The <60 s budget (dials in parentheses)

| Stage | Estimate | Dial |
|---|---|---|
| Deal + Ben auction scan | 1–5 s | calls are single NN inferences, batched |
| Scan overhead for non-qualifying deals | amortized | yield measured in P0; scans are cheap and parallel |
| Layout sampling (Ben) | 2–10 s | N layouts (200–400 target) |
| Rollouts: N × candidates × ~4–8 calls | 15–35 s | batch inference; N; candidate cap |
| DD (~13 ms/deal·denom, existing cache) | 5–10 s | denom count |
| Gate + record | <1 s | — |

If P0 measures the rollout stage over budget: reduce N (CIs widen
honestly per INV7), batch harder, or trim candidates to the policy
top-3. The <1 min target is per *accepted* deal amortized at expected
scan yield; the report states both numbers separately.

## 4. What is reused vs retired

**Reused unchanged**: dealer, DD + correction, scoring/stats (INV1–8),
pool store, webapp/publish, hard shell V1, the forge gate module
(stakes/doubled/fog/dead-options — written and committed), provenance
discipline.
**Reused, adapted**: forge maker loop (attempt caps, max-seconds,
per-attempt logging, idempotent ids).
**Retired**: the five family YAMLs as a generator (kept only as legacy
drill content); SimpleBidder for generation; the LLM finalizer;
knife-edge lens machinery.
**Deferred, unchanged**: R2-3 oracle as a future prior; family compiler
can return later for curriculum drilling of specific decisions.

## 5. Phases and gates

- **P0 — Ben feasibility + owner acceptance (~2–3 days).**
  Install Ben (pip + models, ~2–3 GB, cached); benchmark: ms/call,
  auction/s, sampling and rollout throughput; wire a `trainer ben-demo`
  that prints **20 complete auctions on random deals**.
  **Gate (owner, bridge decision)**: are these auctions "accurate 2/1"
  by your standard (req 2/4)? If no → BBA/EPBot fallback path.
  **Gate (engineering)**: measured budget table fits <60 s.
- **P1 — Scanner + candidates (~2–3 days).** Random-deal scan loop,
  policy thresholds (P_TOP≈0.70, P_2ND≈0.15, P_OPT≈0.08 — tuned on the
  known-answer set below), V1 legality, candidate records.
  **Calibration set**: the owner's flagged non-problems (e50006-19's
  1NT hand, b2-000273ee's Stayman hand) must fail the scan; the b1
  panel-endorsed problems must pass it.
- **P2 — Verdict + gate + pool (~1 week).** Layout sampling, rollouts,
  DD verdict, forge gate wiring, pool records, `trainer ben-forge
  --count N`. **Gate**: owner rubric Q1–Q5 on a 10-problem batch
  (core_problem_method §6, ship targets).
- **P3 — The 20-deal run + cleanup.** Timed batch of 20, report
  (wall clock, yield, rejection reasons, learnings); delete the old
  b1/b2/b3 deals and retire the legacy pool.

## 6. Risks, stated plainly

1. **System flavor** (the big one): Ben's 2/1 is GIB-style — specific
   sequences (double meanings, raise structures, NT ranges) may differ
   from the owner's preferences. That is what the P0 gate is for; the
   fallback is BBA's explicit 2/1 card at the cost of losing the policy
   distribution (candidates would then need a screening probe).
2. **Rollout wall-clock** vs req 6 — measured before commitment;
   honest dials identified.
3. **Rare-auction weirdness**: any engine goes strange in freak
   auctions; containment = auction-length cap, policy-mass floor on
   every stem call (a stem call Ben itself assigns <5% mass flags the
   deal for discard), V1 legality.
4. **"No missing options" ceiling**: options are complete relative to
   Ben's judgment. A call no strong engine considers won't appear —
   accepted as the definition of complete.
5. **GPL-3.0**: fine for personal use; keep Ben behind a subprocess
   boundary if the repo is ever distributed.
6. **Model footprint**: ~2–3 GB in CI cache; one-time.
