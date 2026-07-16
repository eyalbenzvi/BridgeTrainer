# Knife-Edge Generation — Full Concept (v1 draft)

Author role: bridge expert (2/1 GF) + software architect.
Status: high-level design for expert-panel review, then owner decision.
Date: 2026-07-16. Parent: `docs/problem_quality_concepts.md`, Concept 2.

---

## 0. Thesis

Every pipeline so far has **dealt first and asked "is this a problem?"
second** — with a bot, an LLM, or an ensemble as the asker, and three
batches of owner-flagged failures as the answer. Knife-edge generation
inverts the direction: **define what a dilemma is, mathematically, in the
terms bridge experts actually use — then generate or select hands that
satisfy the definition.** Clear-cut hands (e50006-19's routine 1NT,
b2-000273ee's automatic Stayman) become *ungeneratable*, not merely
filterable; the option list is *derived* from the same definition instead
of authored, so a missing 2C or a nonsense Pass (f50022-21's missing
3NT/4C/X) becomes a type error, not a review finding.

## 1. The objection this design must defeat first

`docs/core_problem_method.md` §1.3(c) already convicted a naive version of
this idea: the bot's slack mechanism generated *threshold near-misses* —
"1 HCP from a boundary of a non-expert rule set" — and they were not
dilemmas. Any design that generates hands "close to a card boundary" walks
straight back into that conviction unless it changes what "boundary" means.

**The fix is the core of this design.** A real dilemma, per §1.3(c) itself,
is a spot where *principles conflict*. So the knife edge is not distance to
one rule's threshold measured by one metric; it is **disagreement between
independent, expert-endorsed evaluation lenses**, each applied to the same
card:

> A hand is on the knife edge for a decision context when two or more
> standard evaluation methods, honestly applied to the partnership's own
> card, recommend *different systemic calls*.

"1 HCP short but nothing else going on" disagrees with nobody — every lens
says pass — so it is interior, and is never generated. That is the precise
difference between this design and the slack mechanism.

## 2. Architecture overview

```
Archetype taxonomy (curated, versioned)         The Card (machine-readable 2/1)
        │                                                │
        ▼                                                ▼
  stem templates ──► stem realization ──► region map at the decision point
        │                (deal/harvest)                  │
        ▼                                                ▼
  lens battery ───────────────► DISAGREEMENT SAMPLER ──► hero hand on the edge
                                                         │
                                                         ▼
                              options = the straddled regions (derived, complete)
                                                         │
                                                         ▼
              existing machinery: meanings (semantics) → layouts (dealing)
              → continuations (finalize/projections + hard shell V1–V7)
              → DD + IMP stats (dd/, scoring/, INV1–INV8) → verdict → publish
```

Everything below the sampler is the current pipeline, unchanged. The design
replaces only the two components that produced all owner-flagged failures:
**where spots come from** and **where option lists come from**.

## 3. The five artifacts

### 3.1 The Card (machine-readable convention card)

The single source of truth for what every call means, already the
prerequisite of hard-shell V2. Seeded from the existing
`semantics/rules/our_2over1.yaml` notation: per auction context, each
systemic call carries HCP bands, per-suit length bands, quality floors, and
named exclusions. Extended with two fields per rule:

- `lens_bands`: which evaluation lens each numeric band is expressed in
  (default: raw HCP — but a limit raise is *defined* in support points, a
  preempt in playing tricks; the card should say so, as real system notes do);
- `always_available`: calls that exist as alternatives in this context even
  when not the primary recommendation (X where legal and systemic, e.g.),
  so option derivation can include them.

Owner effort: days, amortized forever; every rule is reviewed once, versioned,
and reused by V2, by this design, and by explanations.

### 3.2 The lens battery

Standard, published, computable evaluation methods — each a pure function
`lens(hand, context) → call` obtained by evaluating the card's regions
under that lens's metric:

| Lens | Metric | Where it rules |
|---|---|---|
| L-HCP | raw Work points | default band arithmetic |
| L-ADJ | adjusted points (aces/tens up, quacks down, flatness penalty, honors-in-shorts penalty) | opening/inviting borderlines |
| L-LTC | losing trick count + cover cards | fit auctions, raises |
| L-SP | support points (shortness with fit) | raises |
| L-PT | playing tricks | preempts, overcalls, rebids |
| L-LAW | total-trumps arithmetic | competitive part-scores |
| L-ODR | offense-to-defense ratio | sacrifices, forcing passes, high-level X |
| L-TEX | texture/stoppers (NT suitability) | NT vs suit choices |

Every lens is a published method with decades of expert literature behind
it — the battery encodes *recognized* schools of judgment, not invented
thresholds. Lenses are versioned; adding or tuning one is an expert-review
event, like a card change.

### 3.3 The archetype taxonomy

A curated catalogue of judgment families. Each archetype specifies:

- **context pattern** — auction-stem template(s) with slots
  (e.g., `1M – (pass|overcall) – ?` for the raise family);
- **the conflict** — which lens pair must disagree, between which regions
  (e.g., L-SP says 3♠ limit raise, L-LTC says game);
- **option derivation rule** — the straddled regions plus
  `always_available` calls, capped at 4;
- **principle text** — the named idea being drilled ("shape beats points
  in fit auctions", "the LAW vs. pushing them into game");
- **publishability tag** — `drill` (one defensible answer exists),
  `judgment` (a panel would split; publish as toss-up), or
  `style` (**never publish** — this is e50006-19's tombstone: the
  1NT-vs-1m-with-17-balanced family is *tagged style at the taxonomy
  level* and cannot recur).

Seed catalogue (~15 families): open-or-pass borderline; limit-vs-GF raise;
invite-vs-game acceptance; overcall-vs-double-vs-pass (incl. off-shape X);
two-level overcall discipline by vulnerability; first-seat preempt
discipline; 3-over-3 LAW decisions; reopen-vs-sell in balancing seat;
5-level bid/double/pass; forcing-pass agreements; misfit discipline;
action doubles; game-try acceptance; sacrifice arithmetic; quantitative
slam invites.

### 3.4 The disagreement sampler

Given an archetype and a realized stem, produce hero hands in the
**disagreement set** `D = {h : lens_i(h) ≠ lens_j(h), both calls systemic}`.

- **Mode G (generate)**: vectorized rejection over the existing NumPy
  dealer, predicate = archetype conflict. If acceptance is too low,
  the reserve dealers already contemplated in the README (shape-vector
  enumeration with combinatorial weighting, INV3-honest) construct hands
  directly.
- **Mode H (harvest-filter)**: scan harvested real-deal stems for hero
  hands already inside `D` — keeps the owner's decision-record preference
  for real tournament provenance; the archetype predicate becomes a
  *selection* criterion instead of a generation one.
- **Mode M (mutate)**: take a real deal near the edge and swap 1–2
  non-structural cards to land exactly on it (provenance recorded as
  "derived from board X").

A **difficulty dial** falls out for free: depth of disagreement (how many
lenses split, how far inside `D` the hand sits) is a per-problem scalar —
near-edge = subtle, deep-split = textbook classic.

### 3.5 Option derivation (completeness by construction)

Options are **computed**: the set of calls named by the straddling lenses,
plus `always_available` calls in that context, capped at 4 with a
determinism rule for overflow. Two guarantees follow:

- *No absurd option*: every option is some lens's honest recommendation
  under the card (Pass appears only if a lens genuinely recommends it —
  b2-000273ee's filler Pass cannot occur).
- *No missing option relative to the card*: any call a card-playing expert
  would consider is a region this hand touches; if 3NT/4C/X were live in
  f50022-21, their regions contain the hand and they are in the set. (An
  expert consideration *outside* the card — a masterful psyche — is out of
  scope by design; this is a trainer for a system, not for anarchy.)

## 4. What stays exactly as it is

The evidence stack survives untouched, per the owner decision record:
meanings from `semantics/`, constrained layouts from `dealing/` (INV2/3),
continuation projections + hard shell V1–V7 from `finalize/` and
`validate/`, DD + corrected IMP comparison from `dd/` + `scoring/`
(INV1, INV5–INV8), pool/webapp publishing. **The DD simulation remains the
sole verdict authority.** Knife-edge generation only changes what enters
the top of that funnel.

Honest non-goal: **continuation realism is not solved here.** Projection
trees are still authored (LLM finalizer + V6) or, later, engine-rolled
(Ben/EPBot per the architecture brief). Knife-edge is orthogonal to, and
composes with, whichever continuation source wins that debate.

## 5. Emergent property: the boundary map

Aggregating verdicts across many problems of one archetype produces an
**empirical map of the card's boundary**: "quack-heavy 11-counts lost an
average 0.7 IMPs by opening; ace-rich 10-counts gained." The trainer stops
merely testing the user against the card and starts testing **the card
against the universe** — published as per-archetype summary pages. No other
concept produces this; it exists because problems are indexed by archetype
and position-on-edge from birth.

## 6. Failure-mode check (the three cited problems + b2 howlers)

| Failure | Why it cannot recur |
|---|---|
| f50022-21 — unreasonable given 3C; missing 3NT/4C/X | Stems are realized from card rules (dealt conforming hands) or harvested real auctions; a call no rule produces can't appear in a stem. Options are the computed straddled-region set — completeness relative to the card is structural. |
| e50006-19 — clear 1NT published as a problem | Interior point of the 1NT region under every lens → not in `D` → ungeneratable. Its family is additionally tagged `style` in the taxonomy — tombstoned twice. |
| b2-000273ee — Stayman missing, Pass offered | 2C region contains the hand under every lens → in every derived option set. No lens recommends Pass → Pass cannot enter the set. |
| b2-0135277b (penalty-X nonsense) | X enters options only via card regions / `always_available` with its card meaning attached; meaning text comes from the card, not a bot's private definition. |
| b2-01352789 (Pass-with-10-opposite-opening in set) | Same as Pass above: no lens, no entry. |

## 7. Risks and mitigations

1. **Card + taxonomy authoring is real expert work** (days, plus review
   events for every change). Mitigation: seeded from existing semantics
   YAML; each archetype ships with golden example hands; the b1-style
   expert panel reviews the catalogue once, not every problem.
2. **Lens formulas are contestable** (whose LTC? which adjustments?).
   Mitigation: published standards only, versioned, expert-reviewed once;
   disagreement between *reasonable* lens variants widens `D` slightly —
   acceptable, since the sim still judges.
3. **Synthetic hands lack real-table provenance**, in tension with owner
   decision #3. Mitigation: Modes H and M keep real provenance; Mode G is
   the volume/curriculum fallback. The decision record needs an owner
   amendment either way — flagged explicitly for that conversation.
4. **Taxonomy coverage bias**: the tool drills what the catalogue names and
   is blind to unknown dilemma families. Mitigation: harvest-side discovery
   (field divergence) proposes *new* archetypes for expert induction into
   the catalogue — the taxonomy grows by observation, not only authorship.
5. **Style leakage**: some lens conflicts are style, not judgment (the
   panel decides by temperament, and both sides shrug). Mitigation: the
   `style` tag; plus the existing toss-up discipline (INV7) publishes
   honest coin-flips as toss-ups when they slip through.
6. **Continuation realism remains the weakest layer** (inherited, not
   created, by this design) — see §4 non-goal.

## 8. Migration phases

- **P0 — Card + 3 archetypes (~1 week).** Extend semantics YAML into the
  card schema; author limit-vs-GF raise, off-shape X, open-or-pass
  borderline with golden hands; lens battery for L-HCP/L-ADJ/L-SP/L-LTC.
  Gate: expert panel review of card + archetypes (documents, not code).
- **P1 — Sampler + first batch (~1 week).** Mode G sampler; 10 problems
  through the existing finalization/hard-shell/DD pipeline. Gate: owner
  rubric Q1–Q5 (`core_problem_method.md` §6), targets as Phase-2 there.
- **P2 — Taxonomy buildout + Modes H/M (~2 weeks).** ~12 archetypes;
  harvest-filter mode; difficulty dial surfaced in the webapp; per-archetype
  category pages. Gate: owner rubric, ship targets.
- **P3 — Boundary map + curriculum (~1 week).** Per-archetype verdict
  aggregation pages; spaced repetition keyed by archetype instead of by
  problem.

## 9. Cost profile

No new engines, no new runtime dependencies, no API cost in the core loop
(LLM remains only where it already is: finalization prose). Generation is
NumPy rejection + existing DD (~13 ms/deal); wall clock per problem is
unchanged from today. The scarce resource spent is **expert authoring time
on card, lenses, and taxonomy — spent once, versioned, and reviewable**,
instead of expert review time spent per-problem, forever.
