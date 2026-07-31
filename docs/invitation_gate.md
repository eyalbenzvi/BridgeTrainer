# The invitation gate: a call the board calls an invitation, and a rollout that does not

Measured 2026-07-25 over the published Firestore pool (477 bidding
boards) and reproduced with the Ben engine (BEN-21GF, pinned commit
`2b53414`). Source: `engine/explain_check.py` (`invite_violations`),
`engine/maker.py`, `pool/firestore_store.py`
(`purge_mislabeled_invites`).

## The defect

`ben1-19f947b9723` — `2NT-P-3♦-P-3♥-P`, hero responder with
♠75 ♥KJ9752 ♦QT ♣K98 (9 HCP, six hearts) opposite a 20-21 notrump — was
published with four options and `6♥` as the winner:

| option | gloss shown to the trainee | where the rollout leads | graded |
|---|---|---|---|
| 6♥ | 6+♥, 12+ pts | 6♥N **100%** | **best** |
| 4NT | *Quantitative invite*, 5♥, 12-12 | 6♥N 52%, 6NT N 48% (**slam 100%**) | −0.8 IMPs |
| 3NT | 5♥, 5-10 | 3NT 48%, 6♥ 45%, 5♥ 8% | −2.7 IMPs |
| 4♥ | *Mild slam try*. No shortness, 6+♥, 9-10 pts | 4♥N **100%** | **−5.3 IMPs** |

Three things are wrong at once, and they are one defect:

1. **4♥ is narrated as a slam try and evaluated as a signoff.** Over 512
   sampled partner hands — every one of them a 20-21 balanced hand that
   has just completed a transfer — Ben's partner passes 4♥ *every single
   time*. A try nobody ever accepts is a signoff.
2. **4NT is narrated as an invitation and evaluated as a commitment.**
   The same 512 layouts reach slam 512 times. Partner never has a
   decision; the difference between 4NT and blasting 6♥ is which strain
   the engine's own continuation picks (they push on 88% of layouts).
3. **Therefore 6♥ "wins".** The 5.3 IMPs charged against 4♥ — the call
   Ben's own policy rates at 51% — are not the cost of inviting, they are
   the cost of the partner model refusing a try that the very same
   evidence says should be accepted: the winner reaches slam and makes
   it on 100% of layouts. The board teaches "never invite, blast", which
   is a fact about the engine, not about bridge.

The board passed every existing gate. The gloss-vs-hand check
(`hand_violations`) noticed only that the hero shades 4NT's `12-12` band
by three points and kept it as a soft annotation (`option 4NT: hcp 9
outside 12-12`) — correctly, since band shading is the trainer's subject
matter. Nothing compared the displayed *function* of a call against the
rollout that graded it.

## The rule

For every offered option whose GIB gloss is an invitation
(`invitational`, `invite`, `game try`, `quantitative`, `slam try`), take
the invited bracket — slam when the gloss says slam/quantitative/6NT,
otherwise game — and measure how often the rollout behind that option
reaches it, over the layouts the hero's side declares:

* **never declined** — reached on ≥ 98% of layouts. Partner has no
  decision at all: the call is a commitment in the system that produced
  the evidence, whatever the gloss calls it.
* **never accepted** — reached on ≤ 2% of layouts, *while* the board's
  accepted call reaches it on ≥ 50% of its own and the invitation is
  charged ≥ 1.0 IMPs for missing it. The board then asserts both that
  the level is right and that the systemic invitation to it never gets
  there.
* **never accepted, and it is the answer** (added 2026-07-31, see
  below) — reached on ≤ 2% of layouts while the invitation *is* the
  board's accepted call. No winner corroborates here because the call
  is the winner: the gloss is the board's central lesson, and the
  board's own projection refutes it.

Either one rejects the **board**, not the option, for the reason
`forcing_pass_violations` gives: the same partner model produced the
rollout behind every other candidate, so dropping the misdescribed
option would leave the rest of the evidence resting on it.

Two abstentions keep the rule honest. A stored row carries only its top
three contracts, so a distribution that does not account for ≥ 95% of
the samples is not judged (the forge passes the full per-candidate
counter and always answers). And if the opponents declare more than 10%
of the layouts, the level was never partner's to accept — their bidding
took the decision away — so the branch says nothing about the
invitation.

## Why the thresholds sit at the extremes

Acceptance rate is a genuine bridge quantity here: the hero's hand is
fixed and partner's is sampled, so an invitation partner accepts 3% of
the time is a *thin* invitation (partner needs a maximum), not a
mislabelled one. Over the 477 published bidding boards, 57 offered
options carry an invitational gloss; 39 of those rows are judgeable from
the stored top-three distributions (18 abstain: diffuse branches and
auctions the opponents took over), and their acceptance rates spread
across the whole range:

| acceptance rate of the invited level | rows |
|---|---|
| 0.00 – 0.02 (**never accepted**) | 6 |
| 0.03 – 0.10 | 8 |
| 0.11 – 0.30 | 13 |
| 0.31 – 0.70 | 10 |
| 0.71 – 0.97 | 0 |
| 0.98 – 1.00 (**never declined**) | 2 |

