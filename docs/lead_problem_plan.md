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
gap; and a v1 exclusion of **doubled contracts** (double-dummy defense of
doubled contracts is unrealistic, and Lightner/lead-directing doubles demand a
convention-specific lead the sampler cannot infer from the bare `X` token).

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
   declarer. Doubled contracts are excluded here.
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
schema, type="lead", id="lead1-XXXXXXXX", created_at, generator{...}
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
  driving `pickUnseen(index, mode)` and `problemUrl`; per-type stats.
- New `lead.html`: the hand is the input (four suit rows of tappable cards);
  the **completed auction is clickable** — tap any call to read its meaning;
  the reveal leads with a ✓/✗ headline, a small per-suit bar comparison, then a
  collapsed 13-card ranked table and the full deal. Reuses the shared CSS/JS.
- `generate.yml`: `lead-forge` runs as a sequential step after `ben-forge` in
  the same job (shared model cache, one commit, disjoint `+500` seed space).

## Testing

`tests/test_lead_verdict.py` covers the contract mechanics and every verdict
path (C1, C2, ties, within-suit choice, doubled exclusion, difficulty) with no
BEN dependency. `lead.html` was smoke-tested end-to-end in a headless browser.
The BEN-touching layer is exercised only in the `generate` CI job.
