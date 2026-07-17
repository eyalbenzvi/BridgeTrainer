# Expert panel — R2-1 / R2-3 / R2-5 plans v2, round 2 (verification)

Date: 2026-07-16. Same three reviewer roles as round 1, verifying that
the v2 plans (commit 37ddea0) resolve every round-1 required change.

| Plan | Round-1 changes | Verified | Verdict |
|---|---|---|---|
| R2-1 Empirical mining | 9 | 9/9 RESOLVED | **APPROVED WITH NOTES** |
| R2-3 Field oracle | 8 | 8/8 RESOLVED | **APPROVED WITH NOTES** |
| R2-5 Problem compiler | 8 | 8/8 RESOLVED | **APPROVED WITH NOTES** |

No reviewer requested another revision round; all notes were judged
"P0-addressable specifications, not design flaws." All notes were
nevertheless patched into the plans immediately after verification:

## R2-1 notes → patches

- **N1 invite boundary**: quarantine applies to invitational *candidates*
  inside kept raise contexts (3♠-vs-4♠ spots), not only to invite
  contexts; labeled invite-in-competition spot added to the P0
  calibration set.
- **N2 censored continuations**: doubled terminal nodes are never pruned
  from trees; the penalty exclusion is an empirical *context* filter
  (share of layouts terminating doubled > threshold ⇒ context dropped
  and reported).
- **N3 anti-lottery knob**: "near-uniform" defined (no call clairvoyantly
  best on ≥40% of layouts), pre-registered in P0.
- **N4 knob count**: corrected to eight, with the three
  non-stake-normalized ones named.
- (from R2-3's review) publish-priority hook added to R2-1's pipeline:
  oracle score prioritizes; unscored spots publish neutrally.

## R2-3 notes → patches

- **N1 interface**: hook now exists on the R2-1 side (above).
- **N2 third branch**: no-score path (support-gate fail / unminable
  context) publishes neutrally as `oracle: none`; absence of score never
  reads as low score.
- **N3 clustering practicalities**: pair convention signatures pooled
  across contexts (alert-informed); `pn|` name normalization; P0 census
  reports pairs-per-context and boards-per-pair.
- **N4 ordering**: separator runs on the unfiltered corpus; the oracle
  trains on the filtered sub-corpus.

## R2-5 notes → patches

- **Proxy defined**: two-stage screen — card-rule lookup, then generic
  short continuation trees per off-menu call family (P0 deliverable,
  calibrated on the five trusted recipes).
- **Re-route fallback**: reject when no target family exists; rejection
  reports distinguish "re-routable" from "no home in catalogue."
- **Sequencing + genre bias**: R2-1 P0 completes before the R2-5 gate
  freezes (fallback: existing ≤3-IMP + INV7 machinery); genres R2-1
  excludes for directional DD bias are gate-quarantined (CI-only + flag)
  and their families scheduled after correction-table validation — the
  b1 #12 discount applies to the gate, not just explanations.
