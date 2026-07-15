# Bridge Understanding: Five Architectural Approaches — Decision Brief

Author role: bidding-panel-caliber bridge expert + senior software architect.
Status: decision brief for owner choice. No implementation. Date: 2026-07-15.
Fixed owner decisions honored throughout (decision record,
`docs/core_problem_method.md`): DD simulation judges the finalized options;
problems sourced from real tournament deals; offline batch generation, no
scheduled jobs; the INV1–INV8 statistics stack is the evidence engine.

---

## 0. What the three v5 failures prove

v5 removed the toy bot and put a capable generalist LLM in the author's
chair, with a schema (`bridge_trainer/finalize/schema.py`) that validates
*shape* but not *bridge*. The owner's review found three new errors. Each
one identifies a **missing guarantee**, and each guarantee is mechanically
computable — meaning it was a design failure, not an authoring failure, that
these could reach review at all.

**(1) f50022-21 — auction-legality blindness.** The stem
`1D P 1H 3S 4H 4S P P ?` has two passes standing; hero's Pass is the third
consecutive pass and **ends the auction**, yet the projection for "P" routes
layouts to 5H♠/4S♠x and the explanation says Pass "hands partner the
decision." Missing guarantee: **an auction-state engine in code** — pass-out
detection, insufficient bids, X/XX legality, whose turn, what contracts are
still reachable. No author, human or LLM, may ever be the source of truth
for auction mechanics. `validate_finalization` checks call *syntax*
(`VALID_CALL`) and tree shape; it never looks at the stem.

**(2) f50021-27 — fabricated precision on information-equivalent options.**
2S vs 3S (cue vs jump cue) differ almost purely in *information exchanged*,
not in the contracts they mechanically reach. The author invented two
different continuation trees, and DD then "measured" a 0.5-IMP gap that is
an artifact of the trees, not of bridge. Missing guarantees:
**option-equivalence detection** (when two options' meanings differ only in
information, their continuations must be derived by one consistent
mechanism or the pair must be collapsed / published as a declared toss-up)
and **continuation-margin honesty** (a DD gap smaller than the uncertainty
of the continuation model itself is noise and must be labeled as such —
an extension of INV7 from sampling error to *model* error).

**(3) f50003-18 — no system of record.** 2D — a two-level free bid showing
~10+ in the 2/1 system being taught — was offered and *won* with an 8-count.
Missing guarantee: **a machine-readable convention card** that every option
is checked against twice: (i) *availability* — the call exists with this
meaning in this auction; (ii) *conformance* — the hero's actual hand
satisfies the call's requirements. Same check applies to the authored
`meanings` of concealed seats, with a free oracle: the **real deal's actual
concealed hands** must satisfy the authored meaning bands (real players
held those cards and made those calls).

### The hard shell — mandatory regardless of approach chosen below

Deterministic validators, pure code, no ML, run before anything is judged:

- **V1 Auction legality**: full auction state machine; every option legal at
  the stem; every projected contract reachable by some legal continuation;
  auction-over detection (kills class 1).
- **V2 Convention-card conformance**: options and meanings checked against a
  versioned machine-readable 2/1 card (kills class 3).
- **V3 Equivalence / margin honesty**: information-only option pairs
  detected from the card; near-identical projected-contract distributions
  collapsed or declared toss-ups; DD gaps below continuation-model
  uncertainty never published as winners (kills class 2's *publication*;
  only an engine kills its *cause* — see below).
- **V4 Meaning/simulation consistency**: real deal's hands satisfy the
  meanings; sampled layouts audited against them; explanations generated
  from validator-checked structured claims, never free-assert auction
  mechanics.

