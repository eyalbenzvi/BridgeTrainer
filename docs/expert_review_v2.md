# Expert review v2 — bidding logic, candidate generation, problem selection

Reviewer role: 2/1 GF expert. Targets: `bridge_trainer/bot/bidder.py`,
`bridge_trainer/generate/random_problem.py` (`_plausible_candidates`,
`_turn_interest`). Line numbers refer to current files.

Shared helper used throughout (add to `HandView`):

```
STOP(s) := shcp[s] >= 4  or  (shcp[s] >= 3 and length[s] >= 2)
```

(A = 4 alone stops; Kx / QJx = 3 with length >= 2 stop; stiff K does not.)

Enemy suits visible to a rule are `view.opening_denom_them` (if they opened)
and `view.denom` when `view.last_bidder_side == "them"` and `denom != "NT"`.
Define `ENEMY_STOPPED := STOP(s) for every such s`. (TableView does not keep
their full suit history; this approximation is the implementable version.)

One recommended TableView addition (used by 1.16, 2.D3, 3): 
`passes_since_last_bid: int` — number of consecutive passes immediately
preceding this turn (walker already has `self.calls`; trivial to compute).
Every rule below that uses it also states its fallback without it.

---

## 1. Bidding-logic corrections (bug list)

1.1 **`resp_1nt` (L291)** — the r01352772 bug. Fires over RHO's suit
overcall with no stopper and no shape check (W held `T.AQT7.QJT85.J73`, stiff
spade, and bid 1NT over 1C-(1S)). Corrected condition:

```
6 <= hcp <= 10 and cheapest_level("NT") == 1
and (last_bidder_side != "them" or denom == "" or STOP(denom))
and length[S] <= 5 and length[H] <= 5 and length[D] <= 6 and length[C] <= 6
```

The length caps also fix the unsound signature (see 1.13). The hand that
used to fall into this rule over an overcall now takes the negative double
(1.2) or, failing that, `resp_pass_competition`.

1.2 **NEW rule: negative double** (yes, add it — it is one rule plus one
rebid branch, and it is the only sane action for hands like r01352772-W).
Insert in `_respond_to_partner` after `resp_two_over_one` (L278) and before
the minor-raise / 3NT / 1NT block, guarded by interference:

```
neg_x fires iff:
  last_bidder_side == "them" and denom in (S,H,D,C) and level <= 2
  and not doubled
  and length[denom] <= 3
  and M := [m for m in (S,H) if m != popen and m != denom] is non-empty
  and all(length[m] >= 4 for m in M)
  and hcp >= (6 if level == 1 else 8)
```

Emit token `"X"`, rule `neg_double`, with a SPLIT signature so partner_mid
stays honest: if `hcp <= 11` sig = `((6,11), mins={m:4 for m in M},
maxs={denom:3})`; else sig = `((12,40), mins={m:4 for m in M},
maxs={denom:3})`. No walker change needed: `record()` (walker L131-135)
already marks a first-call X of an enemy bid as `doubled_takeout`, so opener
sees `partner_doubled_takeout=True`.

Opener's rebid over the negative double — one new branch at the top of
`_my_rebid` (before "Partner bid a new suit", L327):

```
if partner_doubled_takeout and partner_last_bid == "" :
    their = denom (last_bidder_side is "them"; RHO may have raised)
    for m in (S,H) ordered by my length desc, m != their, m != our_first_denom:
        if length[m] >= 4:
            lvl = cheapest_level(m)
            if lvl <= 2 and outbids(lvl, m):
                return f"{lvl}{m}", rule "rebid_negx_major", sig ((10,17), {m:4})
            if lvl == 3 and hcp >= 15 and outbids(3, m):
                return f"3{m}",   rule "rebid_negx_major_j", sig ((14,21), {m:4})
    # else fall through: rebid_six_card / NT rebids (now stopper-checked) / rebid_pass
```

1.3 **`resp_3nt` (L288)** — 3NT with no stopper over an overcall. Add
`and ENEMY_STOPPED`.

1.4 **`resp_rebid_3nt` (L371) and `resp_rebid_invite` 2NT (L374)** — same
disease at responder's second turn (e.g. 1C-P-1S-(2H)-...-3NT with xx in
hearts). Add `and ENEMY_STOPPED` to both.

