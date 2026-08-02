
/* ===== progress dashboard =====
   One hero number; everything else behind a labelled, collapsed heading whose
   summary already carries the payoff value. Design notes and the reasoning
   behind the statistics live in docs/dashboard_redesign_plan.md. */
/* MIN_N, the attempt vocabulary (firstMs/attKind/accOf/badge/...) and the
   shared attempt-row builder live in _SCORE_JS (bt-shared.js), because the
   practice log (history.js) renders the same rows. */
const MIN_CI = 12;       // an interval appears, and the cell may drive advice
const MIN_LABEL = 20;    // a cell may be NAMED the weakest
const MIN_TREND = 20;    // the trend slope appears
const HERO_WIN = 5 * SESSION_SIZE;   // hero window: 50 first attempts
const TREND_WIN = 100;   // slope is fitted over at most this many
const DOM_LO = 40;       // category-row domain floor (= ERROR_MIN)
const H_FLOOR = 2;       // DISPLAY guard only: never print "76-76"
const OPEN_KEY = "bt_dash_open", AGG_KEY = "bt_dash_agg";
const SUIT_NAME = {S: "עלה", H: "לב", D: "יהלום", C: "תלתן"};
function num(x) { return typeof x === "number" ? x : (parseFloat(x) || 0); }
/* Mean panel score with a 95% interval on the mean. Uses the t multiplier,
   not 1.96: sd is ESTIMATED from the sample, and at small n the normal
   multiplier makes the interval far too narrow (it covered ~87% while
   claiming 95%). No variance floor -- flooring sd was cosmetic, it changed
   coverage by less than a decimal. Instead no interval at all is SHOWN below
   MIN_CI (see rowHtml): an honest absence beats a fabricated width. */
function meanCI(xs) {
  const n = xs.length, m = mean(xs);
  const sd = n > 1
    ? Math.sqrt(xs.reduce((s, x) => s + (x - m) * (x - m), 0) / (n - 1)) : 0;
  const h = n > 1 ? Math.max(btT95(n - 1) * sd / Math.sqrt(n), H_FLOOR) : null;
  return {m, sd, n, h,
          lo: h === null ? m : Math.max(0, m - h),
          hi: h === null ? m : Math.min(100, m + h)};
}
/* tsMillis / firstMs / LIVE_IDS / btOrphan: see _SCORE_JS (bt-shared.js). */
let POOL_BY_TYPE = null;   // pool counts per problem type, for coverage

/* ---- fixed-slot open/closed state -------------------------------------- */
function loadOpen() {
  try { return new Set(JSON.parse(localStorage.getItem(OPEN_KEY)) || []); }
  catch (e) { return new Set(); }
}
function saveOpen(set) {
  try { localStorage.setItem(OPEN_KEY, JSON.stringify([...set])); }
  catch (e) { /* private mode */ }
}

/* ---- the score bar chart: dot + interval on a clipped domain ------------
   The track is an AXIS (a 1px rule of uniform width on every row), not a
   bar, so nothing invites a length comparison across rows.
   Named domPct, not pct: bt-shared.js already declares a pct() percent
   formatter, and a second top-level `function pct` here silently shadowed it
   app-wide on this page. Two page scripts sharing a global scope must not
   collide -- see test_no_shared_function_name_is_shadowed. */
function domPct(score) {
  return btClamp((score - DOM_LO) / (100 - DOM_LO) * 100, 0, 100);
}
function axisCapHtml(cols) {
  return '<div class="rcap"><span>' + cols + '</span><span class="ax">' +
    [DOM_LO, REVIEW_MIN, 100].map(v =>
      `<span style="inset-inline-start:${domPct(v)}%">${v}</span>`).join("") +
    '</span><span></span><span></span></div>';
}
function rowHtml(label, scores, opts) {
  const o = opts || {}, n = scores.length;
  if (n < MIN_N) return "";
  const c = meanCI(scores), m = Math.round(c.m);
  const showCI = n >= MIN_CI;
  let marks = [DOM_LO, 100].map(v =>
    `<i class="rtick" style="inset-inline-start:${domPct(v)}%"></i>`).join("") +
    `<i class="rthr" style="inset-inline-start:${domPct(REVIEW_MIN)}%"></i>`;
  if (showCI) {
    const lo = domPct(c.lo), hi = domPct(c.hi);
    marks += `<i class="rci" style="inset-inline-start:${lo}%;` +
             `width:${Math.max(0, hi - lo)}%"></i>`;
  }
  marks += c.m < DOM_LO
    ? '<i class="runder">◂</i>'
    : `<i class="rdot${showCI ? "" : " thin"}" ` +
      `style="inset-inline-start:${domPct(c.m)}%"></i>`;
  return `<div class="rrow${c.m < NEAR_MIN ? " low" : ""}">` +
    `<span class="rlbl">${label}</span>` +
    `<span class="rtrack" role="img" aria-label="ציון ${m}` +
      (showCI ? `, טווח ${Math.round(c.lo)} עד ${Math.round(c.hi)}` : "") +
      `, ${nDecisions(n)}">${marks}</span>` +
    `<span class="rval">${m}</span><span class="rn">${n}</span></div>`;
}
/* Rows for one breakdown, plus one aggregate line for everything too sparse
   to score. Returns null when no cell qualifies, so the caller can skip the
   whole sub-section instead of shipping a heading whose payoff is "no data". */
