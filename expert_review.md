# Expert review: bridge content of the BridgeTrainer problem bank

Reviewer brief: 2/1 Game Force expert standard, IMPs-oriented competitive judgment,
Law-of-Total-Tricks-aware. All YAML below is complete and copy-paste ready against
the observed schemas (`problems/*.yaml` per `bridge_trainer/bank/schema.py`,
rulesets per `bridge_trainer/semantics/engine.py`).

**One engineering note before the bridge.** The corrected projection trees below use
`me_*` features, per-suit honor-point features (`partner_hearts_hcp`,
`partner_spades_hcp`, ...) and compound expressions, per the stated feature spec.
The committed `feature_names()` in `bridge_trainer/projection/tree.py` currently
exposes only `{seat|role}_hcp` and suit *lengths* (no `me_*`, no `*_<suit>_hcp`,
no `our_combined_*`). If that file has not yet been extended to the full spec,
extend `feature_names()`/`deal_features()` first or the loader will reject these
trees with "unknown feature".

`terminal` convention used throughout (matching `domain/contracts.py`:
"author consciously truncated the auction here"): `terminal: true` = I am
deliberately cutting the auction off even though it could in principle continue;
`terminal: false` = the modeled auction genuinely ends at this contract
(pass-out or final doubled contract after all seats' last calls are modeled).

---

## Part A — Critique of `comp_3s_over_3h`

The user's complaint is justified. The candidates are defensible; the *meanings*,
ranges and continuations are not. Point by point:

### A.1 Candidates and the meaning of X

Pass / 3S / X **are** the right three candidates for this hand class — but only if
two things are fixed:

1. **The hand class is too wide at the bottom.** With 5 HCP and 3-3-4-3 junk no
   serious player considers X; the only live question is Pass vs 3S. A hand class
   must be tight enough that *every* sampled hand genuinely faces the stated
   three-way decision. Narrow HCP to **[6, 10]** (and even at 6 X is a stretch the
   tool will correctly punish; at 8-10 with an ace it is a mainstream choice).

2. **X is mislabeled and mis-modeled.** "Responsive double" is a misnomer:
   responsive doubles apply when *partner has doubled* and the opponents raise.
   After partner **overcalls** and RHO raises preemptively, expert-standard 2/1
   treats advancer's double as a **value-showing / competitive card double**:
   roughly 8-11 HCP, typically exactly three-card support (or 4-4 in the unbid
   suits), defensive tolerance, inviting partner to choose between bidding on and
   converting for penalty. It is emphatically *not* penalty, and partner's default
   action is to **pull to 3S**. Sitting is the exception, reserved for a defensive
   maximum with **heart honors sitting over opener** — not "any 12-count with two
   small hearts", which is what the current tree encodes
   (`partner_hearts >= 2 and partner_hcp >= 12 and partner_spades <= 5`). Passing
   the double with Axxxx-xx-KQx-Kxx is anti-expert: two small trumps take zero
   tricks and 3HX making is -730 at this vulnerability. The corrected sit rule
   requires `partner_hearts_hcp >= 3` (a real trump-suit holding) *and* 13+.

   This single modeling error is the main reason the raw verdict (+0.57 IMPs for X)
   looked wrong to a strong player: the sim was collecting phantom +500s and
   eating phantom -730s in layouts where no expert pair ever defends 3HX.

### A.2 Dead code: the 3SNx branch can never fire

In the 3S tree:

```yaml
- when: "east_spades >= 5 and east_hcp >= 7"
  contract: "3SNx"
```

The 3H raise rule constrains East to `S: {core: [0, 3]}` **with no margin band**,
so `east_spades >= 5` has probability zero in the sampled population. The tree
*pretends* to price the penalty risk of 3S and actually never does. (In real life
3S essentially never gets doubled on this auction anyway — the preemptive raiser
is broke and opener has five-plus hearts — so the correct fix is to delete the
branch, not to loosen East's constraint.)

### A.3 The 4H push is modeled on the wrong variables — and ignores vulnerability

`west_hcp >= 17` as the sole trigger for 4H is backwards twice over:

- **They are vulnerable.** A vulnerable push to 4H over our 3S at IMPs risks -200
  against our +140. Vulnerable opponents take that push on **shape and trumps**
  (the 10-card fit, a 7-bagger, splinter-shape), not on a flat 17-count.
- **A 17+ opener with a known big fit bids 4H over 3H anyway** — so gating game on
  our action only via HCP creates a false asymmetry between the Pass tree
  (needed a 10-card fit) and the 3S tree (also fired on `west_hcp >= 18` with six
  hearts). The push conditions should be nearly the same event in both trees:
  offense-driven, rarer because vulnerable.

### A.4 Missing continuations

- **After our Pass, the overcaller never reopens.** An expert who overcalled 1S
  and hears (3H)-P-(P) reopens with a sixth spade and sound values, or doubles
  with real extras and short hearts. Omitting this systematically overtaxes Pass
  (part of the reported 2.7-4.3 IMP loss is partner being gagged).
- **Our side never doubles their 4H.** At favorable, with an ace-rich 9-count and
  three trumps, doubling their vulnerable save/push is routine and is exactly what
  `me_*` features exist for. Omitting it flattens the comparison between the
  bidding candidates precisely on the layouts where they differ most.
- **Partner never raises 3S to 4S** with an offensive maximum, and over our X
  partner's 4S pull (`partner_spades >= 6 and partner_hcp >= 13`) is close but
  should key on offense (six trumps *and* a genuine max), since the double is
  competitive, not forcing.

### A.5 Semantics ranges

- **1H opener 11-21 (margin 10)**: the top is wrong. 22+ opens 2C; balanced 20-21
  opens 2NT. Correct: core **[11, 19]**, margin 10 @ 0.4 (light style) and
  unbalanced 20-21 @ 0.3, with exclusions `balanced_15_17` and a new
  `balanced_20_21`. Also cap hearts at core [5, 7] with an 8-card margin @ 0.2
  (many 8-baggers open 4H).
- **1S overcall 8-16, spades 5-7**: range fine, but there is **no suit-quality
  constraint**, so 7-9 HCP overcalls on Jxxxx sample at full weight. Expert light
  overcalls concentrate honors in the suit. Add exclusion
  `light_overcall_junk_spades` (≤9 HCP with ≤2 HCP in spades → would pass).
- **3H raise 2-8 with 4-5 hearts, 3-card margin**: a preemptive *jump* raise
  promises four trumps — the 3-card margin at 0.2 is not expert-standard at any
  style and must go. They are vulnerable, so the raise is sound-ish: core
  **[3, 8]**, margins 2 @ 0.4 and 9 @ 0.5. Five trumps stays as a real margin
  (0.4): vulnerable, many hands with five trumps still only bid 3H (nonvul they
  blast 4H).

### A.6 On the raw-vs-corrected disagreement

Raw DD saying X wins and corrected saying toss-up is the classic "inside the DD
fog" signature of defending doubled partscores: double-dummy defense against 3HX
is systematically too good. With the corrected sit rule (partner converts far
less often) the X and 3S trees converge on the same 3SN contract on ~85% of
layouts, so the honest expert verdict is: **3S and X are close, X gaining only
when partner has a genuine penalty pass; Pass is a clear loser** — which is what
a strong player expects, and what the corrected files below will show for the
right reasons.

---

## Part B — Corrected files for the existing family

> **Note:** the two ruleset files below are the *complete final versions* — they
> also contain every rule needed by the Part C families that reuse these files
> (rule keys are (context, call), so the additions cannot collide with the
> corrected rules). Copy all three files verbatim.

### B.1 `problems/comp_3s_over_3h.yaml`

```yaml
# Competitive decision: compete to 3S over a preemptive heart raise?
schema_version: 1
id: comp_3s_over_3h
title: "Compete to 3S over the preemptive raise?"
category: competitive_part_scores
description: >
  IMPs, favorable vulnerability. LHO opens 1H, partner overcalls 1S, RHO
  jumps to a preemptive 3H (weak, four trumps). You hold exactly three-card
  support with scattered values. Sell out, bid 3S on the eight-card fit, or
  make a value-showing double (cards, exactly three spades, defensive
  tolerance — NOT penalty; partner pulls to 3S by default)?

dealer: W
vul: EW              # favorable: they are vulnerable, we are not
my_seat: S
my_hand: "K93.752.A854.T62"
auction: ["1H", "1S", "3H"]

# "Next deal": exactly three-card support, 2-3 hearts, 6-10 HCP, so that
# Pass / 3S / X is a genuine three-way decision for EVERY hand in the class
# (below 6 HCP nobody considers X and the problem degenerates).
my_hand_class:
  hcp: [6, 10]
  suits:
    S: [3, 3]
    H: [2, 3]
variants: 24

our_system:
  name: "2/1"
  description: "2/1 GF; sound but flexible overcalls at favorable"
  ruleset: our_2over1.yaml

opps_system:
  name: "Light/aggressive"
  description: "Light openings allowed; 3H is weak (4-card preemptive raise)"
  ruleset: opps_light_preempts.yaml

n_deals: 800

breakdowns:
  - feature: partner_spades
    label: "Partner's spade length"
  - feature: west_hcp
    label: "Opener's HCP"

candidates:
  - call: "P"
    label: "Pass (defend 3H)"
    projection:
      # Opener with a genuine maximum and a 6th heart raises himself to the
      # vulnerable game over the preemptive raise; we double holding an
      # ace-rich hand with trump length (favorable, +200/+500 territory).
      - when: "west_hcp >= 17 and west_hearts >= 6 and me_hcp >= 9 and me_hearts >= 3"
        contract: "4HWx"
        terminal: false
      - when: "west_hcp >= 17 and west_hearts >= 6"
        contract: "4HW"
        terminal: true
      # The overcaller does NOT sell out silently: he reopens 3S with a 6th
      # spade and sound values...
      - when: "partner_spades >= 6 and partner_hcp >= 12"
        contract: "3SN"
        terminal: true
      # ...or reopens with a double holding real extras and at most a
      # doubleton heart; with our 3-card support we bid 3S.
      - when: "partner_hcp >= 16 and partner_hearts <= 2"
        contract: "3SN"
        terminal: true
      # Otherwise it goes pass-pass-pass: the auction is genuinely over.
      - else: {contract: "3HW", terminal: false}

  - call: "3S"
    label: "Bid 3S (eight-card fit, three level)"
    projection:
      # Vulnerable opponents take the push only on offense: the 10-card fit
      # opposite a sound opening, or a 7-card suit. When they do, we double
      # with defence (ace-rich 9+ and trump length); this is where the
      # favorable vulnerability pays.
      - when: "(opps_combined_hearts >= 10 and west_hcp >= 16 or west_hearts >= 7 and west_hcp >= 14) and me_hcp >= 9 and me_hearts >= 3"
        contract: "4HWx"
        terminal: false
      - when: "opps_combined_hearts >= 10 and west_hcp >= 16 or west_hearts >= 7 and west_hcp >= 14"
        contract: "4HW"
        terminal: true
      # Partner raises himself to game only with an offensive maximum and a
      # 6th trump (our 3S was purely competitive).
      - when: "partner_hcp >= 15 and partner_spades >= 6"
        contract: "4SN"
        terminal: true
      # 3S essentially never gets doubled here: the raiser is broke and
      # East's spade length is capped at 3 by the raise itself. (The old
      # "east_spades >= 5" penalty branch was dead code.)
      - else: {contract: "3SN", terminal: true}

  - call: "X"
    label: "Value-showing double (cards, 3 spades, tolerance for defending)"
    projection:
      # Partner converts for penalty ONLY with a defensive maximum whose
      # heart honours sit over opener — never with small doubletons.
      - when: "partner_hearts >= 2 and partner_hearts_hcp >= 3 and partner_hcp >= 13 and partner_spades <= 5"
        contract: "3HWx"
        terminal: false
      # Offensive maximum with a 6th spade jumps to the nonvul game.
      - when: "partner_spades >= 6 and partner_hcp >= 14"
        contract: "4SN"
        terminal: true
      # Default: partner signs off in 3S. The vulnerable opponents push to
      # 4H only with the big fit opposite a sound opening; we double with
      # defence.
      - when: "opps_combined_hearts >= 10 and west_hcp >= 16 and me_hcp >= 9 and me_hearts >= 3"
        contract: "4HWx"
        terminal: false
      - when: "opps_combined_hearts >= 10 and west_hcp >= 16"
        contract: "4HW"
        terminal: true
      - else: {contract: "3SN", terminal: true}
```

### B.2 `bridge_trainer/semantics/rules/our_2over1.yaml` (complete, incl. Part C rules)

```yaml
# Our side: 2/1 game forcing, sound-ish overcalls but flexible at favorable.
schema_version: 1
system: our_2over1
rules:
  # --- Openings ---------------------------------------------------------
  # Partner's 1S opening (used by five_level_over_save).
  - id: open_1s
    context: []
    call: "1S"
    constraints:
      hcp:
        core: [11, 19]
        margin:
          - {range: [10, 10], weight: 0.3}   # shapely rule-of-20 tens
          - {range: [20, 21], weight: 0.3}   # unbalanced 20-21, no 2C bid
      suits:
        S: {core: [5, 7]}
    exclusions:
      - balanced_15_17     # opens 1NT
      - balanced_20_21     # opens 2NT

  # --- Direct-seat actions over (1H) ------------------------------------
  # Partner's 1S overcall over a 1H opening.
  - id: overcall_1s_over_1h
    context: ["1H"]
    call: "1S"
    constraints:
      hcp:
        core: [8, 16]
        margin:
          - {range: [7, 7], weight: 0.5}   # shapely light overcalls happen
          - {range: [17, 17], weight: 0.4} # slightly too strong, no better call
      suits:
        S: {core: [5, 7]}
        H: {core: [0, 4]}
    exclusions:
      - takeout_double_shape_over_hearts   # would double, not overcall
      - strong_jump_shift_values           # would start with a stronger action
      - light_overcall_junk_spades         # light overcalls need suit quality

  # Partner passes over a 1H opening (used by tests / other problems, INV8).
  - id: pass_over_1h
    context: ["1H"]
    call: "P"
    constraints:
      hcp:
        core: [0, 12]
        margin:
          - {range: [13, 14], weight: 0.3} # trap pass / awkward shape
      suits:
        S: {core: [0, 4], margin: [{range: [5, 5], weight: 0.2}]}

  # --- Sandwich-seat pass over (1S)-P-(2S) (used by bal_reopen_after_2s) --
  # Partner heard 1S on his right and 2S coming back; he passed twice by
  # implication of this single call (his only call so far). Caps his values
  # and denies clear direct action.
  - id: pass_sandwich_after_1s_p_2s
    context: ["1S", "P", "2S"]
    call: "P"
    constraints:
      hcp:
        core: [0, 11]
        margin:
          - {range: [12, 14], weight: 0.4}   # flat or misfitting 12-14 sells
      suits:
        S: {core: [0, 4]}
    exclusions:
      - takeout_double_shape_over_spades       # would have doubled 2S
      - sound_two_level_overcall_over_spades   # would have overcalled

  # --- Forcing pass over (5H) (used by five_level_over_save) -------------
  # Opener's pass of 5H after 1S-(3H)-4S-(5H) is forcing: "no clear
  # direction, cards suggest defending but I will respect your decision."
  # With a heart void + extreme shape opener bids 5S himself; with a
  # trump-stack-proof double he doubles himself. So the pass shows 1-3
  # hearts and a normal opening without extreme shape.
  - id: forcing_pass_after_5h
    context: ["1S", "3H", "4S", "5H"]
    call: "P"
    constraints:
      hcp:
        core: [11, 16]
        margin:
          - {range: [17, 19], weight: 0.4}   # extras but still no clear call
      suits:
        H: {core: [1, 3], margin: [{range: [0, 0], weight: 0.3}]}
```

### B.3 `bridge_trainer/semantics/rules/opps_light_preempts.yaml` (complete, incl. Part C rules)

```yaml
# Opponents' assumed style: light openings allowed, aggressive weak raises
# and preempts. 3H over (1H) 1S is preemptive: 4-card support, weak hand.
schema_version: 1
system: opps_light_preempts
rules:
  - id: open_1h
    context: []
    call: "1H"
    constraints:
      hcp:
        core: [11, 19]
        margin:
          - {range: [10, 10], weight: 0.4}   # light style: shapely 10-counts
          - {range: [20, 21], weight: 0.3}   # unbalanced 20-21, below a 2C bid
      suits:
        H: {core: [5, 7], margin: [{range: [8, 8], weight: 0.2}]}
    exclusions:
      - balanced_15_17    # would have opened 1NT
      - balanced_20_21    # would have opened 2NT

  - id: raise_3h_preemptive
    context: ["1H", "1S"]
    call: "3H"
    constraints:
      hcp:
        core: [3, 8]
        margin:
          - {range: [2, 2], weight: 0.4}   # total trash, but they are vul
          - {range: [9, 9], weight: 0.5}   # maximum with no game interest
      suits:
        # A preemptive JUMP raise promises four trumps; no 3-card margin.
        H: {core: [4, 4], margin: [{range: [5, 5], weight: 0.4}]}
        S: {core: [0, 3]}
    exclusions:
      - game_forcing_raise_values          # would have cue-bid 2S instead

  - id: pass_after_1h_1s
    context: ["1H", "1S"]
    call: "P"
    constraints:
      hcp: {core: [0, 8], margin: [{range: [9, 10], weight: 0.4}]}
      suits:
        H: {core: [0, 2], margin: [{range: [3, 3], weight: 0.3}]}

  # --- Weak two in spades (used by comp_over_weak_2s; they are vul) ------
  - id: open_2s_weak
    context: []
    call: "2S"
    constraints:
      hcp:
        core: [5, 10]
        margin:
          - {range: [4, 4], weight: 0.3}
          - {range: [11, 11], weight: 0.3}
      suits:
        S: {core: [6, 6], margin: [{range: [5, 5], weight: 0.2}]}
        H: {core: [0, 3], margin: [{range: [4, 4], weight: 0.3}]}
    exclusions:
      - seven_card_suit        # would open 3S
      - weak_two_suit_junk     # vulnerable weak twos need a real suit

  # --- Weak jump overcall over our 1S (used by five_level_over_save) -----
  - id: wjo_3h_over_1s
    context: ["1S"]
    call: "3H"
    constraints:
      hcp:
        core: [5, 9]
        margin:
          - {range: [4, 4], weight: 0.5}
          - {range: [10, 10], weight: 0.4}
      suits:
        H: {core: [6, 6], margin: [{range: [7, 7], weight: 0.25}]}
        S: {core: [0, 2], margin: [{range: [3, 3], weight: 0.3}]}

  # --- The 5H save over our 4S (used by five_level_over_save) ------------
  # Favorable for them: big fit, shortness in our suit, no defence.
  - id: save_5h_over_4s
    context: ["1S", "3H", "4S"]
    call: "5H"
    constraints:
      hcp:
        core: [3, 9]
        margin:
          - {range: [10, 11], weight: 0.4}
      suits:
        H: {core: [4, 5], margin: [{range: [3, 3], weight: 0.3}]}
        S: {core: [0, 1], margin: [{range: [2, 2], weight: 0.3}]}

  # --- Preemptor's pass after the save and our forcing pass --------------
  - id: pass_after_save
    context: ["1S", "3H", "4S", "5H", "P"]
    call: "P"
    constraints:
      hcp: {core: [0, 11]}
```

---

## Part C — Four new problem families

| id | decision | vul | opp style |
|----|----------|-----|-----------|
| `bal_reopen_after_2s` | balance over their dead 2M | Both | sound (new ruleset) |
| `ovc_quality_1s_over_1h` | marginal 1-level overcall on a bad suit | NS (unfavorable) | light |
| `five_level_over_save` | X vs 5S over their save | NS | light |
| `comp_over_weak_2s` | direct action over a vul weak two | EW | light |

### C.1 `problems/bal_reopen_after_2s.yaml`

**Expert commentary.** The single most drilled balancing position in the game:
they find a fit and stop, so partner is marked with values ("borrow a king") and
selling out to 2S at Both is a long-run leak — yet 3H can go -200 against their
-110, and the double risks partner jumping. The field error is symmetric: timid
players sell out, and aggressive players balance with the wrong call (3H on a
bad suit when X keeps three suits and the penalty pass in play). What decides it
per layout is partner's heart fit and their ninth trump — exactly the breakdowns
shown.

```yaml
# Balancing decision: they die in 2S; reopen or defend?
schema_version: 1
id: bal_reopen_after_2s
title: "Balance over their 2S, or sell out?"
category: balancing
description: >
  IMPs, both vulnerable. RHO opens 1S, sound style; responder raises to 2S
  and opener passes it out to you in the balancing seat. You passed over 1S
  (sound two-level overcalls). Partner is marked with values but couldn't
  act. Sell out to 2S, reopen with a flexible double, or bid your suit?

dealer: W
vul: Both
my_seat: N
my_hand: "82.KJT95.K74.Q83"
auction: ["1S", "P", "2S", "P", "P"]

# Exactly five decent hearts, at most two spades, 8-10 HCP: too weak/bad-suited
# for a direct vulnerable 2H, clearly enough to think about balancing.
my_hand_class:
  hcp: [8, 10]
  suits:
    S: [0, 2]
    H: [5, 5]
variants: 12

our_system:
  name: "2/1"
  description: "2/1 GF; sound direct two-level overcalls, active balancing"
  ruleset: our_2over1.yaml

opps_system:
  name: "Sound/standard"
  description: "Sound openings, constructive single raises, 15-17 NT"
  ruleset: opps_sound.yaml

n_deals: 800

breakdowns:
  - feature: partner_hearts
    label: "Partner's heart length"
  - feature: opps_combined_spades
    label: "Their combined spades"

candidates:
  - call: "P"
    label: "Pass (sell out to 2S)"
    projection:
      # Pass-pass ends it: the auction is genuinely over.
      - else: {contract: "2SW", terminal: false}

  - call: "X"
    label: "Balancing double (takeout-ish, flexible)"
    projection:
      # Partner converts with a real trump stack behind declarer.
      - when: "partner_spades >= 5 and partner_spades_hcp >= 4"
        contract: "2SWx"
        terminal: false
      # Partner remembers I already borrowed a king: game needs a true max
      # plus a 4-card fit.
      - when: "partner_hcp >= 13 and partner_hearts >= 4"
        contract: "4HS"
        terminal: true
      # Normal case: partner bids 3H; opener competes 3S with a 6th trump,
      # or responder with a 4th trump and the 9-card fit (Law push at the
      # three level over a balance is routine even at Both).
      - when: "partner_hearts >= 4 and (west_spades >= 6 or east_spades >= 4 and opps_combined_spades >= 9)"
        contract: "3SW"
        terminal: true
      - when: "partner_hearts >= 4"
        contract: "3HS"
        terminal: true
      # Flat misfit: partner converts under protest with 4 flat spades...
      - when: "partner_spades >= 4 and partner_hearts <= 3 and partner_diamonds <= 3 and partner_clubs <= 3"
        contract: "2SWx"
        terminal: false
      # ...otherwise scrambles into his longer minor.
      - when: "partner_diamonds >= 4 and partner_diamonds >= partner_clubs"
        contract: "3DS"
        terminal: true
      - when: "partner_clubs >= 4"
        contract: "3CS"
        terminal: true
      - else: {contract: "3DS", terminal: true}

  - call: "3H"
    label: "Balance with 3H (natural)"
    projection:
      # They take the Law push with the 9-card fit or a 6th trump in opener's
      # hand; we are done at Both vulnerable.
      - when: "west_spades >= 6 or opps_combined_spades >= 9 and east_hcp >= 8"
        contract: "3SW"
        terminal: true
      # Partner raises a balancing 3H to game only with a fitting maximum.
      - when: "partner_hearts >= 4 and partner_hcp >= 12"
        contract: "4HN"
        terminal: true
      # The trap: opener with a heart stack and a sound maximum doubles.
      - when: "west_hearts >= 4 and west_hcp >= 13"
        contract: "3HNx"
        terminal: false
      - else: {contract: "3HN", terminal: true}
```

**New ruleset file `bridge_trainer/semantics/rules/opps_sound.yaml`** (covers all
three concealed opponent calls: W's 1S at context `[]`, E's 2S at
`["1S", "P"]`, W's pass at `["1S", "P", "2S", "P"]`; partner's pass at
`["1S", "P", "2S"]` is `pass_sandwich_after_1s_p_2s` in `our_2over1.yaml`):

```yaml
# Opponents' assumed style: sound openings, constructive raises, 15-17 NT.
schema_version: 1
system: opps_sound
rules:
  - id: open_1s_sound
    context: []
    call: "1S"
    constraints:
      hcp:
        core: [12, 21]
        margin:
          - {range: [11, 11], weight: 0.4}
      suits:
        S: {core: [5, 7]}
    exclusions:
      - balanced_15_17     # opens 1NT
      - balanced_20_21     # opens 2NT

  - id: raise_2s_constructive
    context: ["1S", "P"]
    call: "2S"
    constraints:
      hcp:
        core: [6, 9]
        margin:
          - {range: [5, 5], weight: 0.4}
      suits:
        S: {core: [3, 4]}
    exclusions:
      - game_forcing_raise_values   # 10+ makes a limit raise or better

  # Opener's pass of 2S caps him: no game try, no extras.
  - id: opener_pass_after_2s
    context: ["1S", "P", "2S", "P"]
    call: "P"
    constraints:
      hcp:
        core: [11, 14]
        margin:
          - {range: [15, 16], weight: 0.3}   # flat 15-16, no playable try
```

### C.2 `problems/ovc_quality_1s_over_1h.yaml`

**Expert commentary.** The unfavorable-vulnerability overcall on a queen-high
suit is where the field bleeds: 1S on Q9653 gets you to good spade partials and
directs the killing lead, but it also eats -200/-500 when responder has a stack,
and the "flexible" off-shape double (doubleton club!) finds partner jumping in
the wrong suit. Experts decide on suit texture, defensive strength and the
danger of the specific vulnerability — most club players decide on raw HCP. All
concealed calls in this auction are covered by the single existing
`open_1h` rule in `opps_light_preempts.yaml` (context `[]`).

```yaml
# Direct-seat action over (1H) at unfavorable with a bad 5-card suit.
schema_version: 1
id: ovc_quality_1s_over_1h
title: "Overcall 1S on a bad suit, vulnerable?"
category: direct_actions
description: >
  IMPs, we are vulnerable, they are not. RHO opens 1H (light style). You
  hold an opening-ish 11-count with a shabby five-card spade suit and a
  doubleton club. Pass and defend, overcall 1S on Q-high, or stretch to an
  off-shape takeout double?

dealer: E
vul: NS              # unfavorable: we are vulnerable, they are not
my_seat: S
my_hand: "Q9653.A4.KQ72.85"
auction: ["1H"]

# Exactly five spades, 10-12 HCP, 2-3 hearts, both minors 2+: every hand in
# the class genuinely weighs all three actions (with a singleton minor the
# double stops being a candidate, so minors are floored at 2/3 cards).
my_hand_class:
  hcp: [10, 12]
  suits:
    S: [5, 5]
    H: [2, 3]
    D: [3, 5]
    C: [2, 4]
variants: 12

our_system:
  name: "2/1"
  description: "2/1 GF; disciplined vulnerable overcalls"
  ruleset: our_2over1.yaml

opps_system:
  name: "Light/aggressive"
  description: "Light openings allowed"
  ruleset: opps_light_preempts.yaml

n_deals: 800

breakdowns:
  - feature: partner_spades
    label: "Partner's spade length"
  - feature: west_spades
    label: "Responder's spade length (the penalty risk)"

candidates:
  - call: "P"
    label: "Pass (quiet defence)"
    projection:
      # Their constructive auction runs unimpeded.
      - when: "opps_combined_hcp >= 25"
        contract: "4HE"
        terminal: true
      # Partner acts in the sandwich/balancing seat with a sound takeout
      # shape; we bid our spades and buy it.
      - when: "partner_hcp >= 13 and partner_hearts <= 2 and partner_spades >= 3"
        contract: "2SS"
        terminal: true
      - when: "opps_combined_hcp >= 21 and opps_combined_hearts >= 8"
        contract: "3HE"
        terminal: true
      # Dead responder: 1H sometimes gets passed out around the table.
      - when: "west_hcp <= 5 and partner_hcp <= 12"
        contract: "1HE"
        terminal: true
      - else: {contract: "2HE", terminal: true}

  - call: "1S"
    label: "Overcall 1S (bad suit, good hand)"
    projection:
      # The nightmare first: responder has length/values in spades, the
      # penalty machinery (trap pass + reopening double) catches us.
      - when: "west_spades >= 5 and west_hcp >= 9"
        contract: "1SSx"
        terminal: false
      # Constructive raise, we carry on to the vulnerable game with a max.
      - when: "partner_spades >= 4 and partner_hcp >= 11 and me_hcp >= 11"
        contract: "4SS"
        terminal: true
      # They own the deal: heart fit + power outbids us to 3H.
      - when: "opps_combined_hearts >= 9 and opps_combined_hcp >= 20"
        contract: "3HE"
        terminal: true
      # Simple raise buys it...
      - when: "partner_spades >= 3 and partner_hcp >= 8"
        contract: "2SS"
        terminal: true
      # ...misfit: opener rebids his hearts and plays there...
      - when: "opps_combined_hearts >= 8 and partner_spades <= 2"
        contract: "2HE"
        terminal: true
      # ...or it dies in 1S.
      - else: {contract: "1SS", terminal: true}

  - call: "X"
    label: "Off-shape takeout double"
    projection:
      # Best case: partner has the heart stack and passes for penalty.
      - when: "partner_hearts >= 5 and partner_hearts_hcp >= 5 and partner_hcp >= 9"
        contract: "1HEx"
        terminal: false
      # Partner drives spades opposite a (presumed) sound double.
      - when: "partner_spades >= 4 and partner_hcp >= 11"
        contract: "4SN"
        terminal: true
      - when: "partner_spades >= 4 and partner_hcp >= 8"
        contract: "2SN"
        terminal: true
      - when: "partner_spades >= 4"
        contract: "1SN"
        terminal: true
      # They compete the heart fit over partner's minor advance.
      - when: "opps_combined_hearts >= 9 and opps_combined_hcp >= 20"
        contract: "3HE"
        terminal: true
      # The cost of the doubleton club: partner advances a minor and we
      # play the 4-3 / 4-2 at the two level.
      - when: "partner_diamonds >= 4 and partner_diamonds >= partner_clubs"
        contract: "2DN"
        terminal: true
      - else: {contract: "2CN", terminal: true}
```

### C.3 `problems/five_level_over_save.yaml`

**Expert commentary.** "The five level belongs to the opponents" — but only as a
prior, not a rule. After 1S-(3H)-4S-(5H)-P(forcing)-P, partner's forcing pass
hands you a pure two-way decision: X collects 300-500 when the hands are
defensive; 5S is right when the double fit runs and both defensive tricks are in
their short suits. The field's two classic errors are both modeled: passing 5H
out undoubled (a forcing-pass violation that turns +300 into +100 or worse) and
bidding 5S "insurance" with flat defensive hands. Trump-length, singleton-heart
and ace-count features drive the per-layout verdict.

```yaml
# The five-level decision: they save over our vulnerable game.
schema_version: 1
id: five_level_over_save
title: "They save in 5H over your 4S: double or bid on?"
category: high_level_decisions
description: >
  IMPs, we are vulnerable, they are not. Partner opens 1S, RHO jumps to a
  weak 3H, you bid 4S (fit + shape), and LHO saves in 5H at his favorable
  vulnerability. Partner's pass is FORCING: he is voting for defence but
  leaves the decision to you. Double, press on to 5S, or (illegally cheap)
  sell out undoubled?

dealer: N
vul: NS              # we vulnerable, their save is at favorable
my_seat: S
my_hand: "KT74.6.A9532.Q84"
auction: ["1S", "3H", "4S", "5H", "P", "P"]

# Four trumps, at most one heart, 8-11 HCP: every hand in the class had a
# normal 4S bid and now faces a genuine X-vs-5S decision.
my_hand_class:
  hcp: [8, 11]
  suits:
    S: [4, 4]
    H: [0, 1]
variants: 12

our_system:
  name: "2/1"
  description: "2/1 GF; forcing passes apply after our voluntary game"
  ruleset: our_2over1.yaml

opps_system:
  name: "Light/aggressive"
  description: "Weak jump overcalls, aggressive saves at favorable"
  ruleset: opps_light_preempts.yaml

n_deals: 800

breakdowns:
  - feature: partner_hearts
    label: "Opener's heart length (defensive texture)"
  - feature: opps_combined_hcp
    label: "Their combined HCP"

candidates:
  - call: "X"
    label: "Double (take the money)"
    projection:
      # Opener may pull the double with a heart void and a 6th trump —
      # the classic hand that passed first to leave room for exactly this.
      - when: "partner_hearts == 0 and partner_spades >= 6"
        contract: "5SN"
        terminal: true
      - else: {contract: "5HEx", terminal: false}

  - call: "5S"
    label: "Bid 5S (the fit is huge)"
    projection:
      # With an 11-card fit and a 7th trump for the preemptor they
      # occasionally save again — and now everybody doubles.
      - when: "east_hearts >= 7 and opps_combined_hearts >= 11 and west_spades <= 1"
        contract: "6HEx"
        terminal: false
      # We are vulnerable at the five level: they double with any defence.
      - when: "east_hcp >= 8 or west_hcp >= 9"
        contract: "5SNx"
        terminal: false
      - else: {contract: "5SN", terminal: true}

  - call: "P"
    label: "Pass (sell out undoubled)"
    projection:
      # A second pass ends the auction: 5H plays undoubled. (Under forcing-
      # pass agreements this option should not exist — the drill shows why.)
      - else: {contract: "5HE", terminal: false}
```

Rules used (all already included in the Part B ruleset files): `open_1s` and
`forcing_pass_after_5h` in `our_2over1.yaml`; `wjo_3h_over_1s`,
`save_5h_over_4s` and `pass_after_save` in `opps_light_preempts.yaml`.

### C.4 `problems/comp_over_weak_2s.yaml`

**Expert commentary.** Direct action over a vulnerable weak two with a
one-suited 13-count is the textbook three-way squeeze: 3H commits a king-light
opening bid to the three level; the double is off-shape (doubleton spade is
fine, but 2-5-3-3 invites a 3C/3D advance on a 4-3); pass risks defending 2S
with game on. The field's systematic error is doubling "because I have an
opening bid" and then correcting 3-of-a-minor to 3H — showing a much better
hand. The 2S opener's rule is deliberately sound-ish (they are vulnerable), so
penalties from trap-passing are real but rarer than nonvul intuition suggests.

```yaml
# Competing over their vulnerable weak two.
schema_version: 1
id: comp_over_weak_2s
title: "Over their weak 2S: pass, double, or 3H?"
category: direct_actions
description: >
  IMPs, they are vulnerable, we are not. RHO opens a (sound, vulnerable)
  weak 2S. You hold a decent 13-count with a good five-card heart suit and
  a doubleton spade. Defend quietly, make a slightly off-shape takeout
  double, or bid a natural 3H?

dealer: E
vul: EW              # they are vulnerable, we are not
my_seat: S
my_hand: "A7.KQT84.K93.J52"
auction: ["2S"]

# Exactly five hearts, 1-2 spades, 12-14 HCP: strong enough that passing
# throughout is not automatic, weak enough that neither X nor 3H is clear.
my_hand_class:
  hcp: [12, 14]
  suits:
    S: [1, 2]
    H: [5, 5]
variants: 12

our_system:
  name: "2/1"
  description: "2/1 GF; sound three-level overcalls"
  ruleset: our_2over1.yaml

opps_system:
  name: "Light/aggressive"
  description: "Aggressive preempts, but vulnerable weak twos deliver a suit"
  ruleset: opps_light_preempts.yaml

n_deals: 800

breakdowns:
  - feature: partner_hearts
    label: "Partner's heart length"
  - feature: west_spades
    label: "LHO's spade fit (the jam risk)"

candidates:
  - call: "P"
    label: "Pass (defend 2S)"
    projection:
      # LHO raises the preempt to game with a fit and real values...
      - when: "west_hcp >= 14 and west_spades >= 3"
        contract: "4SE"
        terminal: true
      # ...or extends the preempt with a 4th trump.
      - when: "west_spades >= 4"
        contract: "3SE"
        terminal: true
      # Partner balances with a takeout double; we jump to our hearts.
      - when: "partner_hcp >= 13 and partner_spades <= 2"
        contract: "3HS"
        terminal: true
      - else: {contract: "2SE", terminal: false}

  - call: "X"
    label: "Takeout double (off-shape 2-5-3-3)"
    projection:
      # Partner converts with a genuine trump stack (they are vulnerable:
      # +200/+500/+800 territory).
      - when: "partner_spades >= 5 and partner_spades_hcp >= 4"
        contract: "2SEx"
        terminal: false
      # LHO jams to 3S on a fit; we double again with a full maximum,
      # otherwise it plays there when partner is broke.
      - when: "west_spades >= 3 and west_hcp >= 6 and partner_hcp <= 9 and me_hcp >= 14"
        contract: "3SEx"
        terminal: false
      - when: "west_spades >= 3 and west_hcp >= 6 and partner_hcp <= 9"
        contract: "3SE"
        terminal: true
      # Partner advances: game with values + a fit, else the cheapest suit —
      # including the painful 4-3 minor when he has no major.
      - when: "partner_hcp >= 10 and partner_hearts >= 4"
        contract: "4HN"
        terminal: true
      - when: "partner_hearts >= 4"
        contract: "3HN"
        terminal: true
      - when: "partner_diamonds >= 5"
        contract: "3DN"
        terminal: true
      - when: "partner_clubs >= 5"
        contract: "3CN"
        terminal: true
      - else: {contract: "3DN", terminal: true}

  - call: "3H"
    label: "Overcall 3H (natural, sound)"
    projection:
      # Partner raises to game with 3-card support and 10+.
      - when: "partner_hearts >= 3 and partner_hcp >= 10"
        contract: "4HS"
        terminal: true
      # They Law-raise to 3S with the 9-card fit; partner competes to the
      # nonvul 4H holding 4 trumps and a working 8+.
      - when: "west_spades >= 3 and opps_combined_spades >= 9 and partner_hearts >= 4 and partner_hcp >= 8"
        contract: "4HS"
        terminal: true
      - when: "west_spades >= 3 and opps_combined_spades >= 9"
        contract: "3SE"
        terminal: true
      - else: {contract: "3HS", terminal: true}
```

Rules used: the new `open_2s_weak` in `opps_light_preempts.yaml` (only concealed
call in the auction). Our ruleset is referenced but contributes no rule here
(partner has not yet called).

---

## Part D — New exclusion predicates

Add these to `bridge_trainer/semantics/predicates.py` (formulas over `hcp`,
per-suit lengths, per-suit hcp, `is_balanced`; True = excluded):

1. **`balanced_20_21`** — would have opened 2NT.
   `is_balanced and 20 <= hcp <= 21`

2. **`light_overcall_junk_spades`** — a light 1S overcall requires suit quality;
   with a near-honorless suit and sub-opening values the expert passes.
   `(hcp <= 9) and (spades_hcp <= 2)`

3. **`takeout_double_shape_over_spades`** — would have doubled 2S (or 1S) for
   takeout instead of passing.
   `(hcp >= 12) and (spades <= 2) and (hearts >= 3) and (diamonds >= 3) and (clubs >= 3)`

4. **`sound_two_level_overcall_over_spades`** — would have made a direct
   two-level overcall over 1S/2S instead of passing: opening values with a good
   five-card suit outside spades.
   `(hcp >= 12) and ((hearts >= 5 and hearts_hcp >= 5) or (diamonds >= 5 and diamonds_hcp >= 5) or (clubs >= 5 and clubs_hcp >= 5))`

5. **`weak_two_suit_junk`** — a (vulnerable-style) weak two promises two of the
   top honors or equivalent; Q-empty and worse is excluded.
   `spades_hcp <= 2`

Existing predicates reused: `balanced_15_17`, `takeout_double_shape_over_hearts`,
`strong_jump_shift_values`, `game_forcing_raise_values` (also as "would have made
a limit raise or better" for the sound 2S raise — same 10+ threshold),
`seven_card_suit`.

---

## Summary of rule coverage per problem (audit checklist)

| Problem | Concealed call | Context | Rule (file) |
|---|---|---|---|
| comp_3s_over_3h | W 1H | `[]` | `open_1h` (opps_light_preempts) |
| | N 1S | `["1H"]` | `overcall_1s_over_1h` (our_2over1) |
| | E 3H | `["1H","1S"]` | `raise_3h_preemptive` (opps_light_preempts) |
| bal_reopen_after_2s | W 1S | `[]` | `open_1s_sound` (opps_sound) |
| | E 2S | `["1S","P"]` | `raise_2s_constructive` (opps_sound) |
| | S P | `["1S","P","2S"]` | `pass_sandwich_after_1s_p_2s` (our_2over1) |
| | W P | `["1S","P","2S","P"]` | `opener_pass_after_2s` (opps_sound) |
| ovc_quality_1s_over_1h | E 1H | `[]` | `open_1h` (opps_light_preempts) |
| five_level_over_save | N 1S | `[]` | `open_1s` (our_2over1) |
| | E 3H | `["1S"]` | `wjo_3h_over_1s` (opps_light_preempts) |
| | W 5H | `["1S","3H","4S"]` | `save_5h_over_4s` (opps_light_preempts) |
| | N P | `["1S","3H","4S","5H"]` | `forcing_pass_after_5h` (our_2over1) |
| | E P | `["1S","3H","4S","5H","P"]` | `pass_after_save` (opps_light_preempts) |
| comp_over_weak_2s | E 2S | `[]` | `open_2s_weak` (opps_light_preempts) |

(My own seat's calls are skipped by the engine in every family; all dealer/seat
arithmetic was verified so each auction ends with `my_seat` to act.)
