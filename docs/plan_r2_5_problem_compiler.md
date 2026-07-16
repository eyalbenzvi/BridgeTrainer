# Plan R2-5 — The Problem Compiler (high-level, v1)

Status: high-level plan for expert review. Date: 2026-07-16.
Parent: `docs/problem_quality_concepts_round2.md` §R2-5.

## What it is, in plain language

A **problem family** is a recipe, not a deal. Example recipe:

> *"You hold 10–12 HCP with exactly three spades after partner opens 1♠
> and RHO overcalls 2♥. Options: 3♠, X, 2♠, Pass."*

That recipe describes a *decision*, not a hand. The **compiler** turns a
recipe into an endless stream of concrete problems: it deals you a fresh
13-card hand fitting the recipe, deals the three concealed hands to fit
what the auction showed, and runs the full simulation for *that specific
deal* — because with ♠KQ5 and club values the answer may be 3♠, while
with ♠Q52 and wasted heart honors it may be Pass. Same decision, fresh
cards, honest per-deal verdict, forever.

**You review a recipe once; it generates problems for life.** Twenty
reviewed recipes ≈ a bottomless, quality-controlled problem bank.

The key fact: **~70% of this already exists in the repo.** The five YAMLs
in `problems/` are exactly recipes (hand constraints + auction + options
+ meanings + projections), and the `my_hand_class` + `variants: N`
machinery already deals fresh hero hands from a class and re-simulates
each one (README: "variant 0 is the authored hand, the rest are freshly
dealt from the class and fully re-simulated"). This plan promotes that
side feature into the main generator, hardens the missing quality layer,
and grows the catalogue.

## What's genuinely new (the plan), on top of what exists

### 1. The instance gate — the layer that doesn't exist yet

A family guarantees the decision *class*; it cannot guarantee every
*instance*. A hand at the extreme edge of the class can be an auto-bid
(the maximum 12-count with perfect shape is a clear 3♠ — publishing it as
a "problem" recreates e50006-19). So every compiled instance passes a
**per-instance publish gate** before it reaches the pool, using R2-1's
metrics on the instance's own sim output:

- dominance check: if one option wins on ≥90% of layouts → the instance
  is an auto-bid → *served as a calibration hand or skipped*, never
  published as a dilemma;
- degenerate-option check: an option best on ~0% of layouts for THIS
  instance is dropped from THIS instance's display (the family's option
  list is the superset; the instance shows the live ones, min 2);
- the existing INV7/fog discipline unchanged.

This is the plan's central quality argument: **family review fixes the
decision's bridge-sense once; the instance gate fixes per-deal
degeneracy automatically.**

### 2. The family schema (formalizing `problems/*.yaml`)

Additions to the existing problem schema: `family_id`, hero hand-class
(already exists as `my_hand_class`), per-family principle text (one
paragraph: what this decision teaches), tags (genre, difficulty prior,
vulnerability/scoring form), and instance-gate thresholds. Existing
semantics rulesets and projection trees are reused untouched.

### 3. Where families come from (three feeders, in trust order)

1. **Owner-authored** (~20 to start): the decisions he actually cares
   about, written in an afternoon each with the authoring guide
   (`docs/authoring_guide.md` exists); expert-reviewed once, b1-panel
   style, at the *family* level — meanings, options, projections.
2. **Classics from memory**: a remembered great problem becomes a family
   by generalizing its hero hand into a class (the compiler's isomorph
   mode: spot-card shuffles and honor jitter *within the class*; suit
   swaps only where the auction's level relationships survive the swap —
   a nontrivial legality check, e.g. 1♠–(2♥) does NOT survive ♠↔♥ because
   2♠ over 1♥ would be a jump).
3. **Mined candidates** (later): R2-1/R2-3 spots that score well get
   *proposed* as families; the owner inducts or rejects. Discovery
   proposes, the catalogue disposes — no unreviewed family ever compiles.

### 4. Family-level product surfaces

- **Verdict distribution page** per family: "across 500 instances of this
  raise decision: 3♠ best 46%, X 31%, Pass 18%, toss-up 5%" — this *is*
  the lesson ("mostly bid game with this type; the exceptions share wasted
  heart values"), and it is a self-audit of the family's realism.
- **Spaced repetition keyed by family** (not by board): a lapse on the
  raise decision schedules *fresh instances* of that family — repetition
  without repeating a single card, which no fixed problem bank can do.
- **"Deal me a hand"** across families, weighted by SRS state and owner
  tags — the existing webapp flow, unchanged.

## Pipeline

```
family YAML (authored once, reviewed once)
   → compiler: deal hero from class → deal concealed from meanings
   → full existing sim (projections, DD, INV1–8)
   → INSTANCE GATE (dominance / degenerate options / CI+fog)
   → publish instance (family_id, principle, per-instance verdict)
```

No new engines, no APIs, no network. New code is the instance gate, the
family schema fields, and catalogue/webapp surfaces; the heavy machinery
(dealing, semantics, projection, DD, scoring, publish) exists.

## Phases

- **P0 — Promote the existing five (~3–4 days).** Wrap `problems/*.yaml`
  as families; implement the instance gate; compile 20 instances of each;
  measure gate rejection rates. Gate: owner plays 10 instances,
  rubric Q1–Q5 — this tests the *compiler*, since these five recipes are
  already trusted.
- **P1 — Catalogue sprint (~1–2 weeks, mostly owner-paced).** Authoring
  guide refresh; owner writes ~10 families; one expert-panel review pass
  over the batch (documents, not code). Gate: panel verdicts per family.
- **P2 — Product surfaces (~1 week).** Family pages with verdict
  distributions; SRS by family; catalogue browsing in the webapp.
- **P3 — Feeders.** Isomorph mode for classics; mined-candidate induction
  queue from R2-1/R2-3.

## Risks

1. **Variety ceiling** — the catalogue only drills what it names.
   Accepted consciously: 20 good families beat 17 random problems (the
   current pool); the mined feeders (P3) grow breadth over time.
2. **Family review quality is load-bearing** — a wrong meaning band or
   unrealistic projection tree poisons every instance. Same exposure as
   today's authored path, but paid once per family and guarded by the b1
   panel process + V1–V7 shell; the verdict-distribution page also makes a
   sick family visible (a "raise or pass" family where Pass wins 92% of
   instances is mis-specified).
3. **Instance-gate thresholds** — too strict starves output, too loose
   ships auto-bids; tuned in P0 against the five trusted recipes.
4. **Concealed-hand realism** — inherited from the semantics engine
   (exclusion completeness); unchanged from the current authored path.
5. **Owner authoring stamina** — ~10 families is the P1 ask; the feeders
   exist precisely so the catalogue doesn't depend on his output forever.

## What the owner gets

The strongest quality guarantee available — *every* published decision
was reviewed by an expert (once, at family level) — combined with what he
asked for in round 2: a true generator (fresh cards every time), fully
offline, in his system only, with per-deal honest verdicts and a
spaced-repetition loop no fixed bank can offer.
