# Problem Quality, Round 2: Six New Concepts — Idea Brief

Status: concepts only, no implementation. Date: 2026-07-16.
Parent: `docs/problem_quality_concepts.md` (round 1) + owner feedback.

## Owner feedback on round 1 (the new constraints)

1. *Field-as-panel* — **best of round 1**, but confounded: at other tables,
   "people might play different systems and it would be difficult to
   understand what is a dilemma and what is a different system."
2. *Knife-edge* — covered (full design v1 + expert-panel round 1 on branch).
3. *Jury of engines* — bots agree too much; needs APIs / credit card. No.
4. *MSC scoring* — doesn't help obtain deals.
5. *Whole-auction play* — not the desired product.
6. *Import human problems* — too restricted; **"I want a generator."**
7. *Canary tenure* — inherits earlier problems; too time-consuming.

Derived constraints for round 2 — every concept below satisfies all five:

- **G**: it is a *generator* — unlimited fresh deals, not a finite import;
- **F**: offline and free — no external APIs, no paid services, no
  credit card; local compute only;
- **P**: the product stays curated single-decision problems with options
  and an evidence-backed verdict;
- **S**: "dilemma" must be separable from "different system";
- **T**: bounded owner time — effort spent once, not per problem.

---

## Concept R2-1 — Empirical dilemma mining: define the dilemma in tricks, not in system

All previous approaches asked some authority — bot, LLM, card, field —
"is this a dilemma?" and inherited that authority's system assumptions.
This concept asks the **deal itself**, using only machinery that already
exists and is already trusted (dealing + DD + INV1–8 stats):

A hero hand at a decision point is a *problem* precisely when, over the
layouts consistent with the auction so far:

1. **No dominant action** — no candidate call's outcome distribution beats
   all others on (almost) every layout; and