1.5 **Opener NT rebids (L344-354)** — `rebid_2nt_1819`, `rebid_1nt_1214`,
`rebid_3nt`, `rebid_nt_strong` all lack stopper checks over interference.
Add `and ENEMY_STOPPED` to all four. Additionally:
- `rebid_1nt_1214` (L346) has NO hcp condition at all — only the signature
  claims (11,14). Add `and 11 <= hcp <= 14` (a balanced 15-17 opened 1NT,
  but make the rule sound on its own).
- `rebid_nt_strong` (L351) also fires unbalanced (e.g. 6-5 shapes). Add
  `and min(length.values()) >= 1 and length[longest()] <= 5` (semi-balanced
  guard) besides `ENEMY_STOPPED`.

1.6 **`overcall_1nt` (L399)** — `shcp[their] >= 3` accepts a stiff king as
a "stopper". Replace the quality test with `STOP(their)`.

1.7 **`penalty_double` (L497)** — far too loose: 10 hcp + QJxx of trumps
doubles their freely-bid game (this rule is the in-auction cousin of the
candidate-generation bug the user flagged). Replace with two cases:

```
common: last_bidder_side == "them" and denom != "" and not doubled and level >= 2
case A (they bid unopposed — our_first_denom == ""):
    level >= game_level(denom)            # 4 for S/H, 5 for D/C, 3 for NT
    and length[denom] >= 5 and shcp[denom] >= 5 and hcp >= 13
    sig ((13,40), {denom:5}, quality={denom:5})
case B (competitive — our_first_denom != ""):
    level >= 2 and length[denom] >= 4 and shcp[denom] >= 4
    and hcp >= 11 and hcp + partner_mid() >= 20
    sig ((11,40), {denom:4}, quality={denom:4})
```

1.8 **`power_double` (L421)** — 16+ hcp doubles with ANY shape up to the
3-level, including 5 cards in their suit (should trap-pass) and no support
for the unbid suits. Correct: `hcp >= 17 and length[their] <= 3 and
view.level <= 3` (X-then-bid shows 17/18+). Signature `((17,40),
maxs={their:3})`.

1.9 **`takeout_double` (L394)** — flat 12 doubles a 3-level preempt.
Scale with level: `hcp >= 12 + 2*(view.level - 1)` (12 / 14 / 16 at the
1/2/3 level). Signature hcp min likewise.

1.10 **`advance_x_game` (L468) and `advance_x_jump` (L471)** — UNSOUND
SIGNATURES: both emit `{best: 4}` but never test `length[best]`. A 3-3-3-4
hand with 12 hcp jumps to 4M on a 3-card suit. Add `and length[best] >= 4`
to both; a 12-count without a 4-card suit falls to `advance_x_min`
(whose `{best:3}` signature is satisfied).

1.11 **`resp_new_suit_1` (L267)** — iterates `("S","H")`: responds 1S with
4-4 majors and 1S holding 5 hearts / 4 spades. Correct order: iterate majors
sorted by `(length desc, H before S on ties)` (longest first, up-the-line on
ties).

1.12 **`_direct_seat` overcall loop (L405)** — `for s in SUITS_DESC`
overcalls the highest-RANKING 5-card suit, not the longest (with 5 spades
and 6 hearts it bids spades). Iterate suits sorted by `(length desc,
denom_rank desc)`.

1.13 **`resp_1nt` signature unsound (L292)** — `maxs={D:6, C:6}` but a 6-10
hand with a 7-card minor (no 2/1 available) reaches the rule. Fixed by the
length caps added in 1.1.

1.14 **`weak_two` other-major guard (L201)** — `length["S" if s != "S" else
"H"] < 4` checks only ONE other major; a weak 2D with 4 hearts is allowed.
Replace with `all(length[m] < 4 for m in ("S","H") if m != s)`.

1.15 **`compete_law` fit counting (L487-489)** — assumes partner holds 2
cards in `our_first_denom` even when that suit is PARTNER's (double
counting) or partner never supported. Correct: `assumed = 2 if
(s == our_first_denom and s in my_bids) else 0; total = length[s] +
max(partner_suit_min.get(s,0), assumed)`.