**Candidate C (full system codification) — evaluated and folded.** An
expert-authored DSL bidding system at real scale is EPBot's life's work and
GIB's ~3000 pages of system notes; the v2/v3 arithmetic (§1.1 of the prior
doc) says owner-scale rule authoring caps out far below panel quality, and
every rule needs the same expert review that is the scarce resource. But
codification has a crucial asymmetry: **validating** a call ("is 2D
systemic here?") needs a card two orders of magnitude smaller than
**generating** one. BML (github.com/Kungsgeten/bml, gpaulissen/bml +
gpaulissen/bridge-systems) gives a bootstrappable notation for exactly this
reduced card. So C survives as V2 of the hard shell and as the conformance
backbone of every approach below — and is rejected as a standalone bidding
brain. That is why five approaches are briefed, not six.

---

## 1. Approach A — Ben (neural engine) as the bridge brain

**Concept.** The pretrained Ben engine (github.com/lorserker/ben, GPL-3.0,
Python/TF, CPU-only, live on BBO, GIB-flavored 2/1 models shipped in-repo)
replaces the *authored* parts of the finalization document. Harvest still
supplies real-deal stems. At the decision point, Ben's policy distribution
supplies the 2–5 options (probability threshold) and the dilemma signal
(top-call probability < ~0.7). Ben's auction-consistent hand sampler
replaces authored meaning bands for layout generation. Continuations: Ben
bids each option out to legal completion, all four seats, per layout —
replacing authored projection trees entirely. DD judges, as decided. An
LLM may still write prose, quoting only validated facts.

**Guarantees.** Auction legality of continuations *by construction* (an
engine cannot bid past three passes). Candidates from trained judgment, not
authorship. Continuations per layout are real auctions — class (2)'s cause
dies: 2S and 3S are rolled out by the same policy, so any DD gap reflects
the model's actual responses to the information difference, and V3 can
measure rollout-distribution similarity directly. **Cannot guarantee:**
exact match to the owner's card (GIB-flavored 2/1 — the owner must accept
it as "close enough to train against"); human-readable meanings (samples,
not statements — the published `meanings` text needs an LLM or card
lookup, checked by V4); sane behavior in rare/undisciplined auctions;
that its hand sampler's biases don't leak into EV (re-establish INV7-style
ESS honesty on its samples).

**Advantages**
- The only approach where continuation realism is *supplied*, not merely
  checked — the deepest v5 failure becomes structurally impossible.
- Policy distribution is a native dilemma detector and candidate source.
- Free, active (v0.8.8.4, June 2026), Python, CPU-only; fits the offline
  producer; battle-tested on BBO (~1 IMP/board over GIB Basic at bidding).
- Meanings-as-samples encode negative inferences no band notation can.

**Disadvantages / risks**
- System mismatch is permanent background noise; specific double meanings
  and raise structures will occasionally grate on a serious 2/1 player.
- Opaque: when Ben does something weird there is no rule to fix — only
  thresholds, genre whitelists, and vetoes.
- GPL-3.0: keep behind a process boundary if this repo is ever distributed.
- ~2–3 GB models in CI cache; rollouts × layouts × options is the new
  wall-clock driver (tens of seconds to minutes per problem — tolerable).

**Cost & effort.** Build: ~1–2 weeks (adapter: policy / sample_hands /
bid_out; wire into `build_record`; hard shell shared). Per problem: $0
engine (+ ~$0.01–0.05 LLM prose, optional). Runtime ~30–120 s/problem CPU.
Licensing GPL-3.0 (fine for personal use). Owner provides: a verdict on 20
printed Ben auctions ("close enough?") — the Phase-1 gate already designed.

**Failure-mode check.** (1) Impossible: the state machine ends the auction
after hero's pass; "P" projects to 4S-undoubled mechanically; prose is
generated from that checked fact. (2) Both cue-bids rolled out by one
policy; if partner's responses don't actually differ, distributions match
and V3 collapses/toss-ups the pair — no fabricated 0.5 IMPs. (3) Ben's
policy gives 2D-on-8 negligible probability (its card wants ~10+), so it is
never nominated; V2 blocks it even if injected.

---

## 2. Approach B — Hardened LLM finalizer (automate the current contract)