function rowGroup(groups, opts) {
  const rows = [], thin = [];
  for (const g of groups) {
    if (g.scores.length >= MIN_N) rows.push({g, html: rowHtml(g.label, g.scores, opts)});
    else if (g.scores.length) thin.push(g);
  }
  if (!rows.length && !thin.length) return null;
  let html = rows.length ? axisCapHtml(opts && opts.cols || "נושא") : "";
  html += rows.map(r => r.html).join("");
  if (thin.length)
    html += `<div class="rmore">עוד ${thin.length} ` +
      (thin.length === 1 ? "נושא" : "נושאים") +
      ` עם פחות מ-${MIN_N} החלטות — עדיין ללא ציון.</div>`;
  if (!rows.length) return {html, worst: null, any: false};
  let worst = null;
  for (const r of rows) {
    const m = mean(r.g.scores);
    if (!worst || m < worst.m) worst = {m, label: r.g.label, n: r.g.scores.length};
  }
  return {html, worst, any: true};
}
function worstSum(g) {
  if (!g || !g.worst) return "";
  const w = g.worst;
  // the wording carries the epistemic status: only a well-sampled cell earns
  // the word "weakest"
  const lead = w.n >= MIN_LABEL ? "החלש ביותר" : "הנמוך עד כה";
  return `${lead}: ${w.label} ${Math.round(w.m)}`;
}

/* ---- grouping helpers -------------------------------------------------- */
function byType(list) {
  const by = new Map();
  for (const a of list) {
    const t = a.type;
    if (!t) continue;
    if (!by.has(t)) by.set(t, []);
    by.get(t).push(btScoreOfAttempt(a));
  }
  return [...by.entries()]
    .sort((x, y) => y[1].length - x[1].length)
    .map(([t, scores]) => ({key: t, label: typeLabel(t), scores}));
}
function byDiff(list) {
  const by = {};
  for (const a of list) {
    const d = a.difficultyLevel;
    if (!d) continue;
    (by[d] ??= []).push(btScoreOfAttempt(a));
  }
  return [1, 2, 3, 4, 5].filter(d => by[d])
    .map(d => ({key: String(d), label: DIFF_NAMES[d] || ("רמה " + d),
                scores: by[d]}));
}

/* ---- empirical-Bayes shrinkage for "what should I practise" ------------
   Ranking ~15 small samples and taking the minimum is the batting-average
   problem: the argmin is usually the noisiest cell, not the weakest. A
   one-sided SE haircut applied once does not fix that (it still names a false
   weakness on roughly 40% of null category sets). So shrink each category
   mean toward the overall mean by n/(n+k), with k estimated from the observed
   between- vs within-category variance, and rank -- and DISPLAY -- the shrunk
   value. With no real signal every cell collapses to the overall mean and the
   fallback ladder fires; a genuine hole at decent n survives. */
function shrink(groups, overall) {
  const elig = groups.filter(g => g.scores.length >= MIN_N);
  if (elig.length < 2) return [];
  let wss = 0, wdf = 0;
  for (const g of elig) {
    const m = mean(g.scores);
    for (const s of g.scores) wss += (s - m) * (s - m);
    wdf += g.scores.length - 1;
  }
  const within = wdf > 0 ? wss / wdf : 0;          // pooled within-cell var
  const ms = elig.map(g => mean(g.scores));
  const gm = mean(ms);
  const spread = elig.length > 1
    ? ms.reduce((s, m) => s + (m - gm) * (m - gm), 0) / (elig.length - 1) : 0;
  const noise = mean(elig.map(g => within / g.scores.length));
  const between = Math.max(0, spread - noise);     // real variance between
  const k = between > 0 ? within / between : Infinity;
  return elig.map(g => {
    const n = g.scores.length, raw = mean(g.scores);
    const w = k === Infinity ? 0 : n / (n + k);
    return {...g, n, raw, adj: overall + w * (raw - overall), weight: w,
            diffMean: g.diffMean};
  });
}

/* ---- pattern detectors -------------------------------------------------
   Three ship. A fourth ("leads passively from own longest suit") needs the
   player's hand, which no attempt document stores. */
function patterns(first) {
  const out = [];
  const bid = first.filter(a => (a.kind || "bidding") !== "lead");
  const lead = first.filter(a => a.kind === "lead");
  // 1. pass bias -- exact, no height arithmetic and no exclusions
  let passive = 0, pushy = 0;
  for (const a of bid) {
    const acc = accOf(a);
    if (a.chosenCall === "P" && !acc.includes("P")) passive++;
    else if (a.chosenCall !== "P" && acc.includes("P")) pushy++;
  }
  if (passive + pushy >= 8 && Math.max(passive, pushy) >= 2 * Math.min(passive, pushy))
    out.push(passive > pushy
      ? {w: passive, txt: `מ-${passive + pushy} טעויות הכרזה שבהן פאס היה ` +
         `הגורם המבדיל, ב-${passive} פאסת כשהיה צריך להכריז. אתה נוטה לפאסיביות.`}
      : {w: pushy, txt: `מ-${passive + pushy} טעויות הכרזה שבהן פאס היה ` +
         `הגורם המבדיל, ב-${pushy} הכרזת כשפאס היה המיטבי. אתה נוטה להיכנס יותר מדי.`});
  // 2. lead: wrong suit vs wrong card. Tested against acceptedSet, not a
  // single recommended card -- acceptedSet can span several suits, and using
  // one card would misfile right-suit-wrong-card and INVERT the finding.
  let wrongSuit = 0, wrongCard = 0;
  for (const a of lead) {
    if (btScoreOfAttempt(a) >= 100) continue;
    const acc = accOf(a);
    if (!acc.length || !a.chosenCall) continue;
    if (acc.some(c => c[0] === a.chosenCall[0])) wrongCard++; else wrongSuit++;
  }
  if (wrongSuit + wrongCard >= 12)
    out.push({w: Math.max(wrongSuit, wrongCard),
      txt: `מ-${wrongSuit + wrongCard} טעויות הובלה, ב-${wrongSuit} בחרת את ` +
        `הסדרה הלא נכונה וב-${wrongCard} את הקלף הלא נכון בסדרה הנכונה. ` +
        (wrongSuit > wrongCard ? "בחירת הסדרה היא הבעיה, לא הטכניקה."
                               : "בחירת הסדרה טובה — חדד את הקלף בתוך הסדרה.")});
  // 3. bidding height. bidHeight() returns null for P/X/XX, so those attempts
  // drop out of the comparison rather than being counted as overbids.
  let high = 0, low = 0;
  for (const a of bid) {
    if (btScoreOfAttempt(a) >= 100) continue;
    const acc = accOf(a);
    if (acc.length !== 1) continue;
    const mine = bidHeight(a.chosenCall), best = bidHeight(acc[0]);
    if (mine === null || best === null) continue;
    if (mine > best) high++; else if (mine < best) low++;
  }
  const hl = high + low;
  if (hl >= 15 && Math.max(high, low) / hl >= 0.65)
    out.push({w: Math.max(high, low),
      txt: high > low
        ? `מ-${hl} טעויות הכרזה שניתן להשוות בגובה, ב-${high} הכרזת גבוה ` +
          `מהמיטבי. אתה נוטה להגזים בהכרזה.`
        : `מ-${hl} טעויות הכרזה שניתן להשוות בגובה, ב-${low} הכרזת נמוך ` +
          `מהמיטבי. אתה נוטה להיות שמרן מדי.`});
  // 4. difficulty cliff
  const easy = first.filter(a => a.difficultyLevel && a.difficultyLevel <= 3)
    .map(btScoreOfAttempt);
  const hard = first.filter(a => a.difficultyLevel && a.difficultyLevel >= 4)
    .map(btScoreOfAttempt);
  if (easy.length >= MIN_CI && hard.length >= MIN_CI) {
    const de = mean(easy), dh = mean(hard);
    if (de - dh > 12)
      out.push({w: Math.round(de - dh),
        txt: `על בעיות קלות ובינוניות הציון שלך ${Math.round(de)} ` +
          `(${nProblems(easy.length)}), ועל מאתגרות ומעלה ${Math.round(dh)} ` +
          `(${nProblems(hard.length)}).`});
    else if (dh - de > 6)
      out.push({w: Math.round(dh - de),
        txt: `דווקא על הבעיות הקלות הציון שלך ${Math.round(de)}, ` +
          `מול ${Math.round(dh)} על הקשות — שווה לבדוק חיפזון.`});
  }
  return out.sort((a, b) => b.w - a.w);
}

