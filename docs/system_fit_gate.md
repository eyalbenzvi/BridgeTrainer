# The system-fit gates: a promise the call does not carry, and a force the rollout ignores

Measured 2026-07-26 over the published Firestore pool (472 bidding boards)
with the Ben engine (BEN-21GF, pinned commit `2b53414`). Source:
`engine/explain_check.py` (`band_vs_shaded_hand`,
`game_force_stop_violations`), `engine/maker.py`, `engine/ben.py`
(`seat_features.len_ge`).

Both rules answer owner reports on published boards, and both are the same
kind of fault: the board's own numbers say the call means something the
displayed system does not contain.

## R7 — the one-card shade, arbitrated by the call's own band

### The defect

`ben1-19f975caec3` — third seat, nobody vulnerable, hero ♠JT875 ♥KJ53 ♦Q9
♣KT (9 HCP) after `P-P` — was published as "open 2♠ or pass" and graded 2♠
best (+0.7 IMPs over Pass, Ben's policy 60/39):

| option | gloss shown to the trainee | graded |
|---|---|---|
| 2♠ | *Weak two bid*, **6+♠**, 0-10 | **best** |
| Pass | No suitable call, 0-11 | −0.7 IMPs |

The hand holds **five** spades. The owner's report: *"the suggested 2♠ is
very unsuitable for the system — not BEN's, not GIB's."*

Nothing caught it. `hand_violations` compares every gloss against the
bidder's actual 13 cards, but forgives a one-card length shade
(`SLACK_LEN = 1`) — a promised six met by five is exactly the shade the
constant exists for, because GIB describes the systemic meaning and sound
bridge shades it by a card. `band_vs_card` compares the gloss against Ben's
measured meaning, but its share half was hard-wired to the FIVE-card
threshold (`len5plus`), which a `6+` promise passes trivially: Ben's 2♠
band holds five spades on 100% of layouts. Its average half (`avg <
promise − 2.0`) reads 5.09 against 4.0 and stays silent.

### The rule

The band decides whether the shade is a shade. For every suit a gloss
states a minimum of five or more cards in, where the bidder's hand is short
of it: measure `P(length >= promise)` over the layouts Ben's sampler accepts
for that very call. Below `BAND_PLEN_DENIED` (0.15) the call does not carry
the promise at all — the gloss is describing a different call, not a
stretched version of this one — and the board dies.

On the reported board: Ben's 2♠ band is **avg 5.09 spades, six on 9% of
layouts**. BEN-21GF's third-seat weak twos *are* five-card suits, which is
also why its bidder chose 2♠ with 60% policy on a five-card suit. The board
is not a stretched weak two; it is a call GIB's card, and the board's own
"meanings follow standard 2/1 Game Force" label, both deny.

Minima below five are left alone: GIB attaches `2+ !S` / `3+ !H` to raises
and notrump bids as shape statements, where one card either way is ordinary
bridge, and a 2+ card breach is already fatal in `hand_violations`.

Deletion, not repair — the same reason `purge_forcing_pass` and
`purge_incomplete_menus` delete. The promised length is the whole content of
the call the trainee is asked to judge, and rewriting the gloss to match Ben
("weak two, 5+♠") would publish a system claim GIB's card denies, on
evidence gathered from a partner who reads the call Ben's way.

### Why the threshold sits at 0.15

Of the 472 published bidding boards, **71 stem/option rows** state a minimum
of 5+ cards that the bidder's hand is short of (all of them short by exactly
one card — larger breaches are already fatal). Measuring each one's band:

| P(promised length) | rows | what they are |
|---|---|---|
| 0.00 – 0.13 | **24** | weak twos Ben means as five-card suits, three-level preempts it means as six |
| 0.20 – 0.50 | 11 | jump overcalls and rebids Ben means as the promised length a third to half the time |
| 0.51 – 1.00 | 36 | the genuine shade: Ben means the promise, the hand is a card light |

The gap between 0.13 and 0.20 is the rule's whole calibration: any floor in
(0.14, 0.20] picks the same 24 rows. It is the mirror of the existing
`BAND_P5_SURE = 0.90` ("measured: the bid promises 5+ here"), read at the
length the gloss actually promises.

