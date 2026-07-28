# Pool audit, 2026-07-28 — 2030 live Firestore problems

Every problem in the live `problems` collection (692 bidding, 1338 lead) was
streamed and checked twice:

1. **`scripts/audit_pool.py`** (the shipped gates, cheap level) — **0 of 2030
   violate them.** Six point-mass suspects were reported, none confirmed
   without `--rollout`.
2. **`scripts/audit_pool_second.py`** (new, this audit) — the checks the
   shipped gates do not run. **327 of 2030 boards carry at least one finding.**

The four families below follow the request: hand description vs the hand,
offered options, scoring, and general bridge soundness. Codes match the
script's output, so `--code D6` re-lists any group.

---

## 1. The displayed hand description vs the actual 13 cards

### D6 — the `pts` band is never vetted (36 boards, 47 calls) — root cause

`explain_check.card_vs_hand` — the only gloss-vs-cards check in the codebase —
reads `hcp`, `minlen`, `maxlen` and explicit holding assertions. It never reads
`pts`. But `explain.terse_meaning` renders the **`pts` band whenever GIB gave no
HCP band**, so every "16-18 pts" a trainee reads has been vetted by nothing.
1772 of 2030 boards display at least one such band (6873 calls in total).

Worst offenders (displayed text → actual hand):

| board | displayed | hand |
|---|---|---|
| `lead1-b8b469b31` | W's 2♠ and pass: "3+♠, 6-11 pts" | `T654.932.T95.983` — **0 HCP**, no shape at all |
| `lead1i-19f92cab633` | W's pass: "6+♣, **0-0 pts**" | `2.KJ5.752.AKJ876` — 12 HCP |
| `lead1i-19fa5191961` | N's pass: "6+♦, **0-0 pts**" | `6.QT73.AKT42.Q82` — 11 HCP |
| `lead1i-19f9e0fd886` | S's 3♠: "Overcall, 6+♠, **19+ pts**", then 4♠ "19+ pts" | `KQJ7642.6.KJ2.42` — 10 HCP (a weak jump overcall) |
| `ben1-19f94d0039d` | E's 2♦: "Natural, not forcing, 6+♦, 7-9 pts" | `Q.KT9.AKJ853.K73` — 16 HCP |
| `lead1i-b8b42c8ff` | N's 4♦ "16+ pts", pass "16-16 pts" | `KJ6.T97532..QJ93` — 7 HCP |
| `lead1-19fa34d5e7b` | S's 4NT "Blackwood, 26+ pts", 5♠ "Signoff, 26+ pts" | `A5.AJT85.KT8.AQT` — 18 HCP |
| `ben1-19fa09d3291` | E's 3♠: "Invitational to 4S, 6+♠, **9-9 pts**" | `987642.73.QT983.` — **2 HCP** |
| `lead1i-19f9b552c30` | W's 4NT "Blackwood (S), 25+ pts", 6♠ "25+ pts" | `QT.K4.AKT7.AQT53` — 18 HCP |
| `lead1-19f9f1b5850` | W's 3♣: "Competitive raise, 4+♣, 7-9 pts" | `T94.97.KQ.AKJT98` — 13 HCP |
| `lead1-19fa59675d8` | S's **5♦**: "**5+♠**, 20-21 pts" | `QJT86.6.AJ63.KQ7` — 13 HCP |

22 of the 47 are on a Pass, 25 on a real bid. A recurring shape is a pass shown
"No suitable call, 0-8 pts" over a hand with 11-13 HCP: `lead1-b8b3ef832`,
`lead1-b8b35d0c1`, `lead1-b8b4512f9`, `lead1-b8b5f04c4`, `lead1i-19f9f34e82d`,
`lead1i-19fa217f1ed`, `lead1i-b8b5fc6e5`, `lead1-19fa0ae770f`,
`lead1-19f9ec68dbd`, `lead1i-19f9b552cef`.

### D4/D3 — a suit-length claim the hand contradicts, on a Pass (5 boards)

