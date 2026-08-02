
/* ===== practice log =====
   The dashboard answers "how am I doing"; this page answers "what did I do".
   Design decisions and the reviews behind them: docs/history_feature_plan.md.
   The attempt vocabulary (actMs/attKind/badge/attemptRowHtml/...) comes from
   bt-shared.js, so a row here and a row in the dashboard's miss list are built
   by one function. */
const CHUNK = 100;              // rows per page, extended to a day boundary
const KIND_KEY = "bt_hist_kind";   // the scenario persists; "misses" never does
const MONTH_HE = ["בינואר", "בפברואר", "במרץ", "באפריל", "במאי", "ביוני",
  "ביולי", "באוגוסט", "בספטמבר", "באוקטובר", "בנובמבר", "בדצמבר"];
const WDAY_HE = ["יום ראשון", "יום שני", "יום שלישי", "יום רביעי",
  "יום חמישי", "יום שישי", "שבת"];
/* Module state, NOT re-derived per render: the background sync fires a
   re-render, and a re-render that recomputed these would throw away the
   filter the user set and page them back to the first chunk. */
let FILTER = {kind: "all", miss: false};
let LIMIT = CHUNK;
let SYNCED = false;      // has the authoritative sync landed at least once?
let ATTEMPTS = [];       // last list rendered, for re-render on demand
let PENDING = null;      // ids whose write has not reached the server

/* ---- local day keys and Hebrew labels ----------------------------------
   Local, never UTC: toISOString() would bucket everything answered between
   00:00 and 03:00 Israel time into the previous day. And day arithmetic is
   done on the KEYS, never on milliseconds -- Israel observes DST, so a day is
   sometimes 23 or 25 hours long and `- 86400000` lands in the wrong one. */
function dayKey(ms) {
  const d = new Date(ms);
  return d.getFullYear() * 10000 + (d.getMonth() + 1) * 100 + d.getDate();
}
function daysAgoKey(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return dayKey(d.getTime());
}
/* Hand-formatted, not toLocaleTimeString(): the device locale decides that
   one, so an en-US phone would print "2:20 PM" -- English in a Hebrew UI, in
   a string the localisation test cannot see because it scans static markup. */
function hhmm(ms) {
  const d = new Date(ms);
  return String(d.getHours()).padStart(2, "0") + ":" +
         String(d.getMinutes()).padStart(2, "0");
}
function dateHe(ms) {
  const d = new Date(ms), now = new Date();
  return d.getDate() + " " + MONTH_HE[d.getMonth()] +
    (d.getFullYear() === now.getFullYear() ? "" : " " + d.getFullYear());
}
function dayLabel(key, ms) {
  if (!key) return "ללא תאריך";
  if (key === dayKey(Date.now())) return "היום";
  if (key === daysAgoKey(1)) return "אתמול";
  for (let i = 2; i <= 6; i++)
    if (key === daysAgoKey(i)) return WDAY_HE[new Date(ms).getDay()];
  return dateHe(ms);
}

/* ---- ordering and grouping --------------------------------------------- */
/* Ordered by LAST ACTIVITY, not by first answer: a session spent re-answering
   old problems bumps no firstTs at all, so a firstMs order would render that
   whole session invisible -- the log failing its own purpose.
   The problemId tiebreak is not cosmetic: Object.values(ATTEMPTS) is in map
   insertion order, which changes across a full reconcile, and a queued row's
   ts is second-granular, so without it two rows sharing a key can swap places
   between renders and paging can show one twice or skip it. */
function sortRows(list) {
  return [...list].sort((a, b) => actMs(b) - actMs(a) ||
    (String(a.problemId) < String(b.problemId) ? 1 : -1));
}
function filterRows(list) {
  return list.filter(a =>
    (FILTER.kind === "all" || attKind(a) === FILTER.kind) &&
    (!FILTER.miss || btScoreOfAttempt(a) < REVIEW_MIN));
}
/* Undated rows (docs old enough to predate `ts`) carry key 0, so they sort
   last and land in their own trailing group -- never silently dated today. */
function groupByDay(sorted) {
  const out = [], by = new Map();
  for (const a of sorted) {
    const ms = actMs(a), key = ms ? dayKey(ms) : 0;
    if (!by.has(key)) { by.set(key, {key, ms, rows: []}); out.push(by.get(key)); }
    by.get(key).rows.push(a);
  }
  return out;
}
/* Whole days only: a fixed row cut would leave a day heading claiming 6
   problems above 2 visible rows. */
