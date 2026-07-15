# Expert panel review of batch b1 (all 11 live problems)

Three independent critical reviewers, each covering all 11 problems:

- **Panelist** — Master Solvers' Club-style moderator: are the options the real
  options, would a top panel split, does the accepted answer match expert
  judgment?
- **Auditor** — systems/simulation methodologist: do the meanings match what
  the auction showed, are the continuation trees realistic, is the DD margin
  trustworthy?
- **Editor** — bridge author/teacher: is the explanation text factually right,
  coherent with the verdict, and does it teach?

## Per-problem verdicts

| id | Panelist | Auditor | Editor | Headline defect |
|---|---|---|---|---|
| e50000-12 | FLAWED | SHAKY | NEEDS EDIT | X flagged as deviation though it's a mainstream competitive double; X tree can't advance 2S; text never separates X from 2H |
| e50004-24 | SOUND | SHAKY | NEEDS EDIT | Same physical deal as e50006-24 in one batch; 3C never doubled though E may hold 15 with a club stack; "nine-card fit" and behind-dummy claims wrong |
| e50004-30 | FLAWED | SHAKY | MISLEADING | Missing the textbook 3C option; slam-reach asymmetry baked into the trees; fog=true ignored; text argues for the rejected 3H; "5-2-2-3" is wrong (hand is 5=2=2=4) |
| e50005-26 | SOUND | INVALID | MISLEADING | Opponent aggression thresholds differ per option (no floor over 1D, 14+ over 2C, 16+ over 1S) — the asymmetry manufactures 2C's win; hearts-only doubler rebids overfit to the actual deal; "balanced six" on a 4=1=4=4 hand |
| e50006-18 | FLAWED | INVALID | NEEDS EDIT | **Fictional auction**: the real 2D overcall was conventional (overcaller holds 6 spades, 2 diamonds); simulated a natural diamond overcall that never existed; 7.4-IMP margin is an artifact |
| e50006-24 | SOUND | TRUSTWORTHY | NEEDS EDIT | The model problem of the batch — but the text crowns X while the verdict is an X/2H toss-up |
| e50012-13 | BROKEN | INVALID | NEEDS EDIT | **Fictional auction**: real 2C was Landy (overcaller 5-5 majors, 2 clubs); also a non-dilemma (P wins 11.9 IMPs, p_gain 0.998, zero pushes — tree-vs-tree, not bid-vs-bid) |
| e50018-10 | SOUND | TRUSTWORTHY | MISLEADING | Bridge content solid; but the text sells the losing 2S and never reports the answer ("the double-dummy verdict will show...") |
| e50022-32 | BROKEN | INVALID | NEEDS EDIT | **Fictional auction**: real 2D showed spades (overcaller 6 spades, 3 diamonds); remaining decision is pass-or-illegal-double — not a problem |
| e50023-18 | FLAWED | SHAKY | PUBLISHABLE | X here is a *support double* on a standard card (hero has 3 diamonds — card-perfect), mis-modeled as takeout and wrongly flagged; P punished by fictional sellouts to 1S |
| e50023-20 | SOUND | SHAKY | NEEDS EDIT | 1H tree forbids hero from accepting partner's invite, so "1H misses game" is baked in, not discovered; "king behind the opener" is geometrically backwards |

**Score: no problem passed all three lenses clean.** Best of batch: e50006-24,
e50018-10. Recommended for immediate pull: e50006-18, e50012-13, e50022-32
(all three simulate auctions that never happened — the "natural" 2m overcalls
of 1NT were conventional major-showing bids, provable from the source hands
and room declarer seats).

## Consolidated improvement backlog

### A. Source truth & meanings (highest priority — three problems are fictional)

1. **Ground-truth admissibility validator.** After meanings are authored, test
   the ACTUAL concealed hands from the source deal against the bands. If the
   real deal has ~zero likelihood under the sampling model, the meanings
   mis-read the auction — quarantine. This one check catches all three
   fictional problems (real overcaller held 2-3 cards in the "shown" suit).
2. **Convention-inference pass on vugraph sources.** Treat room final
   contracts as evidence (2D overcall → 2S played by overcaller's side =
   transfer/Landy footprint). Never trust a "natural" label the deal
   contradicts.
3. **Negative-inference generator for silence.** Every pass in the stem must
   emit constraints, not just an HCP cap: failure to overcall denies a decent
   5+ suit at strength; failure to preempt denies weak 6-7 card suits (the
   e50012-13 "silent" hand holds SEVEN diamonds); failure to open light in
   third seat; 1S response up-the-line denies 4 hearts. Author overrides
   explicitly, never by omission.
4. **Richer meanings schema.** Per-suit quality bands (suit_hcp / top-honor
   count) so "decent suit" is enforceable, and conditional bands
   (strength-dependent shape denials). The projection language already reads
   `*_suit_hcp`; the sampler should too.
5. **Hero-stem consistency check.** Validate hero's own stem calls against
   hero's hand with the card engine and auto-annotate stem lies (e50004-30's
   2S rebid on five) so they don't silently corrupt partner's meanings.

### B. Projection trees

