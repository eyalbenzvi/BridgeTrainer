# Problem Classification: Type + Difficulty

Every published problem record carries a `classification` object:

```json
"classification": {
  "difficulty_score": 58.3,     // 0-100, computed at publication
  "difficulty_level": 4,        // 1-5, fixed cut points, never recomputed
  "type": "compete_or_sell",    // one of 10 fixed category ids
  "type_reason": "..."          // classifier's one-sentence audit trail
}
```

Both fields are attached **at generation time**: the difficulty by
`build_record` (pure computation), the type by `scripts/classify_pool.py`
run after each forge batch. The same script is idempotent and doubles as
the backfill for older records. `index.json` exposes `type` and
`difficulty_level` per problem for client-side filtering.

## Difficulty (engine/difficulty.py)

Construct: **the estimated probability that a competent club player gets
the problem wrong** — not the cost of an error (`quality.stakes`), not
editorial interest (`quality.interest`). Reviewed by a bridge-expert/
statistician panel pass; v2 collapsed a six-component draft into three
named factors:

    DiffScore = 50*INSTINCT + 30*CLOSENESS + 20*STRUCTURE

- **INSTINCT** = 0.7*(1 − p̃(winner)) + 0.3*misled. p̃ is BEN's policy
  renormalized over the candidates — how little of the "field's" mass the
  winning call carries. `misled` is 1 when the natural compass points
  wrong: `quality.trap` (the policy argmax loses ≥ 0.8 IMPs) OR dissonance
  (the winner loses more layouts than it wins — an EV edge carried by a few
  large swings). Trap and dissonance are mutually exclusive by
  construction. The Master-Solvers literature says the "instinct is wrong"
  factor is the strongest predictor of human error, hence half the scale.
- **CLOSENESS** — how nearly tied the decision is, measured twice and
  averaged for variance reduction: the IMP EV gap (noisy: CI up to 1.5 on
  a 2.5 band) and the per-layout win-rate margin (paired binomial on 512
  samples, sd ≈ 0.03).
- **STRUCTURE** — mean of five cheap indicators: contested auction,
  ≥ 4 non-pass stem calls, declare/defend flip ≥ 0.25, doubled share
  ≥ 0.15, and the winner being a low-frequency action (Pass/X/XX — the
  classic human graveyard).

Levels: fixed cuts 35 / 47 / 57 / 68 (provisional; recalibrate once at
pool ≈ 50–100, then freeze — never per-pool quantiles, so a label can't
change as the pool grows). Near a cut (< 3 points) the label is the median
of the full-sample level and the two split-half levels
(`quality.half_stats`, stored by the verdict since this change) — "would
this label replicate under resampling?".

Known limits, to validate when answer telemetry exists: Spearman ρ of
level vs empirical error rate (target > 0.6), recalibrating cuts to error
bands, testing BEN-policy-as-field-proxy against real answer
distributions, and separating coin-flip items (high difficulty, low
discrimination) from trap items via item discrimination.

## Type (engine/classify.py)

Ten fixed categories — no misc bucket (it only attracts classifier
laziness; `describe_hand` absorbs constructive leftovers). Synthesized
from the de-facto taxonomies in the judgment literature (Lawrence's
*Judgment at Bridge* chapters, Robson & Segal's *The Contested Auction*,
Cohen's LOTT framing); BridgeWinners and the MSC publish no typology.

| id | he | decision |
|---|---|---|
| `open_or_pass` | החלטת פתיחה | open a borderline hand, and with what |
| `preempt_decision` | הכרזת מנע | obstruct or not, and how high |
| `enter_auction` | כניסה למכרז | overcall / double / 1NT / stay out, balancing |
| `compete_or_sell` | קרב חוזה חלקי | bid once more, pass, or push them (LOTT) |
| `invite_or_game` | הזמנה או משחק מלא | sign off / invite / bid game; accept tries |
| `slam_try` | ניסיון סלם | move toward slam or not; accept partner's try |
| `choice_of_strain` | בחירת שליט | level settled — WHERE: 3NT vs major, preference |
| `double_or_bid` | להכפיל או להכריז | penalty/negative/action X; leave in or pull |
| `sacrifice_decision` | הקרבה | deliberate minus vs defending their make |
| `describe_hand` | תיאור היד | which constructive call describes the hand |

Classifier: `claude-sonnet-5` via the headless `claude` CLI (generation
runs inside Claude Code sessions at this stage). It sees the hero hand,
auction with the engine's call meanings, vulnerability, candidates with
policy, and the verdict winner; answers strict JSON (closed enum,
validated, one retry) plus a one-sentence reason stored for audit.

## Type (leads, engine/lead_classify.py)

Opening-lead problems carry the same `classification.type`, but the category
is a **mechanical fact of the final contract**, not an LLM judgment — so it is
computed directly (exact, no model, trivially backfilled). One per problem;
doubled takes precedence over the level/strain buckets.

| id | he | contract |
|---|---|---|
| `lead_part_score` | חוזה חלקי | below game |
| `lead_3nt` | 3NT | notrump game (3NT; rare 4NT/5NT) |
| `lead_suit_game` | משחק בשליט | 4+ major / 5+ minor, below slam |
| `lead_slam` | סלם | level 6 or 7 |
| `lead_doubled` | חוזה מוכפל | any doubled contract |

Set at generation by `lead_maker`; `index.json` exposes it alongside the
bidding types (the `lead_` prefix keeps the two disjoint in the shared
client-side facet counts).

## Operations

```
# after a forge batch (or as one-time backfill):
python3 scripts/classify_pool.py data              # difficulty + type
python3 scripts/classify_pool.py data --difficulty-only

# backfill lead categories directly onto the live Firestore pool:
trainer pool backfill-leads --key sa-key.json      # --dry-run to preview
```