function visibleGroups(groups, limit) {
  const out = [];
  let n = 0;
  for (const g of groups) {
    if (n >= limit && out.length) break;
    out.push(g);
    n += g.rows.length;
  }
  return out;
}

/* ---- one row ----------------------------------------------------------- */
/* The chip is built here rather than by btScoreChipHtml because (a) a
   reconstructed or absent grade must not wear the chrome of a measured one,
   and (b) btScoreChipHtml carries data-gloss, and a tappable gloss target
   inside a row <a> would fire navigation and the glossary card at once. */
function chipHtml(a) {
  if (btScoreIsFallback(a))
    return '<span class="scorechip sm noscore">ללא ציון</span>';
  const sc = btScoreOfAttempt(a), approx = btScoreIsApprox(a);
  // dir="ltr" on the approximate chip: "~" is bidi-neutral, so in the page's
  // RTL run it lands AFTER the digits and the chip reads "42~"
  return '<span class="scorechip sm tone-' + BAND_TONE[btBandOf(sc)] + '"' +
    (approx ? ' dir="ltr"' : '') + '>' + (approx ? "~" : "") + sc + '</span>';
}
/* The row's accessible name. It REPLACES the visible text, so it repeats every
   marker the row shows -- otherwise the replay count, the first-solved date and
   the unsynced warning would be sighted-only.
   A type with no taxonomy entry is left out rather than read aloud as
   "competitive_partscore" in a Hebrew sentence (the badge drops it too). */
function rowLabel(a, marks, gone) {
  const d = Math.min(5, Math.max(0, (+a.difficultyLevel || 0) | 0));
  const ms = actMs(a);
  const acc = accOf(a);
  return [ms ? hhmm(ms) : "ללא תאריך", scenHe(a), typeName(a.type) || "",
          d ? "קושי " + d + " מתוך 5" : "", "בחרת " + a.chosenCall,
          (acc.length && !acc.includes(a.chosenCall))
            ? "מיטבי " + acc.join(", ") : "",
          btScoreIsFallback(a) ? "ללא ציון" : "ציון " + btScoreOfAttempt(a),
          +a.attemptCount > 1 ? "חזרה " + (+a.attemptCount) + " פעמים" : "",
          ...(marks || []),
          gone ? "הבעיה הוסרה מהמאגר" : "תרגל שוב"]
    .filter(Boolean).join(", ");
}
function logRowHtml(a, dkey) {
  const ms = actMs(a), fms = firstMs(a);
  // A replayed row sits in the day it was LAST answered while its grade is
  // still the first attempt's, so when those fall on different days the row
  // says when it was first solved -- otherwise the score reads as today's work.
  const marks = [];
  if (+a.attemptCount > 1 && fms && dayKey(fms) !== dkey)
    marks.push("נפתרה לראשונה ב-" + dateHe(fms));
  if (PENDING && PENDING.has(a.problemId)) marks.push("טרם נשמר בענן");
  // plain escaped text: these marks are Hebrew phrases (a date reads "3 ביולי"
  // correctly in an RTL run), so no .ltr isolate -- that would flip them
  const mark = marks.length
    ? ' · <span class="hmark">' + marks.map(esc).join(" · ") + '</span>' : "";
  return attemptRowHtml(a, {cls: "hrow", chip: chipHtml(a), chose: false,
    time: ms ? hhmm(ms) : "", replays: true, mark: mark,
    label: rowLabel(a, marks, btOrphan(a))});
}
function dayHtml(g) {
  const miss = g.rows.filter(a => btScoreOfAttempt(a) < REVIEW_MIN).length;
  const times = g.rows.map(actMs).filter(Boolean);
  // No day MEAN, by ruling: a handful of problems mixes three scoring scales
  // (bidding, lead MP, lead IMP) and possibly two calibrations, and the app
  // refuses to print even an interval below 12 decisions. The time span is the
  // honest substitute for the session boundary we decline to guess.
  const lo = times.length ? hhmm(Math.min(...times)) : "";
  const hi = times.length ? hhmm(Math.max(...times)) : "";
  const span = lo ? '<span class="ltr">' + (lo === hi ? lo : lo + "–" + hi) +
                    '</span>' : "";
  const bits = [nProblems(g.rows.length), miss ? miss + " לשיפור" : "", span]
    .filter(Boolean);
  return '<h2 class="dday" tabindex="-1" data-day="' + g.key + '">' +
    dayLabel(g.key, g.ms) + ' <span class="ddsub">· ' + bits.join(" · ") +
    '</span></h2>' +
    '<div class="card hcard">' +
    g.rows.map(a => logRowHtml(a, g.key)).join("") + '</div>';
}