Pass is exempt from the shipped gate by design ("its gloss only restates what
the seat's own bids established"). That premise does not hold — GIB's pass card
carries claims the seat's bids never made, and the page prints them:

- **`lead1-19f9f6c19be`** — N's final pass reads *"No suitable call, 5♠, 25+"*.
  N holds `AK8` — **three** spades. Cause: GIB's `5- !S` (five **or fewer**)
  was parsed into `minlen S=5`, so a maximum is rendered as a promise.
- **`lead1-19fa45cd957`** — W's final pass reads *"No suitable call, 6+♠, 6+♥,
  16-18 pts"*. W holds `AKQT84.9.A52.KJ2` — a **singleton** heart. Cause: GIB's
  "twice rebiddable !H" parsed into `minlen H=6`.
- **`lead1i-19fa5191916`** — N's final pass reads *"No suitable call, 4+♠,
  11-21"*. N holds `42` — two spades.
- `lead1-19f9ca502b3` (2+♦ claimed, E void in diamonds) and
  `lead1-19f9ec68c20` (2+♠ claimed, S void in spades) carry the false claim in
  the record but do not render it, so the page is not wrong — the data is.

### E11 — option text states an HCP range the hero's hand misses (50 boards)

The shipped gate classifies this **soft** on purpose: "the stretch/underbid
dilemma is exactly what this trainer trades in". That reasoning covers a point
or two. It does not cover these:

| board | option text offered | hero holds | off by |
|---|---|---|---|
| `ben1-19f94d0042d` | "2NT — Invitational to 3NT game, **24-24**" | `4.94.AQ874.K9843` — 9 HCP | 15 |
| `ben1-19fa337da08` | "**21-21**" | `J932.AT6..AQJT93` — 12 HCP | 9 |
| `ben1-19fa4e91379` | "3+♦, 19-21" | `942..AK987.A9432` — 11 HCP | 8 |
| `ben1-19fa14511b8` | "10-11" | `6.63.973.QJT9853` — 3 HCP | 7 |
| `ben1-19f9c2b971f` | "21-21" | `J9.A93.2.AKQ9854` — 14 HCP | 7 |
| `ben1-19f93fc8377` | "21-21" | `3.7542.AK62.AK74` — 14 HCP | 7 |

Distribution of the gap: 27 boards off by 3, 14 by 4, 3 by 5, 4 by 6, 3 by 7,
and one each by 8, 9 and 15. Everything from ~5 up is not a shading.

### D8 — degenerate one-point bands on the page (104 boards, 157 calls)

`9-9`, `11-11`, `17-17`, `24-24`, `0-0` — GIB never had that precision, and the
hand often misses even the single point. Cosmetic next to D6, same root.

---

## 2. The offered bidding options

**Clean:** across all 692 bidding boards, every offered call is legal at its
decision point (sufficiency, X only over an opponent's undoubled bid, XX only
over their X), no board offers a duplicate call, none offers fewer than two,
`verdict.table` and `candidates` always agree, `verdict.accepted` is always in
the menu, and no board's whole menu converges on one contract (which would make
the choice cosmetic). No insufficient bid and no illegal double is published.

### D7 — a call in the displayed auction with **no explanation at all** (23 boards)

`gib_raw` is blank, so the trainee reads a bare call. Several are the call that
decides the contract they are about to defend:

`lead1-19f9f6c19be` [6] S **4♠** · `lead1i-b8b1fb050` [3] E **4♥** ·
`ben1-19f99977700` [3] S 3♦ · `lead1-19f9485e514` [3] E XX ·
`lead1-19f9485e69b` [7] S 4♠ · `lead1-19fa1faea9b` [2] N 4♠ ·
`lead1-19fa0ae79e8` [3] E 3♣ · `lead1-19fa34d6163` [3] W 3♣ ·
`lead1-19fa4a3be99` [3] S 3♣ · `lead1i-19fa217f27c` [3] S 3♣ ·
`lead1i-19f9cbc6609` [3] S 3♣ · `lead1i-b8b2d6c7f` [2] W 4♠ ·
`lead1-b8b69b279` [2] N 4♣ · and ten boards whose blank call is the **3NT they
are leading against**: `lead1-b8b49a66c`, `lead1-b8b49a824`, `lead1-b8b6089c8`,
`lead1i-013b3429`, `lead1i-19f92dec2cb`, `lead1i-19f952516b4`,
`lead1i-19fa11e37e8`, `lead1i-b8b45d636`, `lead1i-b8b5cba1b`,
`lead1i-b8b5fc74a`, `lead1i-b8b6a75f2`.

---

## 3. Scoring

