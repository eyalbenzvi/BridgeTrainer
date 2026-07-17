# Expert review — selectivity: from 34% to ~10% acceptance (2026-07-17)

Owner directive: 34% of scanned boards accepted is too loose; target
~10%, achieved "in a clever way bridge-wise." Owner's idea classes:
(1) all options bad; (2) 2+ options favorable with very similar odds.
One bridge expert, given the full evaluation data of the first
20-problem batch (verdict tables, contract distributions, push rates).

## Principal findings

1. **q = 1 − p_push — the probability the choice changes the result on
   a given layout — is the single most revealing statistic.** Expert
   keeps ranged q = 0.59–1.00; cuts 0.20–0.47. "Both roads reach the
   same 3NT" is invisible to the EV-gap statistic and glaring in q.
2. **Triage of the 20**: keep 7 (#3 damage-control advance, #4 weak-two
   raise ladder, #6 balance-over-2S trap, #8 vulnerable 2S over
   Stayman, #9 don't-sell-out trap, #12 pure thin-game 4H, #16 sandwich
   1S) — 7/59 boards ≈ 12%, on target. Cuts: route questions (both
   options → same contract), partscore nothingness, engine-temperature
   splits on busts, agreement forks (Drury space, negative-X range),
   point-count coin flips.
3. **Owner class (b) corrected**: "similar odds" must mean *similar
   means with divergent outcomes* (gap ≈ 0 AND low push) — otherwise it
   selects the dullest boards in the batch.
4. **Two unnamed classes added**: **trap verdicts** (policy argmax loses
   by ≥ 0.8 IMPs — the field's reflex is measurably wrong; the highest-
   value teaching content, capped 3/batch against model-bias flooding)
   and **tail-riding** (game/slam/double boundaries moving, as a score
   component).

## The mechanism (implemented)

- **Stage 0 — content exclusions** (scanner/conventions): Ogust/feature
  2NT over weak twos joins the asking-call table (closes the #14 leak);
  Drury-space forks (passed-hand major raise with 2C live); negative-X
  range forks (X + 2-level new suit both live over an overcall); bust
  artifacts (≤4 HCP, no 5-card suit, Pass live).
- **Stage 1 — consequence floor**: q ≥ 0.40 or reject `inconsequential`.
- **Stage 2 — interest score** (0–120, accept ≥ THETA=55):
  `30·min(q/.8,1) + 25·min(p4/.35,1) + 15·min(tv/.6,1) + 10·(flip≥.25)
  + 8·span + 20·trap + 12·damage` where p4 = P(|swing|≥4 IMPs) with
  doubled samples at half weight (raw-DD flattery), tv = contract-
  distribution divergence, flip = declaring-side flips, span = modal
  contract class differs, damage = every candidate's mean EV < 0.
- **Split-half stability**: interest recomputed on disjoint sample
  halves; drift > 15 with a sub-θ half ⇒ `unstable_interest` (the
  "tightening selects DD noise" guard).
- **Left alone, deliberately**: GAP_MAX 2.5 (shrinking it kills the trap
  class and harvests noise), CI/N floors, and all scanner thresholds
  (selectivity belongs post-rollout where consequences are visible).

## Calibration (this session)

Re-judge the 20 published boards (expert regression: keeps ⊇ {3,9,12,16},
cuts ⊇ {1,2,5,7,14,18,19}) + 100 fresh boards; set/confirm θ at the
percentile giving 10±2%; verify accepted-set mean CI and doubled_share
do not rise (noise-harvest check). Economics: boards-per-publish rises
~3.4× → ~3 min of compute per published problem.
