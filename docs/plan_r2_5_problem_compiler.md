# Plan R2-5 — The Problem Compiler (high-level, v2 — post panel round 1)

Status: v2, revised per expert review (`docs/panel/plans_round1.md`).
Date: 2026-07-16. Parent: `docs/problem_quality_concepts_round2.md` §R2-5.

## What it is, in plain language

A **problem family** is a recipe, not a deal:

> *"You hold 10–12 HCP with exactly three spades after partner opens 1♠
> and RHO overcalls 2♥."*

The **compiler** turns a recipe into an endless stream of concrete
problems: fresh hero hand fitting the recipe, concealed hands dealt to
fit what the auction showed, full simulation for *that deal* — because
with ♠KQ5 and club values the answer may be 3♠, while with wasted heart
honors it may be Pass. Same decision, fresh cards, honest per-deal
verdict, forever. **A recipe is reviewed once and generates for life.**

~70% of the machinery exists: `problems/*.yaml` are recipes;
`my_hand_class` + `variants: N` already deals fresh hero hands from a
class and re-simulates each. This plan promotes that side feature into
the main generator and adds the quality layers the panel showed are
missing.

## The v2 quality claim (corrected)

v1 claimed: *family review fixes bridge-sense once; the instance gate
fixes per-deal degeneracy.* The panel showed that is true only at the
class **centroid** — and the centroid was never where this project's
failures came from. v2's claim: **family review fixes the decision's
bridge-sense at the class corners; the instance gate fixes degeneracy,
menu-fit, and stem-fit per deal.** The changes that make it true:

### 1. Conditional options (was: one fixed list per family)

A static menu is bridge-wrong across a class. In "10–12, 3 spades, after
1♠–(2♥)": a flat hand with ♥KJx has natural 2NT live; a 5-card minor
makes 3♣/3♦ live; heart shortness moves the decision into the
splinter/mixed-raise family; heart length + honors makes the penalty
treatment live. So each option carries a **`live_when:` predicate** over
hero features (stopper quality, side-suit length/quality, shortness,
wastage), with its own projection tree; the instance's menu is compiled
from the predicates. Where the predicates get heavy, the honest
alternative is **splitting the class into subfamilies** with constant
menus. (The projection language already reads `*_suit_hcp` — the
machinery is close.)

### 2. The instance gate (was: dominance-only; now four checks)

