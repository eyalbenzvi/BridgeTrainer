# Auction-inference gap in lead grading — `lead1-19fa5daef4b`

Owner report (2026-08-01): the published best lead on `lead1-19fa5daef4b`
(SA) looks right if you sample hands from the *explicit* bidding information,
but wrong once the auction is *analysed* — declarer denied both majors with
2C, then bid 3NT normally showing major stops; dummy rebid 2D rather than
2NT; partner never overcalled hearts over 1C. This audit reproduces the
published number exactly, measures the gap, and generalises the fix.

Everything below was measured live in this branch: Ben installed at the
pinned commit via `scripts/setup_ben.sh` (rollout-context patch applied),
DDS = endplay physical-card grading (`engine/lead_posterior.py`), seeds
recorded, board pulled from Firestore.

## 1. The board

```
Dealer S, vul Both.  1C P 2C P / 2D P 3NT P / P P  ->  3NT by N, East leads.
East (leader): AQJ754.Q.T975.76
GIB cards (persisted in explanations.auction[].card):
  2C  (N): "Inverted minor suit raise -- 4+ !C; 3- !H; 3- !S; 10+ HCP"
  2D  (S): "3+ !C; 11-21 HCP; stop in !D; forcing to 2N"
  3NT (N): "4+ !C; 3- !H; 3- !S; 14-18 HCP; partial stop in !H;
            partial stop in !S"
Published verdict: SA (3.029 avg def tricks), SQ 2.524, n_samples=170.
```

The whole decision hangs on ONE card: the missing spade K. East holds
AQJ754; there are exactly three worlds — SK with declarer (N), dummy (S), or
partner (W).

## 2. What the production sampler actually believed

`BenCurrentSampler` at the shipped τ=0.70 reproduces the published verdict
digit-for-digit (SA 3.029, SQ 2.524, 170 accepted deals — same seed, since
Ben seeds from the leader hand). Its marginals versus the auction's stated
meanings:

| quantity | Ben τ=.70 | GIB cards say |
|---|---|---|
| P(SK with N, declarer) | **0.42** | N announced the partial spade stop |
| P(SK with S, dummy) | **0.48** | S announced only a diamond stop |
| P(SK with W, partner) | 0.11 | — |
| P(N in 14-18 HCP) | **0.43** | 3NT = 14-18, explicit |
| P(N ≤3 spades) | 0.99 | explicit (fine) |
| P(N ≤3 hearts) | 0.94 | explicit (fine) |

DD tricks stratified by SK location (same 170 layouts):

| stratum | share | SA | SQ | D5 | HQ |
|---|---|---|---|---|---|
| SK@N (declarer) | 0.42 | 2.77 | 2.24 | **2.97** | **3.04** |
| SK@S (dummy) | 0.48 | **2.57** | 2.01 | 2.04 | 1.95 |
| SK@W (partner) | 0.11 | **6.11** | 5.94 | 2.11 | 2.33 |

So SA's whole published edge lives in the 59% of layouts where declarer does
NOT hold the spade K — precisely the layouts declarer's own 3NT card argues
against. In the SK@N stratum the ace lead is already ~0.2–0.3 tricks *worse*
than a passive diamond or the HQ.

## 3. Re-grading under the auction's meaning

Ben-free `ConstraintSampler` runs on the same public state (500 accepted
layouts, endplay DDS, physical cards, weighted means):

| distribution | P(SK@N) | winner | SA − runner | SA vs HQ |
|---|---|---|---|---|
| explicit lengths+HCP only | 0.49 | **SA** (3.09) | +0.45 over SQ | +0.84 |
| + owner's inferences, soft (stops weighted, no-2NT filter, no-1H denial) | 0.80 | **SA** (2.77) | +0.23 over D5 | +0.25 |
| strict reading (declarer holds SK + real heart stop) | 1.00 | **D5** (2.78) | SA −0.39 | **SA −0.33** [CI −0.45,−0.21] |

Interpolating the strata, the winner flips at roughly **P(SK@declarer) ≈
0.88**. The production sampler sits at 0.42; any reasonable reading of the
auction sits at 0.8–1.0. `P(set)` moves the same way (strict: diamonds .146,
HQ .134, SA .089), so this is not an MP-vs-IMP artifact.

Conclusion — the owner's suspicion is CONFIRMED, with one refinement: the
answer does not flip on the *soft* reading (SA survives at P(SK@N)=0.8,
margin halved); it flips on the *strict* reading. Which means the published
"single correct answer" rests entirely on an interpretation knob the sampler
doesn't expose and the auction pins near the flip point. Under this repo's
own robustness taxonomy (docs/lead_posterior_sampling.md §8) the board is
`sampler_sensitive` and must not ship as a single-answer problem. The
mechanism is the known one: the thresholded neural-consistency distribution
`Q_τ` is uncalibrated *in exactly the honor-location marginal that decides
this board* — and it also leaks HCP mass outside the explicit 14-18 range.

