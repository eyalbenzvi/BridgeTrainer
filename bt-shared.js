
/* ===== panel score: the 0-100 graded verdict scale =====
   (docs/scoring_scale.md). Pure functions of the problem doc + the chosen
   action — no DOM, no Firebase — so tests run this block under node as-is
   and bt-firebase.js can call it across the classic-script/module boundary
   (inline scripts execute before the deferred module). */
const SCORE_CAP = 95;          // a non-accepted answer never quite ties best
const SCORE_MAX_NONBEST = 94;  // rounded clamp ceiling (< SCORE_CAP, so a
                               // non-accepted answer never rounds up to 95)
// score-band thresholds (BUG-9): single source for btBandOf, the p/lead pages'
// near/bad chip class, and the dashboard's review cut + distribution bins.
const REVIEW_MIN = 85;         // "review below 85"; near band / opt bin floor
const NEAR_MIN = 65;           // minor-deviation floor; p/lead "near" chip cut
const ERROR_MIN = 40;          // error band floor; no-data fallback score
const SESSION_SIZE = 10;       // problems per practice run (bt_session)
const SESSION_TTL_MS = 6 * 60 * 60 * 1000;   // a run older than this is stale
const SCORE_EXP = 1.6;         // soft shoulder, then a fast drop
const SCORE_LENIENCY = 6;      // max field-leniency points (x policy weight)
const SCORE_TAU = {bidding: 2.0, leadMP: 0.6, leadIMP: 1.75};
const STAKES_REF = 2.5;        // stakes at which the bidding scale is neutral
const STAKES_STRETCH_MIN = 0.8, STAKES_STRETCH_MAX = 1.8;
const MP_RANK_WEIGHT = 0.35;   // matchpoints are frequency scoring: blend rank
function btClamp(x, lo, hi) { return Math.min(hi, Math.max(lo, x)); }
function btCurve(cost, tau) {
  if (!(cost > 0)) return SCORE_CAP;
  return SCORE_CAP / (1 + Math.pow(cost / tau, SCORE_EXP));
}
/* display bands; 100 and 0 are semantic (accepted set / dead option) */
function btBandOf(score) {
  if (typeof score !== "number") return null;
  if (score >= 100) return "best";
  if (score >= REVIEW_MIN) return "near";
  if (score >= NEAR_MIN) return "minor";
  if (score >= ERROR_MIN) return "error";
  if (score >= 1) return "blunder";
  return "dead";
}
const BAND_HE = {best: "מיטבי", near: "כמעט מיטבי", minor: "סטייה קלה",
                 error: "טעות", blunder: "טעות חמורה", dead: "אפשרות מתה"};
const BAND_TONE = {best: "win", near: "win", minor: "gold",
                   error: "loss", blunder: "loss", dead: "loss"};
/* bidding: IMP cost below best, a CI haircut (charge the gap minus half its
   noise margin), a stakes-stretched scale (slam swings are judged wider than
   part-score battles), and field leniency by the engine's policy weight.
   Handles both the raw record shape (verdict.table / accepted as a string)
   and the page-normalized shape (verdict.corrected / accepted as an array).
   The dead pin trusts verdict.dead_options as stored: the forge counts tied
   wins (engine/verdict.py), and stale strictly-unique flags on old records
   were removed by the one-off `trainer pool backfill-dead` migration. */
function btScoreBidding(P, action) {
  const v = (P && P.verdict) || {};
  const accepted = (Array.isArray(v.accepted) ? v.accepted
    : (v.toss_up ? (v.toss_up_set || []) : [v.accepted])).filter(Boolean);
  const out = {kind: "bidding", unit: "IMP", accepted: accepted};
  if (accepted.includes(action)) { out.score = 100; return out; }
  if ((v.dead_options || []).some(d => (d.bid || d) === action)) {
    out.score = 0; out.dead = true; return out;
  }
  let row = (v.corrected || []).find(r => r.bid === action);
  if (!row) {
    const t = (v.table || []).find(r => (r.bid || r.action) === action);
    if (t) row = {ev: t.ev_imp_vs_top !== undefined ? t.ev_imp_vs_top : t.ev,
                  ci: t.ci};
  }
  if (!row || row.ev === undefined || row.ev === null) {
    out.score = ERROR_MIN; out.fallback = true; return out;
  }
  out.cost = Math.max(0, -(+row.ev));
  out.ci = +row.ci || 0;
  out.cEff = Math.max(0, out.cost - out.ci / 2);
  const stakes = P.quality && +P.quality.stakes;
  out.stretch = stakes ? btClamp(stakes / STAKES_REF, STAKES_STRETCH_MIN,
                                 STAKES_STRETCH_MAX) : 1;
  out.tau = SCORE_TAU.bidding * out.stretch;
  out.policy = 0;
  for (const c of P.candidates || [])
    if ((c.call || c) === action) out.policy = +c.policy || 0;
  out.base = btCurve(out.cEff, out.tau);
  out.leniency = SCORE_LENIENCY * out.policy;
  out.score = Math.round(btClamp(out.base + out.leniency, 1, SCORE_MAX_NONBEST));
  return out;
}
/* MP's leading metric — the average number of defensive tricks — cannot see
   WHERE those tricks fall. Two leads can average the same number and still
   produce very different results: one takes its tricks while the contract is
   going down, the other only after it is home. So an average-trick tie is not
   by itself proof that two leads are interchangeable, and grading it as one
   hands 100 to a materially worse lead (lead1-19fa8ed5599: ♥K averages 3.480
   tricks against a spade spot's 3.482 — a 0.002 "tie" — yet beats 3NT on 28%
   of the layouts instead of 37%, and is 0.90 IMP behind on the same evidence).

   The score domain settles it, and every mode-aware row carries it (exp_imps,
   measured against the board's own datum). Hence, in MP:
     * accepted (100) = tied on tricks AND within LEAD_TIE_IMP of the
       recommendation in the score domain — btLeadAccepted below;
     * interchangeable (the tie key behind the matchpoint rank and the field
       leniency group) = equal on BOTH metrics at display precision;
     * the charged gap = the WORSE of the two yardsticks — the trick gap, and
       the score-domain gap put on the trick scale by the two modes' taus — so
       a lead that costs most of an IMP is never charged 0.00 tricks.
   IMP mode already ranks and grades in the score domain, so none of this
   changes it. See docs/scoring_scale.md and scoring/lead_metrics.py, which
   applies the identical rule at forge time.

   MONOTONICITY. MP's objective is the trick average, so pulling a second
   yardstick in must never invert it: in MP a lead with MORE expected
   defensive tricks can never score less than one with fewer. Left unguarded
   both mechanisms above break that promise, because exp_imps is not itself
   monotone in the trick average (lead1-19fb5723ed9, 3NT-W: ♥3 averages 3.208
   tricks and scored 94 — dropped from the accepted set for trailing the ♥5
   anchor by 0.07 IMP — while ♥J at 3.180 tricks scored 100; ♠3 at 3.067
   scored 66 against ♣J's 63 at 3.095). So both ends are clamped to the trick
   order:
     * the accepted set is closed UPWARD in tricks — the score domain may trim
       the tail of a trick tie, never its middle (lead_metrics
       .mp_monotone_close);
     * every other lead keeps its own measured grade but is CAPPED at the
       grade of each lead that beats it on the trick average (`capped`). */
const LEAD_TIE_IMP = 0.05;    // score-domain tie epsilon, in IMPs
                              // (== lead_metrics.TIE_EPS_MP_SCORE)
const LEAD_TIE_TRICKS = 0.05; // trick-tie epsilon (== lead_metrics.TIE_EPS_MP)
const IMP_TO_TRICKS = SCORE_TAU.leadMP / SCORE_TAU.leadIMP;
/* The accepted (score-100) leads of a mode, as the POLICY defines them: the
   stored set, narrowed in MP by the score-domain tie test and then closed
   upward in the trick average. Published records are migrated to the same
   set, so this is normally the identity; it exists so scoring, grading and
   the "עדיף היה" line share ONE definition and `correct` can never disagree
   with `score`. Tolerant of every stored shape (accepted as a string, no
   by_mode); legacy tricks-only records — no exp_imps to judge by — keep their
   stored set untouched.

   The candidate set is the stored one UNIONED with the record's own trick tie
   (every lead within LEAD_TIE_TRICKS of the best average), so a record the
   earlier non-monotone narrowing cut too far reads correctly here even before
   `trainer pool backfill-mp-ties` repairs the document. */
function btLeadAccepted(P, mode) {
  mode = mode === "IMP" ? "IMP" : "MP";
  const v = (P && P.verdict) || {};
  const bm = v.by_mode && v.by_mode[mode];
  let acc = (bm && bm.accepted && bm.accepted.length) ? bm.accepted
                                                      : v.accepted;
  acc = (typeof acc === "string" ? [acc] : (acc || [])).filter(Boolean);
  if (mode !== "MP") return acc;
  const rows = v.table || [];
  const numOf = (c, k) => {
    const r = rows.find(x => x.card === c);
    return r && r[k] !== undefined && r[k] !== null ? +r[k] : null;
  };
  const impOf = c => numOf(c, "exp_imps");
  const trickOf = c => numOf(c, "avg_def_tricks");
  const tricks = rows.map(r => r.card).filter(c => trickOf(c) !== null);
  const tied = acc.slice();
  if (tricks.length) {
    const bestT = Math.max.apply(null, tricks.map(trickOf));
    for (const c of tricks)
      if (trickOf(c) >= bestT - LEAD_TIE_TRICKS && !tied.includes(c))
        tied.push(c);
  }
  if (tied.length < 2) return acc;
  const anchor = (bm && bm.recommended) || acc[0] || tied[0];
  const ref = impOf(anchor);
  if (ref === null) return acc;
  // the anchor is the recommendation: it is always accepted, and a lead that
  // is BETTER than it in the score domain is never dropped for being different
  let kept = tied.filter(c => c === anchor ||
                              (impOf(c) === null ? true
                                                 : impOf(c) >= ref - LEAD_TIE_IMP));
  if (!kept.length) return acc;
  // ...then closed upward in the trick average: the score domain may trim the
  // TAIL of the tie, never demote a lead over one it BEATS on MP's own metric.
  // Strictly better, not "at least as good": leads on the SAME average are
  // exactly the tie the score domain is there to split.
  const floor = Math.min.apply(null, kept.map(trickOf)
                                         .filter(t => t !== null));
  if (isFinite(floor))
    kept = tied.filter(c => kept.indexOf(c) >= 0 ||
                            (trickOf(c) !== null && trickOf(c) > floor));
  return kept.length ? kept : acc;
}
/* leads: MP grades tricks below best BLENDED with the matchpoint rank
   (distinct value groups — the second-best lead still beats most of the
   room); IMP grades expected IMPs below the mode's best, pure magnitude.
   No dead pin (leads have no dead concept) and no CI haircut (per-card CIs
   aren't published; ties already collapse into the accepted set at forge
   time).

   Tie invariant — "what the engine cannot distinguish, the score must not
   distinguish": cards the active mode ranks identically (same metrics to
   display precision, i.e. interchangeable leads) MUST score the same. So
   every score input is a property of the tie-GROUP, not the individual card:
   the gap is charged on the rounded metrics (equal-ranked cards share a cost,
   hence a base), and field leniency uses the group's TOTAL policy weight (the
   sum of the interchangeable cards' BEN softmax — the field's probability of
   finding that one idea) instead of the per-card softmax, which used to split
   otherwise-identical cards by a few points. The converse holds too: what the
   engine CAN distinguish — see the score-domain note above — the score must
   not merge, so in MP the tie key spans both metrics. */
