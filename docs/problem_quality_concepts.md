# Problem Quality: Seven Orthogonal Concepts — Idea Brief

Status: concepts only, no implementation. Date: 2026-07-16.

## The trigger (owner review of the live pool)

1. **f50022-21** — the given 3C bid in the stem is not a reasonable bid, and
   the option list is missing obvious candidates (3NT, 4C, X).
2. **e50006-19** — not a problem: a clear 1NT opening, at most a style
   question, published as a toss-up.
3. **b2-000273ee** — a clear-cut Stayman hand where 2C is not among the
   options, while Pass (absurd) is.

Owner conclusion: **the bridge level of the problems is the core defect.**

## Why this brief exists next to `bridge_architecture_options.md`

Yesterday's brief compared five answers to one question: *which bridge
brain authors/validates a finalization document?* Batch b3 was built with
ensemble machinery and still shipped e50006-19. The failures above are not
(only) brain failures — they are failures of **where options come from**,
**what counts as a dilemma**, **what the answer key is**, and **what the
product shape is**. Each concept below moves a different one of those
levers. They compose with each other and with the hard shell (V1–V4) and
any brain from the prior brief.

---

## Concept 1 — "The field is the panel": harvest real divergence

Stop deciding what a problem is; observe it. Source boards exclusively
from multi-table events (vugraph archives, BBO tournament LIN files — the
harvest layer already parses LIN) where the *same board* was bid at many
tables by strong players.

- **Dilemma detector**: the entropy of the field's actual calls at the
  decision point. 28 of 30 tables opened 1NT → not a problem, discard.
- **Option list**: the calls real players actually made at that point (plus
  nothing else). Stayman appears because people bid it; a nonsense Pass
  never appears because nobody passed.
- **Stem sanity**: every auction prefix was produced by real players, so an
  unreasonable given 3C can't occur — someone had to actually bid it at
  multiple tables for the stem to qualify.
- **Answer key**: DD sim as today, now *anchored* by the field split.

Kills all three cited failures by construction. Risks: data volume (need
many-table events at sufficient standard); field-level skew (a club field's
splits are noise); decision points cluster in fashionable auction families.

## Concept 2 — Knife-edge generation: start from the dilemma, not the deal

