# M0 feasibility spike — results (2026-07-15)

Environment: Python 3.11.15, endplay 0.5.12, numpy 2.4.6, Linux container.
Script: `scripts/m0_spike.py` (kept for reference; superseded by the package).

Scenario: South fixed with `K93.752.A854.T62`, auction (1H) - 1S - (3H) - ?,
hidden seats W (1H opener), N (1S overcall), E (3H weak raise). n = 2000,
seed = 42. Contracts DD-solved: spades + hearts tables (3 denominations
excluded). Paired comparison: 3S by N vs 3H by W at favorable vulnerability.

## Measurements

| case  | acceptance rate | generation wall | deals got | DD solve wall |
|-------|-----------------|-----------------|-----------|---------------|
| LOOSE | 0.667%          | 0.39 s          | 2000/2000 | 35.4 s        |
| TIGHT | 0.046%          | 4.60 s          | 1829/2000 (attempt budget hit) | 23.2 s |

Paired IMP comparison (3S vs Pass, + = 3S better), naive unweighted CI:

- LOOSE: EV +3.13 IMPs, 95% CI [+2.99, +3.28], P(gain) 86.5% / P(loss) 10.9% / P(push) 2.6%
- TIGHT: EV +3.64 IMPs, 95% CI [+3.50, +3.78], P(gain) 91.6% / P(loss) 7.3% / P(push) 1.1%

## Gate decision

- Tight-auction generation is **seconds-scale (4.6 s)**, not minutes-scale →
  reserve dealers (HCP-partitioned dealing, shape-vector enumeration) stay
  deferred; the vectorized rejection sampler is the M1 DealSource.
- The tight case did measure acceptance < 0.1% (0.046%), so acceptance rate is
  logged on every generation run (GenerationDiagnostics) to keep driving this
  decision as the problem bank grows, per the spec's build-order item 5.
- **DD solving, not dealing, is the wall-clock bottleneck**: ~17 ms/deal for a
  2-denomination table. To meet the < 30 s definition of done, problems default
  to n ≈ 800 deals (CI half-width ≈ ±0.25 IMPs, comfortably below the 0.5 IMP
  toss-up threshold of INV7).
- DDS `ddTableDeals` holds at most 40 deals per `CalcAllTables` call; the DD
  wrapper must chunk (endplay's own guard of `MAXNOOFTABLES * 5` is wrong for
  this build — indexing fails at 40).
