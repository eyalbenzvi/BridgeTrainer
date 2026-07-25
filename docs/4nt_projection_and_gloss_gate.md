# `ben1-19f975cad49`: a meaningless 4NT gloss, a 100 % projection and a passed cue-bid

Measured 2026-07-25 against the live Firestore pool (477 bidding boards) and
reproduced exactly with the Ben engine (BEN-21GF, pinned commit `2b53414`,
`scripts/setup_ben.sh`). Every number below comes from re-running the board's
own seed through `scanner.scan_board` / `ben.rollout_eval`, from live GIB
queries (`engine/gib_explain.py`), or from the stored records.

## The board

`ben1-19f975cad49` — dealer E, NS vulnerable, IMPs, hero **North**, responder.

```
hand   ♠KQJ62 ♥AK ♦8 ♣KT954          (16 HCP, 5-2-1-5)
deal   N KQJ62.AK.8.KT954   E 8754.743.T963.J3
       S AT9.QJT9.AJ5.Q86   W 3.8652.KQ742.A72
stem   (P) 1♣ (1♦) 1♠ (3♦) P (P) — ?
```

Candidates (Ben's raw softmax): 4♣ .382, **4NT .188**, 3♠ .097, 5♣ .086,
3NT .074, 4♦ .057. Accepted answer: **4NT**, +1.56 IMPs over 3♠, 423 samples,
sampler quality 0.80. Double-dummy on the actual deal: 12 tricks in ♠, ♥ and ♣
for N/S, 10-11 in NT, 7 in ♦.

Three complaints, three different root causes, one shared conclusion: the
board is unpublishable, and the gates that exist cannot see why.

## 1. `4NT — 4+♠, 6+ pts` is not an explanation of 4NT

The displayed meaning is GIB's, and only GIB's (`explain.option_explanations`
→ `gib_explain.card_for_auction`). Asked live for this auction, GIB returns:

| call | GIB's raw meaning for `p-1c-1d-1s-3d-p-p-<call>` |
|---|---|
| **4NT** | `4+ !S; 6+ total points` |
| 3♠ | `6+ !S; 11-12 total points` |
| 4♦ | `5+ !C; 4+ !S; 17+ total points; forcing to 5C` |
| 4♠ | `12+ HCP; strong rebiddable !S; 13+ total points` |
| 3NT | `5- !H; 4-5 !S; 14-21 HCP; likely stop in !D` |

GIB has **no rule for 4NT in this competitive sequence**. Instead of an
error it returns the constraints the seat has already shown — the same
`4+ !S; 6+ total points` its own gloss gave North's 1♠ ("Free bid") four
calls earlier. `explain.terse_meaning` cannot distinguish "no meaning" from
"a meaning", so it renders `4NT — 4+♠, 6+ pts`, which reads as a claim that
4NT shows spade length and 6+ points.

Two independent cross-checks that the line is empty, not merely terse:

* every other level-4+ NT candidate in the pool got a real name from GIB —
  `Blackwood (C/D/H/S)` ×5, `Quantitative invite` ×2 — this board is the only
  one of the eight with none;
* Ben's own measured meaning of that 4NT (sampled from partner's view,
  `ben.seat_features`) is 13-18 HCP, avg **16.0**, 5.1 spades, 4.5 clubs.
  "6+ pts" is not a description of it.

Why no gate fired: `explain_check.card_vs_hand` compares the gloss against
the hero's cards on HCP, `minlen`, `maxlen` and explicit holdings. Here
`hcp` is `None` (GIB stated *total points*, which nothing checks) and
`minlen S 4` is true — the hero does hold five spades. A gloss that says
nothing cannot contradict anything, so a check built entirely on
contradiction is structurally blind to it.

### The same board also displays a false stem gloss

`3♦ (E): 4+♦, 4-8 pts` — East holds ♠8754 ♥743 ♦T963 ♣J3: **1 HCP**, 1-2
total points, three off the bottom of the stated band. `card_vs_hand` checks
GIB's `hcp` band but **never its `pts` band** (`explain_check.py:161-182`;
`band_vs_card` has the same gap), so a stem call whose displayed range is
wrong by 3+ points is published as forced context the trainee must reason
from. Pool-wide, 9 of 477 boards show at least one stem call whose bidder
breaches the stated total-points band by more than 2 (both the length-point
and the shortness-point convention breached, so it is not a convention
artefact).

