# Authoring guide for finalization documents

The standing rules for every proposer / verifier / explanation-writer
subagent in the ensemble. The hard shell (V1/V3/V5/V6/V7) enforces what
it can mechanically; this guide covers the judgment the shell cannot
check. Feed the relevant sections into every ensemble prompt.

## Pipeline order and blindness (anti-peeking)

1. **Spot selection** may use the full deal and room results.
2. **Meanings + options + projections authoring is BLIND**: the author
   receives the hero hand, the auction stem, dealer/vul, and the two
   rooms' CALLS at the divergence — never the concealed hands, never the
   room final contracts or results. Trees written around a known layout
   are memorized answers; the shell's dead-branch telemetry
   (quality.branch_mass) and V5 catch some of this, not all of it.
3. **The DD judge runs.**
4. **Explanations are written AFTER the verdict**, with the verdict
   numbers in hand, and must pass `finalize.prose.lint_explanation`.

## Reading the source auction (V5 will check you)

- Every concealed seat's ACTUAL hand must be possible under the meanings
  you write. If the real 2D overcaller can't hold your "natural 5-7
  diamonds", the call was conventional (Landy, Multi-Landy, transfers,
  cue) — model the convention or reject the spot.
- Suspect any direct 2-level suit overcall of a strong 1NT labeled
  natural: most tournament pairs play conventional defenses. The
  harvest helper `validate.suspect_natural_calls` flags bids the real
  hand is short in; treat its warnings as near-certainties.
- Silence is a call. All-pass seats automatically inherit preempt and
  overcall denials (validate/inference.py); add sharper ones yourself
  (up-the-line response inferences, failure to raise, failure to act in
  third seat) and waive the defaults only explicitly
  (`no_default_denials: true`) with a reason in the note.

## The convention card (assume standard modern 2/1)

Five-card majors, 15-17 NT, 2/1 game force, negative doubles through 3S,
support doubles/redoubles through 2 of responder's suit, standard
balancing (~3-point discount), sound preempts at unfavorable.

Mainstream expert actions are NOT deviations. Do not flag:
- **Support doubles** — after 1m-(P)-1X-(overcall), opener's double
  shows exactly three of responder's suit. It is systemic, not takeout.
- Shape-perfect competitive doubles of limped-in partscores at single-
  digit HCP — the card's opening floors do not apply in dead auctions.
- Jump advances of takeout doubles valued on support points (a fifth
  trump, an ace, shortness) rather than raw HCP.

Deviation kinds:
- `card_violation` — an objective breach a partner would misread:
  wrong promised length (2S on five "showing six", X with the wrong
  shape), strength a full zone off.
- `judgment` — style and evaluation notes (suit quality, upgraded
  counts, thin stoppers). Rendered ℹ, not ⚠.
When an option deviates, its projection tree must price the downside
(partner playing you for the card meaning; the doubled branch V6/T2
requires).

## Options

Enumerate before you prune: every natural new-suit bid, notrump call,
raise, double, and pass that is legal on the card at this level. Then
keep the 2-5 a strong panel would actually vote for. Never hand-pick a
binary when a textbook third call exists (the b1 review found the
mainstream 3C simply missing). If only one non-deviating option
survives, the spot is probably a quiz, not a dilemma — the V7 gate will
bounce it unless the margin is genuinely close.

## Projections

- One policy, applied uniformly: the same concealed hand must act with
  the same vigor in every option's tree (V6/T3 enforces HCP-floor
  symmetry mechanically; you own the rest).
- Model the whole table: reopening actions behind a pass, runouts,
  raises, sane doubles — and HERO's own forced future calls (accepting
  invites!). A tree in which opponents always sell out is an answer
  key, not a model.
- Concealed hands need strength to bid at the 2+ level (V6/T1) and
  conversions to penalties should not be certainties.
- Categories: label every doc `partscore | game | slam | sacrifice |
  opening-style | raise-choice | other` — batch quotas depend on it.

## Explanations (written post-verdict)

- Name the verdict and make the prose agree with it: the winner gets
  the argument, each loser gets its trap explained, toss-ups are called
  toss-ups. Never crown a winner the verdict didn't.
- Calibrate language to the margin: under ~0.5 IMPs is a coin flip;
  above ~4 IMPs (or p_gain ≥ 85%) is a trap, not "a close decision".
- Every checkable fact must be right: shapes, HCP counts, fit sizes,
  who sits over whom. The linter blocks what it can parse; write as if
  it parsed everything.
- Do not restate the ⚠/ℹ flag lines or the at-the-table line — they are
  appended mechanically. When an accepted option is flagged, reconcile
  it in prose: what licenses the lie, and what partner will assume.
- Teach one transferable principle per problem, in a strong club
  player's language.