The 24 rows are one board each — 5.1% of the pool. Fourteen are stem calls
(the trainee reasons from a gloss that misdescribes a hand they cannot see),
ten are offered options, and six of those ten are the board's winner:

| board | call | promise vs held | Ben's own meaning |
|---|---|---|---|
| `ben1-19f975caec3` | option 2♠ | 6+♠ vs 5 | avg 5.09, P(6+)=0.09 |
| `ben1-19f97f890db` | option 2♦ | 6+♦ vs 5 | avg 5.08, P(6+)=0.08 |
| `ben1-19f98ba4d6a` | option 2♥ | 6+♥ vs 5 | avg 5.02, P(6+)=0.02 |
| `ben1-19f98ba4e0e` | option 3♥ | 6+♥ vs 5 | avg 5.00, P(6+)=0.00 |
| `ben1-19f9e871af2` | option 3♠ | 7+♠ vs 6 | avg 6.12, P(7+)=0.12 |
| `ben1-19f9f5f46d1` | option 3♠ | 6+♠ vs 5 | avg 5.05, P(6+)=0.05 |
| `ben1-19f947b976b` | option 4♥ | 6+♥ vs 5 | avg 5.01, P(6+)=0.01 |
| `ben1-01357351` | option 4♠ | 6+♠ vs 5 | avg 5.00, P(6+)=0.00 |
| `ben1-19f93c011b7` | option 4♣ | 6+♠ vs 5 | avg 5.00, P(6+)=0.00 |
| `ben1-19f966c08eb` | option 4♣ | 7+♣ vs 6 | avg 5.31, P(7+)=0.06 |
| `ben1-01354bde`, `ben1-19f9a48f9cf`, `ben1-19f9f5f46a8` | stem 2♦ | 6+♦ vs 5 | avg 5.01–5.11 |
| `ben1-19f97f88fa3`, `ben1-19f97f890e8`, `ben1-19f98ba4d7a`, `ben1-19f98ba4e81`, `ben1-19f99e5b987`, `ben1-19f99e5ba4e`, `ben1-19f9f0ed819`, `ben1-19f9f0ed8dc` | stem 2♥ | 6+♥ vs 5 | avg 5.00–5.11 |
| `ben1-19f9910da08` | stem 2♠ | 6+♠ vs 5 | avg 5.09, P(6+)=0.09 |
| `ben1-19f9dd8aa0f` | stem 3♠ | 7+♠ vs 6 | avg 6.11, P(7+)=0.11 |
| `ben1-19f9609a4f9` | stem 3♥ | 7+♥ vs 6 | avg 6.13, P(7+)=0.13 |

The pattern is not per-board noise: **Ben opens five-card weak twos and
six-card three-level preempts, and GIB's cards for those calls say six and
seven.** So the gate also costs yield in future runs — every board whose
stem or menu contains a weak two or a three-level preempt bid a card light
is now rejected. Boards where the bidder actually holds the promised length
are untouched (`ben1-19f95435b8f`, the same five-card-meaning 2♦ held with
six, stays).

Cost: nothing. The check rides the sampling pass `band_violations` already
pays for each stem call and option, so it adds no sampling — but, like the
rest of the band check, it cannot judge a stored record without the engine
(`scripts/audit_pool.py --band`).

## R6 — a partscore stop with game values stated

### The defect

`ben1-19f9c2b962c` — `P-1NT-P-2♣-P-2♦-P-3♣-P`, hero opener with
♠A4 ♥T83 ♦AJ54 ♣AK52 (16 HCP) — offered 3NT, 5♣ and 4♣:

| option | gloss | where the rollout leads | graded |
|---|---|---|---|
| 3NT | 15-17 | 3NT S 97% | **best** |
| 5♣ | 3-5♣, 15-17 | 5♣N 97% | −0.8 IMPs |
| 4♣ | 3-5♣, 15-17 | **4♣N 57%**, 5♣N 33%, 6♣N 10% | −1.9 IMPs |