Pool-wide for the "gloss describes nothing" class: **23 of 892** non-pass
candidate rows (2.6 %) carry a gloss with no convention name and no suit
information at all — e.g. `4♦ — 0-11`, `2NT — 0-20 pts`, and four rows
(`ben1-19f94d0030c` 3NT, `ben1-19f975cae49` 6♣, `ben1-013527a9` 3♣,
`ben1-01354bee` 4♦) where GIB returned an empty string and the option
renders with no meaning at all.

## 2. `Leads to 6♣S 100 %` is an artefact of a greedy rollout

Reproduced exactly — same 423 samples, same distribution. The rollout
auctions behind that one line:

| n | rollout auction after the hero's 4NT |
|---|---|
| 324 | `4NT P 5♥ P **6♣** P P P` |
| 67 | `4NT P 5♣ P **6♣** P P P` |
| 21 | `4NT P 5♦ P **6♣** P P P` |
| 11 | `4NT P 5♠ P **6♣** P P P` |

Partner's answer *does* vary with partner's hand — four different answers,
i.e. Ben is treating 4NT as an ask. What never varies is what the hero does
next. Ben's policy for the hero's own follow-up, probed directly:

| after | hero's top calls |
|---|---|
| `4NT P 5♣ P` | **6♣ .462**, P .385, 6NT .032 |
| `4NT P 5♦ P` | **6♣ .586**, 5♥ .129, P .071 |
| `4NT P 5♥ P` | **6♣ .829**, P .047, 5NT .033 |
| `4NT P 5♠ P` | **6♣ .729**, P .126, 6NT .037 |

Ben blasts 6♣ whatever the answer — the information the 4NT was supposed to
buy changes nothing. Ben's `bidding_rollout` picks each sample's bid by
**argmax** (`botbidder.py:1159`, `bid = max(range(len(bid_list[i])), …)`), and
the hero's hand is identical in every sample, so the hero's continuation is a
constant and the contract distribution collapses to a point mass. `100 %`
therefore does not mean "this call reliably reaches 6♣"; it means "the greedy
rollout always reaches 6♣" — while in the 5♣ branch Ben's own model is a
46/38 coin-flip between 6♣ and passing 5♣, a two-contract swing the display
reports as certainty.

This is systematic, not a one-off: **6 of the 8** level-4+ NT candidates in
the pool project a single contract at 99-100 %, and 11 option rows across the
pool project one contract at exactly 100 % even though the auction continued
past the call. Two of those readings are self-contradictory on their own line:

| board | displayed | projection |
|---|---|---|
| `ben1-19f9609a54c` | `4NT — Quantitative invite to 6NT` | `6♣S 100 %` |
| `ben1-19f9910d96d` | `4NT — Blackwood (C)` (accepted best, +1.4 IMPs) | `6♣S 100 %` |
| `ben1-19f975cad49` | `4NT — 4+♠, 6+ pts` (accepted best, +1.6 IMPs) | `6♣S 100 %` |

And the two engines do not share a system for this sequence at all: asked what
the 5♥ answer means, GIB replies `3+ !C; 11-21 HCP; biddable !H` — a natural
heart bid, not a keycard step.

Consequence for this board: the answer the trainee is graded against wins its
+1.6 IMPs entirely through a 6♣ contract reached by a call GIB cannot define,
answered in a system GIB does not recognise, and placed without reference to
the answer. Sampling the hero's continuation instead of taking the argmax
would leave ~8-10 % of samples below slam (≈ −70 points on the mean, 6♣ =
1370 vs 5♣+1 = 620 vulnerable), so the crown would probably survive the
arithmetic — the disqualifying faults are the false certainty and the fact
that no partnership plays the line, not the EV.

## 3. `Leads to … 4♦N 9 %` — partner passes a forcing cue-bid

36 of 423 rollouts are `4♦ P P P`: the hero's 4♦ — glossed by GIB
`5+ !C; 4+ !S; 17+ total points; **forcing to 5C**` — is passed out, leaving
North declaring the opponents' suit on a singleton ♦8 opposite ♦AJ5.

That is Ben's partner model, not a decoding error: asked with South's actual
hand, `P` carries 17.1 % of the policy over 4♦ (`4♠ .398, 4♥ .324, P .171`).
The rest of the 4♦ rollout is `4♦ P 4♠ P P P` (276) and
`4♦ P 4♥ P 4NT P 5♥ P 6♣` (60) — i.e. the same 4NT machinery as §2.