Invert the pipeline. Maintain a taxonomy of classic judgment archetypes
(invite-vs-game, 5-level decisions, off-shape takeout X, reopen-vs-sell,
raise-vs-rebid...) expressed as *pairs of adjacent rule regions* on the
machine-readable convention card. Then constraint-generate hero hands that
sit exactly **on the boundary** between two regions (e.g., 11 HCP with a
5th-card queen that the card's 1NT-invite rule counts and its 2-over-1
rule doesn't).

- A clear-cut hand (17 bal → 1NT; 4-4 majors over 1NT → Stayman) is an
  *interior* point of one region and mathematically cannot be generated.
- The option set is the calls whose regions the hand straddles — 2, 3, or
  4 genuine candidates, never a filler Pass.
- Coverage is programmable: you choose which judgment themes to drill.

Risks: the card must be authored (already a prerequisite of V2); dilemmas
are only as interesting as the taxonomy; loses the "real deal" provenance
(can be hybridized: search harvested deals for boundary hands instead of
dealing them).

## Concept 3 — Jury of strong bidders, upstream

Different from the ensemble in the prior brief (which cross-examines a
*finished document*): put the jury at the **front** of the pipeline as the
detector and generator. N independent bidders — Ben, EPBot, 2–3 LLM
personas each locked to a named card — bid the hero seat at the stem,
blind, no coordination.

- **Unanimity → discard.** e50006-19 dies: every juror opens 1NT.
- **Option list = union of jury choices.** 3NT/4C/X appear on f50022-21
  because some juror chooses them; 2C appears on the Stayman hand.
- **Veto**: any option no juror ever selects (Pass on a Stayman hand) is
  deleted; if the *stem itself* contains a call no juror would make from
  the visible evidence, the board is rejected as an unreasonable premise.
- The jury's vote split is published as metadata — an honesty label.

Risks: correlated priors among LLM jurors (mitigate with different cards
per persona); engine system mismatch creates false splits (a transfer vs
natural response is a system difference, not a dilemma) — needs a
"same-meaning" collapse using the card.

## Concept 4 — MSC-in-a-box: score against a panel, not a single winner

Change the **answer model**, not the generator. Real bridge training (the
Master Solvers' Club, 60 years running) never claims one right answer; it
scores you against an expert panel's vote distribution with argued
minority positions. Simulate that: 10–15 diverse expert personas (different
styles: aggressive/sound, scientist/gambler; plus the engines) vote and
write one-paragraph arguments; a moderator synthesizes; the user is scored
MSC-style (100/80/60/...) against the distribution, with the DD simulation
published as *evidence the panel argues about*, not as the verdict.

- "Style questions" flip from a bug to legitimate content — but a 15–0
  vote auto-retires the problem below an entropy threshold, so clear 1NT
  hands still never publish.
- The awkward INV7 toss-up presentation becomes natural: a 8–7 panel split
  IS the answer.
- Failure (2) of v5 (fabricated 0.5-IMP precision) loses its sting: the
  panel, not the margin, carries the verdict.

Risks: the panel is only as good as its personas (the b1 expert-panel
review shows LLM panels catch a lot, but share blind spots); cost per
problem rises; needs honest guardrails so prose never contradicts the sim.

## Concept 5 — Flip the product: bid whole auctions, problems emerge from you

Remove the curated-problem bottleneck entirely. The app becomes a bidding
table: you bid **every call** of your seat on a random (or harvested)
board; an engine bids the other three seats. Wherever your call diverges
from the engine/field/jury, *that moment* is flagged and queued for the
full simulate/DD treatment offline; the verdict comes back to you as a
review item (spaced repetition over your own leaks).

- No option list to get wrong — you can make any legal call.
- Non-problems cost three seconds of play instead of polluting a bank.
- The training signal is personalized: the system discovers *your*
  disagreement surface instead of guessing at universal dilemmas.
- The existing pool machinery survives as the async analysis backend.

Risks: engine quality now shapes every auction (system mismatch is felt
constantly, not per-problem); "play a bad board fast" is a different UX
proposition than "here is a curated gem"; harder to share/discuss problems.

## Concept 6 — Import human-authored problems; be the evidence engine

Concede authorship. Thousands of expert-authored bidding problems already
exist: MSC archives, national magazine panels, Bridge Winners polls
(thousands of real expert votes), classic books. Their stems, options, and
expert answers are already panel-quality — what they *lack* is exactly what
this repo uniquely has: the INV1–INV8 statistically honest DD simulation.
The product becomes: expert-authored problem + this pipeline's evidence
("the panel said 3S; over 800 constrained layouts, 3S gains 0.8 IMPs,
CI ±0.3"). Authorship — the component that produced all three cited
failures — is removed from the machine entirely.

Risks: copyright (needs public-domain/permitted sources, or
paraphrase-with-attribution, or personal-use-only positioning); options
and meanings must still be transcribed into the schema (small, checkable
work); the bank's topics follow the sources' tastes.

## Concept 7 — Canary publishing: problems must earn tenure

Treat quality as a lifecycle, not a gate. Every generated problem ships in
**probation**: shown to the user(s) with two one-tap affordances — "not a
problem / missing option / bad stem" flags, and normal answering. Telemetry
retires problems automatically: if all answerers choose the same call
quickly, it is a non-dilemma and self-destructs; flag reasons are tagged
and fed back as few-shot counterexamples to whichever generator runs
upstream. The bank converges toward problems that *survive contact with a
bridge player* — the exact filter (owner review) that caught all three
cited failures, formalized and made cheap.

Risks: with a single user the sample is one expert (still the product's
target); bad problems are seen before they die (probation must be labeled
as such: "new problem — rate it"); improvement rate is bounded by play
volume.

---

## How they map to the three cited failures

| | f50022-21 (bad stem, missing options) | e50006-19 (non-problem) | b2-000273ee (no Stayman, absurd Pass) |
|---|---|---|---|
| 1 Field-as-panel | stem must have occurred at real tables | field unanimity → discard | options = calls actually made |
| 2 Knife-edge | stems built from card-legal boundaries | interior points can't generate | option set = straddled regions |
| 3 Jury upstream | juror veto on stem + union options | unanimity → discard | 2C in union; Pass vetoed |
| 4 MSC scoring | panel refuses to dignify bad stem | 15–0 vote → auto-retire | panel votes supply options |
| 5 Whole auctions | no curated stems exist | costs 3s of play, no pollution | no option list at all |
| 6 Import human problems | experts authored the stem | editors never publish it | experts list real options |
| 7 Canary tenure | flagged and retired | telemetry retires it | "missing option" flag re-queues |

## Composition notes

These are not mutually exclusive; they are levers on different axes
(source, generation direction, gating, answer model, product shape,
authorship, lifecycle). Natural stacks:

- **1 + 3 + 7**: real-field boards, jury-generated options, canary tenure —
  no authored bridge anywhere in the loop.
- **2 + 4**: card-boundary generation with MSC panel scoring — maximal
  control over curriculum, honest answers on genuine style spots.
- **5 as the long-term product**, with 1/2/6 feeding its board queue.
- **6 + existing pipeline** is the lowest-risk immediate quality jump:
  panel-grade problems on day one, simulation as the added value.