Bridge reading, for the record: with AQJ754 and no side entry, the ace lead
is the percentage play only while dummy/partner may hold Kx — it smothers a
doubleton K and runs the suit with no entry needed. Once declarer (who plays
last to trick 1, over East's Q) is *known* to hold the K, the ace-then-Q
attack establishes a suit East can never reach; a passive diamond (or the
stiff HQ toward partner's length) keeps the A-Q tenace over declarer's K —
worth ~0.4 tricks and nearly double the set chance.

## 4. The generalisation (new in this branch)

`engine/lead_gib_constraints.py` — every published problem already stores a
machine-readable GIB card per call (`explanations.auction[].card`:
hcp/pts/minlen/maxlen + the raw meaning string with its `stop in !X` /
`partial stop in !X` clauses). The module compiles those cards into a
`ConstraintProfile` for the existing `ConstraintSampler`:

* hcp `(lo,hi)` → core band with ±1 stretch margins; `pts` upper bound caps
  HCP; min/maxlen → hard suit-length bands;
* announced stops → suit-HCP bands *relative to the leader's own holding*
  (`stop_threshold`: the cheapest missing honor that can headline a stop),
  with honest miss mass — `FULL/PARTIAL_STOP_MISS_WEIGHT` — because players
  do bid 3NT stopperless when no alternative call exists;
* `stop_miss_scale=0` = the **strict reading** (announcements taken
  literally);
* silence denials: a concealed seat that only ever passed after an enemy
  opening is discounted (never zeroed) for sound-overcall hands in unbid
  suits — the owner's "partner didn't bid hearts over 1C";
* unparsed calls degrade gracefully into `unrecognized_calls`, same contract
  as the rule-engine profile. No YAML ruleset coverage needed, no network
  for stored records, no Ben.

Known limitation (documented in-module): disjunctive negative inferences —
"dummy chose 2D over 2NT so he lacks stops in all three side suits OR is
unbalanced" — do not fit per-suit bands and are not encoded. On this board
that inference only pushes P(SK@N) further up, i.e. further from the
published answer; the encoded stop annotations already carry the decisive
part.

Surfaces:

* `scripts/audit_lead_inference.py --pool data|--key sa.json --ids ...
  |--all-leads` — re-grades stored lead problems under BOTH readings (soft +
  strict) of their own cards and flags `published_loses` /
  `honor_sensitive` / `published_ties`. On this board it prints:
  `lead1-19fa5daef4b: published_loses  soft_winner=SA  strict_winner=D5`
  (strict: published SA −0.25 tricks vs D5, CI [−0.40, −0.07]).
* `trainer lead-posterior-audit --samplers gib-constraint,
  gib-constraint-strict,...` — the pair joins the cross-sampler vote (only
  when the cards actually constrained a seat, like the rule-engine
  constraint sampler).

## 5. Policy (enforced, not advisory)

The app trains lead-finding. A board whose published answer no expert would
choose is not a weak board — it is a wrong one, and wrong answers teach the
opposite of the skill. Boards are generated at scale (~27s each), so the
asymmetry is total: rejecting a good board costs seconds; publishing a bad
answer costs trust. Hence a binary gate, not a flag.

**The rule (one definition — `engine/lead_gib_constraints.inference_verdict`,
shared by the forge and the pool audit so they cannot drift):** a lead
problem ships with a single answer ONLY if that answer survives BOTH
readings of its own displayed auction cards —

* `inference_refuted` — in either reading the published lead loses to the
  reading's winner with a CI clear of 0, **or** by more than
  `REFUTE_MARGIN = 0.15` DD tricks (a low-sample tie must not smuggle a
  refuted answer through). **Blocked / deleted.**
* `honor_sensitive` — soft and strict crown different winners: there is no
  single answer to teach. **Blocked / deleted.**
* `stable` / `abstain` (nothing in the auction was recognisable) — ships.

Enforcement points, all in this branch:

1. **Forge (blocking):** `forge_lead_one` now runs the gate on every
   would-be-accepted record — both the normal and the `lead_doubled` paths —
   after all cheaper gates, and rejects with reason
   `inference_refuted` / `honor_sensitive`. Measured cost: **15.5s** per
   accepted board (2×250 Ben-free layouts + endplay), zero cost on the
   ~90% of boards the earlier gates already kill. On this board the forge
   now prints: `inference_refuted strict: SA loses 0.39 DD tricks to D5
   (CI [-0.57, -0.22])` — the SA answer can never be published again.
2. **Pool purge (one command):**
   `python scripts/audit_lead_inference.py --key sa.json --all-leads
   --purge` audits every stored lead problem under the same verdict and
   DELETES the flagged ones (index-first `remove`, the forcing-pass purge
   machinery; user attempts stay, regrading as `missing_problem`). Run it
   once against production; the forge refills the pool under the new gate.
   `lead1-19fa5daef4b` is flagged `inference_refuted` and goes.
3. **Deeper audits when wanted:** `trainer lead-posterior-audit --samplers
   gib-constraint,gib-constraint-strict,current,...` — the pair votes in
   the cross-sampler verdict.

Rationale for the two named readings (rather than one number): the flip
point on this board is P(SK@declarer)≈0.88 — inside the honest uncertainty
band of "partial stop". Any single interpretation would be a tunable
opinion; requiring the answer to survive BOTH ends of the band is what
"clear-cut" means operationally. The strict reading is exactly "the student
believed the card"; the soft reading is "the bidder stretched". An answer
that needs one of them to be false is not teachable.

Longer term (not in this branch): fold the gib-card profile into Ben's
proposal stage (constrain, then consistency-score) so the primary verdict
table itself is graded on an auction-consistent distribution; extend
`domain.constraints` with per-seat disjunctions so "didn't bid 2NT"-type
denials become encodable.
