# The Core Problem and the Method to Solve It

Author role: bridge expert (2/1 GF, panel-caliber judgment) + software architect.
Status: proposal for owner decision. Date: 2026-07-15.

---

## 1. Diagnosis — why iterations 1–3 failed and will keep failing

### 1.1 The single root cause

**Every quality attribute of a generated problem is downstream of the bot's
bridge understanding, and the bot is a toy.** `SimpleBidder` (~660 lines,
first-match priority rules) supplies:

1. the auction stem (it bids all four seats),
2. the candidate set (its own rules re-fired "with slack"),
3. the hidden-hand model (inversion of its own call signatures),
4. the continuations after every candidate on all 600 layouts (it bids them out),
5. the dilemma signal (near-misses of its own thresholds).

A problem needs roughly 8–12 of these bot decisions to all be
expert-plausible at once. If each is right 90% of the time — generous for a
bot with no cue bids, no Stayman/transfers, no 2C, no forcing-pass logic, no
game tries, no redoubles — whole-problem plausibility is 0.9^10 ≈ 35%. That
is exactly the observed hit rate: iteration 2, user flagged 5/10; iteration 3
(after 17 expert rule fixes), the user's verdict was unchanged. **Rule
patching moves per-rule accuracy from ~90% to ~93%; the product needs ~99%
per decision, which is a complete bidding system — a decades-scale
expert-system project.** Iterations 1–3 all kept the same architecture
(hand-rolled bridge knowledge) and only moved the knowledge around. That is
why the next rule-fix iteration will also fail.

### 1.2 Concrete evidence from the current v2 pool (`pool_data/problems/`)

These are problems the v2 pipeline *published* (i.e., they passed every gate
we have):

- **b2-0135277b** — N holds `K.T52.KQ943.A862` after 1H–(2C). The bot's own
  chosen call is **4H** (support-point rule counts a singleton K as +2 with
  three small trumps), and the *accepted answer* is **X** — which the bot
  defines as a *penalty* double of 2C (`penalty_double_comp`). In any real
  2/1 partnership, X here is *negative*, and this hand cannot make one (no
  four spades). The trainer's "right answer" is a call whose meaning does not
  exist in the system the user plays. **Token-level identity ("X") masks
  meaning-level nonsense** — the deepest recurring failure.
- **b2-01352772** — W holds `T.AQT7.QJT85.J73` (10 HCP) after 1C–(1S).
  Candidates: X (negative double — the system call), 2D, P. Accepted answer:
  **2D**, a two-over-one whose own signature promises more — a systemic
  overbid that "wins" on DD only because the constraint model and bot
  continuations never punish the lie. The verdict directly contradicts the
  bot's own system.
- **b2-01352778** — W holds `AQ98.K6.J852.QT9` after 1D–P–1S–(2H)–P–P.
  Candidate set is **{3NT, P}** — no X, no 2S, no 2NT — and the accepted
  answer is **3NT** on a combined ~22 with K6 as the stopper opposite an
  opener who couldn't act over 2H. Absurd candidate set *and* absurd answer.
- **b2-01352789** — S holds `.AQJ5.6532.K7653` (10 HCP, spade void) after
  P–P–1S–P, and **Pass is in the accepted toss-up set**. No player at any
  level passes; "not even a dilemma", in the wrong direction.