1.16 **Missing balancing relaxation** (improvement, needs
`passes_since_last_bid`): in `_direct_seat`, when `passes_since_last_bid ==
2`, reduce the hcp floors of `takeout_double` and the suit overcalls by 3
(signatures likewise). Without the new field, skip — do not fake it.

1.17 **Rule-of-20 off-by-one (L194)** — `hcp == 10 and rule_of_20` never
lets an 11-count use shape (11 already opens; fine) but a 10-count with
5-4 and 20 total opens while an identical 10-count 5-5 (21) also opens —
OK; the real nit is `hcp >= 11` opens ALL 11-counts including 4-3-3-3.
Change the sound-opening line to `hcp >= 12 or (hcp in (10,11) and
rule_of_20)`.

---

## 2. Candidate-generation rules (replace `_plausible_candidates` entirely)

### 2.1 Mechanism: slack-mode rule enumeration

Refactor `SimpleBidder` so every rule's numeric thresholds are evaluated
through a `Slack` parameter, and add
`bidder.enumerate(hand, view, slack) -> list[BotCall]` that collects EVERY
rule whose (relaxed) condition holds, in priority order, instead of
first-match. Candidates are then rules that fire under slack, filtered by
the legitimacy floors below. No more ad-hoc shape tests in
`random_problem.py`.

Slack values (applied to rule families marked "slacked"):

| dimension        | slack | applies to |
|------------------|-------|------------|
| hcp lower bounds | -2    | slacked families |
| hcp upper bounds | +2    | slacked families |
| support_points   | -2/+2 | slacked families |
| shcp / quality   | -1    | slacked families |
| suit-length mins | -1, only where the strict min is >= 6 | weak twos, preempts, `rebid_six_card`, `resp_1nt_major_game` |

Structural lengths (3-card raises, 4-card suits, 5-card overcalls) get NO
slack — a 4-card 1-level overcall or a 2-card raise is not a legitimate
candidate.

Slacked families: openings, all `_respond_to_partner` rules, `_my_rebid`,
`_responder_rebid`, suit overcalls + `overcall_1nt`, `_advance_overcall`,
`_advance_double` bids, `compete_law` / `compete_game`.

STRICT families (no slack ever): every double (1.7, 1.8, 1.9, neg X 1.2),
`sacrifice`, `_hard_cap`, `resp_preemptive_game`.

### 2.2 Legitimacy floors (applied AFTER enumeration, all must pass)

An **X candidate** is offered iff at least one of D1-D4 holds STRICTLY
(never from a bare hcp test):

- **D1** penalty X of their unopposed contract (`our_first_denom == ""` and
  `partner_min_hcp == 0`): `level >= game_level(denom)` and
  `length[denom] >= 5 and shcp[denom] >= 5 and hcp >= 13`. (Denom NT: never
  — there is no D-floor for doubling an unopposed NT partscore or game.)
- **D2** competitive penalty X (`our_first_denom != ""`): `level >= 2 and
  length[denom] >= 4 and shcp[denom] >= 4 and hcp >= 11 and
  hcp + partner_mid() >= 20`.
- **D3** takeout / balancing X of their suit partscore (`denom in SHDC`,
  `level <= 3`, my side silent): `length[denom] <= 2 and
  all(length[s] >= 3 for s in unbid) and hcp >= 12 + 2*(level-1)`;
  in the balancing chair (`passes_since_last_bid == 2`) the hcp floor is
  `9 + 2*(level-1)`. Without the new field, only the direct-seat floor.
- **D4** negative double per rule 1.2, strict.

A **suit-bid candidate** must come from a slack-fired rule AND satisfy:

- level 4 bid: `length[suit] >= 5` or known fit
  `length[suit] + partner_suit_min.get(suit,0) >= 8`;
- level 5 bid: known fit `>= 9` or `length[suit] >= 7`; additionally a
  5-level SACRIFICE-flavoured candidate (hcp <= 7 hands) only at favorable
  (`not vul_us and vul_them`). This encodes the r01352774 principle: the
  only conceivable alternative to defending 4S is 5H on the 6-card suit,
  and it needs either the self-sufficient suit (7+) or a known fit — a
  2=6=3=2 9-count opposite a silent partner has neither, so no candidate;
