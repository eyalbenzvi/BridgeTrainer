# Bridge-logic inventory — what lives outside Ben, and the path to zero

Owner question (2026-07-17): does the code contain bridge logic outside
BEN? Aspiration: no bridge-specific decisions in code — everything from
BEN and the DD engine.

## The inventory

Three kinds of "logic" exist, and only one of them violates the
aspiration:

- **[laws]** — rules/scoring of the game (must exist somewhere; not
  judgment);
- **[policy]** — the owner's product rules, computed FROM Ben+DD numbers
  (single winner, thresholds; not bridge judgment in code);
- **[bridge]** — genuine bridge knowledge hand-coded — the target for
  elimination.

| Location | What | Kind |
|---|---|---|
| `engine/conventions.py` `classify()` | convention names (Stayman, transfers, Jacoby 2NT, splinter, RKC + steps, 2C/2D waiting, Ogust + steps, cue bids, fourth suit), category structure (raise/rebid/overcall...), jump attributes | **[bridge]** — the largest item |
| `engine/conventions.py` double typing | takeout / negative / penalty / lead-directing / balancing rules | **[bridge]** |
| `engine/conventions.py` `systemic_meaning()` | 2/1 rulebook ranges (openings 11-21, 1NT 15-17, weak twos 5-10, role-aware NT ranges, overcall ranges...) | **[bridge]** |
| `engine/conventions.py` `in_convention_sequence`, asking list | which turns are mid-convention | **[bridge]** |
| `engine/scanner.py` content exclusions | bust artifact, Drury fork, negative-X fork, GF-pass artifact | **[bridge]** (patterns) |
| `engine/scanner.py` thresholds | policy split (0.70/0.15), candidate floor 0.03 (raw softmax, not get_bid_candidates), stem-mass 0.05, depth caps | **[policy]** over Ben's numbers |
| `engine/verdict.py` gates + winner rules | gap/CI/stakes floors, q, interest weights, trap, 0.5-IMP / +10% / policy>=0.15 winner rules; interest anchored to the highest-policy alternative (not the EV runner-up) so it is invariant to candidate-set size | **[policy]** over Ben+DD numbers |
| `engine/verdict.py` `_contract_class` | what counts as game/slam | **[laws]** (scoring boundaries) |
| `engine/maker.py` quotas | opening cap, theme dedup, trap cap | **[policy]** |
| `scoring/tables.py` | IMP table, contract scores | **[laws]** |
| `validate/auction_state.py` | call legality, auction over | **[laws]** |
| `dd/correction_table.yaml` | single-dummy correction | **[bridge]** — legacy path only, unused by the Ben pipeline |
| `semantics/rules/*.yaml`, `projection/`, `bank/` | authored meanings/continuations | **[bridge]** — legacy `trainer run` path only, unused by the Ben pipeline |
| `engine/explain.py`, webapp | rendering only (consumes conventions + evaluation) | none |

## The path to zero [bridge] in the live pipeline

1. **Meanings** (`systemic_meaning`, convention names): two engine-based
   replacements exist —
   a. **BBA/EPBot** (ships inside the ben checkout, `bin/BBA`): a real
      convention-card engine that emits textual explanations per call;
      Ben's config natively consults it (`consult_bba`), disabled today
      only because it is a .NET DLL (needs the dotnet/mono runtime on
      Linux). Enabling it replaces the whole hand-written meaning table
      with card-derived text. **The recommended endgame.**
   b. **Ben's Info model** (`BEN-21GF-Info`): predicts HCP/shape per
      seat from the auction — engine-derived meaning bands. Rejected
      for display by the owner (statistical phrasing), but usable
      internally.
2. **Convention/asking detection** (exclusions, mid-convention): Ben's
   candidate output carries **alert flags** from the NN; BBA provides
   authoritative convention identification. Alert-driven exclusions
   would replace the pattern table.
3. **Content exclusions** (Drury/negative-X forks, bust artifacts):
   with BBA's card on both sides these become detectable as
   "call meaning differs between plausible cards" instead of hard-coded
   patterns; the bust artifact is replaceable by an Info-model check
   (predicted strength vs. actual split).
4. **Stays by design**: [laws] (scoring/legality) and [policy] (the
   owner's own selection and winner rules — they consume engine
   numbers, they don't encode bridge judgment).

Practical order: (1a) BBA runtime spike on Linux → meanings + alerts
from the engine → delete `systemic_meaning` + most of `classify()` →
exclusions via alerts. Estimated effort: a 1-2 day spike (dotnet
runtime + pythonnet inside the Ben venv), then incremental deletion.
