# Improvement round 3 — owner feedback (2026-07-17)

Owner's five findings on pool v2 and the derived fixes:

1. **Speed: reach ~1 min per published problem** (was 208 s).
   Root cause measured: scanning = 83% of wall clock, and most of it is
   Ben's internal search firing at close turns while we bid the stem.
   Fixes: (a) scan commits the raw policy top at every turn (no search)
   — the stem-mass floor still discards engine-weird stems; (b) scan
   stops early once the auction is too deep for any further eligible
   turn. Projected: ~75–90 s per published problem.
2. **Single winner only — no toss-ups.** Owner's decision rule,
   replacing the toss-up publishing policy: if the top-2 expected-IMP
   gap ≥ 0.5 → that option wins; else if the per-layout win rates
   differ by > 10 points → the higher win rate wins (even against a
   small EV edge the other way); else the deal is rejected
   (`no_clear_winner`). Doubled-heavy margins now reject instead of
   downgrading to toss-up.
3. **Hero's stem calls must say what they told partner** — "your own
   call" deleted; hero calls get the same measured meaning treatment
   (sampled from partner's viewpoint), and named conventions state what
   they asked/showed.
4. **ben1-00000d01 class**: decision points inside a convention
   sequence (inquiry → artificial response → lead-directing X) produce
   nonsense menus (raising an artificial call) and nonsense labels.
   Fixes: (a) mid-convention exclusion — no decision point within 3
   calls of an asking call by the acting side; (b) raise detection uses
   ALL of partner's naturally shown suits, not the last bid; (c)
   weak-two inquiry responses classified as artificial steps.
5. **Don't explain bids that show nothing** — uninformative passes get
   empty notes; the UI omits them.
