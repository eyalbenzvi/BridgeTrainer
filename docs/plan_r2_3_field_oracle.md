# Plan R2-3 — Distilled Field Oracle (high-level, v2 — post panel round 1)

Status: v2, revised per expert review (`docs/panel/plans_round1.md`).
Date: 2026-07-16. Parent: `docs/problem_quality_concepts_round2.md` §R2-3.

## What it is, in plain language

Free public archives contain millions of recorded hands bid by real
players (BBO vugraph / tournament LIN files — `harvest/` already parses
the format). Train a small statistical model — the **oracle** — once,
locally, on that corpus, to answer:

> "Given this hand, seat, vulnerability and auction so far — what
> fraction of strong players would choose each call?"

Once trained, the oracle scores any **freshly dealt** hand in
milliseconds. The archive is a *teacher*, consumed once; the generator
never runs out of deals.

## The v2 role change (the panel's principal finding)

v1 positioned the oracle as a standalone generator: its entropy picks
the problems, its top-k calls become the options. The review broke both:

- **Top-k field calls as options resurrect the token/meaning disease at
  scale.** In "P–P–1♠–(P)–?" the field's modal call with a limit raise is
  2♣ — *Drury* — which the owner's card would read as natural clubs and
  simulate a phantom club suit: exactly the b1 "fictional auction"
  failure (e50012-13), now generated systematically. Mirror image: the
  owner's systemically correct call can be field-rare in a mixed corpus
  and vanish from top-k — the missing-textbook-option defect rebuilt.
- **The system/judgment separator was wrong** (below).

**v2 therefore demotes the oracle to what only it can provide: a
_human-hardness prior_.** R2-1's card-driven miner defines problems and
options (in the owner's closed system world); the oracle contributes the
one signal DD cannot compute — *"would strong players actually split
here?"* — separating genuine panel-splitters from dull, stakes-flat
coin-flips that happen to be close in EV. Its distribution ships as
"field estimate" metadata, never as options, never as a verdict.

```
R2-1 miner: deal → candidates/trees (owner's card) → sim → close + material?
                                        │ yes
                                        ▼
                    ORACLE: p(call | hand, ctx), support-gated
                                        │
                 human-split score = high → publish (priority)
                 human-split score = low  → publish rate-limited / deprioritized
```

## The system-vs-judgment separator, rebuilt

v1 claimed: system splits are feature-*independent* (constant ratio),
judgment splits feature-*driven*. The panel refuted it: most system
differences **are** feature-driven — strong-NT vs weak-NT populations
make p(1NT) jump exactly at the 14/15-HCP feature boundary; Landy vs
natural makes p(2♣) swing violently with shape; strong-club 1♣ tracks
HCP precisely. A mixture of two feature-deterministic policies is
maximally "feature-driven." The feature-lift test admits the disease it
was built to exclude.

The confound is a **population mixture**, so the separator must see
population:

1. **Harvest pair identities** (`pn|` tokens — currently unparsed) and
   fit pair-conditioned models. A split is *systemic* when pair-cluster
   membership explains it (within-cluster the call is near-deterministic);
   it is *judgment* when entropy survives **within** clusters of
   same-method pairs.
2. **Stop discarding alert data**: `_norm_call` strips `!` and skips
   `an|` explanation tokens — the corpus's only direct convention
   annotations. Retain both; alert density per context is a direct
   pollution signal.
3. **Per-instance meaning conformance** (the primary guard, promoted from
   v1's vague "sanity check"): for every training row, check the *actual
   hands* behind hero's call **and every stem call** against the owner's
   card bands (the V5 admissibility validator generalized to training
   data). Non-conforming rows are dropped; the per-context **drop rate is
   the honest pollution measure** — a context shedding >30–40% of rows is
   unminable. This approximately isolates the sub-corpus that bids like
   the owner's card — the only population whose splits matter here.
   (v1's token-level "call doesn't exist in the card" guard is deleted:
   call tokens are universal; multi 2♦ maps token-perfectly onto a weak
   2♦ and means the opposite.)

## Trust boundaries of the oracle score

- **Support gate**: the entropy of an extrapolated prediction is
  meaningless — GBT outputs flatten off-distribution, so raw entropy
  *maximizes* exactly on hands unlike anything in training (a classic
  acquisition-function failure). A nominated hand must sit in a
  high-density training region (leaf-occupancy / k-NN distance floor);
  support ships in problem provenance next to the score.
- **Per-context calibration**: entropy thresholds are set against each
  context's known auto-bids, not globally; predicted 60/40s must occur
  60/40 on held-out data or the context is unminable.
- **Known residual noise**, stated: player errors and psychs (few % label
  noise), state-of-match effects in KO vugraph, scoring-form mixture —
  all inflate the noise floor the calibration must absorb; none are
  individually detectable.

## Data reality (v2 bars)

- **2000 samples/context is a census floor, not a minability bar.**
  Calibration + separator statistics + boundary-region coverage need
  ~**10k conforming rows** (post drop-filtering) per mined context;
  statistics ship with bootstrap CIs; boundary-region (top-entropy-decile)
  counts reported separately; two-rooms-per-board dependence respected in
  the resampling.
- Expected shape of the corpus: openings and 1NT-defense contexts have
  the most data and the worst pollution; the trainer's target genres
  (competitive raises, balancing) sit in the 3–5k range per 100k boards —
  so minable contexts will be few at first and the census must say which.

## Phases

- **P0 — Harvest upgrade + census (~1 week).** Extend `harvest/lin.py`:
  `pn|` pair identities, alert flags, `an|` text, event/tier metadata
  (work the v1 estimate omitted). Run the context normalizer; report
  contexts × conforming-row counts × drop rates × alert density.
  Gate: enough post-filter data in ≥5 target-genre contexts, else stop.
- **P1 — Train + honesty checks (~1–1.5 weeks).** Pair-clustered models;
  calibration report; **negative controls**: known system-split contexts
  (1NT-defense conventions, multi 2♦, Drury seats) must be *flagged
  systemic*, and known judgment contexts (competitive raises among
  same-method pairs) must survive — failure kills or reworks the
  separator. Positive control: e50006-19's hand type predicts ~90%+ 1NT.
- **P2 — Integration (~3–4 days).** Wire the score into R2-1's publish
  policy (priority/deprioritize, never author); provenance fields.
- **P3 — Expansion.** More contexts as data allows; optional
  ensemble-disagreement decomposition (epistemic vs aleatoric) replacing
  raw entropy.

## Risks

1. **Data sufficiency in the genres that matter** — the fatal risk; P0 is
   a census with a stop-loss before any modeling.
2. **Separator residual leakage** — pair clustering handles the dominant
   mixture structure; hybrid cases (same pair, style variance by state of
   match) remain in the noise floor; the score is a *prior*, so leakage
   misranks rather than fabricates.
3. **Harvest metadata absent** (event tier) — degrade to "strong-club
   level" calibration, stated honestly.
4. **Scope discipline** — the oracle must never quietly grow back into an
   option source or verdict input; enforced by it living behind a single
   "score this nominated spot" interface.

## What the owner gets

The round-1 concept he ranked best, in the only role that survives expert
scrutiny: real-field wisdom — *"strong players genuinely split here"* —
attached as a prioritization signal and provenance to problems that are
already system-safe by construction, with the system-vs-judgment
question answered by measured population structure instead of hope.