/* ---- trend: OLS slope, not a window-vs-window comparison ---------------
   Comparing two rolling windows by CI non-overlap is about alpha=0.005, so a
   real 10-point gain -- months of work -- would be acknowledged less than
   half the time while the caption asserted flatness. A slope over every point
   in the last TREND_WIN uses all the data, needs no window pairing, and says
   something more useful than an arrow. */
function trendOf(chrono) {
  const xs = chrono.slice(-TREND_WIN);
  const n = xs.length;
  if (n < MIN_TREND) return null;
  const ys = xs.map(btScoreOfAttempt);
  const mx = (n - 1) / 2, my = mean(ys);
  let sxy = 0, sxx = 0;
  for (let i = 0; i < n; i++) { sxy += (i - mx) * (ys[i] - my); sxx += (i - mx) * (i - mx); }
  const b = sxx > 0 ? sxy / sxx : 0;
  let sse = 0;
  for (let i = 0; i < n; i++) {
    const fit = my + b * (i - mx);
    sse += (ys[i] - fit) * (ys[i] - fit);
  }
  const se = n > 2 && sxx > 0 ? Math.sqrt(sse / (n - 2) / sxx) : Infinity;
  const h = btT95(n - 2) * se;
  return {n, per100: b * 100, lo: (b - h) * 100, hi: (b + h) * 100,
          sig: se !== Infinity && (b - h) * (b + h) > 0, ys};
}
function sparkHtml(tr) {
  const ys = tr.ys, n = ys.length;
  // rolling mean, so the line shows level rather than per-answer noise
  const win = Math.max(8, Math.min(20, Math.round(n / 2)));
  const roll = ys.map((_, i) => {
    const lo = Math.max(0, i - win + 1);
    return mean(ys.slice(lo, i + 1));
  });
  // padded dynamic domain with a minimum span, so a genuinely stable player
  // gets a flat line instead of amplified noise
  let lo = Math.min(...roll) - 5, hi = Math.max(...roll) + 5;
  if (hi - lo < 20) { const c = (hi + lo) / 2; lo = c - 10; hi = c + 10; }
  lo = Math.max(0, lo); hi = Math.min(100, hi);
  const W = 300, H = 44, span = hi - lo || 1;
  const y = v => H - (v - lo) / span * H;
  const step = roll.length > 1 ? W / (roll.length - 1) : W;
  const path = roll.map((v, i) =>
    `${i ? "L" : "M"}${(i * step).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const thr = REVIEW_MIN >= lo && REVIEW_MIN <= hi
    ? `<line x1="0" y1="${y(REVIEW_MIN).toFixed(1)}" x2="${W}" ` +
      `y2="${y(REVIEW_MIN).toFixed(1)}" stroke="var(--line)" stroke-width="1" ` +
      'vector-effect="non-scaling-stroke"></line>' : "";
  const last = roll[roll.length - 1];
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" dir="ltr" role="img" ` +
    `aria-label="מגמת הציון על ${n} ההחלטות האחרונות">` + thr +
    `<path d="${path}" fill="none" stroke="var(--data)" stroke-width="2" ` +
    'stroke-linejoin="round" stroke-linecap="round" ' +
    'vector-effect="non-scaling-stroke"></path>' +
    `<circle cx="${W}" cy="${y(last).toFixed(1)}" r="4" fill="var(--data)" ` +
    'stroke="var(--card)" stroke-width="2"></circle></svg>';
}

/* ---- hero -------------------------------------------------------------- */
function heroHtml(scored, legacyN, goneN, pendingN) {
  const n = scored.length;
  const chrono = [...scored].sort((a, b) => firstMs(a) - firstMs(b));
  const win = chrono.slice(-HERO_WIN);
  const ws = win.map(btScoreOfAttempt);
  const c = meanCI(ws), m = Math.round(c.m);
  const lifetime = mean(chrono.map(btScoreOfAttempt));
  const small = win.length < MIN_N;
  // label hysteresis: a stationary player's label otherwise flips on ~10% of
  // sessions (16% near an edge). Only cross a bucket edge by the interval's
  // own half-width, else keep the label already shown.
  let idx = btAggOf(c.m);
  try {
    const prev = JSON.parse(localStorage.getItem(AGG_KEY));
    if (prev && typeof prev.i === "number" && prev.i !== idx && c.h) {
      const edge = idx < prev.i ? AGG_MIN[idx] : AGG_MIN[prev.i];
      if (Math.abs(c.m - edge) < c.h) idx = prev.i;
    }
    if (!small && win.length >= MIN_CI)
      localStorage.setItem(AGG_KEY, JSON.stringify({i: idx}));
  } catch (e) { /* private mode */ }
  const agg = AGG_HE[idx];
  const showAgg = !small && win.length >= MIN_CI;
  // scope, difficulty mix and scenario mix are all disclosures, not decoration:
  // min(50, n) silently changes what the number MEANS, the score does not
  // normalise for how hard the winner is to find, and the three scenarios are
  // graded on three different taus.
  const scope = win.length >= HERO_WIN
    ? `על ${HERO_WIN} הבעיות האחרונות`
    : `על כל ${nProblems(win.length)} שפתרת`;
  const dls = win.filter(a => a.difficultyLevel > 0);
  const dmix = dls.length >= win.length * 0.8
    ? `${glossHtml("diff", "ממוצע קושי")} ${mean(dls.map(a => +a.difficultyLevel)).toFixed(1)}`
    : "";
  const nLead = win.filter(a => a.kind === "lead").length;
  const smix = win.length
    ? `${Math.round((win.length - nLead) / win.length * 100)}% הכרזה · ` +
      `${Math.round(nLead / win.length * 100)}% הובלה` : "";
  const blunders = ws.filter(s => s < ERROR_MIN).length;
  // the RATE, not a run: a blunder-free run length is geometric, so its sd
  // equals its mean -- the noisiest number on the page, dressed as an integer
  const bl = `${glossHtml("blunders", "טעויות חמורות")} ${blunders} ` +
             `מתוך ${win.length}`;
  const ok = ws.filter(s => s >= REVIEW_MIN).length;
  const mid = ws.filter(s => s >= ERROR_MIN && s < REVIEW_MIN).length;
  const tr = trendOf(chrono);
  let trendHtml = "";
  if (tr) {
    const d = tr.per100, arrow = tr.sig
      ? (d > 0 ? '<i class="up">▲</i> ' : '<i class="down">▼</i> ') : "";
    trendHtml = sparkHtml(tr) + '<div class="trendline">' +
      glossHtml("sig", "מגמה") + " · " + arrow +
      (tr.sig
        ? `${d > 0 ? "+" : ""}${d.toFixed(0)} נקודות ל-100 בעיות ` +
          `<span class="ltr">(${tr.lo.toFixed(0)}–${tr.hi.toFixed(0)})</span>`
        : "עוד לא מספיק נתונים כדי לזהות מגמה") + '</div>';
  }
  return '<div class="card hero">' +
    `<div class="hnum${small ? " small" : ""}">${small ? "—" : m}</div>` +
    (showAgg
      ? `<button type="button" class="hagg tone-${agg[1]}" data-gloss="agg">` +
        `${agg[0]}</button><div class="haggtxt">${agg[2]}</div>`
      : `<div class="haggtxt">מדגם קטן — עוד לא מוצג דירוג שיפוט</div>`) +
    '<div class="railax">' + [0, DOM_LO, REVIEW_MIN, 100].map(v =>
      `<span style="inset-inline-start:${v}%">${v}</span>`).join("") + '</div>' +
    `<div class="rail" role="img" aria-label="ציון ממוצע ${m} מתוך 100">` +
      (small ? "" : `<i class="rfill" style="width:${btClamp(c.m, 0, 100)}%"></i>`) +
      (c.h !== null
        ? `<i class="rband" style="inset-inline-start:${c.lo}%;` +
          `width:${Math.max(0, c.hi - c.lo)}%"></i>` : "") +
      `<i class="rlife" style="inset-inline-start:${btClamp(lifetime, 0, 100)}%"></i>` +
      (small ? "" : `<i class="rmark" style="inset-inline-start:${btClamp(c.m, 0, 100)}%"></i>`) +
    '</div>' +
    '<div class="hsub">' +
      `<span>${glossHtml("form", "הטופס הנוכחי")} ${scope}</span>` +
      (c.h !== null
        ? `<span>${glossHtml("ci", "טווח סביר")} ` +
          `<b class="ltr">${Math.round(c.lo)}–${Math.round(c.hi)}</b></span>` : "") +
      (dmix ? `<span>${dmix}</span>` : "") +
      (smix ? `<span>${smix}</span>` : "") +
      `<span>${bl}</span>` +
    '</div>' +
    mixHtml(ok, mid, blunders, win.length) +
    trendHtml +
    '<div class="hdisc">' + glossHtml("panel", "ציון ממוצע") +
    ' 0–100. הציון מודד את בחירותיך מול פתרון המנוע על הבעיות שפתרת ' +
    '— לא מול שחקנים אחרים. ' + glossHtml("firstonly", "ניסיון ראשון") +
    ' בלבד.' +
    (legacyN
      ? ` ${glossHtml("legacy", "לא נכללות")} ${nProblems(legacyN)} שנפתרו לפני ` +
        `עדכון שיטת הציון.` : "") +
    (goneN
      ? ` ${legacyN ? "וכן" : glossHtml("legacy", "לא נכללות")} ` +
        `${nProblems(goneN)} שהוסרו מהמאגר — הציון שלהן לא ניתן לחישוב מחדש.`
      : "") +
    // an answer still queued locally is history the server has never seen, so
    // no regrade or sync can settle its score — say so rather than let it pass
    // for a confirmed grade
    (pendingN
      ? ` <b>${nDecisions(pendingN)}</b> עדיין לא נשמרו לענן, כך שהציון שלהן ` +
        `לא אושר מול השרת.` : "") +
    '</div></div>';
}
function mixHtml(ok, mid, bad, n) {
  if (!n) return "";
  const p = v => Math.round(v / n * 100);
  const seg = (cls, v) => v ? `<i class="s-${cls}" style="flex:${v}"></i>` : "";
  return `<div class="mix" role="img" aria-label="${p(ok)}% בציון 85 ומעלה, ` +
    `${p(mid)}% בין 40 ל-84, ${p(bad)}% מתחת ל-40">` +
    seg("ok", ok) + seg("mid", mid) + seg("bad", bad) + '</div>' +
    '<div class="mixkey">' + glossHtml("mix", "פילוח") +
    `<span><i class="sw ok"></i>מיטבי או קרוב <b class="ltr">${p(ok)}%</b></span>` +
    `<span><i class="sw mid"></i>סטייה <b class="ltr">${p(mid)}%</b></span>` +
    `<span><i class="sw bad"></i>טעות חמורה <b class="ltr">${p(bad)}%</b></span>` +
    '</div>';
}

/* ---- what to practise next -------------------------------------------- */
function weakArea(first, scen) {
  // eligible units are SKILL-named only. Difficulty is deliberately excluded:
  // docs/classification.md defines level 5 as the probability a competent
  // club player gets it wrong, so a low score there is what "level 5" MEANS.
  const groups = [];
  const push = (list, href, suffix) => {
    for (const g of byType(list)) {
      const withDiff = list.filter(a => a.type === g.key && a.difficultyLevel > 0);
      groups.push({...g, label: g.label + (suffix || ""),
        href, key: g.key,
        diffMean: withDiff.length ? mean(withDiff.map(a => +a.difficultyLevel)) : null});
    }
  };
  push(scen.bidding, "index.html?kind=bidding&type=");
  push(scen.lead, "index.html?kind=lead&type=");
  const all = first.map(btScoreOfAttempt);
  if (!all.length) return null;
  const overall = mean(all);
  const adj = shrink(groups, overall);
  // recent activity, for the cooldown
  const recent = [...first].sort((a, b) => firstMs(b) - firstMs(a)).slice(0, 20);
  const recentBy = {};
  for (const a of recent) if (a.type) recentBy[a.type] = (recentBy[a.type] || 0) + 1;
  const answered = new Set(first.map(a => a.problemId));
  const poolLeft = t => {
    if (!POOL_BY_TYPE) return Infinity;
    const e = POOL_BY_TYPE.get(t);
    if (!e) return 0;
    let k = 0;
    for (const id of e.ids) if (!answered.has(id)) k++;
    return k;
  };
  const ranked = adj
    .filter(g => g.n >= MIN_CI)
    .filter(g => (recentBy[g.key] || 0) < 8)          // cooldown
    .filter(g => poolLeft(g.key) >= SESSION_SIZE)      // pool guard
    .sort((a, b) => a.adj - b.adj);
  const hit = ranked.find(g => g.adj < overall - 3);
  if (hit) {
    const dm = hit.diffMean
      ? ` בקושי ממוצע ${hit.diffMean.toFixed(1)}` : "";
    // "the rest" must exclude this category, or the comparison quietly
    // includes the very cell it is comparing against and understates the gap
    const rest = first.filter(a => a.type !== hit.key).map(btScoreOfAttempt);
    const restTxt = rest.length
      ? `, לעומת ${Math.round(mean(rest))} בשאר הנושאים` : "";
    return {kind: "weak", label: hit.label,
      why: `ציון ${Math.round(hit.adj)} על ${nProblems(hit.n)}${dm}${restTxt}.`,
      href: hit.href + hit.key};
  }
  // fallback (a): coverage. A barely-practised topic is not a weakness, and
  // saying so is a true statement at low n.
  const thin = groups.filter(g => g.scores.length < 8)
    .filter(g => poolLeft(g.key) >= SESSION_SIZE)
    .sort((a, b) => a.scores.length - b.scores.length)[0];
  if (thin)
    return {kind: "coverage", label: thin.label,
      why: `פתרת בו ${nProblems(thin.scores.length)} בלבד — עוד לא מספיק ` +
           `כדי לדעת אם זו חולשה.`,
      href: thin.href + thin.key};
  return null;
}

/* ---- render ------------------------------------------------------------ */
/* OUTCOME_HE, attKind/scenHe/unitOf/accOf/badge and the attempt-row builder
   itself now live in _SCORE_JS (bt-shared.js): the practice log renders the
   same rows, and one builder means one esc() path over user-owned fields
   (SEC-A-6) and one removed-problem branch (DB-M-9) for both pages.
   A miss row IS that builder with severity turned on -- the outcome label and
   the cost of the error are the subject of this list, which is exactly what
   the chronological log leaves off. */
function missRowHtml(m, compact) {
  return attemptRowHtml(m, {cost: !compact, outcome: !compact});
}
/* ---- which misses get a row --------------------------------------------
   Both miss lists cover BOTH scenarios, with their slots DEALT OUT between
   them. Pooling the two into one ordered list and cutting it at a cap does
   not work, because the two score scales are not built to the same shape:
   a bidding call that is a dead option is pinned to 0 and any other is charged
   on tau = 2.0 IMP, while a lead has no dead concept, is charged on
   tau = 0.6 tricks blended 35% with its matchpoint rank, and therefore bottoms
   out far higher. Sorted together, the bidding tail filled every slot from the
   bottom and the lead misses fell off the end -- both lists showed a user who
   had apparently never mis-led a hand. So each scenario is ordered WITHIN its
   own scale and the two queues take turns.
   Score still orders each queue (never gradedCost: the units differ). */
const MISS_CAP = 30;      // rows in the full list
function missesOf(list) {
  return list.filter(a => btScoreOfAttempt(a) < REVIEW_MIN)
    .sort((a, b) => btScoreOfAttempt(a) - btScoreOfAttempt(b) ||
                    firstMs(b) - firstMs(a));
}
/* Round-robin over the per-scenario queues, worst first within each. Queue
   order is the page's section order (bidding, then lead) rather than "whichever
   scenario's worst row scores lower" -- that would be the cross-scale
   comparison this function exists to avoid, and a fixed order keeps the list
   from reshuffling between visits. A scenario with nothing left simply yields
   its turns, so a user who has only ever bid still fills the cap. */
function pickMisses(list, cap) {
  const qs = [missesOf(list.filter(a => attKind(a) === "bidding")),
              missesOf(list.filter(a => attKind(a) === "lead"))]
    .filter(q => q.length);
  const out = [];
  while (out.length < cap && qs.some(q => q.length))
    for (const q of qs)
      if (q.length && out.length < cap) out.push(q.shift());
  return out;
}
/* number agreement, as for nProblems/nDecisions: the card genuinely holds one
   row on a new account, where "1 החלטות לחזור אליהן" is broken Hebrew. */
function nToCheck(n) {
  return n === 1 ? "החלטה אחת לחזור אליה" : n + " החלטות לחזור אליהן";
}
/* A section always occupies its slot, in a fixed order. An empty one renders
   disabled rather than vanishing: a page whose STRUCTURE moves between visits
   is exactly as unlearnable as a list that reorders. */
function section(id, title, sum, body, open) {
  if (!body)
    return `<details class="dsec empty" data-sec="${id}"><summary>${title}` +
      `<span class="dsum">עוד לא</span></summary></details>`;
  return `<details class="dsec" data-sec="${id}"${open ? " open" : ""}>` +
    `<summary>${title}<span class="dsum">${sum}</span></summary>` +
    `<div class="dbody">${body}</div></details>`;
}
function sub(id, title, sum, body) {
  if (!body) return "";
  return `<details class="dsub" data-sec="${id}"><summary>${title}` +
    `<span class="dsum">${sum}</span></summary>` +
    `<div class="dbody">${body}</div></details>`;
}
function scenarioBody(list, kind) {
  if (!list.length) return "";
  const tg = rowGroup(byType(list), {cols: kind === "lead" ? "סוג חוזה" : "סוג בעיה"});
  const dg = rowGroup(byDiff(list), {cols: "דרגת קושי"});
  let modes = "";
  if (kind === "lead") {
    const mp = list.filter(a => a.trainingMode !== "IMP").map(btScoreOfAttempt);
    const imp = list.filter(a => a.trainingMode === "IMP").map(btScoreOfAttempt);
    const rows = rowHtml(glossHtml("mp", "מאצ'פוינטס"), mp) +
                 rowHtml(glossHtml("imp", "IMP"), imp);
    if (rows) modes = axisCapHtml("שיטת ניקוד") + rows;
  }
  // conditioned on errors: averaging cost over every attempt mixes "how
  // often" with "how much", and once the hit rate passes 50% the
  // unconditional median is 0.0 forever, which reads as a bug
  const errs = list.filter(a => btScoreOfAttempt(a) < 100 && +a.gradedCost > 0);
  // Grouped BY UNIT, never pooled: a lead scenario holds both MP attempts
  // (costed in tricks) and IMP attempts (costed in IMPs), so one median over
  // the lot would average 0.7 tricks against 2.4 IMP and label the result with
  // whichever unit happened to come first.
  const byUnit = new Map();
  for (const a of errs) {
    const u = unitOf(a);
    if (!byUnit.has(u)) byUnit.set(u, []);
    byUnit.get(u).push(+a.gradedCost);
  }
  const costParts = [...byUnit.entries()]
    .filter(([, cs]) => cs.length >= MIN_N)
    .map(([u, cs]) => {
      const dec = u === "IMP" ? 1 : 2;
      return `<div class="rmore" style="margin-top:0">חציון ` +
        `<b class="ltr">${median(cs).toFixed(dec)}</b> ${u} · הגרועה ביותר ` +
        `<b class="ltr">${Math.max(...cs).toFixed(dec)}</b> ${u} ` +
        `(מתוך ${cs.length} טעויות)</div>`;
    });
  const costLine = costParts.length
    ? `<div class="subh">${glossHtml("cost", "מחיר הטעות")}</div>` +
      costParts.join("")
    : "";
  let ranks = "";
  if (kind === "lead") {
    const rk = list.filter(a => typeof a.chosenRank === "number");
    if (rk.length >= MIN_N) {
      const firsts = rk.filter(a => a.chosenRank === 1).length;
      ranks = `<div class="subh">${glossHtml("leadrank", "דירוג ההובלה")}</div>` +
        `<div class="rmore" style="margin-top:0">דורגה בממוצע במקום ` +
        `<b class="ltr">${mean(rk.map(a => +a.chosenRank)).toFixed(1)}</b> · ` +
        `במקום הראשון ב-${Math.round(firsts / rk.length * 100)}% מהמקרים ` +
        `(${rk.length} הובלות)</div>`;
    }
  }
  const scores = list.map(btScoreOfAttempt);
  const ok = scores.filter(s => s >= REVIEW_MIN).length;
  const mid = scores.filter(s => s >= ERROR_MIN && s < REVIEW_MIN).length;
  const bad = scores.filter(s => s < ERROR_MIN).length;
  return mixHtml(ok, mid, bad, scores.length) +
    `<div class="rmore" style="margin-top:2px">${glossHtml("scale40", "הסולם מתחיל ב-40")}</div>` +
    sub(kind + "-type", kind === "lead" ? "לפי סוג חוזה" : "לפי סוג בעיה",
        worstSum(tg), tg && tg.html) +
    sub(kind + "-mode", "מאצ'פוינטס מול IMP", "", modes) +
    sub(kind + "-num", "המספרים המלאים",
        `${Math.round(mean(scores))} בממוצע`,
        (dg ? `<div class="subh">לפי דרגת קושי</div>` + dg.html : "") +
        costLine + ranks + coverageHtml(list, kind));
}
function render(attempts) {
  const el = document.getElementById("dash");
  if (!attempts.length) {
    el.innerHTML = '<div class="card state"><div class="em">עוד אין נתונים</div>' +
      '<a class="big" href="index.html">ענה על בעיה כדי להתחיל &larr;</a></div>';
    return;
  }
  const open = loadOpen();
  const first = attempts.filter(a => a.isFirstAttempt !== false);
  // Hero, mix and trend use STORED-score attempts only. A legacy attempt is
  // rebuilt by btScoreOfAttempt from the base curve alone -- no CI haircut, no
  // stakes stretch, no leniency -- so it reads several points harsher than the
  // same decision made today, and any view ordered by time would drift upward
  // on its own as the window slid off them.
  // Same reasoning excludes attempts whose problem has since been DELETED from
  // the pool, stored score or not: `trainer pool regrade-attempts` cannot
  // refresh a grade whose verdict is gone (it counts them missing_problem),
  // and boards do get deleted BECAUSE their verdict was wrong -- the
  // explanation gates (engine/explain_check.py, `trainer pool audit`) remove
  // them. Such a grade can never be verified again, so it states nothing about
  // how the user bids today. The rows stay on the page, in the miss list.
  const scored = first.filter(btHasStoredScore).filter(a => !btOrphan(a));
  const legacyN = first.filter(a => !btHasStoredScore(a)).length;
  const goneN = first.length - scored.length - legacyN;
  const pendingN = (window.BT.pendingCount && window.BT.pendingCount()) || 0;
  const heroSet = scored.length ? scored : first;
  const scen = {bidding: [], lead: []};
  for (const a of first) scen[attKind(a)].push(a);
  const recent = [...first].sort((a, b) => firstMs(b) - firstMs(a));
  const heroChrono = [...heroSet].sort((a, b) => firstMs(a) - firstMs(b));
  const winIds = new Set(heroChrono.slice(-HERO_WIN).map(a => a.problemId));

  const weak = weakArea(first, scen);
  const pats = patterns(first);
  const nextup = weak
    ? '<div class="card"><b>' + glossHtml("weakspot", "מה כדאי לחזק") + '</b>' +
      `<div style="margin:7px 0 3px">${weak.kind === "coverage" ? "כמעט לא תרגלת" : "הנושא החלש שלך"}: ` +
      `<b>${weak.label}</b></div>` +
      `<div class="rmore" style="margin-top:0">${weak.why}</div>` +
      (pats.length ? `<div class="rmore">${pats[0].txt}</div>` : "") +
      `<a class="big" href="${weak.href}" style="margin-top:11px">` +
      `תרגל ${SESSION_SIZE} כאלה &larr;</a></div>`
    : (pats.length
        ? '<div class="card"><b>' + glossHtml("pattern", "נטייה שחוזרת") +
          `</b><div class="rmore">${pats[0].txt}</div></div>` : "");

  // the 3 worst decisions IN THE HERO WINDOW: "worst recently" is a review
  // target, the all-time worst from six months ago is not. Ordered by score,
  // not gradedCost -- cost units differ by scenario (IMP vs tricks), so a
  // mixed cost sort would rank 2.4 IMP against 0.7 tricks. The three slots are
  // shared between the scenarios rather than pooled; see pickMisses.
  const inWin = heroChrono.filter(a => winIds.has(a.problemId));
  const winRows = pickMisses(inWin, 3);
  const tocheck = winRows.length
    ? `<div class="card"><b>${nToCheck(winRows.length)}</b>` +
      '<span class="dsum" style="margin-inline-start:8px">מתוך הבעיות האחרונות</span>' +
      winRows.map(m => missRowHtml(m, true)).join("") +
      // the card already admits it shows a subset; this is where the reader
      // asks "and the rest?", so it is where the log is offered
      '<div class="rmore"><a href="history.html">כל התרגולים לפי תאריך &larr;</a>' +
      '</div></div>'
    : "";

  const allMiss = missesOf(first);
  const missRows = pickMisses(first, MISS_CAP);
  // The cap is disclosed, and so is the per-scenario split: a list that is
  // silently truncated reads as "this is everything", and one that names only
  // its total hides which scenario the misses are in.
  const nLead = allMiss.filter(a => attKind(a) === "lead").length;
  const nBid = allMiss.length - nLead;
  const both = nBid > 0 && nLead > 0;
  const parts = [
    both ? `הכרזה <b class="ltr">${nBid}</b> · ` +
           `הובלה <b class="ltr">${nLead}</b>` : "",
    allMiss.length > missRows.length
      ? `מוצגות ${missRows.length} הגרועות` +
        (both ? ", בחלוקה שווה בין השניים" : "") : "",
  ].filter(Boolean);
  const missNote = parts.length
    ? `<div class="rmore" style="margin-top:0">${parts.join(" · ")}</div>` : "";
  // This list and the practice log hold the SAME rows under two different
  // questions -- "what should I fix" (ordered by severity, capped) vs "what did
  // I do" (ordered by time, complete). Naming the other one is what stops them
  // reading as one list shipped twice.
  const histLink = '<a href="history.html">יומן התרגול — אותן החלטות לפי תאריך &larr;</a>';
  const missList = missRows.length
    ? missNote + missRows.map(m => missRowHtml(m, false)).join("") +
      `<div class="rmore">${histLink}</div>`
    : "";

  const patBody = pats.length
    ? '<ul class="patlist">' + pats.map(p => `<li>${p.txt}</li>`).join("") + '</ul>'
    : "";
  const bidBody = scenarioBody(scen.bidding, "bidding");
  const leadBody = scenarioBody(scen.lead, "lead");
  const sumOf = list => list.length
    ? `ציון ${Math.round(mean(list.map(btScoreOfAttempt)))} · ${nDecisions(list.length)}` : "";

  el.innerHTML =
    heroHtml(heroSet, legacyN, goneN, pendingN) + nextup + tocheck +
    section("bidding", "הכרזה", sumOf(scen.bidding), bidBody, open.has("bidding")) +
    section("lead", "הובלה", sumOf(scen.lead), leadBody, open.has("lead")) +
    section("pat", "נטיות שחוזרות",
            pats.length + (pats.length === 1 ? " דפוס" : " דפוסים"),
            patBody, open.has("pat")) +
    section("miss", "כל ההחלטות לשיפור",
            `${allMiss.length} מתחת ל-${REVIEW_MIN}`, missList, open.has("miss")) +
    section("how", "איך מחושב הציון", "0–100 · 6 רמות", howHtml(first),
            open.has("how"));

  el.addEventListener("toggle", ev => {
    const d = ev.target.closest("details.dsec");
    if (!d || !d.dataset.sec) return;
    const s = loadOpen();
    if (d.open) s.add(d.dataset.sec); else s.delete(d.dataset.sec);
    saveOpen(s);
  }, true);
}
/* Coverage lives inside its scenario rather than in a section of its own:
   the section budget is five, and coverage is only meaningful next to the
   breakdown it qualifies -- a topic with no attempts is not a weak topic. */
function coverageHtml(list, kind) {
  if (!POOL_BY_TYPE || !POOL_BY_TYPE.size) return "";
  const done = {};
  for (const a of list) if (a.type) done[a.type] = (done[a.type] || 0) + 1;
  const rows = [...POOL_BY_TYPE.entries()]
    .filter(([, e]) => e.kind === kind)
    .map(([t, e]) => ({t, n: done[t] || 0, pool: e.ids.size}))
    .sort((a, b) => a.n - b.n || b.pool - a.pool);
  if (!rows.length) return "";
  return `<div class="subh">${glossHtml("coverage", "היקף התרגול")}</div>` +
    '<ul class="patlist">' + rows.map(r =>
      `<li>${typeLabel(r.t)} — <b>${r.n}</b> מתוך ${r.pool}` +
      (r.n === 0 ? ' <span class="muted">לא תרגלת</span>' : "") + '</li>').join("") +
    '</ul>';
}
function howHtml(first) {
  const bands = [
    ["מיטבי", "100", "win"], ["כמעט מיטבי", "85–99", "win"],
    ["סטייה קלה", "65–84", "gold"], ["טעות", "40–64", "loss"],
    ["טעות חמורה", "1–39", "loss"],
    ["אפשרות ללא סיכוי", "0", "loss"],
  ];
  const lifetime = first.length
    ? Math.round(mean(first.map(btScoreOfAttempt))) : 0;
  return '<p class="rmore" style="margin-top:0">כל החלטה מקבלת ציון ' +
    '0–100 לפי כמה היא רחוקה מהפעולה המיטבית. <b>100</b> — הפעולה ' +
    'המיטבית (או שקולה לה). <b>0</b> — אפשרות שלא ניצחה באף חלוקה. ' +
    'הפער נמדד ב-' + glossHtml("imp", "IMP") + ' בהכרזה ובהובלת IMP, ' +
    'ובלקיחות בהובלת ' + glossHtml("mp", "מאצ'פוינטס") +
    ', בסולם המותאם לתנודת הלוח. ממוצע מוצג רק מ-' + MIN_N +
    ' החלטות ומעלה, וטווח מ-' + MIN_CI + '.</p>' +
    '<table class="bandtab">' + bands.map(([nm, rng, tone]) =>
      `<tr><td><i class="sw" style="background:var(--${tone})"></i>${nm}</td>` +
      `<td class="sc ltr">${rng}</td></tr>`).join("") + '</table>' +
    `<div class="rmore">ממוצע כל הזמנים <b>${lifetime}</b> · ` +
    `${nProblems(first.length)} (${glossHtml("firstonly", "ניסיון ראשון")} בלבד)</div>`;
}
async function init() {
  try {
    // Learn which problems still exist so deleted ones can be flagged in the
    // miss list (DB-M-9), and the per-type pool counts the coverage section
    // and the recommendation's pool guard need. Cheap: the index is
    // stamp-cached (T10). If it fails, LIVE_IDS stays null and every attempt
    // is treated as live, as before.
    try {
      const idx = await window.BT.fetchIndex();
      const rows = idx.problems || [];
      LIVE_IDS = new Set(rows.map(p => p.id));
      POOL_BY_TYPE = new Map();
      for (const p of rows) {
        if (!p.type) continue;
        if (!POOL_BY_TYPE.has(p.type))
          POOL_BY_TYPE.set(p.type, {ids: new Set(), kind: kindOf(p)});
        POOL_BY_TYPE.get(p.type).ids.add(p.id);
      }
    } catch (e) { LIVE_IDS = null; POOL_BY_TYPE = null; }
    // Render exactly what is stored. A grade is never recomputed at display
    // time: an attempt's score is data, and stale data is repaired where it
    // lives (`trainer pool regrade-attempts` against Firestore), never papered
    // over by the page that shows it.
    render(await window.BT.allAttempts());
  } catch (e) {
    const el = document.getElementById("dash");
    el.innerHTML = 'לא ניתן לטעון את הנתונים שלך: <span class="en"></span>';
    el.querySelector(".en").textContent = e.message;
  }
}
// refresh the dashboard once the background sync (T4) lands. render() reads
// the persisted open-set, so a sync can't collapse a section the user opened.
window.addEventListener("bt-attempts-synced", async () => {
  try { render(await window.BT.allAttempts()); } catch (e) { /* keep prior */ }
});
if (window.BT) window.BT.start(init);
else addEventListener("bt-ready", () => window.BT.start(init), {once: true});
