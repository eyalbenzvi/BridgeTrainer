# Expert panel — knife-edge design v1, round 1 (2026-07-16)

Three independent reviewers over `docs/knife_edge_design.md` v1
(commit 2d1fc3f), same personas as the b1 problem review.

| Reviewer | Verdict | Headline |
|---|---|---|
| Panelist (MSC moderator) | **FLAWED** | Lens disagreement is neither sufficient nor necessary for a dilemma; the design's own tombstone example refutes its "ungeneratable" thesis |
| Auditor (methodologist) | **SHAKY** | `D` is not computable from a mono-unit card as specified; two headline guarantees do not hold as written |
| Editor (author/teacher) | **NEEDS EDIT** | The generator mass-produces hands on which the sole verdict authority is least informative; an all-edge diet teaches miscalibration |

## Consolidated blockers (all addressed in v2)

1. **Sufficiency fails — jurisdiction.** Deep lens splits are often automatic
   bids: ♠AKQJT9876 ♥— ♦T32 ♣2 is the deepest possible L-HCP/L-PT split and
   every expert opens 4♠ in tempo; ♠K ♥QJ32 ♦QJ654 ♣QJ2 (12 raw, quack pile)
   splits L-HCP/L-ADJ and every panelist passes — everyone knows which lens
   *governs*. The v1 difficulty dial ("deep split = classic") is
   anti-correlated with difficulty on these classes. → v2: per-archetype
   declared conflicts with lens *jurisdiction*, plus a golden set of known
   non-problems as a P0 rejection gate.
2. **Necessity fails — coverage.** Strain/route problems (3♠-then-cue vs
   4NT; 3NT vs 4M; 5m vs 3NT), positional/honor-location problems (♠KJ94
   over the overcaller), tactical/tempo calls, inference-from-silence: the
   most common real panel genres involve no valuation disagreement and are
   invisible to a strength-lens battery. → v2: direct-predicate archetypes +
   an explicit v1 scope statement.
3. **`D` is not computable as specified.** Card bands are mono-unit; there
   is no operation "evaluate an HCP band under LTC," and the three implicit
   resolutions are respectively unpriced (re-author everything in 8 units),
   convicted by §1.3(c) (invented translation tables), or degenerate
   (collapse back to threshold near-misses). Lenses are also not total —
   abstention semantics were missing. → v2: dual-unit bands authored per
   archetype at induction; `D` defined over the archetype's declared pair
   only; explicit abstention.
4. **The cap-at-4 contradicts "completeness by construction"** — and the
   schema already accepts 5 options. A 5-region straddle silently deletes a
   live call: f50022-21's missing-option failure recurring inside the
   component certified complete. → v2: cap 5, V3-collapse then
   reject-as-too-wide, invariant "options ⊇ straddled set or no publication."
5. **`always_available` reintroduces missing-X-by-omission**; Pass could
   return through the side door or disciplined passes go missing. → v2:
   X/XX computed from auction state + a card doubles-policy section;
   authored lists demoted to overrides; Pass admitted only via a lens or an
   explicit discipline rule.
6. **Mode-G stems quietly need a generation-quality bidding system for the
   other three seats** (per-call conformance ≠ auction plausibility) —
   re-importing the rejected Candidate C. Harvested stems can contain calls
   with no card rule, silently under-constraining layouts. → v2:
   harvest-first; Mode G restricted to shallow stems with per-seat
   dominance/exclusion-completeness lints; unrecognized-call stems rejected
   or queued; rule-resolution hard check before dealing.
7. **The verdict contradiction.** By design the output sits where the true
   margin is a fraction of an IMP: DD-sole-verdict yields either honest
   mass toss-ups (a bank of shrugs) or winners crowned by continuation
   artifacts (the b1 e50005-26 disease). Tag-vs-sim precedence was
   undefined. → v2: "Verdicts on the edge" section — principle-verdict
   framing from the lens-split data, noise-floor gate, tag precedence, and
   an explicit owner question on amending Decision #1 (vs adopting Concept 4
   scoring for the judgment tier).
8. **All-edge diet miscalibrates.** The skill of recognizing a non-problem
   (the owner's own skill in flagging e50006-19) becomes untrainable when
   interior hands are "ungeneratable." → v2: calibration mix, interior
   hands served in an "is this even a problem?" mode.
9. **Tombstone contradiction / style leakage is the default.** The
   L-HCP/L-ADJ split *is* the mathematical signature of style ("do you
   upgrade?"); the curated tag, not the lens math, is the real anti-style
   filter, and a per-archetype tag is too coarse. → v2: honest restatement;
   tag granularity (archetype × lens pair × depth); owner style encoded on
   the card; LLM real-dilemma gate retained per Decision #2(a).
10. **Boundary map is circular** (layouts sampled from the card's own
    meaning bands measure self-consistency, not truth; systematic error
    survives aggregation). → v2: relabeled card self-audit; anchored with
    harvested real table results; version-partitioned.

Also fixed on review: Mode M must re-run V5 and carry `derived` provenance;
scoring form + vulnerability become first-class context inputs; taxonomy
gaps (3NT-vs-4M, rebid problems, slam route, pass-or-pull) and two
style-heavy families retagged; difficulty metric defined (min card-swap
distance) and demoted to hypothesis; explanation contract with the
lens-split table as mandatory writer input + b1 backlog items 16–21 as
validators; the honesty ledger applied throughout ("ungeneratable" →
"excluded to the extent the card and lens code are correct," authoring
"days" → weeks, etc.).

## What the panel endorsed

The inversion thesis itself (define the dilemma, then find hands) as the
correct answer to §1.3(c); the machine-readable card as overdue
infrastructure that pays off regardless of this design's fate; derived
option sets as the right idea; Mode H's alignment with the owner decision
record; the untouched evidence stack; front-loading expert effort into
reviewable, versioned artifacts; and the boundary self-audit as a genuinely
novel product surface (undersold, then over-claimed, in v1).