**Clean:** probability triples sum to 1 on every row, no negative CI, no
`best_share` outside [0,1], contract counts never exceed the sample count, lead
`exp_score` always sits inside the range its contract can actually produce given
vulnerability, `set_prob` never contradicts `avg_def_tricks` against the tricks
needed to beat the contract, `rank_mp`/`rank_imp` always order the metric each
claims to order, and two leads with identical evidence are always graded
identically (0 violations of that last one).

Two real defects:

### E9/G4 — `ben1-19f9609a4b3`: the graded answer is not the one the evidence favours

`verdict.py` picks `accepted` as the **EV argmax**, so every other row's
`ev_imp_vs_top` (measured against the winner) must be ≤ 0. Here:

| option | `ev_imp_vs_top` | `vs` | `best_share` | policy |
|---|---|---|---|---|
| 3♥ (**accepted**) | **+0.42** | P | 0.312 | 0.323 |
| P | −0.42 | 3♥ | 0.023 | 0.558 |
| **X** | **+0.10** | **3♥** | **0.609** | 0.078 |

X measures **+0.10 IMPs better than the accepted 3♥** and is best on 61% of
layouts against 3♥'s 31%. A trainee who picks X — the call the published
evidence favours — is marked wrong, and the page contradicts itself: *"3♥ — …
Best: +0.4 IMPs vs Pass"* sits next to *"Dbl — … +0.1 IMPs vs the top choice"*.
X carries the lowest policy of the three (0.078), which fits a menu-completion
option added and evaluated after the winner was chosen and never re-argmaxed.

### F12 — `lead1i-19fa11e39af`: two different accepted sets

`verdict.accepted = ["CT","C5","C4","C3"]` but
`verdict.by_mode.IMP.accepted = ["C5","C4","C3"]`, and the board's
`training.target_mode` **is** IMP. ♣T is accepted at the top level and rejected
by the mode that grades the board — so it is graded right or wrong depending
which field the client happens to read.

---

## 4. Bridge soundness

**Clean:** deal integrity on all 2030 (52 distinct cards, 13 per seat, 40 HCP),
every auction legal in sequence, the hero always on turn at the bidding decision
point, every lead auction complete, and contract / declarer / leader always
derivable from the auction and matching the stored fields.

### D3 (H1) — `lead1i-19fa5b321a7`: an auction no table produces

Dealer E passes, S passes, W opens 1NT, and the hero **N — holding
`5.AK75.Q6.AQ9432`, 15 HCP with a six-card club suit — passes**. The auction
dies in 1NT and N is asked to find the opening lead. Nobody passes that hand
over a 1NT opening. Marked `difficulty_level: 5`.

### H1 — `ben1-19f9e871a64`: S sells out to 1NT redoubled with 16 HCP

1NT–X–P–P–XX–P, and S — who made the penalty double holding
`KQ652.93.AQ7.KQ9`, 16 HCP — passes the redouble. (E's XX is also glossed
"17-17" over a 16-HCP hand.) Defensible only if you want to defend 1NTXX with
16 opposite 5; the opponents then ran to 2♣.

### H3 — game reached in an **uncontested** auction on 16-21 combined HCP (8 boards)

Sacrifices and doubled contracts are excluded, so these are the side's own
free-standing overbids:

| board | contract | combined HCP |
|---|---|---|
| `lead1i-b8b1fb050` | 4♥W | 16 — E raised a 3♥ preempt to game with 7 HCP and 3 trumps, on a **blank gloss** |
| `lead1i-b8b39a1c1` | 5♦W | 18 |
| `lead1-19fa59676d7` | 4♥N | 19 |
| `lead1-b8b469ae7` | 4♥S | 19 |
| `lead1i-19f9ee30287` | 4♥W | 19 |
| `lead1i-19fa37cc1c0` | 4♥N | 19 |
| `lead1i-b8b551891` | 3NTE | 20, **vulnerable** — W invited with 3♣ on 5 HCP |
| `lead1-b8b5bf70a` | 3NTE | 21 — E bid 3♣ then 3NT holding a **void in partner's opened major** |

### I1/I2 — lead boards with no decision left to teach (30 + 105 boards)

- **I1 (30):** no lead defeats the contract on more than 2% of layouts.
- **I2 (105):** the best lead averages 2.5+ tricks short of what is needed.