2. **High value of hidden information** — the *best* call varies
   layout-by-layout with real stakes (formally: the gap between
   "expected score of the best fixed call" and "expected score if you
   could see through the backs of the cards" exceeds a threshold).

A clear 1NT opening or an automatic Stayman hand fails test 2 instantly —
one call is best on essentially every layout — so e50006-19 and
b2-000273ee class hands are *measured* out, not judged out. And because
both tests are computed in tricks and IMPs, **no system definition is ever
consulted: constraint S is satisfied by not having the vocabulary to
violate it.** The auction wrapper around the mined spot is a thin,
standardized veneer (your card only), applied after the deal qualifies.

- **G**: deal at random, test, keep — unlimited. **F**: pure local DD.
  **T**: thresholds tuned once.
- Options fall out of the same computation: the calls that are best on a
  material fraction of layouts (a call best on 0% of layouts can never be
  offered — the filler-Pass class dies empirically).
- Risks: DD's known fog (INV5 correction exists); "best call" requires a
  candidate continuation model per call — reuse the existing projection
  machinery; compute cost per kept problem (mitigated by cheap pre-filters
  before full DD).

## Concept R2-2 — Verdict-flip twins: mine the boundary in outcome space

A spot is interesting exactly when it is *sensitive*: move one queen and
the answer changes. Generate a deal, perturb the hero hand minimally (swap
one honor, trade a doubleton), re-run the sim; **keep pairs where the
verdict flips.** Publish them as *twins*: the same auction, two hands one
card apart, opposite answers — "what changed, and why did it matter?"

- This finds the knife edge **empirically** instead of deriving it from
  card algebra — sidestepping every blocker the expert panel raised against
  the lens formalization (jurisdiction, computability, mono-unit bands),
  while keeping the part the panel endorsed (the inversion: define the
  dilemma, then find hands).
- Flip-sensitivity is a system-free property (S ✓): the flip is in IMPs.
- Pedagogically unique: minimal-contrast pairs are how judgment is
  actually sharpened ("with the ♥Q instead of the ♣Q, bid game — the queen
  is working now"). The explanation writes itself from the delta.
- The single hands of a twin are also publishable alone, with the twin
  held back as the post-answer reveal — a product feature no other concept
  has.
- Risks: flips caused by DD artifacts rather than bridge (gate on margin
  exceeding CI on both sides); perturbation search cost (hill-climb from
  near-toss-up hands found by R2-1, not from scratch).

## Concept R2-3 — Distilled field oracle: fix round-1's winner, make it a generator

Direct repair of the concept the owner ranked best, resolving both its
flaws (system confound; finite data):

Train a **small local model once** — gradient-boosted trees or logistic
regression over hand features (HCP, shape, suit quality, seat, vul,
auction-context class), nothing neural or heavy — on the harvested corpus
of real decisions (`harvest/lin.py` already parses LIN; public vugraph /
tournament archives supply volume). The model predicts the *distribution*
of calls strong players choose in a context.

- **The system confound becomes separable instead of baffling**: system
  differences show up as *feature-independent* splits (the same hand types
  go both ways at a fixed ratio — a signature of two populations playing
  different methods), while genuine dilemmas show *feature-driven*
  uncertainty (probability shifts as honors move). Cluster the residuals;
  discard contexts where the split doesn't track hand features; keep
  contexts where it does. That analysis is impossible on raw field counts —
  it is exactly what a fitted model adds.
- **It is a generator (G ✓)**: once trained, the oracle scores any freshly
  *dealt* hand in milliseconds — field-calibrated dilemma detection
  (predictive entropy) and option proposal (top-k calls) on unlimited
  synthetic deals. The finite harvest is spent on training, not on being
  the problem bank.
- **F ✓**: train once locally, minutes of CPU; no APIs ever.
- Verdict remains the DD sim (P ✓); the oracle only nominates.
- Risks: corpus quality/labeling effort (auction-context featurization is
  real work, done once — T ✓); model ceiling (deliberately shallow — it
  detects splits, it doesn't bid); rare contexts underfit (serve only
  contexts with enough support, and report coverage honestly).

## Concept R2-4 — Dilemma-fitness breeding: optimize deals instead of rejecting them

Every pipeline so far *rejection-samples*: deal randomly, test, discard
99%. Instead, make problem quality a **fitness function** and *search*:

`fitness(deal, seat) = closeness of top-2 candidate EVs (from a cheap
proxy sim) × stakes (swing size) × stem plausibility × option-set size
in [2,4] × novelty vs the existing pool`

Then breed: mutate (swap single cards between hands), crossover (exchange
suit blocks between parent deals), climb. Every DD-solve is spent near the
interesting region instead of on random space — orders of magnitude better
yield per compute, which directly answers "each problem takes 20–30s to
build."

- The fitness function **is** the quality spec: every owner complaint
  becomes a term (a missing-option report → penalize small option sets; a
  non-dilemma report → sharpen the closeness term). Tuning replaces
  re-architecting (T ✓).
- Composes with R2-1 (use its two tests as fitness terms) and R2-2 (flip
  pairs are one mutation apart by construction — the breeder finds twins
  for free).
- **G ✓ F ✓ S** (fitness computed in outcome space) **✓**.
- Risks: optimizers exploit their metric — the breeder will find DD
  artifacts and constraint-model leaks if they score well (mitigate:
  novelty pressure, artifact gates as hard constraints, final acceptance
  by the full honest sim, never the proxy); populations can converge to
  one theme (niching by auction family).

## Concept R2-5 — The problem compiler: author families once, deal them forever

The repo already contains the seed of this and calls it something else:
`my_hand_class` + `variants: N` publishes N *fresh seeded deals of the
same decision*, re-simulated. Promote that from a feature to **the
generator**:

- A **problem family** = hand-class for hero (HCP/shape bands), auction
  pattern, option set, meanings for concealed seats — authored *once*,
  expert-reviewed *once* (the five YAMLs in `problems/` are exactly this).
- The **compiler** instantiates unlimited deals from a family: deal hero
  from the class, deal concealed hands from the meanings, re-run the full
  sim per instance (existing machinery, INV1–8 intact). Every instance is
  a fresh board; no two users — no two days — see the same cards.
- Add an **isomorph expander** for concrete classics the owner remembers
  fondly: swap suits (respecting rank), shuffle spot cards, jitter
  non-critical honors within the class — one great problem becomes a
  thousand fresh ones that drill the identical decision.
- Quality lives at family level: ~20 families ≈ one review session (T ✓);
  a family is in *your* system only (S ✓ by construction); zero runtime
  dependencies (F ✓); infinite instances (G ✓).
- Risks: variety is bounded by the family catalogue (mitigate: R2-1/R2-4
  *discover* candidate families empirically, owner inducts the good ones —
  discovery proposes, the catalogue disposes); per-instance verdicts can
  differ within a family (feature, not bug: the family page can show the
  verdict *distribution* — "open this 11-count type: gains on 64% of
  instances").

## Concept R2-6 — Closed-world regret mining: one system, self-play, measured regret

Kill the system-ambiguity problem by **closing the world**: exactly one
card — yours — for all four seats. A deterministic card-driven bidder
self-plays large numbers of cheap auctions (this is NOT SimpleBidder redux:
the bidder is never trusted to *judge*; it only produces card-conforming
auctions). At every hero turn, force each plausible alternative call and
bid both branches out; DD-score both over consistent layouts. A spot is
kept when the card's own recommended call shows **regret** — an alternative
ties it or beats it.

- Dilemma = measured regret of your own system, so every published problem
  is, by construction, a place where *your card* is genuinely under
  tension — the most personally relevant selection criterion of any
  concept (S ✓ trivially: there is only one system in the universe).
- Byproduct: a standing **card audit** — "your 2/1 card loses 0.4 IMPs/board
  in balancing seats over weak twos" — the knife-edge design's boundary
  map, obtained empirically without any lens mathematics.
- **G ✓** (self-play is unlimited) **F ✓ T** (card authoring, once) **✓**.
- Honest risk, stated up front: stem plausibility inherits the
  0.9^10-arithmetic that convicted SimpleBidder (`core_problem_method.md`
  §1.1) — a card-conforming auction is not automatically an expert
  auction. Containment: restrict to shallow stems (≤2 non-pass calls
  before hero) where conformance ≈ plausibility, and let the depth grow
  only as the card earns trust; the deep-auction genres stay with
  R2-1/R2-5.

---

## Comparison against the round-2 constraints

| | G generator | F free/offline | P product kept | S system-safe | T owner time |
|---|---|---|---|---|---|
| R2-1 Empirical mining | ✓ | ✓ | ✓ | ✓ (no system vocabulary) | thresholds, once |
| R2-2 Verdict-flip twins | ✓ | ✓ | ✓ (+ twin reveal) | ✓ (flips are in IMPs) | gates, once |
| R2-3 Field oracle | ✓ (model, not data, is the asset) | ✓ (local training) | ✓ | ✓ (confound made separable) | featurization, once |
| R2-4 Fitness breeding | ✓ (better yield/compute) | ✓ | ✓ | ✓ (outcome-space fitness) | fitness tuning |
| R2-5 Problem compiler | ✓ (per family) | ✓ | ✓ | ✓ (your card only) | ~20 families, once |
| R2-6 Regret mining | ✓ | ✓ | ✓ | ✓ (one-system world) | card, once |

## Natural stacks

- **R2-1 + R2-4**: mining defines quality, breeding searches for it — the
  core generator with the best economics.
- **+ R2-2**: the breeder emits twins as a free byproduct; twins become the
  flagship presentation format.
- **+ R2-3** as the *plausibility* term the fitness function needs (the
  oracle knows what humans actually do at such tables) — field wisdom
  without field noise.
- **R2-5** as the trust anchor: empirically discovered spots that survive
  owner review get inducted as families and generate forever; the
  catalogue is the product's stable core, the miners are its scouts.
- **R2-6** runs beside everything as the card-audit instrument.