- no candidate at the 6-level or higher, ever (bot's own call excepted).

An **NT-bid candidate** requires `ENEMY_STOPPED` (strict, no slack on the
stopper).

**Pass as a candidate** (never padding — this is a legitimacy test):
when `chosen != "P"`, include "P" iff
(a) `last_bidder_side == "them"` (live competitive decision: declining to
act is always coherent), or
(b) the chosen rule fired within 1 of one of its own strict lower bounds
(`hcp <= min+1` or `support_points <= min+1` or a suit length exactly at
its min). Otherwise "P" is NOT offered (partner opens, you hold 13: pass is
not a candidate). When `chosen == "P"`, "P" is trivially in the list but
counts for nothing (section 3).

### 2.3 Assembly, ordering, cap

```
cands = [chosen]
+ every distinct enumerate() token passing 2.2, in bidder priority order
+ "P" last, if admitted by the Pass test
cap: 4 candidates total (chosen + first 3 others)
```

---

## 3. Problem-selection criteria (replace `_turn_interest`)

Signature: `_turn_interest(view, hand, cands_meta, turn_index) -> int` where
`cands_meta` carries, per candidate, its provenance (chosen / slack-fired
rule / D-floor / pass-test) — the generator already has all of it at the
call site.

### 3.1 Qualification gate (hard)

Let `A` = candidates other than the chosen call, excluding "P".
Let `pass_ok` = "P" admitted by the 2.2 Pass test.

- `chosen != "P"`: qualifies iff `len(A) >= 1 or pass_ok` (i.e. two real
  options exist without counting a padding pass).
- `chosen == "P"`: qualifies iff `len(A) >= 1` (a legitimate non-pass
  alternative nearly fires within slack). The pass itself never counts.

### 3.2 Exclusions (hard, checked after the gate)

- **E1 (the "randomly double their game" trap — exact condition):** reject
  the turn if `chosen == "P"` and `A == {"X"}` and `our_first_denom == ""`
  and `partner_min_hcp == 0` and `level >= game_level(denom)`. (D1 already
  makes such an X rare; E1 guarantees a lone trump-stack X of an unopposed
  game is never the whole problem. All five flagged deals die under the
  D-floors alone; E1 is the belt-and-braces.)
- **E2:** reject if any candidate would be the 4th consecutive pass ending
  a passed-out board with `level == 0` (non-problems).

### 3.3 Score

```
S  = 2                                  (gate met)
S += 2 if (len(A) + (1 if pass_ok and chosen != "P" else 0)) >= 2
                                        (3+ real options)
S += 2 if our_first_denom != "" and
          (they_opened or last_bidder_side == "them")
                                        (both sides bidding — competitive)
S += 1 if level >= 3                    (pressure)
S += 1 if level >= 4 and max known fit >= 8
                                        (LAW / 5-level decision)
S += 1 if chosen rule fired within 1 unit (hcp, sp, or exact min length)
          of one of its strict bounds   (hero at a threshold edge)
S += 1 if passes_since_last_bid == 2 and level > 0
                                        (balancing chair; omit w/o field)
```

**Threshold: `S >= 5` qualifies** (previous code used `>= 4` on a softer
score). Consequences to be aware of when tuning: uncontested two-way
decisions (e.g. limit raise vs simple raise at the edge) score 3 and are
NOT selected; they need a third real option to qualify. Competitive
two-option turns (2+2+1) qualify. If the pool runs too dry, drop to
`S >= 4` — that re-admits uncontested edge decisions with a threshold
bonus, which is the correct next tier. Turn choice: max S, ties to the
later `turn_index`. The downstream EV filters (`MAX_DIFFICULTY_GAP`,
`MAX_PUSH_RATE`, ESS) stay as-is.

---

## 4. Regression expectations for the five deals (unit tests)

`game_level`: S/H=4, D/C=5, NT=3. "Rejected" = no turn passes 3.1-3.3, so
`generate_problem` returns `(None, "no decision point")`.

**r01352774** (S/EW, hero E, `1S P 3S P 4S P P ?`, E = `T5.KJ7432.Q72.K5`)
(a) Stem unchanged — E's first turn is over 3S where no rule fires even
with slack (jump-overcall family is capped at the 2-level). (b) The flagged
turn no longer qualifies: X fails D1 (`length[S]=2 < 5`); 5H fails the
level-5 floor (no known fit, `length[H]=6 < 7`, and vul_us). Candidates =
`["P"]`, gate fails. N's raise turn (sp exactly 10: 3S vs 2S) scores
2+1(edge) = 3 < 5. **Deal rejected.**
Tests: `bot(E over 4S) == "P"`; candidate set at that turn == `{"P"}`;
`generate_problem(seed) → reject`.

**r01352773** (E/EW, hero N, `1C P 1H P 1NT P P ?`, N = `K984.Q872.J.AK54`)
(a) Stem unchanged (E's 1C/1NT rebid and W's 1H survive all section-1
fixes; E's 1NT rebid faced no interference). (b) X fails every floor: not
D1/D3 (denom is NT — no floor doubles an unopposed NT contract), not D2
(`our_first_denom == ""`), not D4 (partner didn't open). Candidates =
`["P"]`. N's earlier direct-seat turn: takeout X of 1C fails
(`length[C]=4 > 2`). **Deal rejected.**
Tests: candidate set at final turn == `{"P"}`; reject.

**r01352770** (E/EW, hero E, `P P P 1H P 1S P 4S ?`, E = `J7.KT65.K7.QJ972`)
(a) Stem unchanged (E still passes as dealer: 10 hcp, rule-of-20 total 19).
(b) X fails D1 (`length[S]=2`, `shcp[S]=1`); no 5-level suit candidate
(no fit, no 7-card suit). Candidates = `["P"]`; also caught by E1
(`chosen=P`, lone-X impossible anyway). **Deal rejected.**
Tests: `bot(E dealer) == "P"`; candidate set at final turn == `{"P"}`; reject.

**r01352775** (S/Both, hero E, `1C P 1S P 1NT P P ?`, E = `J832.K84.Q5.K954`)
(a) Stem unchanged. (b) Denom NT unopposed — no D-floor exists; no suit
candidate (no 5-card suit even with slack rules; balancing needs shape).
Candidates = `["P"]`. **Deal rejected.**
Tests: candidate set == `{"P"}`; reject.

**r01352772** (E/NS, hero W, `1C 1S 1NT 3S P P ?`, W = `T.AQT7.QJT85.J73`)
(a) **Stem CHANGES at W's first call.** Over 1C-(1S), rule 1.1 blocks 1NT
(`STOP(S)` false: shcp[S]=0) and rule 1.2 fires: `length[S]=1 <= 3`,
M={H}, `length[H]=4`, `hcp=8 >= 6` → **W's correct call is X (negative
double)**, signature `((6,11), {H:4}, maxs={S:3})`.
Projected continuation (pin loosely — assert only the bracketed calls):
1C-(1S)-**[X]**-(2S: N advance_simple_raise, sp 7)-**[3C]** (E: 12 hcp,
only 4 hearts and `cheapest_level(H)=3 < 15-hcp gate`, so `rebid_six_card`
on AK8542)-(3S: S compete_law, 9-card fit)-then W's turn over 3S.
(b) The ORIGINAL turn never arises. W's new turn over 3S plausibly
qualifies: chosen P (compete_game combined ≈ 8 + 8.5 < 24), slack admits
**4C** (combined within 2 of the 24 floor; known club fit 3 + 6 = 9 >= 8
satisfies the level-4 floor); X fails D2 (`length[S]=1 < 4`). Candidates =
`["P", "4C"]`, S = 2 + 2(competitive) + 1(level 3) = 5 → **qualifies**.
Tests: `bot(W over 1C-(1S)) == "X"` with rule `neg_double` (NOT `resp_1nt`);
`bot(E rebid over neg X + 2S) == "3C"`; at W's turn over 3S the candidate
set == `{"P","4C"}` (no "X") and the turn qualifies with S == 5.