/* ---- page ------------------------------------------------------------- */
function firstAttempts(list) {
  // mirrors the dashboard: a second answer to a problem whose verdict you have
  // already seen is recall, not judgment. In production every doc carries
  // true, but the preview harness fabricates duplicates.
  return list.filter(a => a.isFirstAttempt !== false);
}
function summaryHtml(all, shown) {
  const times = all.map(actMs).filter(Boolean);
  const span = times.length
    ? "מ-" + dateHe(Math.min(...times)) + " עד " +
      (dayKey(Math.max(...times)) === dayKey(Date.now())
        ? "היום" : dateHe(Math.max(...times)))
    : "";
  const narrowed = shown.length !== all.length;
  const what = [FILTER.kind === "bidding" ? "הכרזה בלבד" : "",
                FILTER.kind === "lead" ? "הובלה בלבד" : "",
                FILTER.miss ? "רק מתחת ל-" + REVIEW_MIN : ""].filter(Boolean);
  return '<div class="hsum">' +
    (narrowed
      ? '<span><b class="ltr">' + shown.length + '</b> מתוך ' +
        nProblems(all.length) + '</span>'
      : '<span>' + nProblems(all.length) + '</span>') +
    (what.length ? '<span class="hsnote">' + what.join(" · ") + '</span>' +
      '<button type="button" class="alllink" id="clearf">הצג את הכל</button>' : "") +
    (span ? '<span class="hsnote">' + span + '</span>' : "") +
    '</div>';
}
function filtersHtml() {
  const seg = (id, opts) => '<span class="segctl" role="group" aria-label="' +
    id + '">' + opts.map(([v, lbl, on]) =>
      '<button type="button" data-' + (id === "תרחיש" ? "kind" : "miss") +
      '="' + v + '" aria-pressed="' + (on ? "true" : "false") + '">' + lbl +
      '</button>').join("") + '</span>';
  return '<div class="hfilt">' +
    seg("תרחיש", [["all", "הכל", FILTER.kind === "all"],
                  ["bidding", "הכרזה", FILTER.kind === "bidding"],
                  ["lead", "הובלה", FILTER.kind === "lead"]]) +
    seg("סינון", [["1", "רק לשיפור", FILTER.miss]]) +
    '</div>';
}
/* Every limit the log has, stated in the log. goneN is recomputed whenever
   LIVE_IDS changes (see markRemoved) rather than only at first paint: the pool
   index lands after the page is already on screen, so a footnote written once
   would claim nothing was removed while rows above it say otherwise. */
