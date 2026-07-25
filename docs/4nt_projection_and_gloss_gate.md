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

## Conclusions

1. **A sampler that lands on the rescue floor is evidence, not a missing
   measurement.** `n == min_sample_hands_auction` (or `quality <
   bidding_threshold_sampling`) on a candidate prefix means Ben cannot place
   the call in any system. Reject the board on it instead of skipping the band
   check — the current behaviour disables the check exactly where the engine
   is most confused. This alone would have stopped this board.
2. **Reject degenerate projections.** A non-signoff candidate whose rollout
   projects one contract at 100 % while the auction ran two or more calls past
   the candidate is reporting argmax determinism as bridge certainty. Either
   drop such boards or roll the hero's own later turns out by sampling the
   policy rather than taking the argmax; at minimum stop printing `100 %` for
   a contract the hero had to bid twice more to reach.
3. **Never display a gloss that does not describe the call.** For calls that
   cannot be natural (NT at level ≥ 4, a cue-bid in a suit only the opponents
   bid, a jump to slam), require a convention name from GIB and drop the
   option/board when there is none — and never render a "meaning" whose whole
   content is constraints the seat's earlier calls already established.
4. **Check GIB's total-points band.** `card_vs_hand` and `band_vs_card` read
   `hcp` only; adding `pts` (HCP plus length or shortness points, whichever is
   kinder, with the existing ±2 slack) catches this board's false `3♦ (E):
   4-8 pts` and 9 boards' worth of the same class.
5. **Extend the forcing check into the rollout.** If a candidate GIB marks
   forcing (or a cue-bid in the opponents' suit) survives as the final
   contract in more than a few percent of rollouts, that option's EV is built
   on a partner nobody plays with — flag it, and refuse to crown it best.
6. **Clean-up list for the published pool**: `ben1-19f975cad49` (this board),
   the three other 4NT point-mass boards (`ben1-19f9609a54c`,
   `ben1-19f966c0800`, `ben1-19f9910d96d`), the 6 boards whose accepted answer
   is a forcing call the rollout passes out, and the 23 candidate rows with an
   empty gloss.
