# The forcing-pass gate, and why the HCP band cannot replace it

Calibrated 2026-07-25 with the Ben engine (BEN-21GF, pinned commit
`2b53414`) over the published Firestore pool. Source of the numbers:
`engine/explain_check.py`, `scripts/audit_pool.py`, and the measurement
harness described below.

## The defect

`ben1-19f93c01296` — `1♣-P-1♥-P-2♦-P-3♣-P`, hero opener with
♠A75 ♥Q ♦KQ84 ♣AQ983 (16 HCP) — offered **Pass** and graded it best, 2.8
IMPs ahead of 3NT. GIB glosses partner's 3♣ `3+ !C; 4+ !H; 8+ HCP;
forcing to 3N` and repeats the commitment on the pass's own card, so in
the system the board claims to teach, pass is not a legal choice.

Measured with Ben (`sample_prefix` + `seat_features`, n=128 layouts
sampled from the hero's view after 3♣):

| partner's 3♣ | gloss | Ben's measured meaning |
|---|---|---|
| HCP | 8+ | avg **7.0**, p10 6, p50 7, p90 8 — **73%** of layouts below 8 |
| hearts | 4+ | avg 4.4 |
| clubs | 3+ | avg 3.8 |

Ben rates Pass at 46% of the policy there, i.e. its own model of 3♣ is a
club preference, not a game force — which is exactly why the rollout
liked passing: the partner hands behind the evidence would not have
forced. Re-solving the decision with partner held to what the gloss
promises (4+♥, 3+♣, 8+ HCP; 400 DD layouts, both vul) puts 3NT **+6.8
IMPs** ahead of passing 3♣.

## Why not tighten the HCP band check

`band_violations` already compares GIB's HCP band against Ben's measured
band, with `BAND_HCP_GAP = 2`. It does not fire here (p90 = 8 is not
below the floor 8 − 2 = 6), so the obvious fix is to tighten it. It was
measured instead, over 80 published boards spread across the pool
(249 stem/option rows carrying a GIB HCP band, n ≥ 30 layouts each):

| rule | rows flagged | boards flagged (of 80) | catches `19f93c01296`? |
|---|---|---|---|
| current: `p90 < lo-2` or `p10 > hi+2` | 0 | 0 | no |
| `p90 < lo-1` | 0 | 0 | no |
| `p90 < lo` | 3 | 3 | no |
| `p50 < lo-2` | 0 | 0 | no |
| `p50 < lo-1` | 4 | 4 | no |
| `p50 < lo` | 21 | **20 (25%)** | yes |
| `P(hcp < lo) ≥ 0.7` | 12 | 12 (15%) | yes (0.73) |

The reason no threshold separates: **GIB states its floors in a different
dialect than Ben measures.** Over the same 249 rows the floor sits
systematically above Ben's measured HCP mean — `lo − avg`: p50 **−1.8**,
p90 +0.6, p95 +1.0, max +2.0. GIB's "9 HCP" invitational 2NT is a hand
Ben samples at avg 7.5 (P(below floor) = 1.00) and that board is
perfectly sound. `19f93c01296`'s +0.99 gap sits inside that healthy
tail, not outside it.

So `BAND_HCP_GAP = 2` is **confirmed, not tightened**: it is the smallest
tolerance with no false positives on the published population, and no
HCP-band rule can catch a false *forcing* claim without killing a quarter
of the pool.

## What does separate: the pass under a live force

The discriminating fact is not how strong Ben thinks partner is, but
whether Ben will pass at all. GIB carries the commitment on the pass's
own card for exactly as long as it lives (an opponent's bid over the
forcing call discharges it and the clause disappears), and the forge
offers every call Ben's softmax rates ≥ 2% (`P_OPTION`), so "Pass is
among the candidates while the pass gloss says forcing" is a mechanical
test of the disagreement.

Population check over all 418 published bidding boards (GIB card for
`auction + [P]`, Ben's policy at the decision point from the stored
`policy_trail`):

| boards | pass mass at the decision point |
|---|---|
| 409 not in a live force | (gate never applies) |
| 9 in a live force, Ben agrees | Pass never offered → **< 3%** on all 9 |
| 3 in a live force, Ben disagrees | **13%, 16%, 46%** — all three deleted |

The healthy population and the offenders are separated by an order of
magnitude, with the gate's trigger inside the gap. The three offenders
were `ben1-19f935304d6` (pass of partner's forcing Michaels after RHO's
double), `ben1-19f93c01296` (the reported board — the only one where
pass was the graded winner) and `ben1-19f9609a50c` (pass of partner's
forcing free bid).

## Auditing the published pool

`trainer pool audit --firestore [--band] [--remove]`
(`scripts/audit_pool.py`) re-runs the gates over stored records using the
cards each record carries — boards forged before a gate existed were
never vetted by it. The cheap half needs neither engine nor network; the
band half needs Ben and costs ~3-7 s per board.