function btScoreLead(P, card, mode) {
  mode = mode === "IMP" ? "IMP" : "MP";
  const v = (P && P.verdict) || {};
  const accepted = btLeadAccepted(P, mode);
  const out = {kind: "lead", mode: mode,
               unit: mode === "IMP" ? "IMP" : "לקיחות", accepted: accepted};
  if (accepted.includes(card)) { out.score = 100; return out; }
  const rows = v.table || [];
  const row = rows.find(r => r.card === card);
  if (!row) { out.score = ERROR_MIN; out.fallback = true; return out; }
  const impOf = r => (r.exp_imps === undefined || r.exp_imps === null)
    ? null : Math.round(+r.exp_imps * 100);
  const trickOf = r => (r.avg_def_tricks === undefined ? null
                        : Math.round(+r.avg_def_tricks * 100));
  // MP's objective at FULL stored precision. The tie key below deliberately
  // rounds (interchangeable leads must share a score); the monotonicity guard
  // must not, or two leads the table itself prints apart — 5.803 vs 5.795 —
  // could still be graded out of order.
  const rawTrickOf = r => (r.avg_def_tricks === undefined
                           || r.avg_def_tricks === null)
    ? null : +r.avg_def_tricks;
  const useImp = mode === "IMP" && impOf(row) !== null;
  // the tie key at DISPLAY precision (2 decimals): the mode's leading metric,
  // plus — in MP — the score domain, which the trick average cannot see
  const scored = !useImp && rows.some(r => impOf(r) !== null);
  const keyOf = useImp ? impOf
    : r => (trickOf(r) === null ? null
            : (scored ? trickOf(r) + ":" + impOf(r) : String(trickOf(r))));
  const myKey = keyOf(row);
  if (useImp) {
    let best = -Infinity;
    for (const r of rows) {
      const k = keyOf(r);
      if (k !== null && k > best) best = k;
    }
    // charge the rounded gap so equal-ranked cards get an identical cost
    out.cost = Math.max(0, (best - myKey) / 100);
    out.tau = SCORE_TAU.leadIMP;
    out.base = btCurve(out.cost, out.tau);
  } else {
    out.unit = "לקיחות";   // also the IMP-mode fallback for a row with no
                           // exp_imps: it is graded (and labeled) in tricks
    out.tau = SCORE_TAU.leadMP;
    let ref = null;
    for (const r of rows)
      if (accepted.includes(r.card)) {
        const k = impOf(r);
        if (k !== null && (ref === null || k > ref)) ref = k;
      }
    // one row's OWN charge: the trick gap, rounded to the same precision as
    // the rank grouping so a tie-group shares one cost (and thus one base),
    // or the score-domain gap when THAT is the bigger deviation, converted to
    // the trick scale by the two modes' taus. Both ends are rounded metrics,
    // so a tie-group still shares one cost.
    //
    // The trick gap is measured off avg_def_tricks — the tie key's OWN source
    // — not off the separately-rounded vs_best, which rounds to a different
    // 2nd decimal for leads whose averages round the same (1.302 / 1.298 both
    // print 1.30 yet gave 0.25 / 0.26) and split interchangeable leads by a
    // point. vs_best remains the fallback for a row with no average stored.
    let bestTrick = null;
    for (const r of rows) {
      const t = trickOf(r);
      if (t !== null && (bestTrick === null || t > bestTrick)) bestTrick = t;
    }
    const rawCost = r => {
      const o = {trick: (bestTrick !== null && trickOf(r) !== null)
        ? Math.max(0, (bestTrick - trickOf(r)) / 100)
        : Math.max(0, -Math.round((+r.vs_best || 0) * 100) / 100)};
      o.cost = o.trick;
      if (ref !== null && impOf(r) !== null) {
        o.imp = Math.max(0, (ref - impOf(r)) / 100);
        const asTricks = Math.round(o.imp * IMP_TO_TRICKS * 100) / 100;
        if (asTricks > o.cost) { o.cost = asTricks; o.source = "score"; }
      }
      return o;
    };
    const vals = [];
    for (const r of rows) {
      const q = keyOf(r);
      if (q !== null && !vals.some(g => g.key === q))
        vals.push({key: q, t: trickOf(r), i: impOf(r) === null ? 0 : impOf(r)});
    }
    vals.sort((a, b) => b.t - a.t || b.i - a.i);
    // ONE row's whole grade, before the monotonicity ceiling below.
    const gradeOf = r => {
      const p = {tau: SCORE_TAU.leadMP}, mine = rawCost(r);
      p.trickCost = mine.trick;
      if (mine.imp !== undefined) p.impCost = mine.imp;
      p.cost = mine.cost;
      if (mine.source) p.costSource = mine.source;
      p.base = btCurve(p.cost, p.tau);
      const k = keyOf(r);
      const idx = vals.findIndex(g => g.key === k);
      if (vals.length > 1 && idx >= 0) {
        p.rank = idx + 1; p.groups = vals.length;
        const rankScore = SCORE_CAP * (vals.length - 1 - idx) / (vals.length - 1);
        p.base = (1 - MP_RANK_WEIGHT) * p.base + MP_RANK_WEIGHT * rankScore;
      }
      // field leniency: the tie-group's TOTAL policy weight, so
      // interchangeable cards never split (see the tie invariant above)
      p.policy = 0;
      for (const o of rows) if (keyOf(o) === k) p.policy += +o.ben_softmax || 0;
      p.leniency = SCORE_LENIENCY * p.policy;
      p.score = Math.round(btClamp(p.base + p.leniency, 1, SCORE_MAX_NONBEST));
      return p;
    };
    const p = gradeOf(row);
    for (const k in p) out[k] = p[k];
    // The monotonicity ceiling — MP's promise, enforced. Every input above
    // can invert the trick order on its own: the charged gap is the worse of
    // two yardsticks and exp_imps is not monotone in the trick average, the
    // matchpoint rank orders tie-GROUPS (rounded metrics, score domain
    // second), and field leniency follows BEN. So each lead keeps its own
    // measured grade — nothing is re-charged for another lead's deficit —
    // but is capped at the grade of every lead that BEATS it on the trick
    // average. That is the minimum that makes the mode coherent, and it is
    // enough: cap(b) <= raw(a) and cap(b) <= cap(a) whenever a beats b.
    //
    // Accepted leads score 100 and are exactly the top of the trick order
    // (the accepted set is closed upward), so they never cap anything. Leads
    // with an EQUAL average never cap each other: that is the tie the score
    // domain is allowed to split, and interchangeable leads share a grade, so
    // they stay level either way.
    if (rawTrickOf(row) !== null)
      for (const r of rows) {
        if (rawTrickOf(r) === null || rawTrickOf(r) <= rawTrickOf(row)) continue;
        const s = accepted.includes(r.card) ? 100 : gradeOf(r).score;
        if (s < out.score) { out.score = s; out.capped = true; }
      }
    return out;
  }
  // field leniency: the tie-group's TOTAL policy weight, so interchangeable
  // cards never split (see the tie invariant above)
  out.policy = 0;
  for (const r of rows)
    if (keyOf(r) === myKey) out.policy += +r.ben_softmax || 0;
  out.leniency = SCORE_LENIENCY * out.policy;
  out.score = Math.round(btClamp(out.base + out.leniency, 1, SCORE_MAX_NONBEST));
  return out;
}
/* stored attempts: new ones carry `score`; legacy ones are approximated from
   gradedCost + outcomeClass with the base curve only (the haircut, stakes
   stretch and leniency need the problem doc, which isn't loaded here). */
function btScoreOfAttempt(a) {
  if (!a) return null;
  if (typeof a.score === "number") return a.score;
  if (a.correct) return 100;
  if (a.outcomeClass === "dead") return 0;
  const cost = +a.gradedCost || 0;
  // a recorded MISTAKE with no measured cost (the old graders left cost 0
  // when the chosen option had no table row) gets the scorers' explicit
  // no-data fallback, not a free ride up the curve at cost 0
  if (!(cost > 0)) return ERROR_MIN;
  const tau = a.kind === "lead"
    ? (a.trainingMode === "IMP" ? SCORE_TAU.leadIMP : SCORE_TAU.leadMP)
    : SCORE_TAU.bidding;
  return Math.round(btClamp(btCurve(cost, tau), 1, SCORE_MAX_NONBEST));
}
/* An attempt carries a FULL-scale score only if the grader stored one.
   btScoreOfAttempt's fallback above rebuilds a legacy attempt from the base
   curve alone -- no CI haircut, no stakes stretch, no field leniency (the
   problem doc isn't loaded here) -- so a legacy attempt reads several points
   HARSHER than the identical decision made today. Anything ordered by time
   (the dashboard's rolling window, its sparkline, its trend slope) would
   therefore drift upward on its own as the window slides off the legacy
   attempts, showing improvement nobody earned. Views that compare across
   time must filter on this. */
function btHasStoredScore(a) { return !!a && typeof a.score === "number"; }
/* ===== aggregate vocabulary =====
   BAND_HE grades ONE decision against ONE optimum, so it must never label a
   MEAN: an average of 86 can be 100/100/100/44, which is not "almost
   optimal". These four buckets describe a mean instead. ~10-point buckets
   because a narrower bucket flips between visits on sampling noise alone.
   The wording is derived, not chosen: with non-best answers averaging ~75,
   mean = 100p + 75(1-p), so the share of best answers is p = (mean-75)/25 --
   0.52 at 88 and 0.28 at 82. Hence "half" and "a quarter"; "most" would need
   ~92.5 and would overclaim. */
const AGG_MIN = [88, 78, 68];
const AGG_HE = [
  ["שיפוט מדויק", "win",
   "בכמחצית הבעיות בחרת בדיוק את הפעולה המיטבית, ובשאר היית קרוב."],
  ["שיפוט טוב", "win",
   "בכרבע מהבעיות בחרת את המיטבית, וברוב השאר היית קרוב."],
  ["שיפוט סביר", "gold",
   "כמעט תמיד בחרת אפשרות הגיונית, אך רק לעתים את המיטבית."],
  ["יש מה לחזק", "loss",
   "לצד בחירות קרובות יש גם טעויות של ממש."],
];
function btAggOf(mean) {
  for (let i = 0; i < AGG_MIN.length; i++)
    if (mean >= AGG_MIN[i]) return i;
  return AGG_MIN.length;
}
/* Contract-bid height, for the over/under-bidding detector. NOT candOrder:
   that sorts P/X/XX to 100/101/102 (above 7NT) for display purposes, so
   reusing it here would classify every Pass as an overbid. Non-contract
   calls have no height and are excluded from the comparison instead. */
function bidHeight(c) {
  if (!c || c === "P" || c === "X" || c === "XX") return null;
  const d = ["C", "D", "H", "S", "NT"].indexOf(c.slice(1));
  if (!(+c[0] >= 1) || d < 0) return null;
  return +c[0] * 10 + d;
}
/* Two-sided 95% t multiplier. The normal 1.96 is wrong when sd is ESTIMATED
   from a small sample -- at n=5 the right value is 2.776, a 42% wider
   interval -- which made the old dashboard's intervals cover ~87% where they
   claimed 95%. Table for df 1..20, then close enough to 1.96. */
const T95 = [0, 12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306,
             2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110,
             2.101, 2.093, 2.086];