**Concept.** Keep the v5 architecture — the finalization document *is* the
product of one API call per problem — but harden it three ways. (i) The
hard shell rejects before anything is simulated. (ii) The prompt carries
the machine-readable card, and every option, meaning, and projection rule
must **cite the card line** it relies on; uncited or miscited bridge claims
are mechanical rejects. (iii) **Self-consistency sampling**: N independent
finalizations (N=3–5, varied seeds/orderings); publish only where the
option sets agree and the projected-contract distributions are stable;
disagreement is itself a signal (either a genuine judgment spot → owner
queue, or model confusion → discard). Explanations generated last, from
validated facts + final DD numbers only.

**Guarantees.** All three observed error classes are caught (see below).
Meanings are human-readable and card-anchored — the best explanations of
any approach. **Cannot guarantee:** continuation *realism* — the trees are
still authored; stability across N samples proves consistency, not truth;
correlated blind spots (same model, same GIB-heavy training priors) pass
every vote unanimously. v5 *was* this approach minus the hardening; the
honest claim is "the three known classes die; unknown classes are only
dampened."

**Advantages**
- Smallest distance from working code: schema, projector, judging pipeline
  all survive unchanged; only `panel/llm.py` + validators + card are new.
- Prose quality and meaning-labeling are the LLM's genuine strengths.
- Card citations make every problem auditable line-by-line after the fact.
- No new runtime dependencies; batch API fits the offline producer.

**Disadvantages / risks**
- The proven failure mode (authored continuations) is gated, not solved:
  V3 catches *equivalent* options, but a plausible-looking wrong tree for
  genuinely different options sails through and DD judges fiction.
- N-way sampling multiplies cost and still shares one brain.
- Card authoring is real owner work and becomes the de-facto system spec.
- Rejection rates may be high early (good) and demoralizing (real).

**Cost & effort.** Build: ~1–2 weeks (validators + card + prompts + N-way
agreement logic). Per problem: ~$0.05–0.30 at N=3–5 on an Opus-class model
(halved via Batches API). Runtime: seconds of API + existing simulation.
Owner provides: the 2/1 card (a few days, amortized — reused by V2 forever)
and periodic prompt-rubric review.

**Failure-mode check.** (1) V1 rejects: projection for "P" names contracts
unreachable from a dead auction; the citation requirement would also force
the model to state pass-count. (2) V3: card shows 2S/3S differ only in
information; trees must come from one declared mechanism or the pair
collapses; N-way sampling would also expose the arbitrariness as
instability. (3) V2 rejects: 2D's cited line demands 10+; hero has 8 —
mechanical, before simulation.

---

## 3. Approach D — EPBot/BBA: an established system-defined engine