The owner's report: *"it says 57% of hands end in 4♣ if you bid 4♣, but that
is a forcing bid."* It is: partner's own gloss for 3♣ is `5+ !C; 13+ total
points` opposite a 1NT opening glossed `15-17 HCP` — 28 stated points, in an
auction the opponents never entered. A partnership with game values does not
park in a four-club partscore, so the 290 layouts on which partner passed
4♣ out come from a partner nobody plays with, and the 1.9 IMPs charged
against 4♣ measure that pass rather than the merit of the call.

`forcing_contract_violations` (R3) is the adjacent rule and cannot see this:
it needs GIB to have written "forcing" on the candidate's own card, and
GIB's card for 4♣ here is a bare `3-5 !C; 15-17 HCP`. The force lives in the
arithmetic of the two cards, not in a clause.

### The rule

Fatal when all four hold:

* the auction is **uncontested** (no opponent call but Pass — once they bid,
  a partscore is a real resting place and a force may have been discharged,
  the same reasoning `forcing_pass_violations` applies to GIB's clause);
* **hero's stated minimum + partner's stated minimum ≥ `GAME_PTS` (26)**,
  each seat's own minimum being the highest its glosses state (cumulative by
  max, not by sum: a later call re-describes the same hand);
* the option's **own call** is left in as the final contract by the hero's
  side on ≥ `FORCING_CONTRACT_SHARE` (5%) of layouts;
* and that contract is a **partscore**.

Fatal for the board, not the option, for the reason above: the same partner
model produced every other row.

### Why 26, and what it kills

26 is the classic "26 points and the partnership belongs in game" line, in
the same total-points currency GIB's cards state. The pool brackets it. Of
the 472 published boards, 419 option rows show the hero's side playing the
option's own call as a partscore; sorted by the two hands' stated minimum,
the uncontested ones stop at 24 and then jump:

| stated minimum | uncontested rows | what they are |
|---|---|---|
| 28 | 1 | `ben1-19f9c2b962c` (the report) |
| 26 | 1 | `ben1-19f93c0121d` — 3♦ *17-20 pts* opposite 3♥ *9-12*, 4♦ left in on 99% of layouts **and graded best** |
| 24 | 10 | 1NT-2♥-2♠-2NT invitations, where opener's 3♠ **is** a place to play |
| ≤ 23 | rest | ordinary partscore auctions |

So the gate flags **2 boards (0.4% of the pool)** and leaves the
invitational class alone. Cost: nothing — it counts contracts the confirm
rollout already produced, and `record_violations` carries it, so stored
records are judged with no engine and no network.

## Operations

```bash
python3 scripts/audit_pool.py --firestore                  # R6 (cheap)
python3 scripts/audit_pool.py --firestore --band --remove   # R7 too (needs Ben)
python3 scripts/audit_pool.py --firestore --band --ids ben1-...  # a shortlist
```

R6 rides `record_violations`, so `trainer pool audit --firestore` (and the
daily data-hygiene job, report-only) flags it next to the gloss-vs-hand,
forcing-pass and invitation offenders. R7 needs `BEN_HOME` and the Ben venv
(`scripts/setup_ben.sh`); the boards worth paying the band pass for are
exactly those whose cheap check already shows a one-card shortfall. Stored
attempts on purged boards are left alone; `regrade_attempts` counts them as
`missing_problem`.

The 2026-07-26 purge ran both and took the published pool from 472 bidding
boards to 444: **2 boards on R6**, **24 on R7**, and **2 more that the same
band shortlist convicted under the pre-existing `band_vs_card` rule** —
`ben1-01357327` (3♦ glossed `5+ !D` on a band of avg 4.3, P5+ 0.33) and
`ben1-19f947b975d` (5♦, avg 4.1, P5+ 0.27) — boards forged before the band
check reached options, which no cheap audit can see.

## What these gates do not do

They do not decide whether Ben's *bid* is good bridge — only whether the
board's own displayed system contains it. A five-card weak two in third seat
is a real (if aggressive) treatment; the reason the board goes is that
everything printed next to it — GIB's card, the 2/1 label — says six, and
the evidence was gathered from a partner who reads it as five. Making Ben's
own measured meanings the source of the glosses instead of GIB's cards would
be a different product; it is not attempted here.

Nor does R6 audit partscore stops in general. It fires only where the two
hands' own glosses have already committed the partnership to game in an
uncontested auction; a stop reached after an opponent's bid, or on stated
values below 26, is left to the trainee's judgment.