function btT95(df) {
  if (df < 1) return T95[1];
  return df <= 20 ? T95[df] : 1.96 + 1.6 / df;
}
function btScoreChipHtml(score, small) {
  const band = btBandOf(score);
  if (!band) return "";
  return '<span class="scorechip tone-' + BAND_TONE[band] +
         (small ? ' sm' : '') + '" data-gloss="panel"' +
         ' aria-label="ציון ' + score + ' מתוך 100">' +
         score + '</span>';
}
/* the transparency line: how the number came to be, in Hebrew */
function btScoreExplain(parts) {
  if (!parts || parts.score === 100 || parts.dead || parts.fallback) return "";
  const bits = [];
  let gap;
  if (parts.costSource === "score")
    // the trick average did not separate the leads but the result did: say so,
    // or the line would read "פער 0.00 לקיחות" under a sub-100 score
    gap = "פער " + (+parts.impCost).toFixed(2) + " IMP בתוצאה (" +
          (+parts.trickCost).toFixed(2) + " לקיחות)";
  else
    gap = "פער " + (+parts.cost).toFixed(parts.unit === "IMP" ? 1 : 2) +
          " " + parts.unit + " מהמיטבי";
  if (parts.ci) gap += " (±" + (+parts.ci).toFixed(1) + " — חויב " +
                       (+parts.cEff).toFixed(1) + ")";
  bits.push(gap);
  if (parts.stretch > 1.05) bits.push("סולם מקל — לוח עתיר תנודה");
  else if (parts.stretch && parts.stretch < 0.95)
    bits.push("סולם מחמיר — לוח שקט");
  if (parts.rank) bits.push("מדורגת " + parts.rank + " מתוך " + parts.groups +
                            " (שקלול מצ'פוינטס)");
  if (parts.leniency >= 0.5)
    bits.push("+" + Math.round(parts.leniency) + " הקלת שדה (המנוע נתן לבחירתך " +
              Math.round(parts.policy * 100) + "%)");
  // the MP monotonicity ceiling bound: say so, or the parts above would not
  // add up to the number shown
  if (parts.capped)
    bits.push("תקרה " + parts.score +
              " — במצ'פוינטס אין ציון מעל הובלה שנותנת יותר לקיחות");
  return "מרכיבי הציון: " + bits.join(" · ");
}
/* ---- small pure display/data helpers (shared, DOM-free) --------------- */
/* HTML-escape a FREE-TEXT document field before it is interpolated into
   innerHTML (SEC-A-2). Use this for prose/opaque strings that originate
   outside our code — P.source.* (parsed from external LIN vugraph files),
   engine notes, meanings — NEVER for helpers that intentionally emit markup
   (callHtml/suitHtml/handHtml/contractHtml/terse), or you double-escape their
   glyphs. */
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}
/* A finite number or the default (BUG-5): used for CSS widths so a missing
   probability never emits `width:NaN%`. */
function safeNum(x, d) {
  const n = +x;
  return Number.isFinite(n) ? n : (d === undefined ? 0 : d);
}
/* Format a 0-1 fraction as a rounded percent, or an em dash when it is
   missing/NaN (BUG-5) — mirrors the comparison table's guard so options and
   chips never show "NaN%". */
function pct(x) {
  const n = +x;
  return Number.isFinite(n) ? Math.round(n * 100) + "%" : "—";
}
/* The accepted-call list, tolerant of every stored shape, with empty entries
   dropped so callHtml(accepted[0]) never receives undefined (BUG-4). When the
   list ends up empty it falls back to the top corrected/table row's bid, the
   same fallback gradeBidding uses, so the verdict still names a best call. */
function normAccepted(v) {
  v = v || {};
  let acc = Array.isArray(v.accepted) ? v.accepted
          : (v.toss_up ? (v.toss_up_set || []) : [v.accepted]);
  acc = (acc || []).filter(Boolean);
  if (!acc.length) {
    const fb = (v.corrected && v.corrected[0] && v.corrected[0].bid) ||
               (v.table && v.table[0] && (v.table[0].bid || v.table[0].action));
    if (fb) acc = [fb];
  }
  return acc;
}
/* ===== stored-attempt vocabulary =====
   Everything below reads a RECORDED attempt (users/{uid}/attempts/{problemId})
   rather than a problem doc. It lived in the dashboard's own script until the
   practice log (history.html) needed the same rows; it sits here, in the
   DOM-free shared block, so there is exactly one definition of "what a row
   says" and one escaping path for both pages -- and so bt-shared.js ships it
   once for the whole app instead of each page carrying a copy.
   Two call-time dependencies are declared LATER in bt-shared.js (TYPE_NAMES,
   glossHtml/routeFor). That is fine at runtime -- the whole file has executed
   before any page calls these -- and the node harness stubs them. */
const MIN_N = 5;               // a mean may be shown at all (see MIN_CI = 12)
function mean(xs) { return xs.reduce((s, x) => s + x, 0) / xs.length; }
function median(xs) {
  if (!xs.length) return 0;
  const s = [...xs].sort((a, b) => a - b), m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}
/* Hebrew number agreement: a bare "1 בעיות" reads as broken Hebrew, and these
   counts legitimately reach 1 on a new account and in sparse categories. */
function nProblems(n) { return n === 1 ? "בעיה אחת" : n + " בעיות"; }
function nDecisions(n) { return n === 1 ? "החלטה אחת" : n + " החלטות"; }
function tsMillis(a) {
  if (!a || !a.ts) return 0;
  if (typeof a.ts.toMillis === "function") return a.ts.toMillis();
  if (a.ts.seconds) return a.ts.seconds * 1000;
  return 0;
}
/* Order first-attempts by their FIRST-attempt time. A re-answer bumps `ts`
   (so incremental cross-device sync notices attemptCount updates -- DB-M-9),
   but `firstTs` is written once and never moves. Fall back to `ts` for legacy
   docs that predate firstTs -- there `ts` IS the first attempt's time. */
function firstMs(a) { return tsMillis(a && a.firstTs ? {ts: a.firstTs} : a); }
/* LAST activity on a problem: the first answer, or the latest re-answer. `ts`
   is bumped by a re-answer and `lastTs` is written alongside it (DB-M-9), so
   the max of the three is the honest "when did I last work on this".
   The practice log orders by THIS, not by firstMs: a session spent
   re-answering old problems bumps no firstTs at all, so a firstMs order would
   render that whole session invisible. */
function actMs(a) {
  return Math.max(firstMs(a), tsMillis(a),
                  tsMillis(a && a.lastTs ? {ts: a.lastTs} : null));
}
/* one definition of "which scenario is this attempt", since a missing `kind`
   means the record predates the lead trainer and is therefore a bidding one */
function attKind(a) { return (a && a.kind) === "lead" ? "lead" : "bidding"; }
function scenHe(a) { return attKind(a) === "lead" ? "הובלה" : "הכרזה"; }
function unitOf(a) {
  if (attKind(a) !== "lead") return "IMP";
  return a.trainingMode === "IMP" ? "IMP" : "לקיחה";
}
/* acceptedSet as an array, whatever the cache holds. Every stored doc carries
   an array, but a cached attempt can hold a bare string (a raw
   verdict.accepted that reached the cache), and `.join`/`.some` on it throws
   and takes the whole page down with it. Normalize at every read. */
function accOf(a) {
  const s = a && a.acceptedSet;
  return Array.isArray(s) ? s : (s ? [s] : []);
}
/* The Hebrew label for a problem type, or null when the taxonomy has no entry
   (a renamed/retired type, or a key that only resolves on Object.prototype --
   "constructor" used to print "· undefined"). Callers that must show SOMETHING
   fall back to the raw key via typeLabel; callers that would otherwise read a
   snake_case id aloud in a Hebrew UI skip it instead. */
function typeName(t) {
  return (typeof TYPE_NAMES !== "undefined"
          && Object.prototype.hasOwnProperty.call(TYPE_NAMES, t)
          && TYPE_NAMES[t]) ? TYPE_NAMES[t][0] : null;
}
function typeLabel(t) { return typeName(t) || t; }
const OUTCOME_HE = {winner: "מנצחת", "accepted-alt": "חלופה קבילה",
  dead: "אפשרות ללא סיכוי", suboptimal: "נחותה מהמיטבית"};
/* Ids still present in the pool index; attempts whose problem was deleted are
   marked "removed" instead of linking to a dead page (DB-M-9). null = unknown
   (index not loaded / unavailable) -> treat every attempt as live, as before.
   An attempt whose problem is gone can never be re-graded (the verdict it was
   scored against is gone), so it is also kept out of every aggregate. */
let LIVE_IDS = null;
function btOrphan(a) { return !!LIVE_IDS && !LIVE_IDS.has(a.problemId); }
/* A legacy attempt whose score is not a measurement at all: the old graders
   left gradedCost 0 when the chosen option had no table row, so
   btScoreOfAttempt hands back exactly ERROR_MIN for it. Inside an aggregate
   that is invisible; in a per-row LOG a column of 40s reads as a measured
   result and is not one, so the log prints "no score" for these instead. */
function btScoreIsFallback(a) {
  return !btHasStoredScore(a) && !a.correct && a.outcomeClass !== "dead"
         && !(+a.gradedCost > 0);
}
/* A legacy score that was RECONSTRUCTED from the base curve, and therefore
   reads a few points harsher than the same decision graded today. An accepted
   call (100) and a dead option (0) are exact by definition even without a
   stored score, so they are NOT approximations and must not be marked as such.
*/
function btScoreIsApprox(a) {
  return !btHasStoredScore(a) && !a.correct && a.outcomeClass !== "dead"
         && +a.gradedCost > 0;
}
/* ---- one attempt row, for both the miss list and the practice log --------
   The dashboard's miss list and the log's chronological rows differ in which
   fields they print and in their CSS box (flex vs grid), NOT in what a row
   means -- so they share this builder. That keeps ONE esc() path over
   user-owned fields (SEC-A-6), ONE removed-problem branch, and one unit
   decision for cost.
   opts: cls (row class), time (formatted; "" still emits the CELL -- see
   below), cost/outcome (booleans), replays (attemptCount), mark (extra muted
   suffix), label (aria-label).
   Attempt fields are user-owned free text -> esc() before innerHTML. */