**Concept.** EPBot is the closed-source bidding engine behind BBA —
authored by **Edward Piwowar** (correction: not Piotr Beling, who wrote the
bcalc double-dummy solver). Verified July 2026: free DLLs (EPBot86/64/
ARM64) on github.com/EdwardPiwowar/BBA, .NET Framework 4.8.1, sample
Python integration by Thorvald Aagaard; plays five configurable systems —
**2/1 GF**, SAYC, WJ, Polish Club, Acol — with extensive convention toggles
via its properties; extremely fast; BBA itself is used to generate training
data for AI bots (including Ben's ecosystem). Pipeline: harvest supplies
stems; EPBot (configured to the owner's nearest 2/1 card) bids
continuations for every option on every layout; candidate discovery — EPBot
is a *one-call* bidder, no distribution — comes from table divergence +
LLM/owner proposals, each screened by "does EPBot ever choose this call
holding a card-conforming hand?" (probe by sampling hero-consistent hands).
DD judges.

**Guarantees.** Continuations legal by construction and **system-defined
against a named, configurable 2/1 card** — the closest any approach gets to
"the meaning of every call is on file." Deterministic and reproducible.
**Cannot guarantee:** candidate sets or dilemma detection (no policy
distribution — the screening probe is a workaround, not judgment); insight
into *why* (closed binary; limited meaning extraction through its API);
exact owner agreements (toggles get close, not identical).

**Advantages**
- A real expert's decades of system codification, free — approach C
  bought instead of built.
- Deterministic: same input, same auction, forever; ideal for golden tests.
- Millisecond-fast; negligible runtime cost per rollout.
- Doubles as a second opinion for any other approach (its original role in
  the prior doc, method 5a).

**Disadvantages / risks**
- Windows/.NET Framework 4.8.1 DLL on a Linux pipeline: mono + pythonnet
  (build-from-source) or a Windows container/CI job — the largest
  integration friction of any approach, and unfixable if it breaks.
- Closed source, single maintainer, no license text verified — key-person
  and continuity risk for a load-bearing dependency.
- Candidate generation remains someone else's job; this is half a brain.
- Anti-system table calls (real experts deviate) get screened *out* —
  slightly narrows the most interesting problems.

**Cost & effort.** Build: ~2–4 weeks dominated by the .NET boundary
(subprocess service with JSON IPC recommended). Per problem: $0 engine
(+ LLM for candidates/prose if used). Licensing: freeware, closed;
redistribution terms must be confirmed with the author. Owner provides: the
convention-toggle configuration session (hours, pleasant work for a serious
player).

**Failure-mode check.** (1) Impossible — engine state machine. (2) EPBot
continues both cue-bids under one card; if its system treats them alike the
contract distributions match and V3 collapses honestly; if the card *does*
distinguish them, the measured gap is at least system-real. (3) The probe
finds no conforming 8-count on which EPBot bids 2D → option rejected as
non-systemic; V2 catches it independently.

---

## 4. Approach E — Human-in-the-loop curation platform

**Concept.** Accept low volume; maximize trust. The LLM drafts finalization
documents (approach B's machinery, gates loosened), the hard shell filters
mechanically, and everything surviving lands in a **fast review UI**: hand,
stem, options with card citations, meanings vs the real deal, per-option
trees with a "these two trees differ — justified?" diff view, DD preview.
The owner approves, edits inline, or rejects with a reason tag; only
approved problems publish. Reason tags feed the draft prompts and gate
thresholds. This formalizes what already happens (the owner reviewed every
iteration anyway) — but turns each review-hour into published problems
instead of postmortems.

**Guarantees.** The only approach where a panel-caliber human sees every
published problem — including **unknown-unknown** error classes no
validator anticipates; v5's class (2) was caught by exactly this reviewer.
Every explanation carries an expert's sign-off. **Cannot guarantee:**
volume (5–15 problems per owner-hour); freedom from owner blind spots;
durability — review fatigue degrades into rubber-stamping, silently.

**Advantages**
- Highest floor of any approach; trust is absolute by construction.
- Cheapest build; mostly UI over the existing webapp/pool machinery.
- Every rejection is labeled training signal for whichever generator sits
  upstream — this approach *composes* with all others as their gate.
- The owner authoring verdict prose occasionally is a feature: the product
  is for him.

**Disadvantages / risks**
- The scarcest resource (owner time) becomes the throughput ceiling —
  permanently.
- A one-user review loop cannot exceed one expert's judgment; MSC panels
  exist because single experts split 60/40 against themselves.
- Motivation risk: reviewing is homework; the tool was supposed to be play.

**Cost & effort.** Build: ~1 week (review UI, approve/edit/reject flow,
tag export). Per problem: ~$0.05 LLM draft + 3–10 min owner time.
Runtime: unchanged. Owner provides: the hours — this is the approach.

**Failure-mode check.** (1) and (3) never reach the owner (hard shell).
(2) reaches the owner flagged by the tree-diff view — and the historical
record shows this exact reviewer catches this exact class.

---

## 5. Approach F — Ensemble verification (multi-source agreement)

**Concept.** Defense in depth: no single bridge brain is trusted; a problem
publishes only when independent sources agree. The LLM finalizer (approach
B) proposes the document. Ben (approach A) cross-examines it: are the
proposed options inside Ben's policy support? do Ben's rollouts of each
option reach contract distributions compatible with the authored trees? do
Ben's auction-consistent hand samples fall inside the authored meaning
bands (and vice versa)? DD coherence gates finish: verdict must be stable
whether continuations come from the trees or the rollouts, and the margin
must exceed both sampling and model uncertainty. Hard shell underneath, as
always. Disagreements are logged with reasons; near-misses can drain to a
small owner queue (approach E as overflow, not bottleneck).

**Guarantees.** Errors must be *correlated across a symbolic validator, a
neural engine, and a statistical gate* to publish — the three known classes
and most imaginable cousins die. Continuation realism is verified against
an actual engine while keeping human-readable authored meanings; you get
approach A's honesty with approach B's explanations. **Cannot guarantee:**
truth from agreement — Ben's GIB training and the LLM's GIB-heavy priors
share bias, and both can bless the same fashionable error; coverage — the
double-veto slashes throughput, especially where the two "cards" differ
legitimately (false vetoes look identical to true ones without inspection).

**Advantages**
- Highest automated-quality ceiling; the only approach whose *publication
  criterion* is inter-source agreement rather than one source's say-so.
- Every component is independently useful — this is approaches A+B staged,
  so investment is never stranded (see §7).
- Disagreement logs are a free research instrument: they locate exactly
  where system assumptions diverge.

**Disadvantages / risks**
- Most complex build; three subsystems and their glue must all work.
- Throughput unpredictable until the veto-rate curve is measured.
- Two convention cards (LLM's cited card, Ben's implicit card) must be
  reconciled or every systemic difference becomes a permanent veto.
- Tuning agreement thresholds is a new dark art replacing rule-patching.

**Cost & effort.** Build: ~3–5 weeks (A + B + comparison layer). Per
problem: ~$0.05–0.15 LLM (batch) + engine CPU; runtime minutes/problem.
Licensing: GPL boundary for Ben as in A. Owner provides: the card (as B),
the Ben-system acceptance verdict (as A), and threshold reviews.

**Failure-mode check.** (1) Hard shell, before any model runs. (2) Authored
2S/3S trees diverge; Ben's rollouts don't → cross-check disagreement →
collapse or toss-up, never a fabricated margin. (3) V2 rejects on the card;
Ben's near-zero policy on 2D-with-8 rejects independently — two locks.

---

## 6. Comparison table

| | A: Ben engine | B: Hardened LLM | D: EPBot/BBA | E: Human curation | F: Ensemble |
|---|---|---|---|---|---|
| Bridge quality ceiling | High (BBO-proven; GIB-2/1 flavor) | Medium-high (correlated blind spots) | High within its card (half a brain: no candidates) | Owner's own level — highest floor | Highest automated |
| Legality errors (1) | Eliminated (by construction + V1) | Eliminated (V1) | Eliminated (by construction + V1) | Eliminated (V1, pre-review) | Eliminated (V1) |
| System errors (3) | Mostly (engine card ≈ 2/1; V2 backstop) | Eliminated vs the card (V2 + citations) | Eliminated vs its card (probe + V2) | Eliminated (V2 + owner) | Eliminated (double lock) |
| Equivalence errors (2) | Cause eliminated (one policy rolls out all options) | Gated only (V3 + N-way stability) | Cause eliminated within card | Caught by reviewer (proven) | Cause eliminated + cross-checked |
| Continuation realism | Engine-real | Authored (weakest point) | Engine-real, system-defined | Authored, human-vetted | Authored but engine-verified |
| Volume | High | High (minus rejects) | Medium (candidate bottleneck) | Low (owner-hours) | Medium (double veto) |
| Cost / problem | ~$0 (+$0.01–0.05 prose) | $0.05–0.30 | ~$0 | $0.05 + 3–10 min owner | $0.05–0.15 |
| Build effort | 1–2 wks | 1–2 wks | 2–4 wks (.NET boundary) | ~1 wk | 3–5 wks |
| Owner-time dependence | One-off system acceptance | Card authoring + rubric | Convention configuration | Permanent, per problem | Card + thresholds |
| Key risk | Card mismatch grates; opaque | Plausible wrong trees still publish | Closed binary, Windows DLL, one maintainer | Fatigue → rubber-stamping; ceiling = one expert | Complexity; correlated bias blesses shared errors |

(Hard shell V1–V4 assumed present in every column — it is not optional.)

---

## 7. Panel recommendation

**Ranked: 1) A, 2) F, 3) B, 4) E, 5) D.** The three v5 failures split into
two kinds: (1) and (3) are *validator problems* — they die permanently the
week the hard shell exists, under any approach, and building it first is
therefore not a choice but a precondition. Failure (2) is different in
kind: fabricated continuation margins cannot be fully *validated* away,
because checking a continuation tree for realism requires exactly the
bridge judgment whose absence caused the error. The only structural cure is
that continuations come from an engine that actually bids, which is why the
panel ranks A first: Ben is the one component that replaces authorship
where authorship failed, at near-zero marginal cost, with the dilemma
detector (its policy distribution) thrown in. F is the destination, not the
starting point — and the good news is that F is literally A+B composed, so
starting with A strands nothing. B alone is ranked below A despite being
the shortest step from current code, precisely because it hardens the
proven weak point instead of removing it; it earns its keep inside the
stack as the meanings-and-prose layer, where the LLM is genuinely best. E
is not a volume strategy but should exist from day one as a thin approval
gate (the owner reviews anyway; make each review produce a published
problem). D is a fine second engine and the natural fallback if the owner
rejects Ben's card at the Phase-1 gate, but the closed Windows DLL should
not be load-bearing while an open, active, Python-native alternative
exists. **The combination that works: hard shell (V1–V4) as bedrock + A for
candidates/layouts/continuations + B for card-cited meanings and
explanations + E as the publish gate — i.e., grow into F incrementally.**