function noteHtml(all) {
  const legacyN = all.filter(a => !btHasStoredScore(a)).length;
  const pendingN = (window.BT.pendingCount && window.BT.pendingCount()) || 0;
  const goneN = all.filter(a => btOrphan(a)).length;
  const undatedN = all.filter(a => !actMs(a)).length;
  return '<p class="footnote" id="hnote">היומן מציג שורה אחת לכל בעיה שפתרת, ' +
    'לפי הפעם האחרונה שעסקת בה. חזרה על בעיה מסומנת בשורה שלה ואינה יוצרת ' +
    'שורה חדשה, והציון נשאר של ' + glossHtml("firstonly", "הפעם הראשונה") +
    ' — תשובה שנייה לבעיה שראית את פתרונה היא זכירה ולא שיפוט.' +
    (goneN ? ' ' + nProblems(goneN) + ' הוסרו מהמאגר: הן נשארות ביומן אך לא ' +
      'ניתן לתרגל אותן שוב.' : "") +
    (legacyN ? ' ' + nProblems(legacyN) + ' נפתרו לפני ' +
      glossHtml("legacy", "עדכון שיטת הציון") + ' — הציון שלהן שוחזר בקירוב, ' +
      'מסומן ב-~ ומחמיר בכמה נקודות. בחלקן נשמרה רק העובדה שטעית, בלי מידת ' +
      'הטעות, והן מסומנות "ללא ציון".' : "") +
    (undatedN ? ' ' + nProblems(undatedN) + ' נשמרו לפני שהמערכת רשמה זמנים, ' +
      'ולכן הן מקובצות תחת "ללא תאריך".' : "") +
    (pendingN ? ' <b>' + nDecisions(pendingN) + '</b> טרם נשמרו לענן; הזמן ' +
      'שלהן נלקח משעון המכשיר.' : "") +
    ' ציון של בעיה יכול להתעדכן בין ביקורים אם המאגר חושב מחדש את הפתרון ' +
    'שלה — התאריך והבחירה שלך לא משתנים.</p>';
}
function render(list) {
  ATTEMPTS = list;
  const all = firstAttempts(list);
  const el = document.getElementById("hist");
  if (!all.length) {
    // NOT "no history": allAttempts() serves a localStorage cache that is
    // empty on a new device, and telling a user with 400 answers that they
    // have none is the worst possible first impression on this page.
    el.innerHTML = SYNCED
      ? '<div class="card state"><div class="em">עוד לא פתרת בעיות</div>' +
        '<div class="muted">היומן יתמלא אחרי התרגול הראשון.</div>' +
        '<a class="big" href="index.html">התחל תרגול &larr;</a></div>'
      : '<div class="card state"><div class="em">טוען את היומן שלך&hellip;</div>' +
        '<div class="muted">הנתונים מסתנכרנים מהענן.</div></div>';
    return;
  }
  const rows = sortRows(filterRows(all));
  const groups = groupByDay(rows);
  const vis = rows.length ? visibleGroups(groups, LIMIT) : [];
  const shownN = vis.reduce((s, g) => s + g.rows.length, 0);
  const rest = rows.length - shownN;
  el.innerHTML = summaryHtml(all, rows) + filtersHtml() +
    '<div id="hlist">' +
    (rows.length
      ? vis.map(dayHtml).join("")
      : '<div class="card state"><div class="em">אין תרגולים בבחירה הזו</div>' +
        '<div class="muted">שנה את הסינון כדי לראות שורות נוספות.</div></div>') +
    '</div>' +
    '<div class="hmore" id="hmore">' + moreHtml(rest) + '</div>' +
    noteHtml(all);
}
/* Paging is a secondary control, so it must not wear the gold CTA: on this page
   the one gold button is "practise new problems", which is what the reader
   should do when they reach the end of their own history. */
function moreHtml(rest) {
  return rest > 0
    ? '<button type="button" class="morebtn" id="moreb">הצג עוד ' +
      Math.min(CHUNK, rest) + ' <span class="ltr">(נותרו ' + rest + ')</span>' +
      '</button>'
    : '<a class="big" href="index.html">תרגל ' + SESSION_SIZE +
      ' בעיות חדשות &larr;</a>';
}
/* Appends, rather than re-rendering: the reader's scroll position is the one
   piece of state a "show more" button must not disturb. */
function showMore() {
  const all = firstAttempts(ATTEMPTS);
  const rows = sortRows(filterRows(all));
  const groups = groupByDay(rows);
  const before = visibleGroups(groups, LIMIT);
  // Days are indivisible, so one huge day can already exceed LIMIT + CHUNK --
  // a plain `LIMIT += CHUNK` then reveals NOTHING and the tap does nothing
  // (focus dropped, same button re-rendered). Raise the limit past what is
  // already shown, and keep raising it until at least one more day appears.
  const shownBefore = before.reduce((s, g) => s + g.rows.length, 0);
  LIMIT = Math.max(LIMIT, shownBefore) + CHUNK;
  let after = visibleGroups(groups, LIMIT);
  while (after.length === before.length && after.length < groups.length) {
    LIMIT += CHUNK;
    after = visibleGroups(groups, LIMIT);
  }
  const added = after.slice(before.length);
  document.getElementById("hlist")
    .insertAdjacentHTML("beforeend", added.map(dayHtml).join(""));
  markRemoved();
  const shownN = after.reduce((s, g) => s + g.rows.length, 0);
  document.getElementById("hmore").innerHTML = moreHtml(rows.length - shownN);
  // a keyboard or screen-reader user must land on the new rows, not be left
  // at the top of a page that silently grew
  const head = added.length
    ? document.querySelector('#hlist h2[data-day="' + added[0].key + '"]') : null;
  if (head) head.focus();
}
function setFilter(patch) {
  Object.assign(FILTER, patch);
  if ("kind" in patch) {
    try { localStorage.setItem(KIND_KEY, FILTER.kind); } catch (e) { /* */ }
  }
  LIMIT = CHUNK;             // a new selection starts at the first chunk
  render(ATTEMPTS);
  markRemoved();
  // render() replaced the button that was just tapped, which drops keyboard
  // focus to <body>. Put it back on the equivalent control.
  const sel = "kind" in patch
    ? '#hist [data-kind="' + FILTER.kind + '"]' : '#hist [data-miss]';
  const btn = document.querySelector(sel);
  if (btn) btn.focus();
}
/* Patch the rows the pool index turned out not to cover, instead of
   re-rendering: the index arrives after first paint (see init), and a second
   full render would move rows under the reader's finger. */
