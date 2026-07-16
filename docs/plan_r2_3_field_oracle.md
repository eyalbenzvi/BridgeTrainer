# Plan R2-3 — Distilled Field Oracle (high-level, v1)

Status: high-level plan for expert review. Date: 2026-07-16.
Parent: `docs/problem_quality_concepts_round2.md` §R2-3.

## What it is, in plain language

Free public archives contain **millions of recorded hands bid by real
players** (BBO vugraph and tournament LIN files — the repo's `harvest/`
module already parses this format). Round 1's "field-as-panel" idea used
those records directly as the problem bank: find a board where real
players split, publish it. The owner liked it best but named its two
flaws — the records run out, and players at different tables play
different systems, so a "split" may be two systems, not one dilemma.

This plan uses the same data differently: **as a teacher, not as a
question bank.** We train a small statistical model — the *oracle* — that
answers one question:

> "Given this hand, this seat, this vulnerability, this auction so far —
> what fraction of strong players would choose each call?"

Once trained (once, locally, minutes of CPU, no API), the oracle can
score **any freshly dealt hand in milliseconds**. Deal unlimited random
boards; wherever the oracle says "players would genuinely split here"
(predicted 55/35/10, not 97/3), that's a nominated problem, and the split
calls are the option list. The archive is consumed once at training time;
the generator never runs out of deals.

## Why this fixes the system confound (the owner's stated flaw)

Raw field counts cannot distinguish "half the field plays weak twos" from
"this hand is a genuine dilemma." A **fitted model can**, because the two
produce different statistical signatures:

- **System split**: the disagreement is *constant* across hands — in a
  context where two methods coexist, every hand of the type splits at
  roughly the same ratio, regardless of its features. The model finds
  that its hand features don't reduce uncertainty (its predictions barely
  beat a context-only baseline).
- **Judgment split**: the disagreement *tracks the hand* — move a queen
  and the predicted split moves. Hand features carry real signal.

Concretely: per context, compare the trained model's held-out log-loss
against a features-blind baseline. Contexts where features don't help are
**system-noise contexts → excluded from mining**. Contexts where features
matter are judgment contexts → mined. This measurement is impossible on
raw counts; it is exactly what fitting a model adds.

Second guard: calls that don't exist in the owner's card (multi 2♦,
transfer responses foreign to 2/1) are detected at *label* level —
contexts where a material share of the corpus's calls can't map onto the
owner's card are excluded, with a coverage report saying what was dropped.

## Architecture

```
LIN archives ─► harvest (exists) ─► context normalizer ─► training table
                                                (hand features, context
                                                 features, call label)
                                                        │
                                              train once, locally
                                              (gradient-boosted trees,
                                               scikit-learn; no new heavy
                                               deps, no GPU, no API)
                                                        ▼
random deals (existing dealer) ────────────► ORACLE: p(call | hand, ctx)
                                                        │
                        entropy gate: split? ───────────┤
                        option list: top-k calls ───────┤
                                                        ▼
                              existing pipeline: meanings (card) → layouts
                              → DD sim (INV1–8) → verdict → hard shell → pool
```

**The oracle only nominates.** The verdict authority is unchanged: the DD
simulation over card-constrained layouts (owner decision #1). The oracle
answers "would real players split here?"; the sim answers "what wins?".

## The components

1. **Context normalizer** (the real bridge-engineering work): bucket raw
   auctions into comparable decision classes — seat, vulnerability,
   dealer-relative position, and a normalized auction signature (e.g.,
   "1M–(2m)–?", "(1x)–P–(P)–?"). Shallow contexts first (0–3 prior calls),
   the same catalogue R2-1 uses. Deep or alert-heavy auctions are dropped
   with a counter, not guessed at.
2. **Hand featurizer**: HCP, per-suit lengths and honor holdings, suit
   qualities, controls, shape class — all already computable in
   `dealing/features.py` territory.
3. **The model**: one multiclass gradient-boosted-trees model per context
   family (scikit-learn `HistGradientBoostingClassifier`; small, fast,
   inspectable). Explicitly NOT a bidding engine: it never bids a hand out;
   it only estimates a one-call distribution.
4. **Quality report** (produced at training time, versioned): per context —
   sample count, held-out calibration (do predicted 60/40s happen 60/40?),
   feature-lift vs the blind baseline (the system-noise test), card-label
   coverage. Contexts must pass all four to be mined.
5. **Mining loop**: deal → context match → oracle entropy above threshold →
   nominate with top-k options → existing sim/verdict pipeline.

## Phases

- **P0 — Corpus census (~2–3 days).** Harvest a real archive; run the
  context normalizer; report: contexts × sample counts × call-label
  coverage vs the owner's card. Gate: at least ~10 shallow contexts with
  ≥2000 usable samples each (if the data isn't there, the plan stops
  having cost anything but the census).
- **P1 — Train + honesty checks (~1 week).** Train per-context models;
  produce the quality report; run the **e50006-19 test**: the oracle must
  predict a lopsided distribution (~90%+ 1NT) on that hand type, and
  similar for known auto-bids. Gate: calibration + the flagged
  non-problems scoring as non-splits.
- **P2 — Mining + publishing (~1 week).** Entropy gate + option
  derivation wired to the existing pipeline; 10-problem batch.
  Gate: owner rubric Q1–Q5.
- **P3 — Residual analysis.** The system-vs-judgment separation report per
  context; drop or repair noisy contexts; expand the context catalogue.

## Risks

1. **Data sufficiency per context** — the fatal risk, and why P0 is a
   census before any modeling. Rare contexts stay unmined (reported, not
   guessed).
2. **Corpus standard** — vugraph fields are strong but mixed; weight games
   by event tier if metadata allows; otherwise accept "strong-club level"
   as the oracle's honest calibration and say so.
3. **Convention pollution** — the b1 review's "fictional auction" disease
   (2♦ that showed majors read as natural). Guarded twice: label-coverage
   exclusion (calls unmappable to the card kill the context) and the
   ground-truth check V5 heritage — the *actual* hands behind a call are
   available in the corpus to sanity-check its assumed meaning.
4. **Oracle worship** — the oracle is a nomination heuristic, never a
   verdict source; its distribution is published as "field estimate"
   metadata, not as the answer.
5. **Staleness/versioning** — oracle version recorded per problem
   (INV6 style); retraining is a versioned event.

## What the owner gets

The round-1 concept he ranked best, with its two flaws engineered out:
the archive becomes a *renewable* teacher instead of a finite bank, and
"different system vs real dilemma" becomes a measured, per-context
statistic instead of an unanswerable confusion — plus an option list with
the strongest provenance available anywhere: *this is what strong players
actually do with such hands.*