6. **Cross-option consistency linter.** The same concealed-hand trigger must
   behave the same across all options (level-adjusted). e50005-26's verdict
   was manufactured by asymmetric aggression thresholds. Shared world events
   (e.g. opponents' game drive) must appear in every option's tree.
7. **Tree-completeness requirements.** (a) No sellout to a cheap contract
   while a concealed band allows a hand that systemically must act; (b) every
   flagged-deviation option and bad-split contract needs a doubled branch;
   (c) advancer of a double gets ALL systemically available strains, not the
   one the actual deal holds; (d) hero's own future decisions (invite
   acceptance!) must be modeled — e50023-20's margin came from forbidding
   hero to accept an invite.
8. **Anti-peeking pipeline order.** The tree author must never see full_deal
   or room results (e50005-26's hearts-only continuations memorize the actual
   hand). Add an overfit detector: if >~75% of sampled probability mass falls
   to `else` while the actual deal threads a specific when-chain, reject.
9. **Strength floors + probabilistic conversions.** Any when-condition
   putting a concealed hand into a new 2+-level call needs an HCP/quality
   floor per level; deterministic penalty machinery (reopening double →
   always converted) must carry probability weights.

### C. Verdict integrity

10. **Verdict sanity gates.** Quarantine when p_gain > 0.95, |ev| > ~5 IMPs on
    a partscore decision, or p_push = 0 across the sample (disjoint trees =
    comparing trees, not bids). e50012-13 trips all three.
11. **Fog forces toss-up.** When raw and corrected disagree (e50004-30), never
    crown a single winner; the accepted set widens and the text must say the
    engines can't separate them.
12. **Penalty-branch DD discount.** Doubled-contract branches inherit
    double-dummy defense inflation. Re-run the comparison with doubled
    branches undoubled; if the winner flips, downgrade to toss-up (or apply a
    configurable trick discount).
13. **Dilemma gate.** Ship only if at least two non-deviating options exist OR
    the top-two margin is under a threshold. "Pass or make an illegal
    negative double" is a quiz item, not a dilemma.

### D. Convention card & options

14. **Machine-readable convention card + two-way deviation audit.** Split
    flags into CARD_VIOLATION (objective shape/strength breach) vs
    JUDGMENT_NOTE (stopper quality, light-but-normal competitive actions),
    rendered differently. Stop branding mainstream expert calls as
    violations: shape-perfect competitive doubles of limped partscores,
    five-trump jump advances on support points, and **support doubles**
    (e50023-18's X shows exactly hero's three-card diamond holding — the
    card-perfect call was flagged as a violation). Also catch missing flags
    (4-card raise of a possibly 3-card minor).
15. **Full option enumeration.** Mechanically generate every natural
    new-suit/NT call legal at the level, then prune by EV and panel
    plausibility — never hand-pick a binary that omits the textbook call
    (3C in e50004-30, 3NT in e50006-18).

### E. Explanations

16. **Verdict-aware generation.** Write (or rewrite) the explanation AFTER the
    DD verdict exists, feeding accepted/toss_up/margins in. Validator: reject
    future-tense references to the simulation ("the verdict will show...").
17. **Winner-assertion ↔ toss_up validator.** toss_up=false → text must name
    the winner and why; toss_up=true → per-option sentiment must be balanced
    (no "textbook balance" vs "moth-eaten suit" between co-accepted options).
18. **Margin-calibrated vocabulary.** Map |ev|/p_gain to language tiers
    (coin flip / clear edge / trap) and lint for tier-inconsistent framing —
    an 11.9-IMP blowout may not be described as "a classic close decision."
19. **Deterministic fact linter.** Check every checkable claim against
    hero_hand + meanings: shape ("5-2-2-3" when the hand is 5=2=2=4),
    "balanced" on a hand with a singleton, fit-size arithmetic, HCP counts.
20. **Table-geometry checker.** Resolve every over/under/behind/in-front-of
    phrase against the seating rotation and declarer; three texts got
    positional claims backwards — the exact inference skill the app teaches.
21. **Per-option coverage.** Every offered option gets a verdict-linked
    reason, especially WHY the losers lose (traced through the projections).
22. **Deviation reconciliation.** When an accepted option is flagged, the text
    must reconcile ("off-card, but wins because...; partner will play you for
    the card meaning") instead of scolding the right answer; strip prose that
    duplicates the auto-appended ⚠ lines.
23. **Prose lint + style guide.** Kill generation artifacts ("consumes your
    side's only plus-showing calls") and settle the register.
24. **Use the room results.** Each record carries what two world-championship
    tables actually did — free credibility, currently unused in the text.

### F. Curation

25. **Deal dedup per batch.** Hash full_deal at ingestion; e50004-24 and
    e50006-24 are the same board served twice. If paired perspectives are
    wanted, sequence and cross-reference them deliberately.
26. **Taxonomy quotas.** Seven of eleven problems are two-level partscore
    battles. Batch quotas per category: constructive game-force auctions,
    slam evaluation, high-level competitive decisions, sacrifices.

## Cross-expert convergence

Independent reviewers converged on the same five faults, which is strong
evidence they are real: (1) the three fictional-auction problems; (2)
projection asymmetries that bake in the verdict instead of discovering it;
(3) the deviation engine flagging mainstream expert actions; (4) explanations
written before the verdict and arguing against it; (5) missing negative
inferences for seats that stayed silent.