- **b2-0135277e** — a 4-way toss-up (2H/X/3H/4H) where the real answer is a
  limit raise (cue bid — a call the bot doesn't have). A 4-way toss-up
  verdict teaches nothing.

### 1.3 The three named causes, confirmed

**(a) The bot cannot approximate expert judgment, and everything is only as
good as the bot.** Confirmed, see above. A strong player's consideration set
comes from *meanings and judgment* ("what does X show here, what will
partner do over it"), not from threshold near-misses. The slack mechanism
generates threshold near-misses by construction.

**(b) The verdict conflates "wins on DD under the bot's model" with "the
right bid".** Three error layers stack multiplicatively under the EV
integral: (1) hidden hands come from inverting coarse, sometimes-unsound
signatures — an HCP band plus per-suit min/max, with no shape correlation
and no negative inference from calls the bot doesn't know; (2) continuations
are bid by the same weak bot, so a candidate wins when the *simulated
opponents/partner* misplay the auction (the phantom +500/−730 disease
already documented for the authored problem in `expert_review.md` §A.1);
(3) DD play, partially patched by the correction table (the only layer with
an existing mitigation, INV5). On top of that, **the record schema contains
no explanation of any kind** — even a correct verdict teaches nothing. The
right answer to a bidding problem is *defined* by expert consensus given
agreements; simulation is supporting evidence, never the authority.

**(c) Dilemma-by-rule-near-miss is a proxy that selects threshold artifacts.**
Real dilemmas are spots where principles conflict (LAW vs. vulnerability,
offense vs. defense, misfit discipline, action doubles) or where a panel
would genuinely split. Being 1 HCP from a boundary of a non-expert rule set
is neither. The interest score cannot see meanings, so it cannot see
dilemmas.

### 1.4 What is NOT broken

The **evidence stack is solid and survives**: chunked DDS wrapper + caching
(`dd/`), single-dummy correction with raw-vs-corrected fog labeling (INV5),
paired IMP comparison with importance weights, CIs, ESS, toss-up discipline
(INV1–INV8, `scoring/`), the pool store, the static publisher and webapp,
and the offline producer skeleton. The problem is *what feeds it* and *who
gets to declare the answer*.

---

## 2. Methods considered

| # | Method | Feasibility | Quality ceiling | Cost | Risk | Decision |
|---|--------|-------------|-----------------|------|------|----------|
| 0 | Keep patching SimpleBidder (iteration 4) | High | **Low — capped by §1.1 arithmetic** | Weeks of expert review per iteration | Certain repeat of iterations 2–3 | **Reject** |
| 1 | **Ben** (lorserker/ben) as the bidding/judgment engine | High (Python, CPU-only TF, pretrained models in repo) | High — BBO-deployed, ~1 IMP/board better than GIB Basic at bidding | Free (GPL-3.0); ~GBs of TF + models in CI cache | System card ≈ GIB-flavored 2/1, not the user's exact card; occasional non-expert calls in rare auctions | **Adopt — core engine** |
| 2 | LLM at generation time (vetter / panel voter / explanation writer) | High (producer already offline; one API call per problem) | High for bridge-*sense* and prose; **unreliable for precise EV** | ~$0.03–0.10/problem (Opus 4.8; half via Batches API) | Confident-wrong bridge claims; mitigated by rubric + no EV authority | **Adopt — vet + explain + vote** |
| 3 | Hybrid verdict model (panel decides, sim is evidence) | High (policy layer over 1+2 + existing stats) | This is what makes the answer *bridge-logic-first* | Marginal | Sources disagree often → many "judgment" labels (honest, not a bug) | **Adopt — verdict policy** |
| 4 | Source real published problems (MSC, panels, tournament deals) | Low–medium | High per problem | High legal/manual effort | Bridge World / panel commentary is copyrighted; scraping auctions+answers is not defensible. Raw *deals* are facts and usable, but the valuable part is the panel text | **Reject as source of answers**; optionally reuse real *deals* as a deal source later |
| 5a | EPBot / BBA (Edward Piwowar's engine; Python wrapper by T. Aagaard) | Medium (closed-source .NET DLL; runs via mono; free) | High for *system-defined* bidding — supports 2/1 with configurable card; extremely fast | Free; integration friction (DLL, no source) | Closed binary; meaning extraction limited | **Optional later** — a second panelist / system checker; note Ben itself can integrate BBA for convention cards |
| 5b | WBridge5 / GIB / Blue Chip | Low | — | — | Closed (WBridge5: Windows freeware, no API; GIB: BBO commercial; Blue Chip: defunct) | **Reject** |
| 5c | Single-dummy engine instead of DD | Medium | Marginal over existing DD+correction | — | Ben ships an NN single-dummy estimator; our correction table already addresses the same bias | **Keep our DD+correction**; revisit only if defense-heavy problems stay foggy |
| 5d | Genre restriction (well-understood competitive decisions only) | Trivial | Raises *average* quality immediately | Free | Smaller variety early on | **Adopt as a dial** |
| 5e | Human-in-the-loop review queue (user rates served problems) | Trivial (webapp + localStorage → export) | Directly optimizes the only metric that matters | Free | Slow feedback loop alone; great as a *gate* | **Adopt as the acceptance gate** |

### 2.1 Ben — verified facts (checked July 2026)

- **Repo**: github.com/lorserker/ben. **License GPL-3.0.** Python 3.12,
  TensorFlow 2.18 / Keras 3.5, **CPU-only is the normal mode** (no GPU
  required). Active: v0.8.8.4 released June 2026, 615+ commits, runs live on
  BBO; Discord community.
- **Pretrained models ship in the repo** (`models/TF2models/GIB-BBO-*.keras`),
  trained on GIB/BBO data; **the distributed models play a GIB-flavored 2/1
  system** — the closest open thing to the user's system that exists.
- **The bidder NN outputs a probability distribution over calls.** The
  default config exposes exactly the hooks we need:
  `search_threshold` (per-auction-depth array, e.g. `[0.10, 0.07, …]`) —
  calls above it become *candidates*; when >1 candidate exists Ben samples
  **hidden hands consistent with the auction** (200 samples drawn from up to
  30k boards, quality-checked), bids out each candidate with its own models,
  and scores by DD / NN single-dummy. That is our entire pipeline —
  auction, candidates, dilemma signal (top-2 policy closeness), hidden-hand
  model, continuations — already built, trained, and battle-tested.
- Benchmarks (BBO forum / repo): judged on bidding alone, Ben beats GIB
  Basic by ~1 IMP/board; it agrees with SAYC/2-over-1-oriented bidders far
  more than WBridge5 does.
- **Integration**: import as a library (its tutorials drive bidding and
  hand-sampling from notebooks) or run as a subprocess with JSON IPC. GPL
  consequence: for a personal tool, none; if this repo is ever distributed,
  either accept GPL for the producer or keep Ben behind a process boundary.
- Sources: [github.com/lorserker/ben](https://github.com/lorserker/ben),
  [lorserker.github.io/ben](https://lorserker.github.io/ben/),
  [BBO forums — Ben on BBO feedback](https://www.bridgebase.com/forums/topic/89237-ben-on-bbo-feedback-thread/),
  [BBA (EPBot) site](https://sites.google.com/view/bbaenglish).

### 2.2 LLM-in-the-loop — what it can and cannot be trusted with

Good at (generation-time, offline): catching absurd candidates ("X of 2C is
negative, this hand can't make it"), meaning-labeling calls, judging whether
a spot is a genuine dilemma, voting like a panelist with a stated reason,
and writing Bridge-World-style explanations. **Not trustable for**: precise
EV/percentage claims, deep double-dummy facts, counting to 13 under
pressure. Therefore: the LLM gets **veto power** (bridge-sense) and **voice**
(votes + prose), **never EV authority** — EV numbers always come from the
simulation stack and are quoted to it, not asked of it.

Operational: `ANTHROPIC_API_KEY` as a GitHub Actions secret. Model
`claude-opus-4-8` ($5/$25 per MTok; 50% off via the Batches API for offline
producer runs). A vet+vote+explain exchange is ~3–8k input / 1–2k output
tokens ⇒ **$0.03–0.10 per problem** (half in batch mode). A 100-problem pool
costs a few dollars.

---

## 3. Recommended method

**Replace the hand-rolled bot with Ben as the source of bridge judgment;
keep the DD/scoring/stats stack as the evidence engine; put an LLM expert
panel in the loop at generation time; change the verdict authority to
"panel decides, simulation corroborates"; publish an explanation with every
problem.**

### 3.1 Pipeline (per seed)

```
deal → auction (Ben) → decision point (Ben policy) → candidates (Ben policy)
     → hidden-hand samples (Ben) → continuations (Ben) → DD + IMP stats (ours)
     → LLM panel: veto / vote / explain  → verdict policy → record → publish
```

1. **Deal** — unchanged (`rng.permutation(52)`, random dealer/vul).
2. **Auction stem** — Ben bids all four seats (its own internal sampling +
   search). `SimpleBidder` and the slack machinery are retired from this
   path. *(Optionally: opponents on a second Ben config to model a different
   style; later.)*
3. **Decision point** — at each hero turn, read Ben's policy distribution
   over calls. Dilemma signal = the distribution itself:
   `p(top) < 0.70 and p(second) > 0.15` (tunable), plus a genre whitelist
   (competitive raises, balancing, direct-seat actions, doubles,
   sacrifice/5-level, game tries). Pick the best-scoring turn; reject the
   deal if none qualifies. This replaces `_turn_interest` and §3 of
   expert_review_v2 wholesale.
4. **Candidates** — calls with policy probability ≥ 0.08 (tunable), capped
   at 4, always including Ben's top call. The consideration set now comes
   from a trained policy — i.e., *judgment* — not threshold near-misses.
5. **Hidden-hand model** — Ben samples concealed hands consistent with the
   full auction (its models know what each call *means* in context,
   including inferences from passes). This replaces
   `signature_to_constraints` + rejection dealing for generated problems.
   The rejection dealer and INV2/INV3 machinery remain for the legacy
   authored-problem path and as a cross-check harness.
6. **Evidence** — for each candidate and each sampled layout, Ben bids the
   auction to completion (all four seats); our existing `ScoreEvaluator` +
   `compare_candidates` produce raw and corrected IMP comparisons, CIs,
   push rates, fog labels. **INV1 (same deal set for all candidates), INV5,
   INV6, INV7 survive untouched.**
7. **LLM panel (one structured call, `claude-opus-4-8`)** — input: hero
   hand (restated as explicit suit/HCP features to prevent miscounting),
   auction with seat/vul, candidate list, and the *finished* simulation
   table. Output (JSON, structured outputs):
   - `veto`: reject reasons if the auction is un-bridgelike, a candidate is
     absurd or its meaning is ambiguous/system-dependent in a way that
     poisons the problem, an obvious candidate is missing, or the spot is
     not a real dilemma;
   - `vote`: its answer as a panelist + one-line reason per candidate;
   - `explanation`: Bridge-World-style prose (see §3.3), written against
     the final verdict, quoting sim numbers verbatim (never inventing any).
8. **Verdict policy — who decides when sources disagree**:

   | Ben top call | LLM vote | Simulation (corrected) | Published verdict |
   |---|---|---|---|
   | A | A | A best, or within toss-up of A | **A** — "clear consensus" |
   | A | A | contradicts by > 1.5 IMPs | **A**, flagged *"table result differs — see note"*; explanation must address why (usually a constraint/continuation artifact or DD fog) |
   | A | B | either | **Toss-up {A, B}**, labeled **"judgment"**; explanation presents both cases |
   | any | veto | any | **Problem rejected** (logged with reason for tuning) |
   | p(top) > 0.85 | — | — | **Rejected**: not a dilemma |
   | — | — | gap > 3.0 IMPs | **Rejected**: too one-sided (existing filter) |

   The user's complaint "answers are only based on DD" dies here: DD can
   *corroborate* or *dissent*, but it can no longer *decide* against the
   bridge-logic consensus.
9. **Record & publish** — schema adds `explanation`, `panel` (votes +
   reasons), `policy` (Ben's distribution), `verdict.authority`
   (`consensus` / `judgment`), and provenance (`ben_model`, `llm_model`,
   prompt hash). The webapp shows the verdict line + explanation after the
   user answers; sim table demoted to "evidence" styling.

### 3.2 Component disposition

| Component | Fate |
|---|---|
| `dd/` (DDS wrapper, cache, correction) | **Survives unchanged** |
| `scoring/` (tables, stats, comparison, evaluator) | **Survives unchanged** |
| `pool/`, `app/publish`, `app/webapp`, producer skeleton | **Survives** (schema additions) |
| `dealing/` rejection dealer + INV2/INV3 tests | Survives for authored problems + as cross-check harness |
| `bot/bidder.py` (SimpleBidder), slack/enumerate, `at_edge` | **Retired** from generation (kept only if the authored path needs it) |
| `bot/walker.py` | Reduced to a thin auction-state utility or replaced by Ben's auction handling |
| `generate/random_problem.py` candidate + interest logic | **Replaced** by Ben policy + verdict policy |
| `semantics/` signature inversion for random problems | **Replaced** by Ben sampling |
| New: `engine/ben.py` | Adapter: bid(), policy(), sample_hands(), continue_auction() — subprocess or in-process |
| New: `panel/llm.py` | Anthropic client, rubric prompt, structured-output schema, caching of responses by problem hash |
| New: `verdict/policy.py` | §3.1 step 8 as code + tests |

### 3.3 Explanation format (every published problem)

```
Verdict: 3S  (panel: LLM 3S, engine 3S 62%; sim: 3S +0.4 IMPs vs X, ±0.3)

Why: Partner's 1S overcall plus your three-card support and working cards
make selling out to 3H a clear underbid at favorable vulnerability — the
LAW says the nine-card fit plays at the three level. Double would be
card-showing, not penalty, and with 7 losers and no heart honor you'd hate
partner sitting it. [...]

Against: X gains only when partner can convert with hearts over the opener
(~15% of layouts); Pass wins only when both games fail and 3H goes down —
the sim confirms it as the clear loser (−2.1 IMPs).
```

Rules: bridge logic first; sim numbers quoted, never invented; call
*meanings* stated explicitly (that alone would have caught b2-0135277b);
"judgment" problems present both sides and say why experts would split.

---

## 4. Migration plan (each phase independently shippable; user review is the gate)

### Phase 0 — LLM vet + explain over the EXISTING pipeline (quick win, ~1 day)

No new engine. Add `panel/llm.py`; every v2-generated problem goes through
the veto + explanation call before entering the pool; rejects are logged
with reasons. Expect roughly half the current pool to be vetoed (it would
have caught b2-0135277b, -772, -778, -789 — see §1.2). Survivors get
explanations.
**Gate:** user scores a fresh vetted batch of 10 against the §6 rubric.
**Value even if later phases stall:** the worst absurdities stop reaching
the user, and every problem finally explains itself.

### Phase 1 — Ben feasibility spike (~2–3 days)

Clone Ben, run CPU-only, bid 100 random boards with the distributed 2/1
models; measure sec/board for (a) auction, (b) policy at one turn,
(c) 200-hand sampling, (d) candidate rollouts. Print 20 full auctions.
**Gate:** the user reads the 20 auctions and accepts Ben's system card as
"close enough to train against" (this is a bridge decision only the owner
can make — if rejected, the fallback is BBA/EPBot with an explicit 2/1
card, method 5a).

### Phase 2 — Ben drives auction, decision point, candidates (~1 week)

Steps 2–4 of §3.1 replace `SimpleBidder`+`evaluate_turn`. Hidden hands and
continuations still via the old path *or* naive Ben rollouts — whichever is
less code — because the verdict is now protected by Phase 0's panel anyway.
**Gate:** rubric on a 10-problem batch (targets in §6).

### Phase 3 — Ben hidden-hand sampling + continuations; full hybrid verdict (~1–2 weeks)

Steps 5–8: Ben samples concealed hands and bids out candidates per layout;
our DD/stats score them; verdict policy of §3.1 step 8 goes live; schema
and webapp updated to show authority + explanation.
**Gate:** rubric targets for "ship" (§6).

### Phase 4 — Hardening and learning loop

In-app problem rating (👍/👎 + reason tags: "bad auction", "bad candidates",
"not a dilemma", "wrong answer", "bad explanation") exported from
localStorage; ratings tune the dials (policy thresholds, genre whitelist,
veto rubric). Optional: BBA as a second panelist; real tournament deals as
a deal source; difficulty calibration; spaced repetition.

---

## 5. Costs & risks

**CI/runtime.** Ben inference is milliseconds per call on CPU; the expensive
parts are sampling (bounded by config) and per-layout rollouts. Budget:
~20–90 s per problem depending on n_deals × candidates — inside the stated
tolerance ("even minutes-per-problem is tolerable"). TF + models add ~2–3 GB
to the CI cache (one-time; cacheable). DD solving stays the wall-clock floor
(~13 ms/deal, unchanged).

**API.** $0.03–0.10 per problem on `claude-opus-4-8` (halve with the Batches
API — the producer is offline, so batch mode is natural). 100-problem pool:
single-digit dollars. Requires `ANTHROPIC_API_KEY` as a CI secret; producer
must degrade gracefully (queue problems as "unvetted", don't publish) when
the key is absent.

**Licensing.** Ben is GPL-3.0 — no obligation for personal use; if this repo
is distributed, either the producer goes GPL or Ben runs behind a subprocess
boundary. DDS is Apache-2.0 (already in use). EPBot/BBA is free but a closed
.NET DLL (mono on Linux) — a reason it is optional, not core.

**Residual quality risks that will NOT go away:**

1. **System mismatch.** Ben's card is GIB-flavored 2/1, not the user's exact
   agreements. Some verdicts will feel off-system (e.g., specific double
   meanings, raise structures). Mitigations: LLM meaning-labeling in the
   explanation ("here X is takeout-ish per the engine's card"), genre
   whitelist, and — if it grates — BBA with an explicit card later. It never
   fully disappears short of training a model on the user's own card.
2. **LLM fallibility.** Occasional confident-wrong bridge claims survive any
   rubric. Contained by: no EV authority, structured input, veto asymmetry
   (a false veto costs a problem; a false pass costs a bad problem — Phase 4
   ratings catch those), and provenance in the record so bad prompts are
   fixable retroactively.
3. **DD fog.** Double-dummy defense remains too good in
   doubled-partscore/penalty spots; the correction layer and INV5 labeling
   mitigate but cannot eliminate it. Verdict policy already refuses to let
   sim overrule the panel here.
4. **No true panel.** A real MSC panel is 25 experts; we approximate with
   one strong LLM + one trained policy + simulation. Genuine 60/40 expert
   splits will sometimes be published with a single "answer". The
   "judgment" label is the honest fix, and it will be used often.
5. **Sampling realism.** Ben's hidden-hand sampler reflects *its* models of
   the calls; systematic bias in rare auctions passes through to EV. The
   ESS/shortfall discipline (INV7-style honesty about uncertainty) must be
   re-established on Ben's samples, not assumed.

---

## 6. Acceptance criteria — a falsifiable bar

Per batch: the user (owner) scores **10 freshly generated problems**, each
on five binary questions (a scorecard file `reviews/batch_NN.md` is part of
the phase deliverable):

- **Q1 Auction sense** — the auction to the decision point is one a decent
  2/1 pair could produce (no un-bridgelike calls).
- **Q2 Candidate sense** — every offered candidate is a call a strong club
  player might genuinely consider, **and** no obvious candidate is missing.
- **Q3 Real dilemma** — the user had to actually think; neither an
  auto-bid nor a coin-flip between four junk options.
- **Q4 Defensible verdict** — the answer + explanation is one the user can
  respect in bridge terms (agreement not required; "I see the argument" is
  a pass, "this is absurd" is a fail).
- **Q5 No howler** — nothing in the problem (auction, candidates, verdict,
  explanation, meanings) is outright wrong as bridge.

**Targets (pass = phase gate met):**

| Gate | Q1 | Q2 | Q3 | Q4 | Q5 |
|---|---|---|---|---|---|
| Phase 0 exit | ≥ 9/10 | ≥ 8/10 | ≥ 6/10 | ≥ 7/10 | **10/10** |
| Phase 2 exit | 10/10 | ≥ 9/10 | ≥ 7/10 | ≥ 8/10 | **10/10** |
| Phase 3 = ship | 10/10 | ≥ 9/10 | ≥ 8/10 | ≥ 9/10 | **10/10** |

Q5 is a hard zero-tolerance gate at every phase: one howler fails the batch.
A failed gate means iterate *within* the phase (tune thresholds, rubric,
prompts) — explicitly **not** "add rules to a bot".

**Automatic proxies tracked per batch** (for trend, not gating): LLM veto
rate (should fall across phases), Ben top-call probability distribution of
published problems (should cluster in 0.35–0.70 — genuine dilemmas),
panel/sim agreement rate, toss-up rate, and Phase 4 user-rating tags.

---

## Appendix: why not one more rule-fix iteration (pre-empting the cheapest objection)

`expert_review_v2.md` was a competent review; all 17 fixes landed and its
four regression deals genuinely die. Yet §1.2's five howlers are all *new*
patterns — penalty-X-of-2C-with-support, systemic-overbid-wins-on-DD,
two-candidate 3NT blast, pass-with-10-opposite-opening, cue-bid-shaped
hands with no cue bid available. Each is fixable with 2–3 more rules; each
fix narrows one crack while the same generator keeps producing auctions and
meanings no expert reviewed. The rule bot is a bottomless backlog because
it is being asked to *be* an expert. Ben and the LLM are the two available
artifacts that already encode expert bridge at scale; the architecture
above uses each strictly where it is strong and keeps our own strongest
asset — the honest statistics stack — as the referee's evidence, not the
referee.

---

## Decision record (2026-07-15, owner)

1. **Verdict authority: DD simulation** — the owner overrides §3's hybrid
   verdict. Once the problem definition and candidate options are finalized,
   the DD simulation over the constrained layouts is the sole judge
   (empirical, token-free). The toss-up/CI/fog discipline (INV5, INV7)
   remains mandatory.
2. **LLM role narrowed to problem finalization**: one generation-time call
   per problem — (a) real-dilemma check (discard otherwise), (b) finalize
   the candidate set, (c) emit the auction's call meanings as constraint
   ranges for the hidden-hand simulation, (d) short explanation text. No
   verdict vote.
3. **Problem source: real tournament deal records** (owner's proposal) —
   real auctions harvested from public championship/vugraph archives,
   stopped at decision points (table divergence preferred), replacing
   bot-generated stems. Ben demoted to an optional future volume source.