Pool-wide: **17 boards** offer a candidate that GIB marks forcing, or that
cue-bids a suit only the opponents bid, and whose rollout leaves that very
call as the final contract — up to 96 % of samples
(`ben1-19f975cae9e`, 3♦ cue passed out in 492 of 512), and in **6 boards the
affected option is the board's accepted answer**, so its EV is built partly
on rollouts where partner passed a force:

| board | call | left as contract | share | accepted best? |
|---|---|---|---|---|
| `ben1-19f975cae9e` | 3♦ (cue) | 3♦S | 96 % | no |
| `ben1-013574c2` | 3♠ (forcing) | 3♠N | 69 % | **yes** |
| `ben1-19f947b9854` | 3♠ (forcing) | 3♠S | 68 % | **yes** |
| `ben1-01357319` | 2♥ (forcing to 3NT) | 2♥N | 64 % | **yes** |
| `ben1-19f93fc826f` | 3♣ (forcing to 3NT) | 3♣E | 57 % | **yes** |
| `ben1-19f97f89099` | 2♦ (fourth suit forcing) | 2♦E | 31 % | **yes** |
| `ben1-19f975cad49` | 4♦ (cue, forcing to 5♣) | 4♦N | 8.5 % | no |

`explain_check.forcing_pass_violations` (docs/forcing_pass_gate.md) covers the
adjacent case — *Pass offered to the hero* under a live force — and nothing
looks at *partner passing the hero's forcing call inside the rollout*.

## 4. Why the board passed the gates: the sample floor silences the band check

Re-run on the rescanned board, all three gates are empty:

```
hand_violations fatal: []      forcing_pass: []      band_violations: []
```

`band_violations` → `band_vs_card` returns nothing when
`feats["n"] < BAND_N_MIN` (30). The per-candidate sample counts on this board:

| candidate | n | sampler quality | band check |
|---|---|---|---|
| 4♣ | 128 | 0.735 | checked |
| 3♠ | 123 | 0.776 | checked |
| 4NT | **15** | **0.520** | skipped |
| 4♦ | **15** | **0.477** | skipped |
| 5♣ | **15** | 0.563 | skipped |
| 3NT | **15** | 0.519 | skipped |

`15` is not a coincidence: it is Ben's rescue floor. When fewer than
`min_sample_hands_auction = 15` layouts clear the sampler's
`bidding_threshold_sampling = 0.70` trust score, `sample.py:698-705` throws
the filter away and returns the 15 least-bad layouts regardless of score
(`accepted_samples = samples[:15]`). A candidate that lands on the floor is
one Ben's own bidding model cannot reconcile with any layout it drew — 4NT
scores 0.52 against a 0.70 threshold — which is precisely the signal that the
call is off-system and its gloss needs vetting. The gate instead reads
`n = 15 < 30` and skips.

With the floor lifted (same layouts, `n` raised only so the guard passes),
4♦ fires immediately:

```
gloss promises 5+C but bid shows avg 3.6 (P5+=0.07)
```

i.e. **the board would have been rejected as `expl_vs_band`** had the check
run. Over 14 boards re-measured this way (38 option rows), 15 rows (39 %)
were skipped by the floor and 1 carried a violation the floor silenced — the
one that would have killed this board.

The 4NT row would still have passed even with the floor lifted (`pts` is not
checked, and `4+ !S` is true), so §1 needs its own rule.

## The rules to add

No board is removed except by a rule that fires mechanically, states which
predicate fired, and has a measured cost on the published pool. Three rules
are proposed, one per defect; all three fire on `ben1-19f975cad49`. Each is
calibrated below over the 477 published bidding boards (1 374 option rows,
892 of them non-pass).

### R1 — *the candidate asked a question and ignored the answer*

The defect it names: a candidate's contract distribution reports argmax
determinism as bridge certainty (§2). The naive form of the rule — "the
projection is a single contract at 100 %" — is **not** the rule to adopt: it
was measured and it is wrong about nearly half the boards it flags. What
survives measurement is the answer-insensitivity test.

```
answer_insensitive_violations(ev, spot)      # forge-time; uses ev.auctions,
                                            # which rollout_eval already builds
  k = len(spot.stem)
  for call in ev.bids:                       # skip P / X / XX
      replies = Counter(auction[k+2] for auction in ev.auctions[call])
      # partner's own first call after the candidate; k+1 is LHO, k+3 RHO
      asked = #{r for r in replies if r not in (PASS, absent)
                and replies[r] / n >= 0.05} >= 2
      settled = max(Counter(ev.contracts[call]).values()) / n >= 0.99
      if asked and settled:
          FIRE "option {call}: partner answered {replies} yet the contract is
                {contract} on {share:.0%} of layouts — the rollout discards the
                information the call asks for"
```