There is no gap to cut at below 0.30, which is why the rule takes only
the extremes and, on the never-accepted side, demands corroboration from
the board's own winner: of the six never-accepted rows, three sit on
boards whose winner stays at or below the invited level (`19f9910da11`,
`19f93985aec`, `19f97f88f1f` all won by Pass), so the evidence never
claims the level was there and they are kept. With those conditions the
gate flags **5 rows on 4 boards (0.8% of the pool)**:

| board | option | gloss | measured |
|---|---|---|---|
| `ben1-19f947b9723` | 4♥ | Mild slam try | slam on 0% of layouts vs 100% for the winning 6♥, charged 5.3 IMPs |
| `ben1-19f947b9723` | 4NT | Quantitative invite | slam on 100% of layouts |
| `ben1-19f95ad1603` | 2NT | Invitational to 3NT game | game on 0% vs 100% for the winning 3NT, charged 2.3 IMPs |
| `ben1-19f9609a4d9` | 2NT | Invitational to 3NT game | game on 0% vs 100% for the winning 4♠, charged 1.2 IMPs |
| `ben1-19f9609a54c` | 4NT | Quantitative invite to 6NT | slam on 100% of layouts (and graded −3.7 IMPs against passing) |

Cost: nothing. The check counts contracts the confirm rollout already
produced, so it adds no sampling and no network call — unlike
`band_violations`, it can also re-judge stored records, which is what
the purge below does.

## The answer itself: a try graded best that partner never accepts

Reported from the field 2026-07-31 and measured over the published
Firestore pool of that day (1311 bidding boards). `ben1-19fb00aa07e` —
`2NT-P-3♥-P-3♠-P`, hero responder with ♠T87653 ♥AT7 ♦T2 ♣84 (4 HCP, six
spades) opposite a 20-21 notrump — was published with 4♠ as the winner,
and 4♠ is the right call: game opposite 20-21 with a sixth spade. But
the gloss shown on that very answer was GIB's

> 4♠ — *Mild slam try*. No shortness, 6+♠, 9-10 pts. Leads to 4♠S 100%.

The line contradicts itself on the screen: a slam try that leads to 4♠
on 100% of layouts, shown to a hand holding 4 points against a stated
9-10. In the system that produced the evidence (Ben's rollout — opener
passes 4♠ on 512 of 512 layouts) the call is a plain signoff; in the
system the gloss describes, this hand would never bid it — GIB's weak
route to 4♠ is a four-level transfer, and transfer-then-raise is the
stronger sequence. The trainee is taught a declaration whose displayed
meaning is false in both systems at once.

Both existing checks stepped around it. The gloss-vs-hand check
(`hand_violations`) forgave the band: 9-10 total points against the
hand's loosest countable total of 8 is a 1-point miss, inside
`SLACK_PTS` — correctly, since band shading is the trainer's subject
matter. And the never-accepted half above judged only *losing* options
— its corroboration ("the winner reaches the level") exists to prove a
refused invitation was charged for the refusal, so the winner itself
was exempt.

The fix drops the corroboration exactly when none is needed: when the
invitational gloss sits on the **accepted call itself**, the acceptance
share alone convicts. Partner never accepting a try held with the
values the gloss states is not a thin invitation — opposite a known
20-21, a real 9-10 try is accepted on a fair share of layouts — it is
the signature of a gloss describing a different hand than the one that
bid it.

Measured on the pool, the extreme is separated by an empty decade, so
`INVITE_NEVER` cuts cleanly with no new threshold:

| acceptance rate of the invited level (accepted call only) | rows |
|---|---|
| 0.00 – 0.02 (**never accepted**) | 2 |
| 0.03 – 0.10 | 0 |
| 0.11 – 0.30 | 3 |
| 0.31 – 0.70 | 4 |
| 0.71 – 0.97 | 2 |

The two rows at the extreme are the reported board and one sibling —
the same sequence, the same gloss on the same winning 4♠:

| board | option | gloss | hero | measured |
|---|---|---|---|---|
| `ben1-19fb00aa07e` | 4♠ (winner) | Mild slam try, 9-10 pts | 4 HCP | slam on 0% of layouts |
| `ben1-19faf4e6649` | 4♠ (winner) | Mild slam try, 14-15 pts | 8 HCP | slam on 1% of layouts |

Cost: still nothing — the same stored distributions, one more branch.
Both boards were purged with `purge-mislabeled-invites` on 2026-07-31.

## Operations

```bash
trainer pool purge-mislabeled-invites --dry-run   # report
trainer pool purge-mislabeled-invites            # delete the offenders
python3 scripts/audit_pool.py --firestore        # same rule, with the others
```

`record_violations` carries the check, so `scripts/audit_pool.py` (and
`trainer pool audit`) flag these boards alongside the gloss-vs-hand and
forcing-pass offenders. Stored attempts on a purged board are left
alone; `regrade_attempts` counts them as `missing_problem`.

## What this gate does not do

It does not judge whether a *winner* is a sensible bridge call. On
`ben1-19f947b9723` a direct 6♥ on 9 HCP won because both slam routes
push on 88% of layouts and 6♥ dodges the 48% of 4NT auctions that land
in 6NT — i.e. the margin came from the engine's choice of strain after
the invitation, not from the hero's decision. The board is now rejected
for narrating two invitations it never evaluated, and the blast-wins
verdict goes with it, but "the winner's edge lives entirely inside one
contract class" is a separate measurement (`verdict.EQUIV_TV` is the
existing, much narrower guard) and is not addressed here.