For matchpoints this is defensible (overtrick defence still has a best card),
which is why it is listed last rather than called broken. But the thin end is
very thin — see the worst board below.

### The single worst board: `lead1-19f9f6c19be` (four independent defects)

N `AK8.AK.KJ83.AK93` (25 HCP) opens 2♣; S `JT9764.Q85.2.T42` (**3 HCP**) bids
2♦ waiting; N rebids 3NT; **S bids 4♠ on a completely blank gloss** and declares
it, with the 25-count as dummy. Then:

1. the 4♠ that sets the contract carries no explanation at all (D7);
2. N's pass is displayed as promising "5♠" while N holds three (D4);
3. no lead beats it on more than 1% of layouts (I1);
4. the best lead averages 1.58 defensive tricks with a 0.38-trick spread over
   the worst, on only 103 samples (I2).

### Duplicates

Three deals are published twice, once as an MP board and once as the IMP
variant of the same deal and auction — `lead1-013b345f`/`lead1i-013b345f`,
`…347f`, `…37dc`. Presumably intentional (two training modes), but a trainee
can be dealt the identical layout twice.

---

## Suggested new gates

Counts are boards disqualified out of the 2030 live problems, measured with
`scripts/audit_pool_second.py` (the code in brackets re-lists a group via
`--code`). "Tighten" means the check already exists but exempts this case.

