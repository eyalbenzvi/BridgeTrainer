# Opening-lead problems

A second problem type alongside bidding problems. The user is on lead after a
complete auction and chooses which of their 13 cards to lead.

## Grading (owner's definition)

Deals consistent with the bidding are sampled; **double-dummy** scores every
one of the 13 candidate leads by the **average number of defensive tricks** it
yields. The correct answer is **every card tied for the maximum average**
(touching cards land on identical values and all count).

Two "uninteresting deal" filters, both the owner's:

1. **C1 — obvious.** BEN's opening-lead policy puts more than **70%** on any
   single card → drop.
2. **C2 — suit doesn't matter.** The best card beats the best card of a
   *different suit* by less than **0.25 tricks** → drop. (Same-suit near-ties
   are ignored — they are usually literal double-dummy-equivalent touching
   cards, and genuine within-suit choices survive because C2 only compares
   across suits.)

Mechanical guards: minimum sample count; split-half stability on the headline
gap. (Doubled contracts were excluded in v1; they are now **included** and
form the `lead_doubled` category — see *Categories* below. Their double-dummy
defense is still the least realistic — Lightner/lead-directing doubles ask for
a specific lead the sampler cannot infer from the bare `X` token — so treat the
numbers on doubled boards with more caution than undoubled ones.)

## Categories

Every lead problem carries a `classification.type` — one of five categories,
a **deterministic function of the final contract** (no LLM, unlike the bidding
taxonomy): what you are leading against. A doubled contract takes precedence
over the level/strain buckets.

| id | he | contract |
|---|---|---|
| `lead_part_score` | חוזה חלקי | below game |
| `lead_3nt` | 3NT | notrump game (3NT; rare 4NT/5NT) |
| `lead_suit_game` | משחק בשליט | 4+ major / 5+ minor, below slam |
| `lead_slam` | סלם | level 6 or 7 |
| `lead_doubled` | חוזה מוכפל | any doubled contract |

Computed in `engine/lead_classify.py`, set at generation by
`lead_maker.build_lead_record`, and backfilled onto existing records —
locally by `scripts/classify_pool.py` and directly in Firestore by
`trainer pool backfill-leads`.

## Difficulty (1–5)

Built from trick-based signals; closeness lowers difficulty, a seductive-but-
wrong natural lead raises it:

- `trap` — BEN's top policy card is **not** in the correct set.
- `gap` — best minus best-different-suit (the C2 margin).
- `ben_conf_in_best` — policy mass on the actual best card.
- `n_close_suits` — number of different suits within ~0.5 tricks of the best.

5 = a trap decisively punished; 1 = one suit clearly best, no trap.

## Pipeline

`trainer lead-forge` → `engine/lead_maker.forge_lead_batch`:

1. `scanner.bid_out` — deal, BEN bids all four seats to conclusion (drop
   passed-out).
2. `conventions.final_contract` — level/denom/declarer/doubled; leader = LHO of
   declarer. The contract also fixes the problem's category
   (`lead_classify.classify_contract`).
3. `ben.lead_evaluate` — sample hidden layouts consistent with the auction
   (proven BotBid sampler), one DD pass per layout scoring all 13 cards, plus
   BEN's lead policy (`ben.lead_softmax`). Screen 128 → confirm 512.
4. `lead_verdict.judge_lead` — pure (numpy only, unit-tested in normal CI):
   applies C1, C2, the guards, and the difficulty bucket.
5. `lead_explain` — per-call meanings for the whole auction (clickable in the
   UI) and per-card notes in defensive-trick terms.
6. `pool.store.ProblemPool` — same flat-JSON pool as bidding; records carry
   `type: "lead"`.

### BEN adapter assumptions (verify in the CI spike)

Two BEN internals cannot be exercised outside the BEN-provisioned environment
and are isolated in `engine/ben.py`:

- **`dds.solve(...)` at the opening lead** is assumed to return
  `{card52: [defensive tricks per sample]}` with `solutions=3` (every legal
  lead scored) — see `_defence_tricks`. If the binding returns declarer tricks
  or a different container, adjust only that method.
- **Lead-softmax index space** (32- vs 52-card) is read from the returned
  vector length in `lead_softmax`.

If the DD path proves to only score BEN's NN candidates, the fallback is to
force all 13 cards through the supported `find_opening_lead`/`CardResp` path.

## Record schema (`type: "lead"`)

```
schema, kind="lead", id="lead1-XXXXXXXX", created_at, generator{...}
classification: {difficulty_level: 1-5, type: "<lead category id>"}
scoring_form="tricks"
dealer, vul, declarer, contract ("4HE"), leader, seat(=leader)
hand, auction (complete)
candidates: [{card, avg_def_tricks, ben_softmax}]        # all 13
verdict: {accepted:[cards], gap, n_samples, table:[per-card rows], flags}
difficulty: 1-5
quality: {gap, trap, ben_conf_in_best, n_close_suits, ...}
explanations: {note, auction:[{idx,seat,call,text}], cards:[{card,text}]}
full_deal, engine_auction_complete
```

## Site

- `type` added to records and `index.json` (`rebuild_index` defaults legacy
  records to `"bidding"`).
- Home page: a persisted **Bidding / Opening lead / Either** toggle (`bt_mode`)
  driving `pickUnseen(index, mode)` and `problemUrl`; per-type stats. Both
  scenarios expose the same difficulty **and category** filter (leads on the
  contract categories above); the lead page shows a category badge.
- New `lead.html`: the hand is the input (four suit rows of tappable cards);
  the **completed auction is clickable** — tap any call to read its meaning;
  the reveal leads with a ✓/✗ headline, a small per-suit bar comparison, then a
  collapsed 13-card ranked table and the full deal. Reuses the shared CSS/JS.
- `generate.yml`: `lead-forge` runs as a sequential step after `ben-forge` in
  the same job (shared model cache, one commit, disjoint `+500` seed space).

## Testing

`tests/test_lead_verdict.py` covers the contract mechanics and every verdict
path (C1, C2, ties, within-suit choice, doubled-now-judged, difficulty) with
no BEN dependency; `tests/test_lead_classify.py` covers the category function.
`lead.html` was smoke-tested end-to-end in a headless browser.
The BEN-touching layer is exercised only in the `generate` CI job.