**Smallest first step that proves the direction** (~2–3 days, falsifiable):
build V1 + a minimal V2 card and run them over the existing 8 spike
problems — they must reject f50022-21 and f50003-18 unaided; then install
Ben CPU-only and roll out 2S vs 3S on f50021-27's layouts — if the
fabricated 0.5-IMP gap collapses into an honest toss-up, the architecture
is proven on the exact evidence that motivated it.

---

## Amendments (2026-07-15, after owner review)

### A1. V2 reframed: conformance is "least-lie accounting", not a ban
The owner is right that sometimes only bad options exist and a rule must be
violated. Auction LEGALITY (V1) stays hard. System conformance (V2) becomes:
- every option is annotated with what it SHOWS vs what the hand HOLDS;
  deviations are allowed and are often the training point ("which lie is
  smallest?");
- hard-reject only UNACKNOWLEDGED deviations: if an option deviates, the
  finalization must say so, the concealed-hand meanings must reflect what
  the bid CLAIMS (partner believes the bid — that is how lies get punished
  in the simulation), and the explanation must weigh the lie;
- f50003-18 under this rule: 2D is admissible only as a flagged deviation,
  simulated with partner acting as if it showed 10+, and explained as such.

### A2. Approach F runs inside Claude Code sessions (owner decision)
The ensemble is built with no API key and no scheduled jobs:
- proposer and adversarial verifier = independent subagents in a Claude Code
  session (separate contexts; the verifier sees only the proposal + deal +
  card + auction, never the proposer's reasoning);
- Ben runs locally in the session container (CPU) as the neural
  cross-examiner for continuations/meanings;
- hard shell + DD gates are local code; survivors are pushed to the live
  pool before the session ends; every finalization document is committed
  (auditable, regenerable).
Batch cadence: on demand, ~10-25 problems per sitting. If unattended volume
is ever wanted, the identical pipeline moves to CI with an API key.
