"""The static web app that consumes the problem pool.

Two pages, no build step, no framework:
  index.html  — "Deal me a hand" (random unseen problem) + progress stats
  p.html?id=X — renders one problem document fetched from data/problems/X.json

Answers live in localStorage under key "bt_pool" ({id: {answer, correct,
ts}}). The pool itself is data/ next to these pages; the producer appends to
it continuously, so the app sees new problems without any redeploy.

Look and feel follows Bridge Base Online (ux/bridge panel redesign):
green-felt page with white content cards, a fixed W-N-E-S auction diagram
whose seat headers carry vulnerability as red/green plates, BBO's
four-color suits (blue ♠ / red ♥ / orange ♦ / green ♣), tap-a-bid
alert-style explanations, bidding-box candidate buttons, and an
outcome-first verdict table (EV, win/push/loss bar, contract chips) in
place of prose.
"""
from __future__ import annotations

from pathlib import Path

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  /* light theme tokens */
  --felt: #2E6B4F; --felt-deep: #24573F;
  --on-felt: #ffffff; --on-felt-muted: #C9DCD1;
  --card: #ffffff; --fg: #1C2B24; --muted: #5C6B62; --line: #D9E0DA;
  --accent: #2B6CB0; --accent-tint: #2B6CB014;
  --vul: #B3252F; --nonvul: #E6F4EA; --on-nonvul: #1C5C34;
  --sp: #2838C8; --he: #C8102E; --di: #E07000; --cl: #1A7A1A;
  --win: #1E8E4E; --loss: #C8102E; --push: #A9B3AC;
  --gold: #EAB84C; --on-gold: #2A2410;
  --warn-bg: #FDF3DF; --warn-fg: #7A5312; --warn-line: #E3C87F;
  font-family: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial,
               sans-serif;
  max-width: 640px; margin: 0 auto; padding: 12px;
  background: radial-gradient(120% 90% at 50% 0%, var(--felt),
                              var(--felt-deep)) fixed;
  color: var(--fg); font-size: 15px; line-height: 1.45;
}
@media (prefers-color-scheme: dark) {
  body {
    --felt: #10241A; --felt-deep: #0B1A13;
    --on-felt: #E9F0EB; --on-felt-muted: #9FB4A8;
    --card: #1B2620; --fg: #E8EDEA; --muted: #97A79D; --line: #33413A;
    --accent: #6CA6DD; --accent-tint: #6CA6DD1F;
    --vul: #A62630; --nonvul: #2E4A38; --on-nonvul: #BFE3CC;
    --sp: #8C96FF; --he: #FF7B72; --di: #FFAB40; --cl: #57C957;
    --win: #3BB273; --loss: #E5665F; --push: #5B6961;
    --gold: #D9A93E; --on-gold: #241F0C;
    --warn-bg: #2E2612; --warn-fg: #E7C97E; --warn-line: #6B5A2A;
  }
}
h1 { font-size: 20px; font-weight: 700; color: var(--on-felt); margin: .4em 0; }
.card { background: var(--card); color: var(--fg); border-radius: 14px;
        padding: 16px; margin: 12px 0;
        box-shadow: 0 1px 3px #0003, 0 4px 14px #0000001f; }
@media (prefers-color-scheme: dark) { .card { border: 1px solid var(--line);
                                              box-shadow: none; } }
a { color: var(--accent); }
.topbar, .meta { display: flex; justify-content: space-between;
                 align-items: baseline; gap: 8px;
                 color: var(--on-felt-muted); font-size: 12px; }
.topbar a { color: var(--on-felt); }
.muted { color: var(--muted); font-size: 13px; }
.pill { display: inline-block; border-radius: 999px; padding: 1px 8px;
        font-size: 12px; border: 1px solid #ffffff55; }
/* homepage practice filters: difficulty (segmented) + problem type (list),
   both multi-select and everything selected by default. Each option carries
   the number of problems it holds. */
.fgroup { margin: 0 0 16px; }
.fgroup:last-child { margin-bottom: 0; }
.grow { display: flex; justify-content: space-between; align-items: baseline;
        margin: 0 0 8px; }
.glabel { font-size: 12px; font-weight: 700; text-transform: uppercase;
          letter-spacing: .05em; color: var(--muted); }
.alllink { background: none; border: 0; font: inherit; font-size: 12px;
           font-weight: 600; color: var(--accent); cursor: pointer;
           padding: 2px 2px; }
.alllink:hover { text-decoration: underline; }
/* segmented difficulty control (ordinal, so it reads as one scale) */
.seg { display: grid; grid-template-columns: repeat(var(--n, 5), 1fr);
       border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
.seg button { font: inherit; border: 0; border-left: 1px solid var(--line);
              background: var(--card); color: var(--muted); cursor: pointer;
              padding: 8px 2px 7px; display: flex; flex-direction: column;
              align-items: center; gap: 2px; line-height: 1.1; }
.seg button:first-child { border-left: 0; }
.seg button .sname { font-size: 11px; font-weight: 600; }
.seg button .scount { font-size: 13px; font-weight: 700;
                      font-variant-numeric: tabular-nums; }
.seg button.active { background: var(--accent-tint); color: var(--accent); }
/* problem-type toggle rows: name + proportional volume bar + count */
.typelist { display: flex; flex-direction: column; gap: 6px; }
button.typerow { display: flex; align-items: center; gap: 10px; width: 100%;
                 font: inherit; text-align: left; background: var(--card);
                 color: var(--fg); border: 1px solid var(--line);
                 border-radius: 10px; padding: 9px 12px; cursor: pointer; }
button.typerow .tick { flex: 0 0 auto; width: 18px; height: 18px;
                       border-radius: 5px; border: 1.5px solid var(--accent);
                       background: var(--accent); color: #fff; display: grid;
                       place-items: center; font-size: 11px; }
button.typerow .tick::after { content: "\\2713"; }
button.typerow .tname { flex: 0 0 auto; font-size: 14px; font-weight: 600; }
button.typerow .tbar { flex: 1 1 auto; height: 6px; border-radius: 999px;
                       background: var(--line); overflow: hidden; }
button.typerow .tbar > span { display: block; height: 100%; border-radius: 999px;
                              background: var(--accent); }
button.typerow .tcount { flex: 0 0 auto; min-width: 1.6em; text-align: right;
                         font-weight: 700; font-variant-numeric: tabular-nums; }
button.typerow[aria-pressed="false"] { color: var(--muted); }
button.typerow[aria-pressed="false"] .tick { background: transparent;
                       border-color: var(--line); color: transparent; }
button.typerow[aria-pressed="false"] .tbar > span { background: var(--push); }
a.big.off { background: var(--push); color: var(--card); cursor: not-allowed; }
/* collapsible filter: a tap bar that folds the two groups away by default */
.fbar { display: flex; align-items: center; gap: 10px; width: 100%;
        background: none; border: 0; font: inherit; color: var(--fg);
        cursor: pointer; padding: 0; text-align: left; min-height: 24px; }
.fbar .fbar-main { font-size: 15px; font-weight: 700; }
.fbar .fbar-sub { margin-left: auto; font-size: 13px; color: var(--muted);
                  font-variant-numeric: tabular-nums; }
.fbar.on .fbar-sub { color: var(--accent); font-weight: 700; }
.fbar .fbar-chev { color: var(--muted); font-size: 12px; width: 1em;
                   text-align: center; transition: transform .15s; }
.fbar[aria-expanded="true"] .fbar-chev { transform: rotate(180deg); }
.fbody { margin-top: 14px; }
.fbody[hidden] { display: none; }
/* problem-type badge (classification.type), shown with the problem */
.typebadge { display: inline-block; font-size: 11px; font-weight: 700;
             letter-spacing: .08em; text-transform: uppercase;
             color: var(--accent); background: var(--accent-tint);
             border: 1px solid var(--accent); border-radius: 999px;
             padding: 3px 10px; margin-bottom: 10px; cursor: help; }
/* difficulty stars (classification.difficulty_level), revealed with the
   verdict only — never before the user answers */
.diffline { display: flex; align-items: center; gap: 8px; font-size: 13px;
            color: var(--muted); margin: 0 0 10px; }
.diffline .stars { font-size: 15px; letter-spacing: 2px; line-height: 1; }
.diffline .stars .on { color: var(--gold); }
.diffline .stars .off { color: var(--line); }
.diffline b { color: var(--fg); }
/* four-color suits (BBO default deck) */
.ss { color: var(--sp); } .sh { color: var(--he); }
.sd { color: var(--di); } .sc { color: var(--cl); }
/* ---- auction diagram: fixed W N E S, vul on the seat plates ---- */
table.bidding { width: 100%; border-collapse: collapse; font-size: 17px;
                border-radius: 10px; overflow: hidden; }
table.bidding th { padding: 7px 4px 6px; font-weight: 600; font-size: 14px;
                   width: 25%; border: 0; }
table.bidding th.v  { background: var(--vul); color: #fff; }
table.bidding th.nv { background: var(--nonvul); color: var(--on-nonvul); }
table.bidding th.me { box-shadow: inset 0 -3px 0 var(--gold); }
table.bidding th small { display: block; font-weight: 400; font-size: 10px;
                         text-transform: uppercase; letter-spacing: .07em;
                         opacity: .85; }
table.bidding th sup.d { font-size: 9px; border: 1px solid currentColor;
                         border-radius: 999px; padding: 0 3px;
                         margin-left: 3px; vertical-align: super; }
table.bidding td { text-align: center; padding: 0;
                   border-top: 1px solid var(--line); }
table.bidding td .call { display: block; min-height: 42px;
                         line-height: 42px; font-weight: 600; }
table.bidding td .call.expl { text-decoration: underline dotted 1.5px;
                              text-underline-offset: 4px; cursor: pointer; }
table.bidding td .call.open { background: var(--accent-tint); }
table.bidding td.turn { background: var(--accent-tint); color: var(--accent);
                        font-weight: 700; font-size: 19px; }
@media (prefers-reduced-motion: no-preference) {
  table.bidding td.turn { animation: pulse 1.6s ease-in-out infinite; }
  @keyframes pulse { 50% { background: transparent; } }
}
.bidnote { margin-top: 8px; padding: 10px 40px 10px 12px; border-radius: 8px;
           background: var(--accent-tint); font-size: 13px; line-height: 1.4;
           position: relative; }
.bidnote b { font-size: 15px; white-space: nowrap; margin-right: 6px; }
.bidnote .x { position: absolute; right: 0; top: 0; width: 44px;
              height: 100%; min-height: 40px; border: 0; background: none;
              color: var(--muted); font-size: 16px; cursor: pointer; }
/* ---- hand diagram ---- */
.hand { margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--line);
        font-size: 21px; }
.hand .srow { line-height: 1.5; }
.hand .cd { margin-right: .18em; }
/* ---- full deal, placed by table position (N top, W/E sides, S bottom),
   with a felt compass in the middle \\u2014 the classic bridge diagram ---- */
.fulldeal { display: grid; grid-template-columns: 1fr 1fr 1fr;
            grid-template-areas: ".  n  ." "w  c  e" ".  s  ."; gap: 7px;
            align-items: center; margin: 10px 0 2px; }
.fd-n { grid-area: n; } .fd-e { grid-area: e; }
.fd-s { grid-area: s; } .fd-w { grid-area: w; }
.fdhand { border: 1px solid var(--line); border-radius: 8px; padding: 5px 8px;
          font-size: 13px; line-height: 1.4; background: var(--card); }
.fdhand.hero { border-color: var(--gold);
               box-shadow: inset 0 0 0 1px var(--gold); }
.fdhand .lbl { display: flex; justify-content: space-between; gap: 6px;
               font-size: 10px; font-weight: 700; letter-spacing: .04em;
               color: var(--muted); margin-bottom: 3px; }
.fdhand .lbl .role { font-weight: 700; text-transform: uppercase;
                     color: var(--accent); }
.fdhand.hero .lbl .role { color: var(--gold); }
.fdrow { line-height: 1.45; }
.fdrow .cd { margin-right: .12em; }
.fdcompass { grid-area: c; justify-self: center; width: 58px; height: 58px;
             border-radius: 8px; color: var(--on-felt);
             background: radial-gradient(circle at 50% 42%, var(--felt),
                                         var(--felt-deep));
             display: grid; grid-template-columns: 1fr 1fr 1fr;
             grid-template-areas: ".  cn  ." "cw  .  ce" ".  cs  .";
             place-items: center; font-size: 10px; font-weight: 700; }
.fdcompass .cn { grid-area: cn; } .fdcompass .cw { grid-area: cw; }
.fdcompass .ce { grid-area: ce; } .fdcompass .cs { grid-area: cs; }
/* ---- bidding-box candidates ---- */
.candidates { display: grid; gap: 8px; margin: 12px 0;
              grid-template-columns: repeat(auto-fit, minmax(88px, 1fr)); }
button.cand { min-height: 56px; border-radius: 10px; font-size: 20px;
              font-weight: 700; background: var(--card); color: var(--fg);
              border: 1px solid var(--line); box-shadow: 0 1px 2px #00000026;
              cursor: pointer; position: relative;
              display: flex; align-items: center; justify-content: center; }
button.cand:active { transform: translateY(1px); box-shadow: none; }
button.cand span { margin-left: 2px; }
button.cand.p { color: var(--win); }
button.cand.x { color: var(--loss); }
button.cand.xx { color: var(--accent); }
button.cand.good { border: 2px solid var(--win); background: #E7F4EC; }
button.cand.bad { border: 2px solid var(--loss); background: #FAE8E9; }
button.cand.chosen { outline: 2px solid var(--accent); outline-offset: 2px; }
button.cand.off { color: var(--muted); box-shadow: none; }
button.cand.good::after, button.cand.bad::after {
  position: absolute; top: 2px; right: 6px; font-size: 13px; }
button.cand.good::after { content: "\\2713"; color: var(--win); }
button.cand.bad::after { content: "\\2717"; color: var(--loss); }
@media (prefers-color-scheme: dark) {
  button.cand.good { background: #24382C; }
  button.cand.bad { background: #3A2626; }
}
/* ---- verdict: outcome-first option rows ---- */
#verdict { display: none; }
.headline { font-size: 18px; font-weight: 700; margin: 0 0 2px; }
.headline .ok { color: var(--win); } .headline .no { color: var(--loss); }
.subline { font-size: 13px; color: var(--muted); margin-bottom: 10px; }
.legend { font-size: 11px; color: var(--muted); margin: 8px 0 2px; }
.legend i { display: inline-block; width: 8px; height: 8px;
            border-radius: 2px; margin: 0 3px 0 10px; }
.legend i:first-child { margin-left: 0; }
.opt { padding: 12px 4px; border-top: 1px solid var(--line); }
.opt.mine { background: #C8102E0A; border-radius: 8px; }
.opt .l1 { display: flex; align-items: center; gap: 8px; }
.bidchip { min-width: 40px; height: 32px; border-radius: 6px;
           border: 1px solid var(--line); font-size: 16px; font-weight: 700;
           display: inline-flex; align-items: center; justify-content: center;
           padding: 0 6px; background: var(--card); }
.tag { font-size: 10px; font-weight: 700; letter-spacing: .05em;
       color: #fff; border-radius: 999px; padding: 2px 7px; }
.tag.best { background: var(--win); } .tag.you { background: var(--accent); }
.opt .shows { color: var(--muted); font-size: 13px; flex: 1;
              overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.opt .ev { font-size: 16px; font-weight: 700;
           font-variant-numeric: tabular-nums; white-space: nowrap; }
.opt .ev small { font-size: 12px; font-weight: 400; color: var(--muted); }
.opt .ev .best { color: var(--win); }
.wpl { display: flex; justify-content: space-between; height: 10px;
       border-radius: 5px; overflow: hidden; background: var(--push);
       margin: 8px 0 6px; }
.wpl .w { background: var(--win); } .wpl .l { background: var(--loss); }
.chips { font-size: 12px; color: var(--muted); display: flex; flex-wrap: wrap;
         gap: 6px; align-items: center;
         font-variant-numeric: tabular-nums; }
.chip { background: var(--nonvul); color: var(--on-nonvul);
        border: 1px solid var(--line); border-radius: 999px; padding: 2px 8px;
        white-space: nowrap; }
.chip.them { background: transparent; color: var(--muted); }
.confirmbox .l1 { display: flex; align-items: center; gap: 10px;
                  min-height: 32px; }
.confirmbox .shows { color: var(--muted); font-size: 14px; }
.confirmbox .big { margin: 12px 0 0; }
.fog { background: var(--warn-bg); color: var(--warn-fg);
       border: 1px solid var(--warn-line); border-radius: 8px;
       padding: 8px 12px; font-size: 13px; margin: 10px 0; }
.footnote { font-size: 12px; color: var(--muted); margin: 8px 0 0; }
a.big, button.big { display: block; width: 100%; text-align: center;
  font-size: 17px; font-weight: 700; padding: 15px; border-radius: 12px;
  margin: 14px 0 6px; background: var(--gold); color: var(--on-gold);
  text-decoration: none; border: none; cursor: pointer; min-height: 52px; }
details { margin: 6px 0 0; }
details summary { cursor: pointer; color: var(--muted); font-size: 13px;
                  min-height: 40px; display: flex; align-items: center; }
.notes ul { margin: 4px 0 8px; padding-left: 18px; font-size: 13px; }
.notes li { margin: 6px 0; line-height: 1.4; }
table.plain { border-collapse: collapse; width: 100%; font-size: 13px;
              font-variant-numeric: tabular-nums; }
table.plain th, table.plain td { border-top: 1px solid var(--line);
  padding: 6px 8px; text-align: left; }
table.plain th { color: var(--muted); font-weight: 600; border-top: 0; }
/* scenario switch: the site's top-level split (blue = bidding, gold = lead) */
.scenaseg { display: flex; gap: 6px; background: var(--card); border-radius: 12px;
  padding: 5px; margin: 0 0 12px; border: 1px solid var(--line); }
.scenaseg button { flex: 1; border: 0; background: transparent; color: var(--muted);
  border-radius: 9px; padding: 9px 6px; cursor: pointer; font-size: 15px;
  font-weight: 700; display: flex; flex-direction: column; gap: 2px;
  min-height: 52px; align-items: center; justify-content: center; }
.scenaseg button small { font-weight: 400; font-size: 11px; opacity: .82; }
.scenaseg button[data-kind="bidding"][aria-pressed="true"] {
  background: var(--accent); color: #fff; }
.scenaseg button[data-kind="lead"][aria-pressed="true"] {
  background: var(--gold); color: var(--on-gold); }
/* opening-lead answer grid: the hand IS the keypad, one row per suit */
.leadgrid { margin: 12px 0; }
.suitrow { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin: 5px 0; }
.suitrow .s { width: 1.4em; font-size: 20px; text-align: center; }
button.cardbtn { min-width: 44px; min-height: 48px; font-size: 17px; font-weight: 600;
  border: 2px solid var(--line); border-radius: 9px; background: var(--card);
  color: var(--fg); cursor: pointer; }
button.cardbtn.chosen { border-color: var(--accent); }
button.cardbtn.good { border-color: var(--win);
  background: color-mix(in srgb, var(--win) 16%, var(--card)); }
button.cardbtn.bad { border-color: var(--loss);
  background: color-mix(in srgb, var(--loss) 16%, var(--card)); }
/* reveal: per-suit bar comparison instead of a wall of decimals */
.barrow { display: flex; align-items: center; gap: 8px; margin: 5px 0; font-size: 14px; }
.barrow .bl { width: 3.4em; }
.bartrack { flex: 1; height: 14px; border-radius: 99px; background: var(--line);
  overflow: hidden; }
.bartrack span { display: block; height: 100%; background: var(--accent); }
.bartrack span.good { background: var(--win); }
.barval { width: 6.2em; text-align: right; font-variant-numeric: tabular-nums;
  color: var(--muted); font-size: 12px; }
#bid-meaning { min-height: 1.2em; margin: 6px 0 0; }
.headline { font-size: 18px; font-weight: 700; margin: 4px 0; }
.headline .ok { color: var(--win); } .headline .no { color: var(--loss); }
"""

_SHARED_JS = """
/* Progress + pool now live in Firestore (see web/bt-firebase.js, window.BT).
   store() returns the signed-in user's answered-problem cache synchronously
   (preloaded at sign-in); answers persist through BT.record. */
function store() { return (window.BT && window.BT.attempts()) || {}; }
function saveStore(s) { /* no-op: attempts persist via BT.record */ }
async function fetchIndex() {
  if (!window.BT) throw new Error("Firebase not ready");
  return window.BT.fetchIndex();
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
function routeFor(kind, id) {
  return (kind === "lead" ? "lead.html" : "p.html") + "?id=" +
         encodeURIComponent(id);
}
/* which levels/types exist for a scenario right now, and how many each holds.
   Bidding facets on difficulty x type; leads on difficulty only. */
function poolFacets(index, kind) {
  kind = kind || "bidding";
  const levelCount = {}, typeCount = {};
  for (const p of index.problems) {
    if (kindOf(p) !== kind) continue;
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
/* turn stored (or absent) filters into concrete selected sets */
function resolveFilters(index, raw, kind) {
  kind = kind || "bidding";
  const f = poolFacets(index, kind);
  const base = raw || {};
  return {
    kind,
    levels: Array.isArray(base.levels) ? base.levels : f.levels.slice(),
    types: Array.isArray(base.types) ? base.types : f.types.slice(),
  };
}
function matchesFilters(p, f) {
  if (kindOf(p) !== (f.kind || "bidding")) return false;
  if (!f.levels.includes(p.difficulty_level)) return false;
  if (kindOf(p) === "lead") return true;      // leads: difficulty only
  return f.types.includes(p.type);            // bidding: difficulty + type
}
function pickUnseen(index, filters) {
  const s = store();
  const f = filters || resolveFilters(index, loadFilters());
  const unseen = index.problems.filter(p => !s[p.id] && matchesFilters(p, f));
  if (!unseen.length) return null;
  return unseen[Math.floor(Math.random() * unseen.length)].id;
}
/* BBO four-color deck */
const SUITS = {S: ["ss", "\\u2660"], H: ["sh", "\\u2665"],
               D: ["sd", "\\u2666"], C: ["sc", "\\u2663"]};
function suitHtml(st) {
  const [cls, g] = SUITS[st];
  return `<span class="${cls}">${g}</span>`;
}
function glyphify(text) {
  return text.replace(/!([SHDC])/g, (_, st) => suitHtml(st));
}
function callHtml(tok) {
  if (tok === "P") return "Pass";
  if (tok === "X") return "Dbl";
  if (tok === "XX") return "Rdbl";
  const denom = tok.slice(1);
  if (denom === "NT") return tok;
  return tok[0] + suitHtml(denom);
}
function contractHtml(tok) {
  const m = /^(\\d)([CDHSN])([NESW])$/.exec(tok);
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
    if (["artificial", "forcing", "bidable suit",
         "calculated bid"].includes(low)) continue;
    if (low === "balanced") {
      if (denom !== "NT" && !name) name = "Balanced";
      continue;
    }
    if (/\\d+\\s*(\\+|-\\s*\\d+)?\\s*HCP/i.test(p)) continue;
    const m = /^(\\d+)\\s*\\+?\\s*!?([SHDC])$/.exec(p);
    if (m) { tsuits.push([+m[1], m[2]]); continue; }
    if (!name && p.length <= 18) name = p;
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
  for (const [st, v] of suits) frags.push(v + "+" + suitHtml(st));
  const hcp = card.hcp;
  if (hcp) {
    const [lo, hi] = hcp;
    if (hi >= 25) { if (lo > 0) frags.push(lo + "+"); }
    else frags.push(lo + "-" + hi);
  }
  return frags.join(", ");
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
    return `<div class="srow">${suitHtml(s)} ${cards || "\\u2014"}</div>`;
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
      return `<div class="fdrow">${suitHtml(st)} ${cards || "\\u2014"}</div>`;
    }).join("");
    const role = roles[s] || "";
    const hero = role === "you" || role === "lead" ? " hero" : "";
    return `<div class="fd fd-${s.toLowerCase()}">` +
      `<div class="fdhand${hero}"><div class="lbl"><span>${s}</span>` +
      `<span class="role">${role}</span></div>${rows}</div></div>`;
  }
  const compass = `<div class="fdcompass" aria-hidden="true">` +
    `<span class="cn">N</span><span class="cw">W</span>` +
    `<span class="ce">E</span><span class="cs">S</span></div>`;
  return `<div class="fulldeal">${cell("N")}${cell("W")}${compass}` +
         `${cell("E")}${cell("S")}</div>`;
}
/* fixed W-N-E-S auction diagram (BBO layout); vulnerability lives on the
   seat plates: red = vulnerable, green = not. notes[j] non-empty marks a
   call as tappable (alert-style explanation). */
function auctionTableHtml(p, notes) {
  const cols = ["W", "N", "E", "S"];
  const seats = ["N", "E", "S", "W"];
  const hero = p.seat, partner = seats[(seats.indexOf(hero) + 2) % 4];
  const vul = vulSeats(p.vul);
  const head = cols.map(s => {
    const cls = (vul.includes(s) ? "v" : "nv") + (s === hero ? " me" : "");
    const who = s === hero ? "you" : (s === partner ? "pard" : "");
    const vlab = vul.includes(s) ? "vulnerable" : "not vulnerable";
    return `<th class="${cls}" title="${s} \\u2014 ${vlab}">${s}` +
           `${s === p.dealer ? '<sup class="d">D</sup>' : ""}` +
           `${who ? `<small>${who}</small>` : "<small>&nbsp;</small>"}</th>`;
  }).join("");
  const cells = [];
  for (let i = 0; i < cols.indexOf(p.dealer); i++) cells.push("<td></td>");
  let seat = p.dealer;
  p.auction.forEach((tok, j) => {
    const note = notes && notes[j];
    cells.push(`<td><span class="call${note ? " expl" : ""}"` +
               ` data-i="${j}">${callHtml(tok)}</span></td>`);
    seat = seats[(seats.indexOf(seat) + 1) % 4];
  });
  cells.push('<td class="turn">?</td>');
  while (cells.length % 4) cells.push("<td></td>");
  let rows = "";
  for (let i = 0; i < cells.length; i += 4)
    rows += "<tr>" + cells.slice(i, i + 4).join("") + "</tr>";
  return `<table class="bidding"><tr>${head}</tr>${rows}</table>`;
}
function cardHtml(tok) {  // "SK" -> four-colour suit glyph + rank (T -> 10)
  const r = tok[1] === "T" ? "10" : tok[1];
  return suitHtml(tok[0]) + " " + r;
}
/* A COMPLETE auction (W-N-E-S, BBO layout) for opening-lead problems: no
   pending-call cell, the final contract call highlighted, and every call
   tappable for its meaning (notes[j].text). Leader plate reads "lead". */
function completeAuctionTableHtml(p, notes) {
  const cols = ["W", "N", "E", "S"];
  const seats = ["N", "E", "S", "W"];
  const hero = p.leader, decl = p.declarer;
  const dummy = seats[(seats.indexOf(decl) + 2) % 4];
  const vul = vulSeats(p.vul);
  const head = cols.map(s => {
    const cls = (vul.includes(s) ? "v" : "nv") + (s === hero ? " me" : "");
    const who = s === hero ? "lead" : (s === decl ? "decl"
              : (s === dummy ? "dummy" : ""));
    const vlab = vul.includes(s) ? "vulnerable" : "not vulnerable";
    return `<th class="${cls}" title="${s} \\u2014 ${vlab}">${s}` +
           `${s === p.dealer ? '<sup class="d">D</sup>' : ""}` +
           `${who ? `<small>${who}</small>` : "<small>&nbsp;</small>"}</th>`;
  }).join("");
  let lastBid = -1;
  p.auction.forEach((t, j) => {
    if (t !== "P" && t !== "X" && t !== "XX") lastBid = j;
  });
  const cells = [];
  for (let i = 0; i < cols.indexOf(p.dealer); i++) cells.push("<td></td>");
  p.auction.forEach((tok, j) => {
    const note = notes && notes[j] && notes[j].text;
    const fin = j === lastBid ? " fin" : "";
    cells.push(`<td><span class="call${note ? " expl" : ""}${fin}"` +
               ` data-i="${j}">${callHtml(tok)}</span></td>`);
  });
  while (cells.length % 4) cells.push("<td></td>");
  let rows = "";
  for (let i = 0; i < cells.length; i += 4)
    rows += "<tr>" + cells.slice(i, i + 4).join("") + "</tr>";
  return `<table class="bidding"><tr>${head}</tr>${rows}</table>`;
}
function candOrder(c) {
  if (c === "P") return 100;
  if (c === "X") return 101;
  if (c === "XX") return 102;
  return +c[0] * 10 + ["C", "D", "H", "S", "NT"].indexOf(c.slice(1));
}
/* classification display names (ids: engine/classify.py taxonomy) */
const TYPE_NAMES = {
  open_or_pass: ["Opening decision",
    "Open a borderline hand, or pass \\u2014 and with which opening?"],
  preempt_decision: ["Preempt decision",
    "Obstruct or not \\u2014 and how high?"],
  enter_auction: ["Enter the auction?",
    "Overcall, double, or stay out of their auction?"],
  compete_or_sell: ["Part-score battle",
    "Bid once more, pass, or push them higher?"],
  invite_or_game: ["Invite or game?",
    "Sign off, invite, or bid game \\u2014 accept or reject the try?"],
  slam_try: ["Slam decision",
    "Move toward slam, or settle for game?"],
  choice_of_strain: ["Choice of strain",
    "The level is settled \\u2014 but WHERE: which suit, or notrump?"],
  double_or_bid: ["Double decision",
    "Double, bid on, or pass \\u2014 leave partner's double in or pull?"],
  sacrifice_decision: ["Save or defend?",
    "Deliberately outbid their making contract, or take the defense?"],
  describe_hand: ["Describe your hand",
    "Which constructive call best shows your strength and shape?"],
};
const DIFF_NAMES = ["", "Easy", "Moderate", "Tricky", "Hard", "Expert"];
function typeBadgeHtml(p) {
  const t = p.classification && p.classification.type;
  const nm = TYPE_NAMES[t];
  if (!nm) return "";
  return `<div><span class="typebadge" title="${nm[1]}">${nm[0]}</span></div>`;
}
function diffLineHtml(p) {
  const lv = p.classification && p.classification.difficulty_level;
  if (!lv || lv < 1 || lv > 5) return "";
  return `<span>Difficulty</span>` +
    `<span class="stars" role="img" aria-label="difficulty ${lv} out of 5">` +
    `<span class="on">${"\\u2605".repeat(lv)}</span>` +
    `<span class="off">${"\\u2605".repeat(5 - lv)}</span></span>` +
    `<b>${DIFF_NAMES[lv]}</b>`;
}
"""


def _index_html() -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bridge Bidding Trainer</title>
<style>{_CSS}</style>
<script type="module" src="bt-firebase.js"></script></head><body>
<h1><span style="opacity:.9">&spades;</span> Bridge Trainer</h1>
<div class="scenaseg" id="scenario" role="group" aria-label="Practice scenario">
<button type="button" data-kind="bidding" aria-pressed="true">Bidding
<small>your call at the table</small></button>
<button type="button" data-kind="lead" aria-pressed="false">Opening lead
<small>which card to lead</small></button>
</div>
<div class="card" id="filters">
<button type="button" class="fbar" id="fbar" aria-expanded="false"
        aria-controls="fbody">
<span class="fbar-main">Choose difficulty &amp; type</span>
<span class="fbar-sub" id="fbar-sub"></span>
<span class="fbar-chev" aria-hidden="true">&#9662;</span>
</button>
<div class="fbody" id="fbody" hidden>
<div class="fgroup">
<div class="grow"><span class="glabel">Difficulty</span>
<button type="button" class="alllink" id="all-diff"></button></div>
<div class="seg" id="diff-seg"></div>
</div>
<div class="fgroup" id="type-group">
<div class="grow"><span class="glabel">Problem type</span>
<button type="button" class="alllink" id="all-type"></button></div>
<div class="typelist" id="type-list"></div>
</div>
</div>
</div>
<a class="big" id="deal" href="#">Deal me a hand &rarr;</a>
<div class="card" id="stats">Loading the problem pool&hellip;</div>
<script>{_SHARED_JS}
let INDEX = null;
const SCEN_KEY = "bt_scenario";
const LEAD_FILTERS_KEY = "bt_lead_filters";
let SCEN = localStorage.getItem(SCEN_KEY) || "bidding";
let FILTERS = {{kind: SCEN, levels: [], types: []}};
function curKey() {{ return SCEN === "lead" ? LEAD_FILTERS_KEY : FILTERS_KEY; }}
function loadCur() {{
  try {{ return JSON.parse(localStorage.getItem(curKey())); }}
  catch (e) {{ return null; }}
}}
function saveCur(f) {{ localStorage.setItem(curKey(), JSON.stringify(f)); }}
function setScenario(kind) {{
  SCEN = kind; localStorage.setItem(SCEN_KEY, kind);
  document.body.dataset.scenario = kind;
  document.querySelectorAll("#scenario button").forEach(b =>
    b.setAttribute("aria-pressed", b.dataset.kind === kind ? "true" : "false"));
  document.getElementById("type-group").style.display =
    kind === "lead" ? "none" : "";
  FILTERS = resolveFilters(INDEX, loadCur(), kind);
  buildFilters(); applyFilterUi(); updateFacetCounts(); renderStats();
}}
function toggleFilter(list, value) {{
  const i = list.indexOf(value);
  if (i === -1) list.push(value); else list.splice(i, 1);
}}
function buildFilters() {{
  const f = poolFacets(INDEX, FILTERS.kind);
  const seg = document.getElementById("diff-seg");
  seg.style.setProperty("--n", f.levels.length || 1);
  seg.innerHTML = f.levels.map(lv =>
    `<button type="button" data-level="${{lv}}">` +
    `<span class="sname">${{DIFF_NAMES[lv]}}</span>` +
    `<span class="scount">0</span></button>`).join("");
  document.getElementById("type-list").innerHTML = f.types.map(t => {{
    const nm = TYPE_NAMES[t];
    return `<button type="button" class="typerow" data-type="${{t}}" ` +
      `title="${{nm[1]}}">` +
      `<span class="tick" aria-hidden="true"></span>` +
      `<span class="tname">${{nm[0]}}</span>` +
      `<span class="tbar"><span style="width:0%"></span></span>` +
      `<span class="tcount">0</span></button>`;
  }}).join("");
}}
/* Counts shown on each option are cross-filtered: a difficulty segment
   counts only problems whose type is currently selected, and a type row
   counts only problems whose difficulty is currently selected. So picking
   "Hard" makes every type row show its Hard-only tally. Each axis ignores
   its own selection (standard faceting) so you can still see what turning an
   option back on would add. */
function facetCounts(index, flt) {{
  const levelCount = {{}}, typeCount = {{}};
  for (const p of index.problems) {{
    if (kindOf(p) !== flt.kind) continue;
    if (p.difficulty_level && (flt.kind === "lead" || flt.types.includes(p.type)))
      levelCount[p.difficulty_level] =
        (levelCount[p.difficulty_level] || 0) + 1;
    if (p.type && flt.levels.includes(p.difficulty_level))
      typeCount[p.type] = (typeCount[p.type] || 0) + 1;
  }}
  return {{levelCount, typeCount}};
}}
function updateFacetCounts() {{
  const c = facetCounts(INDEX, FILTERS);
  document.querySelectorAll("#diff-seg button").forEach(b => {{
    b.querySelector(".scount").textContent = c.levelCount[+b.dataset.level] || 0;
  }});
  const rows = [...document.querySelectorAll("#type-list .typerow")];
  const max = Math.max(1, ...rows.map(b => c.typeCount[b.dataset.type] || 0));
  rows.forEach(b => {{
    const n = c.typeCount[b.dataset.type] || 0;
    b.querySelector(".tcount").textContent = n;
    b.querySelector(".tbar > span").style.width = Math.round(100 * n / max) + "%";
    b.setAttribute("aria-label",
      `${{b.querySelector(".tname").textContent}}, ${{n}} problems`);
  }});
}}
function applyFilterUi() {{
  const f = poolFacets(INDEX, FILTERS.kind);
  document.querySelectorAll("#diff-seg button").forEach(b =>
    b.classList.toggle("active", FILTERS.levels.includes(+b.dataset.level)));
  document.querySelectorAll("#type-list .typerow").forEach(b =>
    b.setAttribute("aria-pressed",
      FILTERS.types.includes(b.dataset.type) ? "true" : "false"));
  document.getElementById("all-diff").textContent =
    FILTERS.levels.length >= f.levels.length ? "Clear" : "Select all";
  document.getElementById("all-type").textContent =
    FILTERS.types.length >= f.types.length ? "Clear" : "Select all";
}}
function persist() {{
  const f = poolFacets(INDEX, FILTERS.kind);
  const full = FILTERS.levels.length >= f.levels.length &&
    (FILTERS.kind === "lead" || FILTERS.types.length >= f.types.length);
  if (full) localStorage.removeItem(curKey());   // everything -> follow the pool
  else saveCur({{levels: FILTERS.levels, types: FILTERS.types}});
  applyFilterUi(); updateFacetCounts(); renderStats();
}}
document.getElementById("diff-seg").addEventListener("click", ev => {{
  const b = ev.target.closest("button[data-level]");
  if (!b) return;
  toggleFilter(FILTERS.levels, +b.dataset.level);
  persist();
}});
document.getElementById("type-list").addEventListener("click", ev => {{
  const b = ev.target.closest("button[data-type]");
  if (!b) return;
  toggleFilter(FILTERS.types, b.dataset.type);
  persist();
}});
document.getElementById("all-diff").onclick = () => {{
  const f = poolFacets(INDEX, FILTERS.kind);
  FILTERS.levels =
    FILTERS.levels.length >= f.levels.length ? [] : f.levels.slice();
  persist();
}};
document.getElementById("all-type").onclick = () => {{
  const f = poolFacets(INDEX, FILTERS.kind);
  FILTERS.types =
    FILTERS.types.length >= f.types.length ? [] : f.types.slice();
  persist();
}};
function renderStats() {{
  if (!INDEX) return;
  const s = store();
  const matching = INDEX.problems.filter(p => matchesFilters(p, FILTERS));
  let done = 0, right = 0;
  for (const p of matching) {{
    const rec = s[p.id];
    if (rec) {{ done++; if (rec.correct) right++; }}
  }}
  const f = poolFacets(INDEX, FILTERS.kind);
  const kindTotal =
    INDEX.problems.filter(p => kindOf(p) === FILTERS.kind).length;
  const narrowed = FILTERS.levels.length < f.levels.length ||
    (FILTERS.kind !== "lead" && FILTERS.types.length < f.types.length);
  const label = FILTERS.kind === "lead" ? "lead problems" : "bidding problems";
  const waiting = matching.length - done;
  let h = (narrowed
      ? `<b>${{matching.length}}</b> of ${{kindTotal}} ${{label}} selected `
      : `<b>${{kindTotal}}</b> ${{label}} in the pool `) +
    `<span class="pill" style="border-color:var(--line);color:var(--muted)">` +
    `${{waiting}} waiting for you</span>`;
  if (done) {{
    const pct = Math.round(100 * right / done);
    h += `<div style="margin-top:8px">Your record: <b>${{right}}</b> / ` +
      `${{done}} answered</div>` +
      `<div class="wpl" role="img" aria-label="${{pct}}% correct">` +
      `<span class="w" style="width:${{pct}}%"></span></div>`;
  }} else {{
    h += `<div style="margin-top:8px" class="muted">` +
      `You haven't answered any yet.</div>`;
  }}
  document.getElementById("stats").innerHTML = h;
  const fbar = document.getElementById("fbar");
  document.getElementById("fbar-sub").textContent =
    narrowed ? `${{matching.length}} of ${{kindTotal}}` : "All problems";
  fbar.classList.toggle("on", narrowed);
  const deal = document.getElementById("deal");
  const none = !FILTERS.levels.length ||
    (FILTERS.kind !== "lead" && !FILTERS.types.length);
  deal.classList.toggle("off", none);
  const dealLabel = FILTERS.kind === "lead"
    ? "Deal me a lead problem &rarr;" : "Deal me a bidding problem &rarr;";
  deal.innerHTML = none
    ? (FILTERS.kind === "lead" ? "Pick a difficulty"
       : "Pick a difficulty and type")
    : dealLabel + (waiting
      ? ` <span style="font-weight:400;opacity:.85">(${{waiting}} waiting)` +
        `</span>`
      : "");
}}
async function init() {{
  try {{ INDEX = await fetchIndex(); }}
  catch (e) {{
    document.getElementById("stats").textContent =
      "The problem pool is still being generated \\u2014 check back shortly.";
    return;
  }}
  setScenario(SCEN);
}}
document.querySelectorAll("#scenario button").forEach(b =>
  b.onclick = () => setScenario(b.dataset.kind));
document.getElementById("fbar").onclick = () => {{
  const bar = document.getElementById("fbar");
  const body = document.getElementById("fbody");
  const open = bar.getAttribute("aria-expanded") === "true";
  bar.setAttribute("aria-expanded", open ? "false" : "true");
  if (open) body.setAttribute("hidden", ""); else body.removeAttribute("hidden");
}};
document.getElementById("deal").onclick = () => {{
  if (!INDEX) return false;
  if (!FILTERS.levels.length ||
      (FILTERS.kind !== "lead" && !FILTERS.types.length)) return false;
  const id = pickUnseen(INDEX, FILTERS);
  if (!id) {{
    alert("You've answered every problem in your selection! " +
          "Widen your filters, or check back for the next batch.");
    return false;
  }}
  location.href = routeFor(FILTERS.kind, id);
  return false;
}};
if (window.BT) window.BT.start(init);
else addEventListener("bt-ready", () => window.BT.start(init), {{once: true}});
</script>
</body></html>"""


def _problem_html() -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bidding problem</title>
<style>{_CSS}</style>
<script type="module" src="bt-firebase.js"></script></head><body>
<div class="topbar">
<a href="index.html">&larr; home</a>
<span id="meta"></span>
</div>
<div id="problem"></div>
<div class="candidates" id="cands"></div>
<div id="confirm"></div>
<div id="verdict" class="card">
<div class="headline" id="headline"></div>
<div class="subline" id="subline"></div>
<div class="diffline" id="diffline"></div>
<div id="fog"></div>
<div class="legend"><i style="background:var(--win)"></i>wins
<i style="background:var(--push)"></i>push
<i style="background:var(--loss)"></i>loses</div>
<div id="opts"></div>
<div class="footnote" id="footnote"></div>
<div class="footnote" id="source"></div>
<button class="big" id="next">Next deal &rarr;</button>
<details class="notes" id="deal-box"><summary>The full deal</summary>
<div id="fulldeal"></div></details>
<details class="notes" id="review-box" style="display:none">
<summary>Auction, bid by bid</summary><ul id="review"></ul></details>
<details class="notes" id="prose-box" style="display:none">
<summary>Full analysis</summary><div id="explanation"
style="white-space:pre-line;font-size:13px"></div></details>
<details class="notes" id="meanings-box"><summary>Assumed meanings of the
auction</summary><ul id="meanings"></ul></details>
<details class="notes" id="raw-box"><summary>Raw double-dummy view</summary>
<table id="rtable" class="plain"></table></details>
</div>
<script>{_SHARED_JS}
let P = null, INDEX = null, NOTES = [], OPTSHOWS = {{}};
function stripNoise(t) {{
  return (t || "").replace(/Next call is usually[^]*?%\\)\\.\\s*/g, "")
                  .replace(/most common continuation:[^]*?%\\)\\.\\s*/g, "");
}}
function evHtml(row, isTop) {{
  const ci = row.ci !== undefined ?
    ` <small>\\u00b1${{(+row.ci).toFixed(1)}}</small>` : "";
  const ev = (+row.ev).toFixed(1);
  if (isTop) {{
    return `<span class="best">best</span>` +
           (row.ev > 0 ? ` +${{ev}}${{ci}}` : "");
  }}
  return `${{row.ev >= 0 ? "+" : "\\u2212"}}${{Math.abs(+ev).toFixed(1)}}${{ci}}`;
}}
function chipsHtml(row) {{
  const bits = [];
  const n = (P.quality && P.quality.n_samples) ||
            (P.generator && P.generator.n_deals) || 0;
  const seats = ["N", "E", "S", "W"];
  const partner = seats[(seats.indexOf(P.seat) + 2) % 4];
  for (const [tok, cnt] of (row.contracts || []).slice(0, 3)) {{
    const share = n ? cnt / n : 0;
    if (share < 0.02) continue;
    const decl = tok.slice(-1);
    const ours = decl === P.seat || decl === partner;
    bits.push(`<span class="chip${{ours ? "" : " them"}}">` +
              `${{contractHtml(tok)}} ${{Math.round(share * 100)}}%</span>`);
  }}
  if (row.policy !== undefined)
    bits.push(`<span>engine ${{Math.round(row.policy * 100)}}%</span>`);
  bits.push(`<span>wins ${{Math.round(row.p_gain * 100)}}%</span>`);
  return `<div class="chips">${{bits.join("")}}</div>`;
}}
function optRowHtml(row, i, chosen, accepted) {{
  const dead = (P.verdict.dead_options || []).some(d => d.bid === row.bid);
  const push = row.p_push !== undefined ? row.p_push
             : Math.max(0, 1 - row.p_gain - row.p_loss);
  const tags = (accepted.includes(row.bid)
                  ? '<span class="tag best">BEST</span>' : "") +
               (row.bid === chosen ? '<span class="tag you">YOU</span>' : "");
  const shows = row.shows ? `<span class="shows">${{row.shows}}</span>`
                          : '<span class="shows"></span>';
  const bar = `<div class="wpl" role="img" aria-label="wins ` +
    `${{Math.round(row.p_gain * 100)}}%, push ${{Math.round(push * 100)}}%, ` +
    `loses ${{Math.round(row.p_loss * 100)}}%">` +
    `<span class="w" style="width:${{row.p_gain * 100}}%"></span>` +
    `<span class="l" style="width:${{row.p_loss * 100}}%"></span></div>`;
  const mine = row.bid === chosen && !accepted.includes(row.bid);
  return `<div class="opt${{mine ? " mine" : ""}}">` +
    `<div class="l1"><span class="bidchip">${{callHtml(row.bid)}}` +
    `${{dead ? "\\u2020" : ""}}</span>${{tags}}${{shows}}` +
    `<span class="ev">${{evHtml(row, i === 0)}}</span></div>` +
    `${{bar}}${{chipsHtml(row)}}</div>`;
}}
function reveal(chosen) {{
  const v = P.verdict;
  document.querySelectorAll("button.cand").forEach(b => {{
    const a = b.dataset.action;
    if (v.accepted.includes(a)) b.classList.add("good");
    else if (a === chosen) b.classList.add("bad");
    else b.classList.add("off");
    if (a === chosen) b.classList.add("chosen");
    b.disabled = true;
  }});
  const turn = document.querySelector("table.bidding td.turn");
  if (turn) turn.innerHTML = callHtml(chosen);
  const ok = v.accepted.includes(chosen);
  const rows = v.corrected || [];
  let head;
  if (v.toss_up) {{
    head = `<span class="${{ok ? "ok" : "no"}}">${{ok ? "\\u2713" : "\\u2717"}}
</span> Toss-up \\u2014 ${{v.accepted.map(callHtml).join(" or ")}} both fine`;
  }} else if (ok) {{
    head = `<span class="ok">\\u2713</span> ${{callHtml(chosen)}} ` +
           `\\u2014 best call`;
  }} else {{
    const mine = rows.find(r => r.bid === chosen);
    const gap = mine ? ` (${{(+mine.ev).toFixed(1)}} IMPs)` : "";
    head = `<span class="no">\\u2717</span> ${{callHtml(chosen)}} \\u2014 ` +
           `best was ${{callHtml(v.accepted[0])}}${{gap}}`;
  }}
  document.getElementById("headline").innerHTML = head;
  const n = (P.quality && P.quality.n_samples) ||
            (P.generator && P.generator.n_deals) || 0;
  document.getElementById("subline").textContent =
    `IMPs \\u00b7 corrected single-dummy view` +
    (n ? ` \\u00b7 ${{n}} simulated layouts` : "");
  document.getElementById("diffline").innerHTML = diffLineHtml(P);
  if (v.fog) document.getElementById("fog").innerHTML =
    '<div class="fog">\\u26a0 Double-dummy fog: raw and corrected views ' +
    'disagree \\u2014 lower confidence.</div>';
  document.getElementById("opts").innerHTML =
    rows.map((r, i) => optRowHtml(r, i, chosen, v.accepted)).join("");
  const feet = [];
  if ((v.dead_options || []).length)
    feet.push("\\u2020 never the winner on any simulated layout.");
  if ((v.flags || []).includes("doubled_heavy"))
    feet.push("Much of the doubled margin assumes double-dummy defense " +
              "\\u2014 treat the exact number with care.");
  if (P.explanations && P.explanations.note) {{
    const note = P.explanations.note;
    feet.push(note[0].toUpperCase() + note.slice(1) + ".");
  }}
  document.getElementById("footnote").textContent = feet.join(" ");
  if (P.source) {{
    const s = P.source;
    document.getElementById("source").innerHTML =
      `Real deal: <b>${{s.teams}}</b>, ${{s.event}}, board ${{s.board}}.`;
  }}
  // bid-by-bid review from the same terse grammar as the tap notes
  const items = [];
  const seats = ["N", "E", "S", "W"];
  let seat = P.dealer;
  P.auction.forEach((tok, j) => {{
    const who = seat === P.seat ? "You" : seat;
    if (NOTES[j])
      items.push(`<li><b>${{who}} ${{callHtml(tok)}}</b> \\u2014 ` +
                 `${{NOTES[j]}}</li>`);
    seat = seats[(seats.indexOf(seat) + 1) % 4];
  }});
  if (items.length) {{
    document.getElementById("review").innerHTML = items.join("");
    document.getElementById("review-box").style.display = "block";
  }}
  // legacy prose analysis (authored problems), noise stripped
  if (P.explanation && !(P.generator && P.generator.engine)) {{
    document.getElementById("explanation").textContent =
      stripNoise(P.explanation);
    document.getElementById("prose-box").style.display = "block";
  }}
  if (P.meanings && P.meanings.length) {{
    document.getElementById("meanings").innerHTML = P.meanings.map(m =>
      `<li><b>${{m.seat}}</b>: ${{m.meaning}}</li>`).join("");
  }} else {{
    document.getElementById("meanings-box").style.display = "none";
  }}
  if (P.full_deal) {{
    const seats = ["N", "E", "S", "W"];
    const pard = seats[(seats.indexOf(P.seat) + 2) % 4];
    const roles = {{}};
    roles[P.seat] = "you"; roles[pard] = "pard";
    document.getElementById("fulldeal").innerHTML =
      fullDealHtml(P.full_deal, roles);
  }} else {{
    document.getElementById("deal-box").style.display = "none";
  }}
  const rbox = document.getElementById("rtable");
  if (v.raw && v.raw.length) {{
    let h = "<tr><th>Action</th><th>EV (IMPs)</th><th>Wins</th>" +
            "<th>Loses</th></tr>";
    for (const c of v.raw)
      h += `<tr><td>${{callHtml(c.bid)}}</td><td>${{c.ev >= 0 ? "+" : ""}}` +
           `${{c.ev}} \\u00b1 ${{c.ci}}</td>` +
           `<td>${{Math.round(c.p_gain * 100)}}%</td>` +
           `<td>${{Math.round(c.p_loss * 100)}}%</td></tr>`;
    rbox.innerHTML = h;
  }} else document.getElementById("raw-box").style.display = "none";
  document.getElementById("verdict").style.display = "block";
}}
function choose(action) {{
  if (store()[P.id]) return;
  reveal(action);
  window.BT.record(P.id, window.BT.gradeBidding(P, action));
}}
/* two-step selection: first tap shows what the bid means, a second
   (confirm) tap locks the answer in */
let ARMED = null;
function arm(btn) {{
  if (store()[P.id]) return;
  const a = btn.dataset.action;
  const box = document.getElementById("confirm");
  document.querySelectorAll("button.cand")
    .forEach(b => b.classList.remove("chosen"));
  if (ARMED === a) {{ ARMED = null; box.innerHTML = ""; return; }}
  ARMED = a;
  btn.classList.add("chosen");
  const shows = OPTSHOWS[a];
  box.innerHTML = `<div class="card confirmbox"><div class="l1">` +
    `<span class="bidchip">${{callHtml(a)}}</span>` +
    `<span class="shows">${{shows || "no description"}}</span></div>` +
    `<button class="big" id="go">Bid ${{callHtml(a)}}</button></div>`;
  document.getElementById("go").onclick = () => {{
    ARMED = null; box.innerHTML = "";
    choose(a);
  }};
}}
function normalize() {{
  const v = P.verdict;
  if (!Array.isArray(v.accepted))
    v.accepted = v.toss_up ? v.toss_up_set : [v.accepted];
  v.fog = v.fog || (v.flags || []).includes("dd_fog");
  const policy = {{}};
  for (const c of P.candidates || []) {{
    if (c.call) policy[c.call] = c.policy;
  }}
  const cards = {{}};
  for (const o of (P.explanations && P.explanations.options) || []) {{
    if (o.card) cards[o.bid] = o.card;
    // what the bid shows, terse; older records only baked prose like
    // "5\\u2663 \\u2014 11-21 HCP. Next call ..." \\u2014 take the first
    // clause and strip the wordiness
    let m = o.card ? terse(o.card, o.bid) : "";
    const first = o.text ? o.text.split(". ")[0] : "";
    if (!m && first.includes("\\u2014")) {{
      m = first.replace(/^[^\\u2014]*\\u2014\\s*/, "").replace(/\\.$/, "")
        .replace(/^limited \\u2014 at most (\\d+) HCP$/, "0-$1")
        .replace(/\\s*HCP\\b/g, "");
    }}
    OPTSHOWS[o.bid] = m;
  }}
  if (v.table && !v.corrected) {{
    v.corrected = v.table.map(r => ({{
      bid: r.bid, ev: r.ev_imp_vs_top, ci: r.ci,
      p_gain: r.p_gain,
      p_loss: r.p_loss !== undefined ? r.p_loss
            : Math.max(0, 1 - r.p_gain - r.p_push),
      p_push: r.p_push,
      // Firestore forbids nested arrays, so the uploader wraps each
      // [contract, count] pair as {{items: [...]}}; unwrap it back here.
      // Static-file records keep the plain [contract, count] shape.
      contracts: (r.top_contracts || []).map(
        x => (x && x.items) ? x.items : x),
      policy: policy[r.bid],
      shows: OPTSHOWS[r.bid] || "",
    }}));
    v.raw = [];
  }} else if (v.corrected) {{
    // legacy authored-problem records ({{action, ev, ...}})
    v.corrected = v.corrected.map(r => ({{
      bid: r.bid || r.action, ev: r.ev, ci: r.ci,
      p_gain: r.p_gain, p_loss: r.p_loss, p_push: r.p_push,
      contracts: [], policy: policy[r.bid || r.action], shows: "",
    }}));
    v.raw = (v.raw || []).map(r => ({{
      bid: r.bid || r.action, ev: r.ev, ci: r.ci,
      p_gain: r.p_gain, p_loss: r.p_loss }}));
  }}
  if (P.generator)
    P.generator.n_deals = P.generator.n_deals || P.generator.samples;
  // tap-note per stem call, from the engine card (terse grammar);
  // fall back to the baked text minus its "1♦ (W): " prefix
  NOTES = P.auction.map((tok, j) => {{
    const e = P.explanations && P.explanations.stem &&
              P.explanations.stem[j];
    if (!e) return "";
    const t = e.card ? terse(e.card, tok) : "";
    if (t) return t;
    return (e.text || "").replace(/^[^:]*:\\s*/, "");
  }});
}}
async function init() {{
  const id = new URLSearchParams(location.search).get("id");
  P = await window.BT.getProblem(id);
  if (!P) {{ document.getElementById("problem").textContent =
                "Problem not found."; return; }}
  normalize();
  document.getElementById("meta").textContent =
    `IMPs \\u00b7 Dealer ${{P.dealer}} \\u00b7 you are ${{P.seat}}` +
    (P.category && P.category !== "other" ? ` \\u00b7 ${{P.category}}` : "");
  document.getElementById("problem").innerHTML =
    `<div class="card">${{typeBadgeHtml(P)}}${{auctionTableHtml(P, NOTES)}}` +
    `<div id="bidnote"></div>` +
    `<div class="hand">${{handHtml(P.hand)}}</div></div>`;
  // tap a bid -> alert-style explanation strip under the auction
  let openNote = -1;
  document.querySelector("table.bidding").addEventListener("click", ev => {{
    const el = ev.target.closest(".call.expl");
    const box = document.getElementById("bidnote");
    document.querySelectorAll(".call.open")
      .forEach(c => c.classList.remove("open"));
    if (!el || +el.dataset.i === openNote) {{
      openNote = -1; box.innerHTML = ""; return;
    }}
    openNote = +el.dataset.i;
    el.classList.add("open");
    const seats = ["N", "E", "S", "W"];
    const seat = seats[(seats.indexOf(P.dealer) + openNote) % 4];
    box.innerHTML = `<div class="bidnote"><b>` +
      `${{callHtml(P.auction[openNote])}} (${{seat}})</b> ` +
      `${{NOTES[openNote]}}` +
      `<button class="x" aria-label="dismiss">\\u2715</button></div>`;
    box.querySelector(".x").onclick = () => {{
      openNote = -1; box.innerHTML = "";
      document.querySelectorAll(".call.open")
        .forEach(c => c.classList.remove("open"));
    }};
  }});
  const cands = document.getElementById("cands");
  const list = P.candidates.map(c => c.call || c)
    .sort((a, b) => candOrder(a) - candOrder(b));
  for (const c of list) {{
    const b = document.createElement("button");
    b.className = "cand" +
      (c === "P" ? " p" : c === "X" ? " x" : c === "XX" ? " xx" : "");
    b.dataset.action = c;
    b.innerHTML = callHtml(c);
    if (c === "X") b.setAttribute("aria-label", "Double");
    if (c === "XX") b.setAttribute("aria-label", "Redouble");
    b.onclick = () => arm(b);
    cands.appendChild(b);
  }}
  document.getElementById("next").onclick = async () => {{
    if (!INDEX) INDEX = await fetchIndex();
    const nid = pickUnseen(INDEX, resolveFilters(INDEX, loadFilters(), "bidding"));
    if (!nid) {{ location.href = "index.html"; return; }}
    location.href = "p.html?id=" + encodeURIComponent(nid);
  }};
  const prev = store()[P.id];
  if (prev) reveal(prev.answer);
}}
if (window.BT) window.BT.start(init);
else addEventListener("bt-ready", () => window.BT.start(init), {{once: true}});
</script>
</body></html>"""


_LEAD_JS = r"""
let P = null, INDEX = null;
function avgOf(card) {
  const r = P.verdict.table.find(x => x.card === card);
  return r ? r.avg_def_tricks : 0;
}
function reveal(chosen) {
  const v = P.verdict, acc = v.accepted;
  document.querySelectorAll("button.cardbtn").forEach(b => {
    const a = b.dataset.action;
    if (acc.includes(a)) b.classList.add("good");
    else if (a === chosen) b.classList.add("bad");
    if (a === chosen) b.classList.add("chosen");
    b.disabled = true;
  });
  const ok = acc.includes(chosen);
  document.getElementById("headline").innerHTML = ok
    ? '<span class="ok">✓</span> Best lead — ' + cardHtml(chosen)
    : '<span class="no">✗</span> Better was ' + acc.map(cardHtml).join(" or ");
  document.getElementById("subhead").innerHTML = acc.length > 1
    ? "Equally best: " + acc.map(cardHtml).join(", ") : "";
  const tbl = v.table, maxv = tbl.length ? tbl[0].avg_def_tricks : 1;
  const seen = {}, picked = [];
  tbl.forEach(r => { if (!seen[r.card[0]]) { seen[r.card[0]] = 1; picked.push(r.card); } });
  if (picked.indexOf(chosen) < 0) picked.push(chosen);
  document.getElementById("bars").innerHTML = picked.map(c => {
    const val = avgOf(c), good = acc.includes(c);
    const pct = maxv > 0 ? Math.max(4, Math.round(val / maxv * 100)) : 0;
    const you = c === chosen ? ' <span class="muted">(your lead)</span>' : "";
    return '<div class="barrow"><span class="bl">' + cardHtml(c) + '</span>' +
      '<span class="bartrack"><span class="' + (good ? "good" : "") +
      '" style="width:' + pct + '%"></span></span>' +
      '<span class="barval">' + val.toFixed(2) + ' tr' + you + '</span></div>';
  }).join("");
  const notes = (P.explanations && P.explanations.cards) || [];
  const noteFor = c => { const n = notes.find(x => x.card === c); return n ? n.text : ""; };
  let expl = noteFor(acc[0]);
  if (!ok) { const y = noteFor(chosen); if (y) expl += "\n\n" + y; }
  document.getElementById("lead-expl").textContent = expl;
  const lv = (P.classification && P.classification.difficulty_level) || P.difficulty;
  document.getElementById("difficulty").textContent = "Difficulty " + lv + "/5";
  let rt = "<tr><th>Card</th><th>Avg def. tricks</th><th>vs best</th><th>BEN</th></tr>";
  v.table.forEach(r => {
    const g = acc.includes(r.card) ? ' style="font-weight:700"' : "";
    rt += "<tr" + g + "><td>" + cardHtml(r.card) + "</td><td>" +
      r.avg_def_tricks.toFixed(2) + "</td><td>" +
      (r.vs_best >= 0 ? "+" : "") + r.vs_best.toFixed(2) + "</td><td>" +
      Math.round((r.ben_softmax || 0) * 100) + "%</td></tr>";
  });
  document.getElementById("ltable").innerHTML = rt;
  if (P.full_deal) {
    const seats = ["N", "E", "S", "W"];
    const decl = P.declarer, dummy = seats[(seats.indexOf(decl) + 2) % 4];
    const pard = seats[(seats.indexOf(P.leader) + 2) % 4];
    const roles = {};
    roles[decl] = "decl"; roles[dummy] = "dummy";
    roles[P.leader] = "lead"; if (!roles[pard]) roles[pard] = "pard";
    document.getElementById("fulldeal").innerHTML =
      fullDealHtml(P.full_deal, roles);
  }
  document.getElementById("verdict").style.display = "block";
}
function commit(a) {
  if (store()[P.id]) return;
  reveal(a);
  window.BT.record(P.id, window.BT.gradeLead(P, a));
}
/* two-step selection: first tap arms the card, a second (confirm) tap
   leads it \\u2014 so one stray tap never locks in a final answer */
let ARMED = null;
function arm(btn) {
  if (store()[P.id]) return;
  const a = btn.dataset.action;
  const box = document.getElementById("confirm");
  document.querySelectorAll("button.cardbtn")
    .forEach(b => b.classList.remove("chosen"));
  if (ARMED === a) { ARMED = null; box.innerHTML = ""; return; }
  ARMED = a;
  btn.classList.add("chosen");
  box.innerHTML = '<div class="card confirmbox"><div class="l1">' +
    '<span class="bidchip">' + cardHtml(a) + '</span>' +
    '<span class="shows">Lead this card?</span></div>' +
    '<button class="big" id="go">Lead ' + cardHtml(a) + '</button></div>';
  document.getElementById("go").onclick = () => {
    ARMED = null; box.innerHTML = "";
    commit(a);
  };
}
function loadLead() {
  try { return JSON.parse(localStorage.getItem("bt_lead_filters")); }
  catch (e) { return null; }
}
async function init() {
  const id = new URLSearchParams(location.search).get("id");
  P = await window.BT.getProblem(id);
  if (!P) { document.getElementById("problem").textContent = "Problem not found."; return; }
  const meanings = (P.explanations && P.explanations.auction) || [];
  document.getElementById("meta").innerHTML =
    "Contract " + callHtml(P.contract.slice(0, -1)) + " by " + P.declarer +
    " · you lead (" + P.leader + ")";
  document.getElementById("problem").innerHTML =
    '<div class="card">' + completeAuctionTableHtml(P, meanings) +
    '<div id="bidnote"></div>' +
    '<p class="muted" style="margin:6px 0 0">Tap any call for its meaning · ' +
    'tap a card below to lead it.</p></div>';
  let openNote = -1;
  const tbl = document.querySelector("table.bidding");
  if (tbl) tbl.addEventListener("click", ev => {
    const el = ev.target.closest(".call.expl");
    const box = document.getElementById("bidnote");
    document.querySelectorAll(".call.open").forEach(c => c.classList.remove("open"));
    if (!el || +el.dataset.i === openNote) { openNote = -1; box.innerHTML = ""; return; }
    openNote = +el.dataset.i;
    el.classList.add("open");
    const a = meanings[openNote] || {};
    box.innerHTML = '<div class="bidnote"><b>' + cardHtml_or_call(a.call) +
      ' (' + (a.seat || "") + ')</b> ' + (a.text || "") +
      '<button class="x" aria-label="dismiss">✕</button></div>';
    box.querySelector(".x").onclick = () => {
      openNote = -1; box.innerHTML = "";
      document.querySelectorAll(".call.open").forEach(c => c.classList.remove("open"));
    };
  });
  const parts = P.hand.split(".");
  document.getElementById("grid").innerHTML = ["S", "H", "D", "C"].map((s, i) => {
    const btns = (parts[i] || "").split("").map(rk => {
      const face = rk === "T" ? "10" : rk;
      return '<button class="cardbtn" data-action="' + s + rk + '">' + face + '</button>';
    }).join("");
    return '<div class="suitrow"><span class="s">' + suitHtml(s) + '</span>' +
      (btns || '<span class="muted">—</span>') + '</div>';
  }).join("");
  document.querySelectorAll("button.cardbtn").forEach(b => b.onclick = () => arm(b));
  document.getElementById("next").onclick = async () => {
    if (!INDEX) INDEX = await fetchIndex();
    const nid = pickUnseen(INDEX, resolveFilters(INDEX, loadLead(), "lead"));
    if (!nid) { location.href = "index.html"; return; }
    location.href = routeFor("lead", nid);
  };
  const prev = store()[P.id];
  if (prev) reveal(prev.answer);
}
function cardHtml_or_call(tok) { return tok ? callHtml(tok) : ""; }
if (window.BT) window.BT.start(init);
else addEventListener("bt-ready", () => window.BT.start(init), {once: true});
"""


def _lead_html() -> str:
    return (
        '<!DOCTYPE html>\n<html><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<title>Opening lead problem</title>\n<style>' + _CSS + '</style>\n'
        '<script type="module" src="bt-firebase.js"></script></head>'
        '<body data-scenario="lead">\n'
        '<div class="topbar"><a href="index.html">&larr; home</a>'
        '<span class="muted" id="meta"></span></div>\n'
        '<div id="problem"></div>\n'
        '<div class="leadgrid" id="grid"></div>\n'
        '<div id="confirm"></div>\n'
        '<div id="verdict" class="card" style="display:none">\n'
        '<div class="headline" id="headline"></div>\n'
        '<p class="muted" id="subhead"></p>\n'
        '<div id="bars"></div>\n'
        '<p id="lead-expl" style="white-space:pre-line"></p>\n'
        '<div class="muted" id="difficulty"></div>\n'
        '<button class="big" id="next">Next lead &rarr;</button>\n'
        '<details><summary>All 13 leads, ranked</summary>'
        '<table class="plain" id="ltable"></table>'
        '<p class="footnote">Average defensive tricks over a full double-dummy '
        'simulation. Cards tied for the most are all correct.</p></details>\n'
        '<details><summary>The full deal</summary>'
        '<div id="fulldeal"></div></details>\n'
        '</div>\n<script>' + _SHARED_JS + _LEAD_JS + '</script>\n</body></html>'
    )


_DASHBOARD_CSS = """
.statgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.stat { text-align: center; }
.stat b { font-size: 26px; display: block; line-height: 1.1; }
.catrow { display: grid; grid-template-columns: 9em 1fr auto; gap: 8px;
          align-items: center; margin: 7px 0; font-size: 13px; }
.dbar { height: 12px; border-radius: 99px; background: var(--line);
        overflow: hidden; }
.dbar > span { display: block; height: 100%; background: var(--accent);
               border-radius: 99px; }
.scen .subh { font-weight: 700; margin: 13px 0 3px; font-size: 13px; }
.costline { margin: 6px 0 6px; font-size: 14px; }
.costline b { font-size: 21px; }
.band { display: flex; height: 22px; border-radius: 99px; overflow: hidden;
        background: var(--line); margin: 4px 0 5px; }
.band .bseg { display: flex; align-items: center; justify-content: center;
              font-size: 11px; font-weight: 700; color: #fff; min-width: 0;
              box-shadow: inset -1px 0 0 rgba(0,0,0,.15); }
.band .bseg.opt { background: #2f7d5b; }
.band .bseg.near { background: #c2851b; }
.band .bseg.bl { background: #b04a34; }
.blegend { display: flex; gap: 12px; flex-wrap: wrap; font-size: 12px;
           color: var(--muted); }
.blegend i.sw { width: 10px; height: 10px; border-radius: 3px; display: inline-block;
                margin-inline-end: 4px; vertical-align: middle; }
.blegend i.opt { background: #2f7d5b; } .blegend i.near { background: #c2851b; }
.blegend i.bl { background: #b04a34; }
.drill { border-top: 1px solid var(--line); }
.drill > summary { cursor: pointer; padding: 2px 0; }
.drill > summary .catrow { margin: 5px 0; }
.drill .drillbody { padding: 0 1.6em 6px; }
"""

_DASHBOARD_JS = r"""
const MIN_N = 5, MIN_TREND = 8;
// distribution-band thresholds; units differ by scenario (IMPs vs tricks)
const COST = { bidding: {unit: "IMP", near: 2.0}, lead: {unit: "trick", near: 1.0} };
const SUIT_NAME = {S: "Spades", H: "Hearts", D: "Diamonds", C: "Clubs"};
const RANKS = "AKQJT98765432";
function num(x) { return typeof x === "number" ? x : (parseFloat(x) || 0); }
function median(xs) {
  if (!xs.length) return 0;
  const s = [...xs].sort((a, b) => a - b), m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}
function wilson(k, n) {
  if (!n) return {p: 0, lo: 0, hi: 0};
  const z = 1.96, ph = k / n, z2 = z * z, den = 1 + z2 / n;
  const c = (ph + z2 / (2 * n)) / den;
  const h = z * Math.sqrt((ph * (1 - ph) + z2 / (4 * n)) / n) / den;
  return {p: ph, lo: Math.max(0, c - h), hi: Math.min(1, c + h)};
}
function pct(x) { return Math.round(x * 100) + "%"; }
function tsMillis(a) {
  if (!a || !a.ts) return 0;
  if (typeof a.ts.toMillis === "function") return a.ts.toMillis();
  if (a.ts.seconds) return a.ts.seconds * 1000;
  return 0;
}
function row(label, k, n) {
  if (n < MIN_N)
    return `<div class="catrow"><span>${label}</span>` +
      `<span class="muted">not enough data</span>` +
      `<span class="muted">${k}/${n}</span></div>`;
  const w = wilson(k, n);
  return `<div class="catrow"><span>${label}</span>` +
    `<span class="dbar"><span style="width:${w.p * 100}%"></span></span>` +
    `<span>${pct(w.p)} <span class="muted">(${pct(w.lo)}–${pct(w.hi)}, ` +
    `n=${n})</span></span></div>`;
}
function diffRows(list) {
  const by = {};
  list.forEach(a => { const d = a.difficultyLevel || 0;
    (by[d] ??= {k: 0, n: 0}); by[d].n++; if (a.correct) by[d].k++; });
  const out = [1, 2, 3, 4, 5].filter(d => by[d])
    .map(d => row(DIFF_NAMES[d] || ("level " + d), by[d].k, by[d].n)).join("");
  return out || '<div class="muted">no data</div>';
}
function typeRows(list) {
  const by = {};
  list.forEach(a => { const t = a.type || "—";
    (by[t] ??= {k: 0, n: 0}); by[t].n++; if (a.correct) by[t].k++; });
  const es = Object.entries(by).sort((a, b) => b[1].n - a[1].n);
  return es.length
    ? es.map(([t, s]) => row((TYPE_NAMES[t] && TYPE_NAMES[t][0]) || t, s.k, s.n)).join("")
    : '<div class="muted">no data</div>';
}
function costBand(list, kind) {
  const cfg = COST[kind] || COST.bidding, n = list.length;
  if (!n) return "";
  let opt = 0, near = 0, bl = 0; const costs = [];
  list.forEach(a => { const c = num(a.gradedCost); costs.push(c);
    if (a.correct) opt++; else if (c < cfg.near) near++; else bl++; });
  const mean = costs.reduce((s, c) => s + c, 0) / n, med = median(costs), u = cfg.unit;
  const seg = (cls, v) => v
    ? `<span class="bseg ${cls}" style="width:${(v / n * 100).toFixed(1)}%">` +
      `${Math.round(v / n * 100)}%</span>` : "";
  return `<div class="costline">avg <b>${mean.toFixed(1)}</b> ${u} below best ` +
    `<span class="muted">(median ${med.toFixed(1)})</span></div>` +
    `<div class="band" role="img" aria-label="optimal ${opt}, near-miss ${near}, ` +
    `blunder ${bl} of ${n}">` + seg("opt", opt) + seg("near", near) + seg("bl", bl) +
    '</div><div class="blegend">' +
    '<span><i class="sw opt"></i>optimal</span>' +
    `<span><i class="sw near"></i>near-miss (&lt;${cfg.near} ${u})</span>` +
    `<span><i class="sw bl"></i>blunder (≥${cfg.near} ${u})</span></div>`;
}
function suitRows(list) {
  const suits = {S: {k: 0, n: 0, c: {}}, H: {k: 0, n: 0, c: {}},
                 D: {k: 0, n: 0, c: {}}, C: {k: 0, n: 0, c: {}}};
  list.forEach(a => { const card = a.chosenCall || "", st = card[0], s = suits[st];
    if (!s) return;
    s.n++; if (a.correct) s.k++;
    (s.c[card] ??= {k: 0, n: 0}); s.c[card].n++; if (a.correct) s.c[card].k++; });
  const order = ["S", "H", "D", "C"].filter(st => suits[st].n);
  if (!order.length) return '<div class="muted">no data</div>';
  return order.map(st => {
    const s = suits[st], label = suitHtml(st) + " " + SUIT_NAME[st];
    const cards = Object.keys(s.c)
      .sort((a, b) => RANKS.indexOf(a[1]) - RANKS.indexOf(b[1]))
      .map(c => row(cardHtml(c), s.c[c].k, s.c[c].n)).join("");
    return '<details class="drill"><summary>' + row(label, s.k, s.n) + '</summary>' +
      '<div class="drillbody">' + cards + '</div></details>';
  }).join("");
}
function scenarioCard(title, list, kind) {
  if (!list.length) return "";
  let html = '<div class="card scen"><b>' + title + '</b> ' +
    '<span class="muted">' + (kind === "lead" ? "tricks" : "IMPs") +
    ' · n=' + list.length + '</span>' +
    costBand(list, kind) +
    '<div class="subh">By difficulty</div>' + diffRows(list);
  if (kind === "lead") {
    html += '<div class="subh">By suit led</div>' + suitRows(list) +
      '<div class="muted" style="font-size:12px;margin-top:4px">' +
      'Tap a suit to see the cards.</div>';
  } else {
    html += '<div class="subh">By problem type</div>' + typeRows(list);
  }
  return html + '</div>';
}
function render(attempts) {
  const el = document.getElementById("dash");
  if (!attempts.length) {
    el.innerHTML = '<div class="card">No attempts yet — ' +
      '<a href="index.html">answer a problem</a> to start tracking.</div>';
    return;
  }
  const first = attempts.filter(a => a.isFirstAttempt !== false);
  const n = first.length, k = first.filter(a => a.correct).length;
  const w = wilson(k, n);
  const recent = [...first].sort((a, b) => tsMillis(b) - tsMillis(a));
  let streak = 0;
  for (const a of recent) { if (a.correct) streak++; else break; }
  // split first-attempts by scenario (units differ: IMPs vs tricks)
  const scen = {bidding: [], lead: []};
  for (const a of first) scen[a.kind === "lead" ? "lead" : "bidding"].push(a);
  const byKind = {};
  for (const a of first) { const kd = a.kind || "bidding";
    (byKind[kd] ??= {k: 0, n: 0}); byKind[kd].n++; if (a.correct) byKind[kd].k++; }
  const chrono = [...first].sort((a, b) => tsMillis(a) - tsMillis(b));
  let trend = "";
  if (chrono.length >= MIN_TREND) {
    let cum = 0; const pts = [];
    chrono.forEach((a, i) => { cum += a.correct ? 1 : 0; pts.push(cum / (i + 1) * 100); });
    const W = 300, H = 60, step = W / (pts.length - 1);
    const path = pts.map((y, i) =>
      `${i ? "L" : "M"}${(i * step).toFixed(1)},${(H - y * 0.6).toFixed(1)}`).join(" ");
    trend = '<div class="card"><b>Accuracy over time</b> ' +
      '<span class="muted">(cumulative first-attempt)</span><br>' +
      `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;margin-top:6px">` +
      `<line x1="0" y1="${H - 30}" x2="${W}" y2="${H - 30}" stroke="#8884" ` +
      'stroke-dasharray="3"></line>' +
      `<path d="${path}" fill="none" stroke="var(--accent)" stroke-width="2"></path>` +
      '</svg><div class="muted">dashed line = 50%</div></div>';
  }
  const misses = recent.filter(a => !a.correct).slice(0, 10);
  const missList = misses.length
    ? '<div class="card"><b>Recent misses</b> <span class="muted">(review)</span>' +
      '<ul class="notes">' + misses.map(m =>
        `<li>You chose <b>${m.chosenCall}</b> — ${m.outcomeClass}` +
        (m.gradedCost ? `, cost ≈ ${(+m.gradedCost).toFixed(1)}` : "") +
        (m.acceptedSet && m.acceptedSet.length
          ? `. Best: ${m.acceptedSet.join(", ")}` : "") +
        ` <a href="${routeFor(m.kind || "bidding", m.problemId)}">retry</a></li>`
      ).join("") + "</ul></div>"
    : "";
  el.innerHTML =
    '<div class="card"><div class="statgrid">' +
    `<div class="stat"><b>${n < MIN_N ? "—" : pct(w.p)}</b>` +
    `<span class="muted">first-attempt accuracy</span></div>` +
    `<div class="stat"><b>${streak}</b><span class="muted">current streak</span></div>` +
    `<div class="stat"><b>${n}</b><span class="muted">problems answered</span></div>` +
    `<div class="stat"><b>${attempts.length}</b><span class="muted">total attempts</span></div>` +
    '</div></div>' + trend +
    '<div class="card"><b>By scenario</b>' +
    Object.keys(byKind).map(kd =>
      row(kd === "lead" ? "Opening lead" : "Bidding", byKind[kd].k, byKind[kd].n)).join("") +
    '</div>' +
    scenarioCard("Bidding", scen.bidding, "bidding") +
    scenarioCard("Opening lead", scen.lead, "lead") +
    missList +
    '<p class="footnote">First attempts only. Percentages are suppressed until ' +
    'there are at least ' + MIN_N + '; ranges are 95% Wilson intervals. ' +
    '“Cost below best” averages IMPs (bidding) or defensive tricks (lead) lost ' +
    'versus the optimal action; correct answers count as zero.</p>';
}
async function init() {
  try { render(await window.BT.allAttempts()); }
  catch (e) {
    document.getElementById("dash").textContent =
      "Couldn't load your attempts: " + e.message;
  }
}
if (window.BT) window.BT.start(init);
else addEventListener("bt-ready", () => window.BT.start(init), {once: true});
"""


def _dashboard_html() -> str:
    return (
        '<!DOCTYPE html>\n<html><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<title>Your progress</title>\n<style>' + _CSS + _DASHBOARD_CSS +
        '</style>\n<script type="module" src="bt-firebase.js"></script></head>'
        '<body>\n<div class="topbar"><a href="index.html">&larr; home</a>'
        '<span class="muted">your progress</span></div>\n'
        '<h1>Your progress</h1>\n<div id="dash" class="muted">Loading&hellip;</div>\n'
        '<script>' + _SHARED_JS + _DASHBOARD_JS + '</script>\n</body></html>'
    )


# Static ES-module assets copied verbatim next to the generated pages.
_ASSET_FILES = ("firebase-config.js", "bt-firebase.js")


def write_app(out_dir: str | Path) -> None:
    from importlib import resources
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(_index_html(), encoding="utf-8")
    (out / "p.html").write_text(_problem_html(), encoding="utf-8")
    (out / "lead.html").write_text(_lead_html(), encoding="utf-8")
    (out / "dashboard.html").write_text(_dashboard_html(), encoding="utf-8")
    web = resources.files("bridge_trainer") / "web"
    for name in _ASSET_FILES:
        (out / name).write_text((web / name).read_text(encoding="utf-8"),
                                encoding="utf-8")
    (out / ".nojekyll").write_text("")