Both halves are needed and each is doing work:

* `asked` — partner's action varied with partner's hand, so the call
  functioned as an ask or a force, and the samples genuinely differed in what
  came back;
* `settled` — the final contract nevertheless never moved.

The 5 % floor on a reply and the 99 % on the contract are the loosest values
that keep single-sample noise out; the observed cases are not near either
boundary (this board: four replies at 73/20/5/2 %, contract 100 %).

**Why not the naive point-mass rule.** All 11 rows the record-only screen
flags at 100 % were re-rolled with Ben at n=128 and their rollout auctions
inspected:

| board | call | partner's replies | hero's next call | verdict |
|---|---|---|---|---|
| `ben1-19f975cad49` | 4NT | 5♥×93, 5♣×26, 5♦×6, 5♠×3 | 6♣×128 | **answer-insensitive** |
| `ben1-19f9609a54c` | 4NT | 5♣×105, 5♥×13, 5♦×10 | 6♣×128 | **answer-insensitive** |
| `ben1-19f966c0800` | 4NT | 5♣×118, 5♦×10 | 6♦×128 | **answer-insensitive** |
| `ben1-19f9910d96d` | 4NT | 5♣×103, 5♥×13, 5♠×12 | 6♣×128 | **answer-insensitive** |
| `ben1-19f95ad1501` | 4♣ | 4♦×121, 4♥×7 | 4♥×112, P×16 | **answer-insensitive** |
| `ben1-19f98ba4d93` | 3NT | 4♠×118, 4♣×10 | P×118, 4♦×10 | **answer-insensitive** |
| `ben1-19f95ad153a` | 3♣ | 3NT×128 | P×128 | forced — partner had one action |
| `ben1-19f95ad1594` | 4♥ | 4♠×128 | P×128 | forced |
| `ben1-19f9609a4d9` | 2NT | 3♠×128 | P×128 | forced |
| `ben1-19f97f88f2a` | 2♠ | 3NT×128 | P×128 | forced |
| `ben1-19f93985a7f` | 3NT | 4♣×128 | 4♠×128 | forced |

**5 of the 11 are legitimate**: partner made the same call on all 128 layouts,
so the point mass is a fact about the auction, not about argmax, and deleting
those boards would be exactly the "just drop the board" move this rule exists
to avoid. R1 clears them. It also fires on three rows the 100 % screen misses
(`ben1-19f98ba4e75` 4NT, `ben1-19f95ad156c` 4NT, `ben1-19f975cae49` 4♣ — all
asks whose projection sits at 99.2-100 %), so it is both narrower and broader
than the naive rule, in the right directions.

**Measured false-positive rate.** 22 boards drawn at random from the pool
(seeded shuffle, the suspect boards excluded), re-rolled at n=128: **56 option
rows, 0 hits.** R1 does not quietly delete ordinary boards — on every random
row either partner passed (`distinct_replies = 0`, no question asked) or the
contract distribution moved with the answer.

The record-only 100 % test still has a use — it is the **cheap pre-filter for
auditing the already-published pool**, where `ev.auctions` is gone: 11 rows on
11 boards (2.3 %) to re-roll and confirm, of which 6 die and 5 are cleared.

| screen | rows | boards (of 477) | accepted answer | confirmed by R1 |
|---|---|---|---|---|
| point mass = 100 % (record only) | 11 | 11 (2.3 %) | 3 | 6 of 11 |
| ≥ 99 % | 17 | 16 (3.4 %) | 3 | not measured |
| ≥ 95 % | 30 | 27 (5.7 %) | 5 | not measured |
| **R1 itself, on 22 random boards** | **56 measured** | **0** | 0 | — |

Confirmed R1 set on the published pool: 9 boards — the 6 above plus
`ben1-19f98ba4e75`, `ben1-19f95ad156c`, `ben1-19f975cae49`, which the 100 %
screen missed and R1 catches.

### R2 — *the displayed meaning of a conventional call says nothing*

The defect it names: `4NT — 4+♠, 6+ pts` (§1). Not "GIB gave no convention
name" — GIB routinely describes cue-bids by constraints alone and those
glosses are informative (that predicate flags 24 boards, mostly wrongly). The
defect is that the card states **nothing the seat had not already shown**.