1. **Missing-option audit** — the v1 gate compared offered options
   against each other and was structurally blind to the best call living
   *off* the menu (deal a heart void inside the 10–12 class and the
   expert call is a splinter no option offers). Per instance:
   mechanically enumerate legal natural + card-conventional calls at the
   decision point (b1 backlog #15) and screen them in two defined stages:
   (i) **card-rule screen** — does any card rule recommend this
   un-offered call for this dealt hand? (pure lookup, no simulation);
   (ii) **generic-tree EV screen** — calls passing (i) are scored with
   *generic short continuation trees* authored once per call family
   (splinter, cue, natural NT, penalty pass, …) as a P0 deliverable, and
   compared against the menu's best. Any un-offered call that screens in
   as plausibly best **rejects the instance, or re-routes it** where a
   catalogue family offering that call exists; **when no target family
   exists the fallback is reject**, and rejection reports distinguish
   "re-routable" from "no home in catalogue" so the catalogue's gaps are
   visible. The screen is calibrated in P0 on the five trusted recipes.
2. **Hero-stem validator** (b1 backlog #5) — a compiled hero must be a
   hand that *would have bid the stem*: a "12–14, opened 1♦" hero that
   any expert opens 1NT is a fictional auction at instance level. Every
   hero stem call is checked against the dealt hand; class schema gains
   suit-quality bands (b1 #4), not lengths alone.
3. **Dilemma test on R2-1's corrected metrics** — not layout-share:
   corrected-EV top-2 gap within the closeness band + stakes floor +
   INV7 CI discipline. Auto-bid instances (one option clearly best in
   EV) are *served as calibration hands or skipped*, never published as
   dilemmas; within-CI instances are toss-ups, never single winners.
4. **Menu display honesty** — the family's option set stays visible per
   instance; options dead on *this* deal are greyed and annotated **after
   the answer** ("X was best on 0 of 800 layouts here — see why"), never
   silently dropped (silent shrinking both changes the lesson and leaks a
   meta-clue).

### 3. Family review over compiled corners (was: review the YAML)

The panel reviews the family **plus a fan of 8–12 compiled corner
instances** — HCP extremes, each shape extreme, max/zero wastage in their
suit — because projection-tree realism is hero-conditional (fixed
thresholds like `me_hcp >= 9` treat a quacky 9-count and two aces
identically: the e50023-20 baked-in-verdict disease). Compile-time
lints: the cross-option consistency linter (b1 #6 — asymmetric
aggression thresholds poison every instance) and a flag on
hero-conditional branches keyed to raw HCP where honor placement decides
(`me_hearts_hcp`, controls).

## Family schema

Existing problem schema + `family_id`, hero hand-class with suit-quality
bands, conditional options (`live_when:` + per-option trees), principle
text, tags (genre, vulnerability, scoring form), instance-gate
thresholds. Semantics rulesets and the projection language are reused.

## Where families come from (trust order)

1. **Owner-authored** — the panel's proposed starter catalogue (20
   families, quota ≈ 60/25/15 competitive / constructive / high-level) is
   recorded in `docs/panel/plans_round1.md` §R2-5: twelve
   competitive/raise families (raise structure after 1♠–(2♥); 3-over-3
   pushes; balancing after 1M–P–2M; 5-level/forcing-pass [exists];
   negative double vs penalty pass; support-double positions; "they push
   us" sequences; action doubles; 1M–(X) responder structure; …), five
   constructive 2/1 judgment families (3NT vs 4M with 5-3-3-2; opener's
   awkward 5-4-3-1 rebid; semi-forcing 1NT decisions; minimum-GF slam
   try; fourth-suit vs raise), three high-level/preempt families.
2. **Classics from memory** — generalized by drawing a tight class around
   the remembered hand; the ordinary compiler generates the variety.
   (v1's suit-swap isomorphs are **cut**: the panel showed a legal swap
   must preserve the rank order of every suit mentioned in stem, options
   and trees — which forces the identity permutation. Spot shuffles and
   honor jitter are just class dealing, already free.)
3. **Mined candidates** — R2-1 spots proposed as families; the owner
   inducts or rejects. Discovery proposes, the catalogue disposes.

## Family product surfaces

- **Verdict-distribution page**, fixed per the panel: the *taught*
  distribution is computed over **all compiled instances, pre-gate** (the
  gate filters what is *served*, never what is *taught* — a post-gate
  distribution would systematically understate the majority action and
  teach a false prior); within-CI instances land in a toss-up bucket;
  one-line caveat that percentages are over the sampled class, not
  at-the-table frequency; `breakdowns:` extended to hero features
  (wastage, controls, trump quality) so exception clusters are computed,
  not asserted.
- **SRS keyed by family**: a lapse schedules *fresh instances* of the
  same decision — repetition that never repeats a board. Toss-up
  instances grade as "exposure," not pass/fail.
- **Explanations** (every instance): family principle + **instance
  delta** — the concrete features that put this hand on this side of the
  line ("your ♥QJ sits under the raise — wasted; that's why this 11-count
  passes while 64% of the family bids"); margin-calibrated vocabulary
  (b1 #18: sub-CI edges say "the panel would split", never "clearly
  right"); near-boundary instance pairs surfaced as twins — the
  contradiction becomes the lesson; no doubling lesson asserted without
  the penalty-branch DD discount (b1 #12).

## Pipeline

```
family YAML (authored once; panel-reviewed over compiled corners)
   → compiler: hero from class → concealed from meanings → full sim
   → INSTANCE GATE: missing-option audit / hero-stem validator /
     EV-gap+stakes+CI dilemma test / menu compilation (live_when)
   → publish (family_id, principle, instance delta, verdict or toss-up)
```

No engines, no APIs. New code: the gate's four checks, conditional
options, corner-compile review support, family/catalogue surfaces.

## Sequencing with R2-1 (round-2 verification note)

Gate check 3 consumes R2-1's corrected metrics and their pre-registered,
stake-normalized thresholds — so **R2-1's P0 completes before this
plan's gate thresholds freeze** (if R2-1 dies in its P0, the gate falls
back to the existing ≤3-IMP + INV7 machinery, losing the stakes floor
but not the audit or the validators). Separately, R2-1 pre-declares
penalty/doubled, sacrifice/5-level and invitational genres out of its
scope for *directional* DD bias; the starter catalogue deliberately
includes such families (negative-double-vs-penalty-pass, 5-level,
sacrifice, invite-or-blast). For those genres the gate's dilemma test is
**quarantined to CI-discipline only + a genre flag**, and their P1
authoring is scheduled after the correction table is validated for the
genre — the b1 #12 penalty discount applies to the *gate*, not just the
explanations.

## Phases (re-budgeted per the panel)

- **P0 — Promote the existing five + build the gate (~1.5–2 weeks).**
  Family wrapper; the four gate checks (hero-stem validator and
  cross-option linter promoted from b1 backlog to deliverables here);
  compile 20 instances each; measure gate rejection rates. Gate: owner
  plays 10 instances, rubric Q1–Q5.
- **P1 — Catalogue sprint (~3–5 weeks calendar, owner-paced).** Honest
  authoring economics: **1–2 days per family end-to-end**
  (author → panel over corner instances → revise), not "an afternoon";
  constructive/slam families cost 2–3× the competitive ones — quota
  weighted accordingly. ~10 families.
- **P2 — Product surfaces (~1 week).** Family pages (pre-gate taught
  distribution), SRS by family, catalogue browsing.
- **P3 — Feeders.** Mined-candidate induction queue from R2-1; classics
  intake.

## Risks

1. **Variety ceiling** — accepted consciously; mined feeders grow breadth.
2. **Family review is load-bearing** — mitigated by corner-instance
   review, the two lints, and the pre-gate distribution page making a
   sick family visible (a "raise-or-pass" family where Pass wins 92% is
   mis-specified on its face).
3. **Gate strictness trade-off** — tuned in P0 on the five trusted
   recipes; rejection *reasons* are logged and reported per family.
4. **Conditional-option authoring weight** — the escape hatch is
   subfamily splitting, which trades authoring effort for catalogue size,
   both bounded.
5. **Owner stamina** — ~10 families at the honest budget is the P1 ask;
   feeders exist so the catalogue never depends on his output forever.

## What the owner gets

The strongest quality guarantee in the portfolio — every published
decision reviewed by an expert once, *at its class corners* — combined
with everything he asked for in round 2: a true generator, fully
offline, his system only, per-deal honest verdicts, and spaced
repetition on fresh cards that no fixed bank can imitate.