function attemptRowHtml(m, opts) {
  const o = opts || {};
  const gone = btOrphan(m);
  const chip = o.chip === undefined ? btScoreChipHtml(btScoreOfAttempt(m), true)
                                    : o.chip;
  const cost = (o.cost && m.gradedCost)
    ? ` · ${glossHtml("cost", "עלות")} ≈ ` +
      `<span class="ltr">${(+m.gradedCost).toFixed(unitOf(m) === "IMP" ? 1 : 2)}</span> ${unitOf(m)}`
    : "";
  const acc = accOf(m);
  // "best: X" is dropped when the chosen call IS accepted -- otherwise ~45% of
  // rows print the same call twice.
  const bestTxt = (acc.length && !acc.includes(m.chosenCall))
    ? ` · מיטבי <b class="ltr">${esc(acc.join(", "))}</b>` : "";
  // the multiplier travels INSIDE the isolate, or RTL reordering prints "2×"
  const reps = +m.attemptCount > 1
    ? ` · חזרה <span class="ltr">&times;${+m.attemptCount}</span>` : "";
  // The time CELL is emitted whenever the caller asked for a time column, even
  // when this row has no timestamp (`""`). Dropping the empty cell shifts every
  // later cell one track to the left in a grid row, which crushed an undated
  // row's whole text into the 3.2em time column.
  const body = chip +
    (o.time === undefined ? ""
       : `<span class="rtime ltr">${esc(o.time)}</span>`) +
    // the space after badge() is explicit: badge ends with </span> whenever it
    // printed difficulty stars, and .stars carries no trailing margin
    `<span class="mtxt">${badge(m)} ` +
    (o.chose === false ? "" : "בחרת ") +
    `<b class="ltr">${esc(m.chosenCall)}</b>${bestTxt}` +
    (o.outcome ? ` · ${esc(OUTCOME_HE[m.outcomeClass] || m.outcomeClass)}${cost}` : "") +
    (o.replays ? reps : "") + (o.mark || "") + '</span>' +
    (gone ? '<span class="go muted">בעיה שהוסרה</span>'
          : '<span class="go" aria-hidden="true">&larr;</span>');
  const cls = o.cls || "mrow";
  // aria-label REPLACES the accessible name, so it must carry every marker the
  // visible row does (replay count, first-solved date, unsynced) -- and a
  // removed row keeps its label too: it is still a row a screen reader has to
  // make sense of, it just isn't a link.
  const lbl = o.label ? ` aria-label="${esc(o.label)}"` : "";
  return gone
    ? `<div class="${cls}" data-pid="${esc(m.problemId)}"${lbl}>${body}</div>`
    : `<a class="${cls}" data-pid="${esc(m.problemId)}"` +
      ` href="${routeFor(m.kind || "bidding", m.problemId, {retry: true})}"${lbl}>` +
      `${body}</a>`;
}
/* Scenario + type + difficulty, as one badge. The scenario is NAMED on every
   row, not just implied by the type: the two taxonomies overlap in Hebrew (a
   lead problem's type reads "סלם" and "חוזה חלקי" just like a bidding one), so
   in a list that mixes both a bare type label leaves the reader unable to tell
   an auction from a lead. A lead also names its TRAINING MODE -- MP and IMP
   leads are graded on different scales, and in a list with an aligned score
   column two such rows would otherwise look comparable.
   difficultyLevel is clamped before "★".repeat(): firestore.rules bounds the
   field count and key names but does not type-check this value. */
function badge(m) {
  const t = typeName(m.type);
  const d = Math.min(5, Math.max(0, (+m.difficultyLevel || 0) | 0));
  const mode = attKind(m) === "lead" && (m.trainingMode === "IMP" ? "IMP" : "MP");
  const lbl = scenHe(m) + (mode ? " · " + mode : "") + (t ? " · " + t : "");
  return `<span class="typebadge" style="margin:0">${lbl}</span> ` +
    (d ? `<span class="stars" style="font-size:12px" aria-hidden="true">` +
      `<span class="on">${"★".repeat(d)}</span><span class="off">` +
      `${"★".repeat(5 - d)}</span></span>` : "");
}

/* Progress + pool now live in Firestore (see web/bt-firebase.js, window.BT).
   store() returns the signed-in user's answered-problem cache synchronously
   (preloaded at sign-in); answers persist through BT.record. */
function store() { return (window.BT && window.BT.attempts()) || {}; }
async function fetchIndex() {
  if (!window.BT) throw new Error("Firebase not ready");
  return window.BT.fetchIndex();
}
/* Shared load-error panel: distinguishes an offline device from a genuine
   failure and offers a retry (the caller wires #<retryId> to re-run init),
   so a failed getProblem/fetchIndex never strands the user on a blank
   skeleton with no way out. */
function loadErrorHtml(retryId) {
  var offline = typeof navigator !== "undefined" && navigator.onLine === false;
  var em = offline ? "אין חיבור לרשת" : "הטעינה נכשלה";
  var sub = offline ? "בדוק את החיבור ונסה שוב."
                    : "משהו השתבש. אפשר לנסות שוב או לחזור לתרגול.";
  return '<div class="card state" role="alert"><div class="em">' + em +
    '</div><div class="muted">' + sub + '</div>' +
    '<button type="button" class="big" id="' + retryId + '">נסה שוב</button>' +
    '<div style="margin-top:8px"><a href="index.html">חזרה לתרגול</a></div>' +
    '</div>';
}
/* transient toast for a background failure (e.g. an attempt save that didn't
   reach the server, dispatched as bt-save-failed by web/bt-firebase.js).
   Non-blocking and auto-dismissing — the save is retried automatically. */