| # | Gate | Rule | Disqualified | Sample |
|---|---|---|---|---|
| 1 | `G-PTS` [D6] | New. Check the `pts` band the page displays against the hand: HCP + distribution (shortness **and** length, the most generous count any system uses), slack ±2. Fires when the stated floor exceeds that maximum or the stated ceiling is below plain HCP. | **36** (of 1772 boards that display a `pts` band at all) | `lead1-b8b469b31` |
| 2 | `G-PASS-CLAIM` [D3/D4] | Tighten. Stop exempting Pass in `hand_violations`/`auction_violations` — run `card_vs_hand` on pass cards too. Fixes the two parser faults it exposes: `N- !S` (a *maximum*) landing in `minlen`, and "twice rebiddable !H" landing in `minlen 6`. | **5** (3 of them rendered on the page) | `lead1-19f9f6c19be` |
| 3 | `G-BLANK` [D7] | New. Reject any non-pass call in a displayed auction whose `gib_raw` is empty or whitespace. The gates currently accept `" "` silently. | **23** | `lead1-b8b49a66c` |
| 4 | `G-EVMAX` [E9] | New. `verdict.accepted` must be the EV argmax: every other `table` row's `ev_imp_vs_top` must be ≤ 0. Catches a menu-completion option evaluated after the winner was picked and never re-argmaxed. | **1** | `ben1-19f9609a4b3` |
| 5 | `G-MODE` [F12] | New. `verdict.accepted` must equal `verdict.by_mode[training.target_mode].accepted`. | **1** | `lead1i-19fa11e39af` |
| 6 | `G-SHADE` [E11] | Tighten. Cap the "soft" option-HCP shade. Soft is right at ±2; past ±5 it is a different claim, not a stretch a player weighs. | **11** at ±5 · 25 at ±4 · 50 at ±3 | `ben1-19f94d0042d` |
| 7 | `G-DEGEN` [D8] | New (cosmetic). Do not render a one-point HCP band (`9-9`, `24-24`, `0-0`) as a range — GIB never had that precision, and the hand often misses even the single point. | **104** (157 calls) | `ben1-19f9353043a` |
| 8 | `G-SELLOUT` [H1] | New. A seat that never bids in the whole auction, holds ≥ 15 HCP, and let the auction die at the one level. Threshold matters: at 14 it fires 13 times and most are flat 14-counts correctly passing an opponent's 1NT. | **1** at 15 HCP · 13 at 14 | `lead1i-19fa5b321a7` |
| 9 | `G-OVERBID` [H3] | New. Game or 3NT reached in an **uncontested**, undoubled auction on ≤ 21 combined HCP (3NT) or ≤ 19 (4-level+). Contested and doubled auctions excluded — those are sacrifices. | **8** | `lead1-b8b5bf70a` |
| 10 | `G-COLD-LEAD` [I1] | New. No offered lead defeats the contract on more than 2% of layouts (or every lead defeats it on ≥ 98%). | **30** | `lead1-19f93557236` |
| 11 | `G-HOPELESS` [I2] | New. The best lead averages 2.5+ tricks short of what is needed to beat the contract. Defensible for matchpoints (overtrick defence still ranks), so this is the one gate worth landing as a warning rather than a rejection. | **105** (119 with #10) | `lead1-19fa02bce20` |
| 12 | `G-DUP` | New. Same `full_deal` + same auction published more than once. | **3 pairs** | `lead1-013b345f` / `lead1i-013b345f` |

### The samples in full

1. **`G-PTS` — `lead1-b8b469b31`**: W's 2♠ and closing pass both display
   *"3+♠, 6-11 pts"*. W holds `T654.932.T95.983` — **0 HCP and no distribution
   at all**. Runners-up: `lead1i-19f92cab633` (pass shown "6+♣, **0-0 pts**",
   hand 12 HCP), `ben1-19fa09d3291` (3♠ shown "Invitational to 4S, **9-9 pts**",
   hand `987642.73.QT983.` = **2 HCP**), `lead1i-19f9e0fd886` (a weak jump
   overcall shown "Overcall, 6+♠, **19+ pts**", hand 10 HCP).
2. **`G-PASS-CLAIM` — `lead1-19f9f6c19be`**: N's final pass reads *"No suitable
   call, **5♠**, 25+"*; N holds `AK8`, three spades. GIB said `5- !S` — five *or
   fewer* — and the parser stored it as `minlen S=5`, so a maximum is printed as
   a promise. Same shape in `lead1-19fa45cd957` ("6+♥" over a singleton, from
   "twice rebiddable !H") and `lead1i-19fa5191916` ("4+♠" over a doubleton).
3. **`G-BLANK` — `lead1-b8b49a66c`**: the 3NT at index 6 — the contract the
   trainee is about to lead against — carries `gib_raw == " "`, so the auction
   line shows a bare "3NT" with no meaning. Ten more boards are blank on exactly
   that call; `lead1-19f9f6c19be` is blank on the 4♠ a 3-HCP hand bid and
   declared.
4. **`G-EVMAX` — `ben1-19f9609a4b3`**: accepted 3♥ (`ev_imp_vs_top` +0.42 vs
   Pass, `best_share` 0.312), but X is published at **+0.10 IMPs vs 3♥** with
   `best_share` **0.609**. The page prints both *"3♥ — … Best: +0.4 IMPs vs
   Pass"* and *"Dbl — … +0.1 IMPs vs the top choice"*. X has the lowest policy
   of the three (0.078), consistent with a rollout-completed option.
5. **`G-MODE` — `lead1i-19fa11e39af`**: `accepted = ["CT","C5","C4","C3"]`,
   `by_mode.IMP.accepted = ["C5","C4","C3"]`, `target_mode = "IMP"`. ♣T is right
   or wrong depending which field the client reads.
6. **`G-SHADE` — `ben1-19f94d0042d`**: offers *"2NT — Invitational to 3NT game,
   **24-24**"* to a hero holding `4.94.AQ874.K9843` — 9 HCP, off by 15. Then
   `ben1-19fa337da08` "21-21" to 12, `ben1-19fa4e91379` "19-21" to 11,
   `ben1-19fa14511b8` "10-11" to 3.
7. **`G-DEGEN` — `ben1-19f9353043a`**: N's 2NT glossed `9-9 HCP` over a 7-HCP
   hand. Across the pool: 44× `9-9`, 32× `11-11`, 17× `17-17`, 13× `15-15`.
8. **`G-SELLOUT` — `lead1i-19fa5b321a7`**: P–P–1NT–P–P–P, and the hero N holds
   `5.AK75.Q6.AQ9432` — 15 HCP, six clubs, a singleton — and passed. The board
   then asks N for the opening lead against 1NT. Marked `difficulty_level: 5`.
9. **`G-OVERBID` — `lead1-b8b5bf70a`**: 3NT by E on 21 combined HCP, E having
   bid 3♣ ("Invite, 6+♣, 9-11") and then 3NT while **void in partner's opened
   major**. Also `lead1i-b8b1fb050` (4♥ on 16, E raising a preempt to game with
   7 HCP and three trumps — on a blank gloss) and `lead1i-b8b551891` (3NT on 20,
   vulnerable, partner having invited on 5 HCP).
10. **`G-COLD-LEAD` — `lead1-19f93557236`**: 4♠N survives every offered lead on
    99% of layouts. There is a best card, but no defence to find.
11. **`G-HOPELESS` — `lead1-19fa02bce20`**: the best lead averages **1.07**
    defensive tricks against 3NTN, which needs 5 to beat.
12. **`G-DUP` — `lead1-013b345f` / `lead1i-013b345f`**: identical deal and
    auction, published once as an MP board and once as its IMP variant.

Gates 1-5 are the ones that catch outright wrong content: 66 boards, no
judgement calls. Gates 6-9 are 124 more that need a threshold decision.
Gates 10-12 are content quality, not correctness.

## What was actually done (2026-07-28)

Ten of the twelve gates landed in #101. **`G-BLANK` and `G-HOPELESS` were left
out at the owner's direction** — a blank gloss on a displayed call and a lead
board whose defence is far from beating the contract both still publish.

`G-DEGEN` landed as a **renderer fix, not a rejection**: `explain._band` and its
JS twin in `webapp.py` now print a one-point band as the single number it is.
Those 104 boards were not wrong, only displayed with a precision GIB never had,
and a display bug is not a reason to destroy content. Records forged before the
fix keep their stored `text`; new ones render correctly, and
`scripts/reexplain_pool.py` can backfill the rest from their stored cards
whenever that is wanted.

Then, against live Firestore (which the forge had grown to 2165 by then):

| step | result |
|---|---|
| full pool backup before any deletion | 2165 records dumped to JSONL |
| boards failing the ten new gates | **134** |
| pre-existing duplicate boards (R14) | **3** — the `lead1-` (MP) twin dropped, the `lead1i-` kept, since its `by_mode` serves both MP and IMP so no training content is lost |
| **problems deleted** | **137** of 2165 (6.3%) — 46 bidding, 91 lead |
| pool after cleanup | **2028** (691 bidding, 1337 lead) |
| orphaned attempts deleted | **21** across 4 users, all pointing at boards this cleanup removed — no pre-existing orphans |
| attempts after cleanup | 274, 0 orphaned |

Deletion used index-FIRST ordering for the whole batch (one index write, then
the documents), so a crash mid-way could only leave unlisted orphan documents —
never index rows pointing at missing documents, which is what the client would
surface as "problem not found".

Post-cleanup verification: 2028 documents, 2028 index entries, 0 index rows
without a document, 0 documents missing from the index, 0 duplicate rows, 0
orphaned attempts. `scripts/audit_pool.py --firestore` now reports **0 of 2028**.

Backups (session-local, not committed): `pool_fresh.jsonl` (all 2165 records
including every deleted board), `orphans_backup.json` (all 21 attempt docs
verbatim).

### Why the orphaned attempts could not stay

An attempt stores a grading SNAPSHOT — answer, correct, score, acceptedSet — as
of when it was answered, and the daily `regrade-attempts` job repairs a stale
one from the problem it points at. With the problem gone there is nothing to
repair it from, so the row is frozen at a grade produced by a board that was
withdrawn precisely because that grade was wrong. Two of the 21 were answers to
`ben1-19f9609a4b3` and `lead1i-b8b1fb050`-class boards where the stored
`correct` flag is the defect itself.

## Suggested order of repair

1. **`ben1-19f9609a4b3`** and **`lead1i-19fa11e39af`** — wrong grading, two
   boards, remove or recompute.
2. **Vet the `pts` band.** Teach `card_vs_hand` to check `pts` against
   HCP + distribution, or stop displaying a band nothing verifies. Fixes 36
   boards and closes the gap for the 1772 that display one.
3. **Stop exempting Pass** in `hand_violations`/`auction_violations`, and fix
   the two parser faults the pass glosses exposed: `N- !S` (a maximum) becoming
   `minlen`, and "twice rebiddable !H" becoming `minlen 6`.
4. **Reject a blank gloss** on any non-pass call in a displayed auction (23
   boards) — the current gates accept `gib_raw == " "` silently.
5. **Cap the option-text HCP shade.** Soft is right at ±2; at ±5 and up it is a
   different claim. Would remove ~9 boards.
6. `lead1i-19fa5b321a7`, `ben1-19f9e871a64` and the 8 H3 boards are single-board
   removals.