```
meaningless_gloss_violations(stem_entries, option_cards, auction, dealer, hero)
  prior = cumulative constraints from the HERO's own earlier stem cards
          (minlen/maxlen/hcp/pts/forcing — the same accumulation
           band_violations already does for known_minlen)
  for call, card in option_cards:
      if call is natural: continue        # a natural call is explained by its
                                         # own denomination; only the level is
                                         # in question
      if card is empty:                    FIRE "no meaning stated"
      if card names no convention
         and asserts no holding (!CQ)
         and states no force prior lacked
         and every stated length  <= prior length
         and its hcp/pts band is no narrower than prior:
                                           FIRE "gloss restates what {earlier
                                                 call} already showed"
```

"Cannot be natural" = NT at level 4 or 5, or a bid in a strain only the
opponents have bid (a cue-bid). Calibration:

| variant | rows | boards (of 477) | accepted answer | fires on this board |
|---|---|---|---|---|
| **only calls that cannot be natural** | **2** | **2 (0.4 %)** | **1** | **yes** (4NT, the accepted answer) |
| every candidate | 38 | 33 (6.9 %) | 18 | yes |

Restricting to non-natural calls is what makes the rule surgical: the
all-candidates variant flags rows like `3♠ — 5+♠` where the hero had already
shown five spades — true, uninformative, and harmless, because a natural raise
explains itself. The two boards it does flag are this one (4NT glossed with
North's own 1♠ constraints, `4+ !S; 6+ total points`) and `ben1-013527a9`
(a 3♣ cue-bid with an empty gloss).

### R3 — *a forcing call is left in as the final contract*

The defect it names: `4♦N 9 %` (§3). The companion to
`forcing_pass_violations`, which covers pass-as-an-option and never looks
inside the rollout.

```
forcing_contract_violations(verdict, option_cards, auction, dealer, hero)
  for row in verdict.table:
      call = row.bid;  skip P / X / XX
      if not (option_cards[call].forcing or call is a cue-bid): continue
      for contract, cnt in row.top_contracts:
          if level+strain(contract) == call
             and declarer is on the hero's side
             and cnt / n >= 0.05:
              FIRE "option {call} is {forcing clause} yet the rollout leaves
                    it as the contract on {cnt}/{n} layouts"
```

| share floor | rows | boards (of 477) | accepted answer | fires on this board |
|---|---|---|---|---|
| ≥ 2 % | 16 | 15 (3.1 %) | 6 | yes |
| **≥ 5 %** | **16** | **15 (3.1 %)** | **6** | **yes** (4♦ at 8.5 %) |
| ≥ 10 % | 14 | 13 (2.7 %) | 6 | no |
| ≥ 25 % | 11 | 11 (2.3 %) | 5 | no |
| ≥ 50 % | 7 | 7 (1.5 %) | 4 | no |

5 % is not fitted: the observed shares jump from 8.5 % straight down to 1.2 %
and 0.6 %, so any floor in (2 %, 8 %] selects the same 16 rows. Below 2 % the
two remaining rows are single-sample noise.

### R0 — the one-line fix that closes the hole, inventing no rule at all

`band_violations` already owns the right check; it just declines to run it.
Replace the blanket `feats.n < BAND_N_MIN → skip` with: skip only the
HCP-percentile clause (which genuinely needs n), and run the suit-length
clauses whenever the sample exists. When the low `n` is Ben's rescue floor the
returned layouts are the 15 *best-fitting* ones, so a length violation
measured on them is conservative, not noisy. Measured over 14 boards
(38 option rows): 15 rows sit on the floor, 1 of them carries a violation —
the 4♦ on this board, which alone rejects it as `expl_vs_band`.

### R4 — GIB's total-points band (separate defect, does not remove this board)

`card_vs_hand` and `band_vs_card` read `hcp` only. Adding `pts` — HCP plus
length points or shortness points, whichever is kinder to the bidder, with the
existing `SLACK_HCP = 2` — flags 9 boards of 477 (1.9 %). It does **not**
remove this board: East's ♠8754 ♥743 ♦T963 ♣J3 is 1 HCP + 1 shortness point
= 2 against a promised `4-8`, exactly at the slack boundary. The false
`3♦ (E): 4+♦, 4-8 pts` line therefore survives R4 and is reported by R2's
sibling reasoning only if the slack is tightened to 1 — which is an owner-level
call, not something to slip in with this change.

## What removes `ben1-19f975cad49`

All of R1, R2 and R3 fire on it, independently:

| rule | what fires | on the accepted answer? |
|---|---|---|
| R1 | 4NT projects 6♣S on 423/423 layouts, four calls past the candidate | yes |
| R2 | 4NT's gloss `4+ !S; 6+ total points` is North's own 1♠ card | yes |
| R3 | 4♦ (`forcing to 5C`) is the contract on 36/423 layouts | no (a foil) |
| R0 | 4♦'s gloss promises 5+♣, Ben's 4♦ shows avg 3.6 (P5+ = 0.07) | no (a foil) |

R2 is the one to adopt first: it is record-only, needs no engine, has the
smallest measured cost (2 boards), and fires on the very option the board is
graded against. R1 is the rule for complaint 2 — it needs the forge's
`ev.auctions`, and it is the one that survived measurement where the naive
point-mass rule did not. R3 is the rule for complaint 3.

Adopting R1 + R2 + R3 (at 5 %) removes **23 of 477 boards (4.8 %)**:
9 (R1) + 2 (R2) + 15 (R3), with three boards caught by more than one rule.
Full list:

| board | rules |
|---|---|
| `ben1-19f975cad49` | R1+R2+R3 |
| `ben1-013527a9` | R2+R3 |
| `ben1-19f95ad1501`, `ben1-19f95ad156c`, `ben1-19f9609a54c`, `ben1-19f966c0800`, `ben1-19f975cae49`, `ben1-19f98ba4d93`, `ben1-19f98ba4e75`, `ben1-19f9910d96d` | R1 |
| `ben1-013572e7`, `ben1-01357319`, `ben1-013574c2`, `ben1-0135750a`, `ben1-19f93985aed`, `ben1-19f93fc826f`, `ben1-19f947b97cb`, `ben1-19f947b9854`, `ben1-19f9609a411`, `ben1-19f975cae9e`, `ben1-19f97f89099`, `ben1-19f9910d9de`, `ben1-19f9910da11` | R3 |

## What shipped, and what the rules removed

Implemented in `engine/explain_check.py` (R0-R3), wired into
`engine/maker.forge_one` (R1/R2/R3) and `record_violations` (R2/R3), with
`scripts/audit_pool.py --rollout / --suspects-only` for R1 on stored records.
Covered by `tests/test_rollout_gate.py`.

Run against the live pool on 2026-07-25 (1 030 problems, 503 of them bidding —
the pool had grown since the calibration above):

| stage | result |
|---|---|
| cheap audit (R2 + R3, every board) | 17 boards flagged |
| R1 pre-filter (point mass = 100 %) | 10 suspects |
| R1 re-roll, shortlist of 15 (every board with a ≥ 99 % point mass) | **8 confirmed, 6 cleared** as forced continuations |
| band check on the same shortlist (pre-existing gate) | 1 further board (`ben1-19f9910d9ea`) |
| **removed** | **25 boards** (each re-confirmed by `--band --rollout --remove` before deletion) |

The 6 cleared boards are the point of the exercise: `ben1-19f93985a7f`,
`ben1-19f95ad153a`, `ben1-19f95ad1594`, `ben1-19f97f88f2a`,
`ben1-19f98ba4e0e`, `ben1-19f99977637` all project a single contract on every
layout, and all six survive, because partner made the same call on every
layout too. The naive point-mass rule would have deleted them.

R1's confirmed 8: `ben1-19f95ad1501`, `ben1-19f95ad156c`, `ben1-19f966c0800`,
`ben1-19f975cad49`, `ben1-19f975cae49`, `ben1-19f98ba4d93`,
`ben1-19f98ba4e75`, `ben1-19f9910d96d` — six of them a 4NT ask answered
5♣/5♦/5♥/5♠ and blasted over regardless.

Afterwards: 1 005 problem docs, index in step (1 005 entries), and
`trainer pool purge-orphan-attempts` deleted the 6 stored attempts left on
deleted boards — 5 on boards removed here (including this board's own
answered-4♦-scored-42 attempt, graded against the 4NT verdict) and 1 already
orphaned. 122 attempts remain, 0 orphans.

## Conclusions

1. This board is not a one-off: each of its three faults is a class with 2-15
   boards behind it, and each class has a mechanical predicate that costs
   under 3.5 % of the pool.
2. The reason it survived generation is `R0` — the band check skips exactly
   the calls Ben cannot place, because Ben signals "cannot place" by returning
   too few samples for the check's own floor. Fix that first; it is a
   two-line change to an existing rule and it would have stopped this board
   before any of the new rules existed.
3. Nothing here needs an LLM or a human judgement call at generation time,
   which is the standing requirement for this gate (`engine/explain_check.py`
   preamble).