function btToast(msg) {
  let t = document.getElementById("bt-toast");
  if (!t) {
    t = document.createElement("div");
    t.id = "bt-toast";
    t.setAttribute("role", "status");
    t.style.cssText = "position:fixed;bottom:16px;inset-inline:0;margin:auto;" +
      "width:max-content;max-width:90%;z-index:9998;padding:10px 16px;" +
      "border-radius:10px;font-size:14px;background:var(--fg,#222);" +
      "color:var(--card,#fff);box-shadow:0 2px 10px rgba(0,0,0,.3);" +
      "transition:opacity .3s;pointer-events:none";
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.style.opacity = "1";
  clearTimeout(btToast._t);
  btToast._t = setTimeout(() => { t.style.opacity = "0"; }, 4000);
}
if (typeof window !== "undefined")
  window.addEventListener("bt-save-failed",
    () => btToast("השמירה נכשלה — ננסה שוב אוטומטית."));
/* ===== shared scroll/focus helpers (problem pages) =====
   Motion respects the OS "reduce motion" setting: a smooth glide for users
   who allow it, an instant jump for those who don't. */
function smoothOK() {
  return !(window.matchMedia &&
           window.matchMedia("(prefers-reduced-motion: reduce)").matches);
}
function scrollToEl(el, block) {
  if (!el) return;
  el.scrollIntoView({block: block || "center",
                     behavior: smoothOK() ? "smooth" : "auto"});
}
/* Only scrolls when the element isn't already fully on screen, so an already-
   visible answer area never jumps. Used on load so a fresh problem's cards +
   answer controls are in view without the user hunting for them. */
function ensureVisible(el, block) {
  if (!el) return;
  const r = el.getBoundingClientRect();
  const vh = window.innerHeight || document.documentElement.clientHeight;
  if (r.top < 0 || r.bottom > vh) scrollToEl(el, block || "nearest");
}
/* ===== central Hebrew string table: UI chrome strings live here, so new
   features add a key instead of an inline literal ===== */
const HE = {
  brand: "מאמן הברידג'",
  home: "בית", practice: "תרגול", progress: "התקדמות", account: "חשבון",
  analyze: "ניתוח יד",
  skip: "דלג לתוכן", mainNav: "ניווט ראשי", settings: "הגדרות",
  theme: "ערכת נושא", themeSystem: "מערכת", themeLight: "בהיר",
  themeDark: "כהה", textSize: "גודל טקסט", sizeS: "רגיל", sizeL: "גדול",
  sizeXL: "ענק",
  guestNote: "לא מחובר — התחבר כדי לשמור התקדמות",
  signIn: "התחבר עם Google", signOut: "התנתק", connected: "מחובר",
  close: "סגור", selectAll: "בחר הכל", clear: "נקה", problems: "בעיות",
  reportOpen: "דווח על תקלה", reportTitle: "דיווח על תקלה בבעיה",
  reportChoose: "מה לא תקין?", reportDetail: "פירוט נוסף (רשות)",
  reportSend: "שלח בוואטסאפ", reportOpened: "נפתח וואטסאפ לשליחת הדיווח",
  you: "אתה", partner: "שותף", leader: "מוביל", declarer: "מכריז",
  dummy: "דומם", vul: "פגיע", notVul: "לא פגיע",
  best: "הטוב", yours: "שלך", engine: "מנוע", wins: "זכייה",
  correct: "נכונות", level: "רמה", avgScore: "ממוצע",
  notFound: "הבעיה לא נמצאה.", backHome: "חזרה לתרגול",
};
/* role keys -> on-screen Hebrew (keys stay English: they drive styling) */
const ROLE_HE = {you: HE.you, pard: HE.partner, lead: HE.leader,
                 decl: HE.declarer, dummy: HE.dummy};
const VUL_HE = {None: "אין", NS: "צפון־דרום", EW: "מזרח־מערב",
                Both: "כולם", All: "כולם"};
function vulLabel(v) {
  return VUL_HE[String(v || "None").replace("-", "")] || VUL_HE.None;
}
/* Fixed engine footnotes (closed set) -> Hebrew */
const NOTE_HE = {
  "call meanings follow standard 2/1 game force":
    "משמעויות ההכרזות לפי שיטת 2/1 Game Force סטנדרטית.",
};
/* Bid explanations stay in the engine's English (universal bridge
   vocabulary) and render LTR via the .en/.shows styling — convention
   names are deliberately NOT translated. */
/* inline explainer for statistical jargon: tap to open the gloss card
   (title-only tooltips are unreachable on touch screens) */
function infoHtml(text) {
  return '<button type="button" class="infot" data-glosstext="' + text +
         '" aria-label="' + text + '">&#9432;</button>';
}
/* ===== tap-to-explain glossary =====
   Any element carrying data-gloss="<key>" (a GLOSS entry) or
   data-glosstext="<literal>" opens a floating explainer card above the
   bottom nav; tapping the same term again, the X, or Escape closes it. */
const GLOSS = {
  ben: ["BEN", "מנוע הכרזות מבוסס למידת מכונה (Bridge Engine). האחוז " +
    "מציין את ההסתברות שהמנוע היה בוחר בהכרזה זו."],
  imp: ["IMP", "International Match Points \u2014 סולם הניקוד במשחקי " +
    "קבוצות: הפרש הנקודות מול תוצאת הייחוס מתורגם לסולם מדורג של עד 24 " +
    "נקודות. כאן מוצג ממוצע על פני כל החלוקות המדומות."],
  mp: ["MP", "Matchpoints \u2014 ניקוד תחרות זוגות: התוצאה מושווית לכל " +
    "שאר השולחנות, וכל לקיחה משנה. בהובלה, המטרה למקסם את הלקיחות בהגנה."],
  dd: ["Double-dummy", "ניתוח ממוחשב שבו כל 52 הקלפים גלויים והמשחק " +
    "מושלם משני הצדדים \u2014 מדד ייחוס אובייקטיבי לכל חלוקה."],
  sd: ["תוצאה מתוקנת", "כל אפשרות נבדקה על אותן חלוקות מדומות התואמות " +
    "את המכרז; תיקון single-dummy מקרב את פתרון המחשב (שרואה את כל " +
    "הקלפים) למשחק אנושי, שרואה רק יד אחת ודומם."],
  panel: ["ציון", "ציון 0-100 לכל החלטה: 100 = הפעולה המיטבית או שקולה " +
    "לה; ככל שהעלות מול המיטבית גדלה הציון יורד; 0 = אפשרות שלא ניצחה " +
    "באף חלוקה מדומה."],
  ev: ["IMP צפוי", "הפער הממוצע ב-IMP מול האפשרות המיטבית, על פני כל " +
    "החלוקות המדומות. הסימן \u00b1 הוא רווח בר-סמך של 95%."],
  win: ["זכייה / שוויון / הפסד", "אחוז החלוקות המדומות שבהן האפשרות " +
    "גוברת על האפשרות המיטבית האחרת, משתווה לה, או נופלת ממנה."],
  tricks: ["לקיחות צפויות", "מספר הלקיחות הממוצע שההגנה לוקחת נגד החוזה, " +
    "על פני כל החלוקות המדומות."],
  set: ["סיכוי הכשלה", "אחוז החלוקות שבהן החוזה נכשל \u2014 המכריז לא " +
    "משיג את מספר הלקיחות הדרוש."],
  diff: ["רמת קושי", "דירוג אוטומטי מ-1 (קל) עד 5 (מומחה) לפי מורכבות " +
    "ההחלטה: גודל הפערים בין האפשרויות ורגישות התוצאה."],
  /* ----- dashboard terms (docs/dashboard_redesign_plan.md 4.8) -----
     The progress page explains its jargon the same way the problem pages do:
     tap the term, get the card. `streak` is gone with the metric it
     documented (a run of 100s punished an 84 exactly like a 12, and rewarded
     answering easy problems). */
  form: ["הטופס הנוכחי", "הציון הראשי מחושב על 50 ההחלטות האחרונות שלך " +
    "בלבד (או על כל ההחלטות, אם פתרת פחות מ-50). כך הוא מגיב לשיפור בתוך " +
    "שבוע, במקום להיתקע על ממוצע של כל הזמנים."],
  ci: ["טווח סביר", "הציון מחושב על מדגם של החלטות, ולכן אינו מדויק " +
    "לחלוטין. הטווח מציין את התחום שבו סביר שנמצא הציון האמיתי שלך. טווח " +
    "רחב = פתרת מעט בעיות."],
  agg: ["דירוג השיפוט", "תיאור מילולי של הציון הממוצע שלך. הוא מתאר את " +
    "איכות הבחירות שלך מול פתרון המנוע \u2014 ולא מול שחקנים אחרים."],
  sig: ["מגמה", "המגמה נמדדת ברגרסיה על 100 ההחלטות האחרונות. חץ שיפור " +
    "מוצג רק כשהמגמה גדולה מהתנודה הטבעית של המדידה \u2014 הפרש קטן יכול " +
    "לנבוע מהגרלת הבעיות בלבד."],
  blunders: ["טעויות חמורות", "החלטות שקיבלו ציון מתחת ל-40. בקבוצות " +
    "ובאימפים, הימנעות מתקלות היא מה שמנצח \u2014 החמצה קטנה נסלחת."],
  mix: ["פילוח התשובות", "ממוצע לבדו מסתיר את ההרכב: 85 יכול להיות 'תמיד " +
    "קרוב למיטבי' או 'מושלם לרוב, עם כמה תקלות'. הפילוח מראה איזה מהשניים."],
  scale40: ["הסולם מתחיל ב-40", "בפילוח לפי נושא הסולם מתחיל ב-40 ולא " +
    "ב-0, כדי שההבדלים בין הנושאים יהיו נראים. הנקודה מסמנת את הציון, " +
    "והפס סביבה את הטווח הסביר."],
  cost: ["מחיר הטעות", "כמה עלתה הבחירה שלך מול המיטבית \u2014 ב-IMP " +
    "בהכרזה ובהובלת IMP, ובלקיחות בהובלת מאצ'פוינטס. מוצג רק על החלטות " +
    "שבהן טעית."],
  leadrank: ["דירוג ההובלה", "באיזה מקום דורגה ההובלה שלך מבין ההובלות " +
    "האפשריות. בתחרות זוגות זה מה שקובע: הובלה שנייה-הכי-טובה עדיין " +
    "מנצחת חלק מהאולם."],
  weakspot: ["מה כדאי לחזק", "הציון בכל נושא מכווץ אל הממוצע הכללי שלך " +
    "לפי מספר הבעיות שפתרת בו, כדי שנושא עם מעט נתונים לא ייראה כחולשה. " +
    "הנושא נבחר רק אם הוא נשאר נמוך גם לאחר הכיווץ."],
  pattern: ["נטיות שחוזרות", "דפוסים שחוזרים בטעויות שלך \u2014 למשל " +
    "נטייה להכריז גבוה מהמיטבי. מוצגים רק כשהדפוס חוזר מספר פעמים " +
    "ובאופן חד-צדדי."],
  coverage: ["היקף התרגול", "כמה בעיות פתרת בכל נושא, מול מה שקיים " +
    "במאגר. נושא שכמעט לא תרגלת אינו חולשה \u2014 פשוט אין עליו מספיק " +
    "נתונים."],
  firstonly: ["ניסיון ראשון", "הלוח מציג רק את התשובה הראשונה שלך לכל " +
    "בעיה. תשובה שנייה לבעיה שראית את פתרונה היא זכירה, לא שיפוט."],
  legacy: ["עדכון שיטת הציון", "בעיות שנפתרו לפני עדכון שיטת הציון נשמרו " +
    "ללא ציון מלא, והשחזור שלהן מחמיר בכמה נקודות. כדי שלא ייראה שיפור " +
    "מדומה עם הזמן, הן אינן נכללות בציון הראשי ובגרף המגמה."],
};
let GLOSS_KEY = null;
function hideGloss() {
  GLOSS_KEY = null;
  const b = document.getElementById("glossbox");
  if (b) b.remove();
}
function showGloss(key, title, text) {
  if (GLOSS_KEY === key) { hideGloss(); return; }   // second tap closes
  hideGloss();
  GLOSS_KEY = key;
  const box = document.createElement("div");
  box.id = "glossbox";
  box.innerHTML = '<div class="glosscard" role="status"><b></b><span></span>' +
    '<button type="button" class="x" aria-label="' + HE.close +
    '">\u2715</button></div>';
  box.querySelector("b").textContent = title;
  box.querySelector("span").textContent = text;
  box.querySelector(".x").onclick = hideGloss;
  document.body.appendChild(box);
}
document.addEventListener("click", ev => {
  const g = ev.target.closest("[data-gloss], [data-glosstext]");
  if (!g) return;
  ev.preventDefault();          // gloss chips can sit inside links
  if (g.dataset.gloss) {
    const e = GLOSS[g.dataset.gloss];
    if (e) showGloss(g.dataset.gloss, e[0], e[1]);
  } else {
    showGloss(g.dataset.glosstext, "", g.dataset.glosstext);
  }
});
addEventListener("keydown", ev => { if (ev.key === "Escape") hideGloss(); });
function glossHtml(key, label) {
  return '<button type="button" class="gloss" data-gloss="' + key + '">' +
         label + '</button>';
}
/* Deal filters. Everything is selected by default: an absent key means
   "the whole pool", and selecting every option again clears the key so the
   default keeps following the pool as it grows. Only options that actually
   hold problems are ever offered. (Versioned key: the old empty-means-all
   representation is intentionally not migrated.) */
const FILTERS_KEY = "bt_filters_v2";
const ALL_LEVELS = [1, 2, 3, 4, 5];
function loadFilters() {
  try { return JSON.parse(localStorage.getItem(FILTERS_KEY)); }
  catch (e) { return null; }
}
function saveFilters(f) { localStorage.setItem(FILTERS_KEY, JSON.stringify(f)); }
/* the site splits into two scenarios; kind routes each problem + page */
function kindOf(p) { return p.kind || "bidding"; }
function routeFor(kind, id, opts) {
  let base = (kind === "lead" ? "lead.html" : "p.html") + "?id=" +
             encodeURIComponent(id);
  if (kind === "lead") base += "&mode=" + leadMode();
  // retry=1 deep-links into a clean re-attempt (skips the auto-reveal of the
  // prior answer) so the dashboard's "review" links let you practice again.
  if (opts && opts.retry) base += "&retry=1";
  return base;
}
/* Opening-lead training modes: exactly two — MP (Matchpoints) and IMPs.
   Both modes show every metric; ONLY the ranking objective differs. */
const LEAD_MODES = ["MP", "IMP"];
/* MP / IMP stay Latin (universal scoring jargon); descriptions are Hebrew */
const MODE_INFO = {
  MP:  {title: "MP", banner: "MATCHPOINTS",
        subtitle: "עדיפות למקסימום לקיחות בהגנה",
        goal: "המטרה: למקסם את מספר הלקיחות הצפוי בהגנה."},
  IMP: {title: "IMP", banner: "IMPs",
        subtitle: "עדיפות להפרשי תוצאה גדולים",
        goal: "המטרה: למקסם את ערך ה־IMP הצפוי מהתוצאה הסופית."},
};
const LEAD_MODE_KEY = "bt_lead_mode";
function leadMode() {
  return localStorage.getItem(LEAD_MODE_KEY) === "IMP" ? "IMP" : "MP";
}
function setLeadMode(m) {
  localStorage.setItem(LEAD_MODE_KEY, m === "IMP" ? "IMP" : "MP");
}
/* which training modes an index row / problem doc supports; legacy
   tricks-only records are MP-only */
function problemModes(p) {
  if (Array.isArray(p.modes) && p.modes.length) return p.modes;
  if (p.training && p.training.modes) {
    const m = LEAD_MODES.filter(k => p.training.modes[k]);
    if (m.length) return m;
  }
  return ["MP"];
}
/* which mode's generator FORGED a lead problem (whose gates selected it).
   The generator is split by mode, and each section serves its own pool;
   legacy and pre-split records were all selected by the MP (tricks) gates. */
function targetModeOf(p) {
  const t = p.target_mode || (p.training && p.training.target_mode);
  return t === "IMP" ? "IMP" : "MP";
}
/* which levels/types exist for a scenario right now, and how many each holds.
   Bidding facets on difficulty x type; leads on difficulty only. */
function poolFacets(index, kind) {
  kind = kind || "bidding";
  const levelCount = {}, typeCount = {};
  for (const p of index.problems) {
    if (kindOf(p) !== kind) continue;
    if (kind === "lead" && targetModeOf(p) !== leadMode()) continue;
    if (p.difficulty_level)
      levelCount[p.difficulty_level] = (levelCount[p.difficulty_level] || 0) + 1;
    if (p.type) typeCount[p.type] = (typeCount[p.type] || 0) + 1;
  }
  return {
    levels: ALL_LEVELS.filter(l => levelCount[l]),
    types: Object.keys(TYPE_NAMES).filter(t => typeCount[t]),
    levelCount, typeCount,
  };
}
/* PERF-F-6: precompute all pool counts in ONE pass so each filter interaction
   derives its facets/tallies in O(levels x types) instead of re-scanning the
   whole ~20k-row index 5-7 times. Keyed by scenario ("bidding" / "lead:MP" /
   "lead:IMP") so leadMode() only selects a key at read time. Per key:
     total       - problems in that scenario
     levelTotal  - {level: count} regardless of type (matches poolFacets)
     typeTotal   - {type: count} regardless of level (matches poolFacets)
     matrix      - {level: {type: count}} (both set) for cross-faceted counts */
function countsKey(kind, mode) {
  return kind === "lead" ? "lead:" + (mode || leadMode()) : "bidding";
}
function buildCounts(index) {
  const out = {};
  for (const p of (index && index.problems) || []) {
    const key = countsKey(kindOf(p), targetModeOf(p));
    const c = out[key] || (out[key] =
      {total: 0, levelTotal: {}, typeTotal: {}, matrix: {}});
    c.total++;
    const l = p.difficulty_level, t = p.type;
    if (l) c.levelTotal[l] = (c.levelTotal[l] || 0) + 1;
    if (t) c.typeTotal[t] = (c.typeTotal[t] || 0) + 1;
    if (l && t) {
      const m = c.matrix[l] || (c.matrix[l] = {});
      m[t] = (m[t] || 0) + 1;
    }
  }
  return out;
}
function emptyCount() {
  return {total: 0, levelTotal: {}, typeTotal: {}, matrix: {}};
}
/* poolFacets(index, kind) equivalent, from the precomputed counts */
function facetsFrom(counts, kind, mode) {
  const c = (counts && counts[countsKey(kind, mode)]) || emptyCount();
  return {
    levels: ALL_LEVELS.filter(l => c.levelTotal[l]),
    types: Object.keys(TYPE_NAMES).filter(t => c.typeTotal[t]),
    levelCount: c.levelTotal, typeCount: c.typeTotal,
  };
}
/* facetCounts(index, flt) equivalent (cross-faceted): a level counts only the
   currently-selected types, a type only the currently-selected levels */
function facetCountsFrom(counts, flt) {
  const c = (counts && counts[countsKey(flt.kind, flt.mode)]) || emptyCount();
  const selTypes = new Set(flt.types), selLevels = new Set(flt.levels);
  const levelCount = {}, typeCount = {};
  for (const l in c.matrix) {
    const inLevel = selLevels.has(+l);
    for (const t in c.matrix[l]) {
      const n = c.matrix[l][t];
      if (selTypes.has(t)) levelCount[l] = (levelCount[l] || 0) + n;
      if (inLevel) typeCount[t] = (typeCount[t] || 0) + n;
    }
  }
  return {levelCount, typeCount};
}
/* total problems in a scenario (poolFacets-free kindTotal / scen totals) */
function scenTotal(counts, kind, mode) {
  const c = counts && counts[countsKey(kind, mode)];
  return c ? c.total : 0;
}
/* turn stored (or absent) filters into concrete selected sets. A stored
   selection is sanitized against the CURRENT pool: values that no longer
   exist are dropped, and an axis that ends up empty falls back to "all" (the
   pool default). This heals a stale/corrupt saved filter — e.g. an empty
   `levels` (difficulty cleared, or an older string-vs-number format) that
   matches no problems and would otherwise strand the home page on "0 of N"
   with every category showing a 0 count. Coercion (Number/String) makes the
   match robust to legacy filters that stored levels as strings. */
function resolveFilters(index, raw, kind) {
  kind = kind || "bidding";
  const f = poolFacets(index, kind);
  const base = raw || {};
  const pick = (stored, all, coerce) => {
    if (!Array.isArray(stored)) return all.slice();
    const allow = new Set(all);
    const kept = stored.map(coerce).filter(v => allow.has(v));
    return kept.length ? kept : all.slice();
  };
  return {
    kind,
    mode: kind === "lead" ? leadMode() : null,
    levels: pick(base.levels, f.levels, Number),
    types: pick(base.types, f.types, String),
  };
}
function matchesFilters(p, f) {
  if (kindOf(p) !== (f.kind || "bidding")) return false;
  // each lead section serves its own generator's pool: MP shows boards the
  // MP (tricks) gates selected, IMP shows boards the IMP gates selected —
  // so legacy tricks-only records never appear in (or get ranked by) IMP.
  if (f.kind === "lead" &&
      targetModeOf(p) !== (f.mode || leadMode())) return false;
  if (!f.levels.includes(p.difficulty_level)) return false;
  return f.types.includes(p.type);            // both scenarios: difficulty + type
}
function pickUnseen(index, filters) {
  const s = store();
  const f = filters || resolveFilters(index, loadFilters());
  const unseen = index.problems.filter(p => !s[p.id] && matchesFilters(p, f));
  if (!unseen.length) return null;
  return unseen[Math.floor(Math.random() * unseen.length)].id;
}
/* Prefetch the NEXT problem after an answer so the "next" tap navigates
   instantly: the chosen id + its doc are stashed in sessionStorage, and the
   destination page consumes the doc (takePrefetch) instead of a fresh read. */
const PREFETCH_KEY = "bt_prefetch";
function readPrefetch() {
  try { return JSON.parse(sessionStorage.getItem(PREFETCH_KEY)); }
  catch (e) { return null; }
}
function takePrefetch(id) {
  const pf = readPrefetch();
  try { sessionStorage.removeItem(PREFETCH_KEY); } catch (e) { /* */ }
  return (pf && pf.id === id && pf.doc) ? pf.doc : null;
}
async function prefetchNext(index, filters) {
  try {
    if (!index) return;
    const nid = pickUnseen(index, filters);
    if (!nid) { sessionStorage.removeItem(PREFETCH_KEY); return; }
    const doc = await window.BT.getProblem(nid);
    if (doc) sessionStorage.setItem(PREFETCH_KEY,
      JSON.stringify({ id: nid, doc }));
  } catch (e) { /* prefetch is best-effort */ }
}
/* BBO four-color deck */
// each glyph carries VS15 (U+FE0E) so Android/Samsung fonts render the TEXT
// suit symbol, not a colour emoji — otherwise CSS `color` wouldn't apply and
// the four-colour scheme would break (UX-A-6).
const SUITS = {S: ["ss", "\u2660\uFE0E"], H: ["sh", "\u2665\uFE0E"],
               D: ["sd", "\u2666\uFE0E"], C: ["sc", "\u2663\uFE0E"]};
function suitHtml(st) {
  const [cls, g] = SUITS[st];
  return `<span class="${cls}">${g}</span>`;
}
function glyphify(text) {
  return text.replace(/!([SHDC])/g, (_, st) => suitHtml(st));
}
function callHtml(tok) {
  if (tok === "P") return "פאס";
  if (tok === "X") return "כפל";
  if (tok === "XX") return "כפל כפליים";
  const denom = tok.slice(1);
  if (denom === "NT") return tok;
  return tok[0] + suitHtml(denom);
}
function contractHtml(tok) {
  const m = /^(\d)([CDHSN])([NESW])$/.exec(tok);
  if (!m) return tok;
  if (m[2] === "N") return `${m[1]}NT ${m[3]}`;
  return m[1] + suitHtml(m[2]) + m[3];
}
/* terse BBO alert string from an engine convention card
   {text, hcp:[lo,hi], minlen:{S,H,D,C}} — mirrors engine/explain.py */
function terse(card, call) {
  if (!card) return "";
  const denom = (call && !["P", "X", "XX"].includes(call))
    ? call.slice(1) : null;
  const raw = (card.text || "").replace(/--/g, ";");
  let name = null; const tsuits = [];
  for (const part of raw.split(";")) {
    const p = part.trim().replace(/[.]+$/, "");
    if (!p) continue;
    const low = p.toLowerCase();
    // drop a few non-informative fragments; mirrors engine/explain.py
    // _FILLER_PARTS. GIB's names are already canonical, so this is minimal.
    if (["artificial", "forcing", "bidable suit", "calculated bid"]
        .includes(low))
      continue;
    if (low === "balanced") {
      if (denom !== "NT" && !name) name = "Balanced";
      continue;
    }
    if (/\d+\s*(\+|-\s*\d+)?\s*HCP/i.test(p)) continue;
    const m = /^(\d+)\s*\+?\s*!?([SHDC])$/.exec(p);
    if (m) { tsuits.push([+m[1], m[2]]); continue; }
    // keep the whole convention name — do NOT drop long ones (RKC Blackwood,
    // Lebensohl after double); that cap is what left conventions unexplained.
    if (!name) name = p;
  }
  const byst = {};
  for (const st of "SHDC") {
    const v = (card.minlen || {})[st] || 0;
    if (v >= 4 || (v === 3 && st === denom)) byst[st] = v;
  }
  for (const [v, st] of tsuits) if (v > (byst[st] || 0)) byst[st] = v;
  const suits = Object.entries(byst)
    .sort((a, b) => b[1] - a[1] || "SHDC".indexOf(a[0]) - "SHDC".indexOf(b[0]))
    .slice(0, 2);
  if (name)
    for (const [st] of suits)
      if (name.endsWith(" to !" + st))
        name = name.slice(0, -(" to !" + st).length);
  const frags = [];
  if (name) frags.push(glyphify(name));
  const maxlen = card.maxlen || {};
  for (const [st, v] of suits) {
    const mx = (maxlen[st] === undefined) ? 13 : maxlen[st];
    if (v <= mx && mx < 13)
      frags.push((v === mx ? v : v + "-" + mx) + suitHtml(st));
    else frags.push(v + "+" + suitHtml(st));
  }
  // a one-point band is the single number it is, not a range: GIB emits
  // "9-9"/"24-24" where its rule pinned the count, and printing that as a
  // RANGE claimed a precision the source never had. A band with no floor is
  // an upper bound and says so ("10-", the mirror of "10+") — "0-10" claimed
  // a floor of zero GIB never stated. Mirrors explain._band.
  const band = (lo, hi) =>
    (lo === hi ? String(lo) : (lo <= 0 ? hi + "-" : lo + "-" + hi));
  const hcp = card.hcp;
  const pts = card.pts;
  let hcpFloor = 0;
  if (hcp) {
    const [lo, hi] = hcp;
    hcpFloor = lo;
    if (hi >= 25) { if (lo > 0) frags.push(lo + "+"); }
    else frags.push(band(lo, hi));
  }
  // the total-points band shows when GIB gave no HCP band at all — without
  // this a limited pass ("No suitable call -- 8- total points") rendered with
  // no range whatsoever, which read as a missing explanation — and ALSO when
  // the HCP band has no floor while the points band does, so an upper-bound
  // gloss ("10- HCP") keeps the floor the seat's earlier bidding promised.
  // Mirrors engine/explain.py.
  if (pts && (!hcp || (hcpFloor <= 0 && pts[0] > 0))) {
    const [lo, hi] = pts;
    if (hi >= 25) { if (lo > 0) frags.push(lo + "+ pts"); }
    else frags.push(band(lo, hi) + " pts");
  }
  return frags.join(", ");
}
/* Fold what a seat has ALREADY shown into the card of its later call.
   GIB glosses each call alone, so an upper-bound-only clause ("21- HCP" on a
   reverse) arrives as [0, 21] and used to render "0-21" two calls after the
   same seat's opening rendered "11-21". A hand does not change during the
   auction: its constraints intersect (highest floor, lowest ceiling). Only
   hand facts accumulate — name/gloss/forcing describe THIS call — and where
   two glosses cannot both hold, this call's own wins.
   Mirrors explain.merge_promises. */
function mergePromises(prev, card) {
  card = card || {};
  if (!prev) return Object.assign({}, card);
  const tighten = (a, b) => {
    if (!a || !b) return b || (a ? [a[0], a[1]] : null);
    const lo = Math.max(a[0], b[0]), hi = Math.min(a[1], b[1]);
    return lo <= hi ? [lo, hi] : [b[0], b[1]];
  };
  const out = Object.assign({}, card);
  out.hcp = tighten(prev.hcp, card.hcp);
  out.pts = tighten(prev.pts, card.pts);
  const minlen = Object.assign({}, card.minlen || {});
  const maxlen = Object.assign({}, card.maxlen || {});
  for (const st of "SHDC") {
    const lo = Math.max(minlen[st] || 0, (prev.minlen || {})[st] || 0);
    const pmx = (prev.maxlen || {})[st];
    const hi = Math.min(maxlen[st] === undefined ? 13 : maxlen[st],
                        pmx === undefined ? 13 : pmx);
    if (lo > hi) continue;   // contradictory glosses — this call's own stands
    if (lo) minlen[st] = lo;
    if (hi < 13) maxlen[st] = hi;
  }
  out.minlen = minlen; out.maxlen = maxlen;
  return out;
}
/* Accumulated card per entry of an explanations list ({seat, card}, in
   auction order); `dealer` covers legacy entries that carry no seat. */
function accumCards(entries, dealer) {
  const seats = ["N", "E", "S", "W"];
  const state = {}, out = [];
  (entries || []).forEach((e, j) => {
    const st = (e && e.seat) ||
      seats[(Math.max(0, seats.indexOf(dealer)) + j) % 4];
    state[st] = mergePromises(state[st], (e && e.card) || {});
    out.push(state[st]);
  });
  return out;
}
/* Everything one seat has shown over `entries` — the state a further call by
   that seat (an offered option) is merged into.
   Mirrors explain.seat_promises. */
function seatPromises(entries, dealer, seat) {
  const seats = ["N", "E", "S", "W"];
  let state = null;
  (entries || []).forEach((e, j) => {
    const st = (e && e.seat) ||
      seats[(Math.max(0, seats.indexOf(dealer)) + j) % 4];
    if (st === seat) state = mergePromises(state, (e && e.card) || {});
  });
  return state;
}
function vulSeats(vul) {
  const v = String(vul || "None").replace("-", "");
  if (v === "NS") return "NS";
  if (v === "EW") return "EW";
  if (v === "Both" || v === "All") return "NESW";
  return "";
}
function handHtml(hand) {
  const parts = hand.split(".");
  return ["S", "H", "D", "C"].map((s, i) => {
    const cards = (parts[i] || "").split("").map(
      c => `<span class="cd">${c === "T" ? "10" : c}</span>`).join("");
    return `<div class="srow">${suitHtml(s)} ${cards || "\u2014"}</div>`;
  }).join("");
}
/* Full deal laid out by table position: North on top, West/East on the
   sides, South at the bottom, a compass in the middle. `roles` maps a seat
   to a short label ("you", "pard", "lead", "decl", "dummy"); "you"/"lead"
   get the hero highlight. */
function fullDealHtml(deal, roles) {
  roles = roles || {};
  function cell(s) {
    const parts = (deal[s] || "").split(".");
    const rows = ["S", "H", "D", "C"].map((st, i) => {
      const cards = (parts[i] || "").split("").map(
        c => `<span class="cd">${c === "T" ? "10" : c}</span>`).join("");
      return `<div class="fdrow">${suitHtml(st)} ${cards || "\u2014"}</div>`;
    }).join("");
    const role = roles[s] || "";
    const hero = role === "you" || role === "lead" ? " hero" : "";
    return `<div class="fd fd-${s.toLowerCase()}">` +
      `<div class="fdhand${hero}"><div class="lbl"><span>${s}</span>` +
      `<span class="role">${ROLE_HE[role] || ""}</span></div>${rows}</div></div>`;
  }
  const compass = `<div class="fdcompass" aria-hidden="true">` +
    `<span class="cn">N</span><span class="cw">W</span>` +
    `<span class="ce">E</span><span class="cs">S</span></div>`;
  return `<div class="fulldeal">${cell("N")}${cell("W")}${compass}` +
         `${cell("E")}${cell("S")}</div>`;
}
/* Fixed W-N-E-S auction diagram (BBO layout), shared by both trainers.
   Vulnerability lives on the seat plates (red = vulnerable, green = not).
   opts:
     hero            seat that gets the "me" highlight
     roleOf(seat)    the seat's Hebrew role label ("" for none)
     noteOf(n)       maps notes[j] -> truthy when the call is tappable
                     (default: the entry itself)
     pendingCell     append a trailing "?" cell (bidding: next call is yours)
     highlightFinal  add "fin" to the last non-pass call (lead: the contract) */
function auctionTable(p, notes, opts) {
  opts = opts || {};
  const cols = ["W", "N", "E", "S"];
  const vul = vulSeats(p.vul);
  const head = cols.map(s => {
    const cls = (vul.includes(s) ? "v" : "nv") + (s === opts.hero ? " me" : "");
    const who = (opts.roleOf && opts.roleOf(s)) || "";
    const vlab = vul.includes(s) ? HE.vul : HE.notVul;
    return `<th class="${cls}" title="${s} \u2014 ${vlab}">${s}` +
           `${s === p.dealer ? '<sup class="d">D</sup>' : ""}` +
           `${who ? `<small>${who}</small>` : "<small>&nbsp;</small>"}</th>`;
  }).join("");
  let lastBid = -1;
  if (opts.highlightFinal)
    p.auction.forEach((t, j) => {
      if (t !== "P" && t !== "X" && t !== "XX") lastBid = j;
    });
  const cells = [];
  for (let i = 0; i < cols.indexOf(p.dealer); i++) cells.push("<td></td>");
  p.auction.forEach((tok, j) => {
    const note = notes && notes[j] &&
      (opts.noteOf ? opts.noteOf(notes[j]) : notes[j]);
    const fin = (opts.highlightFinal && j === lastBid) ? " fin" : "";
    cells.push(`<td><span class="call${note ? " expl" : ""}${fin}"` +
               ` data-i="${j}">${callHtml(tok)}</span></td>`);
  });
  if (opts.pendingCell) cells.push('<td class="turn">?</td>');
  while (cells.length % 4) cells.push("<td></td>");
  let rows = "";
  for (let i = 0; i < cells.length; i += 4)
    rows += "<tr>" + cells.slice(i, i + 4).join("") + "</tr>";
  return `<table class="bidding"><tr>${head}</tr>${rows}</table>`;
}
/* bidding page: hero is you, partner labelled, pending "?" cell for your turn;
   every non-empty note marks its call tappable. */
function auctionTableHtml(p, notes) {
  const seats = ["N", "E", "S", "W"];
  const hero = p.seat, partner = seats[(seats.indexOf(hero) + 2) % 4];
  return auctionTable(p, notes, {
    hero,
    roleOf: s => s === hero ? HE.you : (s === partner ? HE.partner : ""),
    pendingCell: true,
  });
}
function cardHtml(tok) {  // "SK" -> four-colour suit glyph + rank (T -> 10)
  const r = tok[1] === "T" ? "10" : tok[1];
  return suitHtml(tok[0]) + " " + r;
}
/* opening-lead page: a COMPLETE auction — hero is the leader, declarer/dummy
   labelled, no pending cell, the final contract call highlighted, and a call
   tappable when its note carries a card or text. */
function completeAuctionTableHtml(p, notes) {
  const seats = ["N", "E", "S", "W"];
  const hero = p.leader, decl = p.declarer;
  const dummy = seats[(seats.indexOf(decl) + 2) % 4];
  return auctionTable(p, notes, {
    hero,
    roleOf: s => s === hero ? HE.leader : (s === decl ? HE.declarer
              : (s === dummy ? HE.dummy : "")),
    noteOf: n => n && (n.card || n.text),
    highlightFinal: true,
  });
}
function candOrder(c) {
  if (c === "P") return 100;
  if (c === "X") return 101;
  if (c === "XX") return 102;
  return +c[0] * 10 + ["C", "D", "H", "S", "NT"].indexOf(c.slice(1));
}
/* classification display names (ids: engine/classify.py taxonomy) */
const TYPE_NAMES = (typeof window !== "undefined" && window.TAXONOMY_HE) || {};
const DIFF_NAMES = ["", "קל", "בינוני", "מאתגר", "קשה", "מומחה"];
/* Hebrew suit + card names for screen-reader labels (glyphs stay four-color) */
const SUIT_NAME_HE = {S: "עלה", H: "לב", D: "יהלום", C: "תלתן"};
const RANK_NAME_HE = {A: "אס", K: "מלך", Q: "מלכה", J: "נסיך", T: "10"};
function cardLabel(tok) {
  const r = RANK_NAME_HE[tok[1]] || tok[1];
  return r + " " + (SUIT_NAME_HE[tok[0]] || "");
}
function callLabel(tok) {
  if (tok === "P") return "פאס";
  if (tok === "X") return "כפל";
  if (tok === "XX") return "כפל כפליים";
  const denom = tok.slice(1);
  if (denom === "NT") return tok[0] + " ללא שליט";
  return tok[0] + " " + (SUIT_NAME_HE[denom] || denom);
}
function typeBadgeHtml(p) {
  const t = p.classification && p.classification.type;
  const nm = TYPE_NAMES[t];
  if (!nm) return "";
  return `<div><button type="button" class="typebadge" ` +
    `data-glosstext="${nm[1]}">${nm[0]}</button></div>`;
}
function diffLineHtml(p) {
  const lv = p.classification && p.classification.difficulty_level;
  if (!lv || lv < 1 || lv > 5) return "";
  return glossHtml("diff", "רמת קושי") +
    `<span class="stars" role="img" aria-label="רמת קושי ${lv} מתוך 5">` +
    `<span class="on">${"\u2605".repeat(lv)}</span>` +
    `<span class="off">${"\u2605".repeat(5 - lv)}</span></span>` +
    `<b>${DIFF_NAMES[lv]} (${lv}/5)</b>`;
}

/* ===== report a problem =====
   A discreet flag in the topbar of every problem page opens a bottom sheet
   (reusing the .sheet/.panel pattern) where the user picks a fault type,
   optionally adds free text, and sends the report over WhatsApp. No backend:
   we build a wa.me deep link and open it. Both scenarios (bidding/lead) wire
   the same openReport() from their init(), passing a context getter so the
   currently-chosen answer (if any) is captured at open time. */
const REPORT_PHONE = "972547918413";
const REPORT_REASONS = [
  "הכרזה לא הגיונית",
  "הסבר לא מתאים להכרזה",
  "חסרה אפשרות הכרזה",
  "ניקוד לא הגיוני",
  "ניתוח יד לא הגיוני",
  "באג בתוכנה",
];
/* scenario + Hebrew classification label, e.g. "הכרזה · יד גבולית" */
function reportTypeLabel(p) {
  const scen = kindOf(p) === "lead" ? "הובלה" : "הכרזה";
  const t = (p.classification && p.classification.type) || p.type;
  const nm = TYPE_NAMES[t];
  return nm ? scen + " \u00b7 " + nm[0] : scen;
}
let _reportSheet = null, _reportCtx = null, _reportReason = null;
function buildReportSheet() {
  if (_reportSheet) return _reportSheet;
  const sheet = document.createElement("div");
  sheet.className = "sheet"; sheet.id = "report";
  sheet.setAttribute("role", "dialog"); sheet.setAttribute("aria-modal", "true");
  sheet.setAttribute("aria-label", HE.reportTitle);
  const chips = REPORT_REASONS.map((r, i) =>
    `<button type="button" class="repchip" data-i="${i}" ` +
    `aria-pressed="false">${r}</button>`).join("");
  sheet.innerHTML =
    '<div class="panel">' +
    '<h2>' + HE.reportTitle + '</h2>' +
    '<p class="muted" id="rep-meta"></p>' +
    '<div class="setrow" style="flex-direction:column;align-items:stretch">' +
    '<span>' + HE.reportChoose + '</span>' +
    '<div class="repchips" id="rep-chips">' + chips + '</div></div>' +
    '<label class="setrow" style="flex-direction:column;align-items:stretch">' +
    '<span>' + HE.reportDetail + '</span>' +
    '<textarea id="rep-text" class="reptext" rows="3"></textarea></label>' +
    '<button type="button" class="sendbtn" id="rep-send" disabled>' +
    HE.reportSend + '</button>' +
    '<button type="button" class="closebtn" id="rep-close">' + HE.close +
    '</button></div>';
  document.body.appendChild(sheet);
  const chipsEl = sheet.querySelector("#rep-chips");
  const sendBtn = sheet.querySelector("#rep-send");
  function close() { sheet.classList.remove("open"); }
  chipsEl.addEventListener("click", ev => {
    const b = ev.target.closest(".repchip"); if (!b) return;
    _reportReason = REPORT_REASONS[+b.dataset.i];
    chipsEl.querySelectorAll(".repchip").forEach(x =>
      x.setAttribute("aria-pressed", x === b ? "true" : "false"));
    sendBtn.disabled = false;
  });
  sheet.querySelector("#rep-close").onclick = close;
  sheet.addEventListener("click", ev => { if (ev.target === sheet) close(); });
  addEventListener("keydown", ev => {
    if (ev.key === "Escape" && sheet.classList.contains("open")) close();
  });
  sendBtn.onclick = () => {
    if (!_reportReason || !_reportCtx) return;
    const c = _reportCtx;
    const lines = [
      "דיווח על תקלה \u2014 " + HE.brand,
      "מזהה בעיה: " + c.id,
      "סוג הבעיה: " + c.type,
    ];
    if (c.answer) lines.push("התשובה שנבחרה: " + c.answer);
    lines.push("התקלה: " + _reportReason);
    const extra = (sheet.querySelector("#rep-text").value || "").trim();
    if (extra) lines.push("פירוט: " + extra);
    lines.push("קישור: " + c.url);
    const url = "https://wa.me/" + REPORT_PHONE + "?text=" +
      encodeURIComponent(lines.join("\n"));
    window.open(url, "_blank", "noopener");
    close();
    btToast(HE.reportOpened);
  };
  _reportSheet = sheet;
  return sheet;
}
/* ctx: {id, type, url, answer} or a function returning it (evaluated on open,
   so the chosen answer reflects the current attempt state). */
function openReport(ctx) {
  const sheet = buildReportSheet();
  _reportCtx = (typeof ctx === "function") ? ctx() : ctx;
  _reportReason = null;
  sheet.querySelector("#rep-send").disabled = true;
  sheet.querySelectorAll(".repchip").forEach(x =>
    x.setAttribute("aria-pressed", "false"));
  sheet.querySelector("#rep-text").value = "";
  sheet.querySelector("#rep-meta").textContent = "מזהה: " + _reportCtx.id;
  sheet.classList.add("open");
}
/* reveal the topbar report flag (hidden until a problem loads) and wire it to
   the given context getter. Called from each problem page's init(). */
function wireReport(ctxFn) {
  const btn = document.getElementById("report-open");
  if (!btn) return;
  btn.hidden = false;
  btn.setAttribute("aria-label", HE.reportOpen);
  btn.setAttribute("title", HE.reportOpen);
  btn.onclick = () => openReport(ctxFn);
}

/* ===== app chrome: theme/text-size, global nav, settings sheet =====
   Injected on every page so there is no per-template markup to maintain.
   Theme + scale are applied immediately to limit flash-of-wrong-theme. */
function applyTheme() {
  const t = localStorage.getItem("bt_theme") || "system";
  const s = localStorage.getItem("bt_scale") || "s";
  const h = document.documentElement;
  if (t === "system") h.removeAttribute("data-theme");
  else h.setAttribute("data-theme", t);
  if (s === "s") h.removeAttribute("data-scale");
  else h.setAttribute("data-scale", s);
}
applyTheme();
/* practice-session progress (a 10-problem run started from the home page) */
function getSession() {
  let s;
  try { s = JSON.parse(localStorage.getItem("bt_session")); }
  catch (e) { return null; }
  // expire a stale run (paused hours ago) so its counter/summary don't leak
  // into a new day's answers (UX-I-6)
  if (s && s.startedAt && Date.now() - s.startedAt > SESSION_TTL_MS) {
    localStorage.removeItem("bt_session");
    return null;
  }
  return s;
}
function bumpSession(score, id, kind) {
  const s = getSession();
  if (!s) return;
  // only count answers from THIS run's scenario: a lead answered from a direct
  // link must not be tallied into a paused bidding run (UX-I-6)
  if (kind && s.kind && kind !== s.kind) return;
  s.count = (s.count || 0) + 1;
  const scored = typeof score === "number";
  if (scored) { s.sum = (s.sum || 0) + score;
                s.scored = (s.scored || 0) + 1; }
  if (score >= 100) s.right = (s.right || 0) + 1;
  // per-problem trail so the end-of-run summary can link the review items
  (s.items = s.items || []).push({id: id || null,
                                  score: scored ? score : null});
  localStorage.setItem("bt_session", JSON.stringify(s));
  renderSessRibbon();
}
function renderSessRibbon() {
  const el = document.getElementById("sessribbon");
  if (!el) return;
  const s = getSession();
  if (!s || !s.size) { el.hidden = true; return; }
  const done = Math.min(s.count || 0, s.size);
  el.hidden = false;
  // a session begun before the panel score shipped has no score trail yet —
  // fall back to its correct count rather than a bogus average
  const tail = s.scored
    ? HE.avgScore + ' <b>' + Math.round(s.sum / s.scored) + '</b>'
    : (s.right || 0) + ' ' + HE.correct;
  el.innerHTML =
    '<span>תרגול \u00b7 ' + done + '/' + s.size + '</span>' +
    '<span class="prog"><span style="width:' + Math.round(100 * done / s.size) +
    '%"></span></span>' +
    '<span>' + tail + '</span>';
}
/* bottom-nav icons: inline SVG (glyph fonts render inconsistently) */
const ICO = {
  spade: '<svg viewBox="0 0 24 24" width="22" height="22"' +
    ' fill="currentColor" aria-hidden="true"><path d="M12 2C9 7 4 9.5 4' +
    ' 13.5 4 16 6 18 8.5 18c1 0 1.9-.3 2.6-.9-.3 1.6-1 2.9-2.1' +
    ' 3.9h6c-1.1-1-1.8-2.3-2.1-3.9.7.6 1.6.9 2.6.9C18 18 20 16 20 13.5 20' +
    ' 9.5 15 7 12 2z"/></svg>',
  chart: '<svg viewBox="0 0 24 24" width="22" height="22"' +
    ' fill="currentColor" aria-hidden="true"><rect x="4" y="12" width="4"' +
    ' height="8" rx="1"/><rect x="10" y="7" width="4" height="13" rx="1"/>' +
    '<rect x="16" y="10" width="4" height="10" rx="1"/></svg>',
  gear: '<svg viewBox="0 0 24 24" width="22" height="22" fill="none"' +
    ' stroke="currentColor" stroke-width="2" stroke-linecap="round"' +
    ' aria-hidden="true"><circle cx="12" cy="12" r="3.2"/>' +
    '<path d="M12 2.8v3M12 18.2v3M2.8 12h3M18.2 12h3M5.5 5.5l2.1 2.1' +
    'M16.4 16.4l2.1 2.1M18.5 5.5l-2.1 2.1M7.6 16.4l-2.1 2.1"/></svg>',
  scope: '<svg viewBox="0 0 24 24" width="22" height="22" fill="none"' +
    ' stroke="currentColor" stroke-width="2" stroke-linecap="round"' +
    ' aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.2"/>' +
    '<path d="M15.2 15.2 21 21M8 10.5h5M10.5 8v5"/></svg>',
};
const NAV_ITEMS = [
  {id: "practice", href: "index.html", ico: ICO.spade, label: HE.home},
  {id: "analyze", href: "analyze.html", ico: ICO.scope, label: HE.analyze},
  {id: "progress", href: "dashboard.html", ico: ICO.chart, label: HE.progress},
];
function initChrome() {
  if (document.getElementById("gnav")) return;
  const active = document.body.dataset.nav || "";
  // skip link -> main
  const skip = document.createElement("a");
  skip.className = "skip"; skip.href = "#main";
  skip.textContent = HE.skip;
  document.body.insertBefore(skip, document.body.firstChild);
  // bottom nav
  const nav = document.createElement("nav");
  nav.className = "gnav"; nav.id = "gnav";
  nav.setAttribute("aria-label", HE.mainNav);
  const links = NAV_ITEMS.map(it =>
    `<a href="${it.href}" ${it.id === active ? 'aria-current="page"' : ""}>` +
    `<span class="ico" aria-hidden="true">${it.ico}</span>${it.label}</a>`).join("");
  nav.innerHTML = `<div class="navwrap">${links}` +
    `<button type="button" class="navbtn" id="nav-account">` +
    `<span class="ico" aria-hidden="true">${ICO.gear}</span>` +
    `<span id="nav-account-lbl">${HE.account}</span></button></div>`;
  document.body.appendChild(nav);
  // settings sheet
  const sheet = document.createElement("div");
  sheet.className = "sheet"; sheet.id = "settings"; sheet.setAttribute("role", "dialog");
  sheet.setAttribute("aria-modal", "true"); sheet.setAttribute("aria-label", HE.settings);
  sheet.innerHTML =
    '<div class="panel">' +
    '<h2>' + HE.settings + '</h2>' +
    '<div class="setrow"><span>' + HE.theme + '</span>' +
    '<span class="segctl" id="ctl-theme">' +
    '<button type="button" data-v="system">' + HE.themeSystem + '</button>' +
    '<button type="button" data-v="light">' + HE.themeLight + '</button>' +
    '<button type="button" data-v="dark">' + HE.themeDark + '</button></span></div>' +
    '<div class="setrow"><span>' + HE.textSize + '</span>' +
    '<span class="segctl" id="ctl-scale">' +
    '<button type="button" data-v="s">' + HE.sizeS + '</button>' +
    '<button type="button" data-v="l">' + HE.sizeL + '</button>' +
    '<button type="button" data-v="xl">' + HE.sizeXL + '</button></span></div>' +
    '<div class="setrow" id="acct-row"><span id="acct-name">' + HE.account + '</span>' +
    '<button type="button" class="alllink" id="acct-btn"></button></div>' +
    '<button type="button" class="closebtn" id="settings-close">' + HE.close + '</button>' +
    '</div>';
  document.body.appendChild(sheet);
  function syncCtl(id, val) {
    document.querySelectorAll("#" + id + " button").forEach(b =>
      b.setAttribute("aria-pressed", b.dataset.v === val ? "true" : "false"));
  }
  syncCtl("ctl-theme", localStorage.getItem("bt_theme") || "system");
  syncCtl("ctl-scale", localStorage.getItem("bt_scale") || "s");
  document.getElementById("ctl-theme").onclick = ev => {
    const b = ev.target.closest("button"); if (!b) return;
    localStorage.setItem("bt_theme", b.dataset.v); applyTheme(); syncCtl("ctl-theme", b.dataset.v);
  };
  document.getElementById("ctl-scale").onclick = ev => {
    const b = ev.target.closest("button"); if (!b) return;
    localStorage.setItem("bt_scale", b.dataset.v); applyTheme(); syncCtl("ctl-scale", b.dataset.v);
  };
  function refreshAcct() {
    // sign-in is REQUIRED (no guest mode): when signed in, show the account;
    // otherwise (only the brief pre-ready window or a transient sign-out, both
    // behind the full-screen gate) offer a sign-in affordance — never a
    // misleading "guest" claim (BUG-8).
    const u = window.BT && window.BT.user();
    const nameEl = document.getElementById("acct-name");
    const btn = document.getElementById("acct-btn");
    const navLbl = document.getElementById("nav-account-lbl");
    if (u) {
      nameEl.textContent = (u.displayName || u.email) || HE.connected;
      btn.textContent = HE.signOut;
      btn.onclick = () => window.BT.signOut();
      if (navLbl) navLbl.textContent =
        (u.displayName ? u.displayName.split(" ")[0] : HE.account);
    } else {
      nameEl.textContent = HE.guestNote;   // "not signed in — sign in to save"
      btn.textContent = HE.signIn;
      // swallow the rejection doSignIn() throws on a real failure so it isn't
      // an unhandled rejection (the gate shows its own error UI).
      btn.onclick = () => {
        const p = window.BT && window.BT.signIn();
        if (p && p.catch) p.catch(() => {});
      };
      if (navLbl) navLbl.textContent = HE.account;
    }
  }
  refreshAcct();
  renderSessRibbon();
  addEventListener("bt-user-changed", refreshAcct);
  function openSheet(o) { sheet.classList.toggle("open", o); }
  document.getElementById("nav-account").onclick = () => openSheet(true);
  document.getElementById("settings-close").onclick = () => openSheet(false);
  sheet.addEventListener("click", ev => { if (ev.target === sheet) openSheet(false); });
  addEventListener("keydown", ev => { if (ev.key === "Escape") openSheet(false); });
}
if (document.readyState !== "loading") initChrome();
else addEventListener("DOMContentLoaded", initChrome);
