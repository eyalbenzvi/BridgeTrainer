# A call's note shows what its seat has shown — never a floor of zero

User report on `lead1-b8b58ea96`, 2026-07-30. Source: `engine/explain.py`
(`merge_promises`, `accumulated_cards`, `seat_promises`, `_band`),
`engine/lead_explain.py`, the `terse()`/`accumCards()` mirror in
`app/webapp.py`, `scripts/reexplain_pool.py`, `scripts/audit_pool_second.py`.
Tests: `tests/test_auction_promises.py`.

## The defect

`lead1-b8b58ea96` — North dealer, `1♣-P-1♥-P-2♦-P-4♥-P-P-P`, West on lead
against 4♥S — displayed its auction like this (the note a trainee taps out
of each call):

| # | seat | call | displayed | GIB's gloss for that call |
|---|---|---|---|---|
| 0 | N | 1♣ | Minor suit opening, 3+♣, **11-21** | `3+ !C; 11-21 HCP; 12-22 total points` |
| 2 | S | 1♥ | One over one, 4+♥, **6+ pts** | `4+ !H; 6+ total points` |
| 4 | N | 2♦ | Opener reverse, 5+♣, 4+♦, **0-21** | `… 3- !H; 21- HCP; 18-22 total points` |
| 6 | S | 4♥ | Long suit, 7+♥, **0-10** | `7+ !H; 10- HCP` |
| 8 | N | P | No suitable call, 5+♣, 4+♦, **0-21** | `… 21- HCP; 18-22 total points` |

Two of the calls claimed a point range starting at zero, and each one
contradicted an earlier call by the same seat:

* North's 2♦ was shown as `0-21` two calls after North's own opening was
  shown as `11-21`. North cannot hold zero after opening the bidding.
* South's 4♥ was shown as `0-10` two calls after South's 1♥ promised
  `6+ total points`.

Neither number came from GIB. GIB stated `21- HCP` and `10- HCP` — *ceilings*.
`parse_meaning` stores a ceiling as `(0, hi)` because a card needs two ends,
and the renderer printed both ends as a range, inventing the floor. The pass
at index 8 repeated the same invented floor, and every "limited pass" in the
pool read `0-11`/`0-16 pts` for the same reason.

## The fix, in two parts

**1. Promises accumulate per seat** (`explain.merge_promises`). A hand does
not change during the auction, so a seat's constraints intersect: the highest
floor and the lowest ceiling it has shown are both true of it on every later
call. GIB glosses each call in isolation and cannot do this — it already
repeats *suit* lengths from call to call (North's pass restates `5+ !C;
4+ !D`) but never carries a point floor. Only hand facts accumulate; the
convention name, the raw gloss and the `forcing` flag describe the current
call and are taken from it alone (a force is discharged by an opponent's bid,
and `explain_check.forcing_pass_violations` reads that flag as a live
commitment). Where two glosses cannot both be true — they describe different
systemic hands — the call being explained wins.

An offered option is one more call by the hero, so it is displayed against
what the hero has already shown (`seat_promises` + `merge_promises`); the
`card` stored per call stays GIB's own, since the gates check each gloss
against the hand that made it.

**2. A band with no floor renders as the upper bound it is** (`explain._band`):
`10-`, the mirror of the `10+` form already used at the other end. This is
GIB's own notation and it is the only honest rendering of a one-sided
statement. Where an HCP ceiling has no floor but the seat's earlier bidding
gave one in total points, both show (`10-, 6+ pts`) rather than dropping the
floor the trainee needs.

The same board now reads:

| # | seat | call | displayed |
|---|---|---|---|
| 0 | N | 1♣ | Minor suit opening, 3+♣, 11-21 |
| 1 | E | P | No suitable call, 16- pts |
| 4 | N | 2♦ | Opener reverse, 5+♣, 4+♦, **11-21** |
| 6 | S | 4♥ | Long suit, 7+♥, **10-, 6+ pts** |
| 8 | N | P | No suitable call, 5+♣, 4+♦, **11-21** |

against the actual hands N 17 HCP (5♣, 4♦, 2♥), S 10 HCP with eight hearts,
E 6, W 7 — every displayed claim true.

## Measured on the live pool

Full census, 2026-07-30: every published board read by id from `meta/index`
(3628 document reads). 3605 of the 3613 problems carry an explained auction;
32501 displayed calls in all.

| quantity | boards | calls |
|---|---|---|
| **the reported defect** — a displayed floor of zero that the seat's OWN earlier bidding had already refuted | **1105 (31%)** | 1852 |
| … lead problems (the whole auction is displayed, so a seat's later calls recur) | 793 | |
| … bidding problems | 312 | |
| any displayed band with no floor (mostly honest limited passes by a seat that never bid — now "16-" rather than "0-16") | 3434 (95%) | 16552 (51%) |
| text changed by the accumulation itself (a floor inherited, or a ceiling: "11+" → "11-21") | | 2851 |

Three shapes account for the gap between 31% and 95%: an opening followed by a
second call GIB glosses with a ceiling only (North's 2♦ here), a rebid after a
total-points promise (South's 4♥), and a final pass by a seat that has already
bid, which repeated the same zero.

Safety, measured over a 150-board random sample (seed 7; 1352 calls, 133
offered options) before the census:

| quantity | count |
|---|---|
| NEW contradictions of the actual hand (suit length / HCP / total points, at the audit's slack) | **0** |
| bands newly pinned to a single number by the intersection | **0** |
| option claims the hero's hand breaches, before → after | 8 → 8 (all pre-existing raw-GIB shades, within the option gate's tolerance) |

Tightening a floor can only ever narrow a claim, so the risk worth measuring
was the opposite one — a narrowed band that the bidder's own cards refute.
Over 1352 calls there are none, which is what the intersection guarantees as
long as each individual gloss holds: the gates already check every gloss
against the hand that made it.

## Reach

Both halves are display-only. The web client re-renders every note from the
stored `card` on each page view (`terse()` at three call sites in
`app/webapp.py`), so the already-published pool is fixed by the deploy — no
backfill, no Firestore reads. The Python renderer is fixed in step for
freshly generated boards and for `scripts/reexplain_pool.py`; the `text`
baked into existing records stays stale until that script is next run, which
is why `scripts/audit_pool_second.py` now re-renders the displayed string
from the stored cards instead of auditing the baked field — auditing a stale
string audits a page nobody sees.

`tests/test_terse_parity.py` and `tests/test_auction_promises.py` pin the
JS ↔ Python agreement, including the accumulation over this board's auction.