function markRemoved() {
  if (!LIVE_IDS) return;
  let n = 0;
  document.querySelectorAll("#hlist a.hrow[data-pid]").forEach(a => {
    if (LIVE_IDS.has(a.dataset.pid)) return;
    n++;
    const div = document.createElement("div");
    div.className = a.className;
    div.dataset.pid = a.dataset.pid;
    div.innerHTML = a.innerHTML;
    // the row is still a row a screen reader must make sense of; only its
    // closing promise changes
    const lbl = a.getAttribute("aria-label");
    if (lbl) div.setAttribute("aria-label",
      lbl.replace("תרגל שוב", "הבעיה הוסרה מהמאגר"));
    const go = div.querySelector(".go");
    if (go) {
      go.className = "go muted";
      go.removeAttribute("aria-hidden");
      go.textContent = "בעיה שהוסרה";
    }
    a.replaceWith(div);
  });
  // the footnote was written before the index arrived, so it still says nothing
  // about removed problems; rewrite just that paragraph
  const note = document.getElementById("hnote");
  if (n && note) note.outerHTML = noteHtml(firstAttempts(ATTEMPTS));
}
async function init() {
  const el = document.getElementById("hist");
  try { FILTER.kind = localStorage.getItem(KIND_KEY) || "all"; }
  catch (e) { /* private mode */ }
  if (["all", "bidding", "lead"].indexOf(FILTER.kind) < 0) FILTER.kind = "all";
  // Deep links: the scenario is shareable, the miss filter is not persisted but
  // IS linkable, so the dashboard can point at exactly what it is talking about.
  const q = new URLSearchParams(location.search);
  const qk = q.get("kind");
  if (qk === "bidding" || qk === "lead" || qk === "all") FILTER.kind = qk;
  if (q.get("f") === "miss") FILTER.miss = true;
  try { PENDING = new Set((window.BT.pendingIds && window.BT.pendingIds()) || []); }
  catch (e) { PENDING = null; }
  // ONE delegated handler, bound once, on the container render() replaces the
  // contents of. Binding inside render() would add a listener per render and
  // paging would advance twice per tap.
  el.addEventListener("click", ev => {
    const b = ev.target.closest("button");
    if (!b || !el.contains(b)) return;
    if (b.dataset.kind) setFilter({kind: b.dataset.kind});
    else if (b.dataset.miss) setFilter({miss: !FILTER.miss});
    else if (b.id === "clearf") setFilter({kind: "all", miss: false});
    else if (b.id === "moreb") showMore();
  });
  render(await window.BT.allAttempts());
  // Belt and braces for the empty state: bt-attempts-synced comes from a
  // .finally, so it fires even on a failed sync -- but if it somehow never
  // arrives, a user with no rows would sit on "loading your log" forever. This
  // only ever flips the ZERO-row case (any cached row renders immediately), and
  // a later sync still corrects it.
  setTimeout(() => {
    if (!SYNCED && !firstAttempts(ATTEMPTS).length) {
      SYNCED = true; render(ATTEMPTS);
    }
  }, 8000);
  // The pool index costs a server-first read and a network round trip, so it
  // is NOT on the path to first paint: every row is tappable until we learn
  // otherwise, and the few removed ones are then patched in place. A failure
  // leaves LIVE_IDS null, i.e. every attempt treated as live, as before.
  const ric = window.requestIdleCallback || ((f) => setTimeout(f, 1));
  ric(() => window.BT.fetchIndex()
    .then(idx => { LIVE_IDS = new Set((idx.problems || []).map(p => p.id));
                   markRemoved(); })
    .catch(() => { LIVE_IDS = null; }));
}
// The authoritative sync lands after first paint (T4). Re-render from module
// state so it can neither reset the filter nor page the reader back to the top
// of a list they had already extended.
window.addEventListener("bt-attempts-synced", async () => {
  SYNCED = true;
  try {
    PENDING = new Set((window.BT.pendingIds && window.BT.pendingIds()) || []);
    render(await window.BT.allAttempts());
    markRemoved();
  } catch (e) { /* keep what is on screen */ }
});
if (window.BT) window.BT.start(init);
else addEventListener("bt-ready", () => window.BT.start(init), {once: true});
