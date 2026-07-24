"""The static web app that consumes the problem pool.

Two pages, no build step, no framework:
  index.html  — "Deal me a hand" (random unseen problem) + progress stats
  p.html?id=X — renders one problem document fetched live from Firestore
                (the ``problems`` collection; see web/bt-firebase.js)

Answers persist as per-user attempt docs in Firestore ({answer, correct,
score, ts, ...}; web/bt-firebase.js syncs and caches them). Problems come
from Firestore too, so the producer's `pool push` makes new problems
appear without any redeploy. Each answer is graded on the 0-100 panel
score (docs/scoring_scale.md) next to the legacy binary `correct` flag.

Look and feel follows Bridge Base Online (ux/bridge panel redesign):
green-felt page with white content cards, a fixed W-N-E-S auction diagram
whose seat headers carry vulnerability as red/green plates, BBO's
four-color suits (blue ♠ / red ♥ / orange ♦ / green ♣), tap-a-bid
alert-style explanations, bidding-box candidate buttons, and an
outcome-first verdict table (EV, win/push/loss bar, contract chips) in
place of prose.
"""
from __future__ import annotations

import hashlib
import json
import re
from importlib import resources
from pathlib import Path


def _sdk_module_urls() -> list[str]:
    """The gstatic Firebase SDK module URLs, read from bt-firebase.js so the
    preload hints can never drift from the modules actually imported."""
    src = (resources.files("bridge_trainer") / "web"
           / "bt-firebase.js").read_text(encoding="utf-8")
    return re.findall(r"https://www\.gstatic\.com/firebasejs/\S+?\.js", src)


def _head_preloads() -> str:
    """<link> hints for the Firebase critical path, shared by every page:
    preconnect to the SDK CDN and the Firestore API, and modulepreload the SDK
    modules (crossorigin — module fetches are CORS) plus the same-origin module
    graph bt-firebase.js pulls in. Kept in one place and derived from
    bt-firebase.js to avoid drift with the real imports."""
    links = [
        '<link rel="preconnect" href="https://www.gstatic.com" crossorigin>',
        '<link rel="preconnect" href="https://firestore.googleapis.com"'
        ' crossorigin>',
    ]
    for url in _sdk_module_urls():
        links.append(f'<link rel="modulepreload" href="{url}" crossorigin>')
    for local in ("bt-logic.js", "firebase-config.js"):
        links.append(f'<link rel="modulepreload" href="{local}">')
    return "\n".join(links)


def _theme_head_script() -> str:
    """A tiny inline <head> script that applies the saved theme/scale to <html>
    BEFORE the stylesheet paints, so a user whose choice differs from the OS
    preference sees no flash of the wrong theme and no font-size reflow
    (PERF-F-8). Mirrors applyTheme() in _SHARED_JS, which still runs later for
    live changes from the settings sheet. Placed first in <head> so the
    html[data-theme]/[data-scale] attributes exist before CSS is applied."""
    return ("<script>(function(){try{var d=document.documentElement,"
            "t=localStorage.getItem('bt_theme'),s=localStorage.getItem('bt_scale');"
            "if(t&&t!=='system')d.setAttribute('data-theme',t);"
            "if(s&&s!=='s')d.setAttribute('data-scale',s);}catch(e){}})();</script>")


_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  /* light theme tokens */
  --felt: #2E6B4F; --felt-deep: #24573F;
  --on-felt: #ffffff; --on-felt-muted: #D9E7DE;
  --card: #ffffff; --fg: #1C2B24; --muted: #5C6B62; --line: #D9E0DA;
  --accent: #2B6CB0; --accent-tint: #2B6CB014;
  --vul: #B3252F; --nonvul: #E6F4EA; --on-nonvul: #1C5C34;
  --sp: #2838C8; --he: #C8102E; --di: #BC5A00; --cl: #1A7A1A;
  --win: #1A7A43; --loss: #C8102E; --push: #A9B3AC;
  --on-accent: #ffffff; --on-win: #ffffff; --on-loss: #ffffff;
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
  --on-accent: #0B1A13; --on-win: #0B1A13; --on-loss: #0B1A13;
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
/* meta text (e.g. the contract line) rides on the green felt, not a card, so
   it needs the on-felt muted tone — the card --muted is too dark to read. */
.topbar .muted, .meta .muted { color: var(--on-felt-muted); }
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
           /* >=24px tap target (WCAG 2.5.8) without growing the visual text */
           display: inline-flex; align-items: center;
           min-height: 24px; padding: 4px 6px; }
.alllink:hover { text-decoration: underline; }
/* in-panel guidance when a filter axis is emptied (UX-I-5): tells the user how
   to leave the "0 problems" dead end instead of only greying the CTA */
.fhint { font-size: 12px; font-weight: 600; color: var(--loss); margin-top: 6px; }
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
.seg button.active { background: var(--accent-tint); color: var(--accent);
  /* non-colour selection cue (UX-A-8): an inset underline, so the state
     doesn't rely on the subtle tint/hue alone */
  box-shadow: inset 0 -3px 0 var(--accent); font-weight: 700; }
/* problem-type toggle rows: name + proportional volume bar + count */
.typelist { display: flex; flex-direction: column; gap: 6px; }
button.typerow { display: flex; align-items: center; gap: 10px; width: 100%;
                 font: inherit; text-align: left; background: var(--card);
                 color: var(--fg); border: 1px solid var(--line);
                 border-radius: 10px; padding: 9px 12px; cursor: pointer; }
button.typerow .tick { flex: 0 0 auto; width: 18px; height: 18px;
                       border-radius: 5px; border: 1.5px solid var(--accent);
                       background: var(--accent); color: var(--on-accent);
                       display: grid;
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
a.big.off { background: var(--push); color: var(--fg); cursor: not-allowed; }
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
/* belt-and-braces with the VS15 in SUITS: force text (not emoji) rendering so
   the four-colour suit scheme's `color` always applies (UX-A-6) */
.ss, .sh, .sd, .sc { font-variant-emoji: text; }
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
/* on phones, wide analysis tables scroll inside their own box so the page
   itself doesn't scroll horizontally (UX-A-9); scoped to <=600px so desktop
   keeps the normal full-width table layout (display:block would otherwise
   shrink-wrap the columns) */
@media (max-width: 600px) {
  #ctable, #rtable, #ltable { display: block; overflow-x: auto;
    -webkit-overflow-scrolling: touch; }
}
/* narrow phones (<=380px): tighten table cells and stack the full-deal diagram
   into two columns (W/E under N, compass below) so nothing overflows */
@media (max-width: 380px) {
  table.plain th, table.plain td { padding: 6px 5px; }
  .fulldeal { grid-template-columns: 1fr 1fr;
              grid-template-areas: "n n" "w e" "c c" "s s"; }
}
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
/* a near-miss (panel score 65-84): gold, neither the green check nor the
   red cross */
button.cand.near { border: 2px solid var(--gold);
  background: color-mix(in srgb, var(--gold) 14%, var(--card)); }
button.cand.near::after { position: absolute; top: 2px; right: 6px;
  font-size: 13px; content: "\\2248"; color: var(--gold); }
@media (prefers-color-scheme: dark) {
  button.cand.good { background: #24382C; }
  button.cand.bad { background: #3A2626; }
}
/* ---- verdict: outcome-first option rows ---- */
#verdict { display: none; }
.subline { font-size: 13px; color: var(--muted); margin-bottom: 10px; }
/* panel-score chip (verdict headline, dashboard rows) + its breakdown line */
.scorechip { display: inline-flex; align-items: center;
  justify-content: center; min-width: 46px; height: 34px;
  border-radius: 10px; padding: 0 9px; font-size: 20px; font-weight: 800;
  color: #fff; vertical-align: middle; font-variant-numeric: tabular-nums; }
.scorechip.tone-win { background: var(--win); color: var(--on-win); }
.scorechip.tone-gold { background: var(--gold); color: var(--on-gold); }
.scorechip.tone-loss { background: var(--loss); color: var(--on-loss); }
.scorechip.sm { min-width: 36px; height: 24px; font-size: 14px;
                border-radius: 7px; font-weight: 700; }
.scoreline { font-size: 13px; color: var(--muted); margin: 0 0 8px; }
.legend { font-size: 11px; color: var(--muted); margin: 8px 0 2px; }
.legend i { display: inline-block; width: 8px; height: 8px;
            border-radius: 2px; margin: 0 3px 0 10px; }
.legend i:first-child { margin-left: 0; }
.opt { padding: 12px 4px; border-top: 1px solid var(--line); }
/* "your pick" tint follows the --loss token in every theme (UX-A-10) instead
   of a hardcoded light-theme red-with-alpha that stayed put in dark mode */
.opt.mine { background: color-mix(in srgb, var(--loss) 4%, transparent);
  border-radius: 8px; }
table.plain tr.mine td {
  background: color-mix(in srgb, var(--loss) 4%, transparent); }
.opt .l1 { display: flex; align-items: center; gap: 8px; }
.bidchip { min-width: 40px; height: 32px; border-radius: 6px;
           border: 1px solid var(--line); font-size: 16px; font-weight: 700;
           display: inline-flex; align-items: center; justify-content: center;
           padding: 0 6px; background: var(--card); }
.tag { font-size: 10px; font-weight: 700; letter-spacing: .05em;
       color: #fff; border-radius: 999px; padding: 2px 7px; }
.tag.best { background: var(--win); color: var(--on-win); }
.tag.you { background: var(--accent); color: var(--on-accent); }
.opt .shows { color: var(--muted); font-size: 13px; flex: 1;
              overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.opt .ev { font-size: 16px; font-weight: 700;
           font-variant-numeric: tabular-nums; white-space: nowrap;
           /* signed EV like "-1.2 +/-0.3": isolate LTR so the leading minus
              (U+2212) doesn't reorder to the right in the RTL page (UX-A-5) */
           direction: ltr; unicode-bidi: isolate; }
.opt .ev small { font-size: 12px; font-weight: 400; color: var(--muted); }
.opt .ev .best { color: var(--win); }
.wpl { display: flex; justify-content: space-between; height: 10px;
       border-radius: 5px; overflow: hidden; background: var(--push);
       margin: 8px 0 6px; }
.wpl .w { background: var(--win); color: var(--on-win); }
.wpl .l { background: var(--loss); color: var(--on-loss); }
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
/* summaries must LOOK tappable: link color + an explicit chevron (the
   flex display below removes the native disclosure triangle) */
details summary { cursor: pointer; color: var(--accent); font-size: 13px;
                  font-weight: 600;
                  min-height: 40px; display: flex; align-items: center; }
details summary::before { content: "\\25C2"; color: var(--accent);
                          font-size: 11px; margin-inline-end: 7px;
                          flex: 0 0 auto; }
details[open] > summary::before { content: "\\25BE"; }
.notes ul { margin: 4px 0 8px; padding-left: 18px; font-size: 13px; }
.notes li { margin: 6px 0; line-height: 1.4; }
table.plain { border-collapse: collapse; width: 100%; font-size: 13px;
              font-variant-numeric: tabular-nums; }
table.plain th, table.plain td { border-top: 1px solid var(--line);
  padding: 6px 8px; text-align: left; }
table.plain th { color: var(--muted); font-weight: 600; border-top: 0; }
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
button.cardbtn.near { border-color: var(--gold);
  background: color-mix(in srgb, var(--gold) 16%, var(--card)); }
/* reveal: per-suit bar comparison instead of a wall of decimals */
.barrow { display: flex; align-items: center; gap: 8px; margin: 5px 0; font-size: 14px; }
.barrow .bl { width: 3.4em; }
.bartrack { flex: 1; height: 14px; border-radius: 99px; background: var(--line);
  overflow: hidden; }
.bartrack span { display: block; height: 100%; background: var(--accent); }
.bartrack span.good { background: var(--win); }
.barval { width: 6.2em; text-align: right; font-variant-numeric: tabular-nums;
  color: var(--muted); font-size: 12px;
  /* signed values like "-0.50 IMP": isolate LTR so the sign stays left (UX-A-5) */
  direction: ltr; unicode-bidi: isolate; }
/* fixed-width "(שלך)" slot on every row keeps all tracks the same length */
.barrow .byou { flex: 0 0 auto; width: 2.9em; font-size: 12px;
  color: var(--muted); }
.barrow.mine { background: color-mix(in srgb, var(--loss) 4%, transparent);
  border-radius: 8px; }
#bid-meaning { min-height: 1.2em; margin: 6px 0 0; }
/* single source for the verdict headline (BUG-10: was defined 3x, the 24px v2
   rule winning) */
.headline { font-size: 24px; font-weight: 800; margin: 4px 0; }
.headline .ok { color: var(--win); } .headline .no { color: var(--loss); }

/* ===== redesign layer (v2): type scale, theming, nav, a11y, RTL ===== */
/* base uplift + room for the fixed bottom nav */
body { font-size: 16px; line-height: 1.55; padding-bottom: 84px;
       padding-inline: 12px; }
h1 { font-size: 26px; font-weight: 800; }
h2 { font-size: 19px; font-weight: 700; color: var(--fg); margin: 0; }

/* manual theme override (wins over prefers-color-scheme) */
html[data-theme="light"] body {
  --felt: #2E6B4F; --felt-deep: #24573F; --on-felt: #ffffff;
  --on-felt-muted: #D9E7DE; --card: #ffffff; --fg: #1C2B24; --muted: #5C6B62;
  --line: #D9E0DA; --accent: #2B6CB0; --accent-tint: #2B6CB014;
  --vul: #B3252F; --nonvul: #E6F4EA; --on-nonvul: #1C5C34;
  --sp: #2838C8; --he: #C8102E; --di: #BC5A00; --cl: #1A7A1A;
  --win: #1A7A43; --loss: #C8102E; --push: #A9B3AC;
  --on-accent: #ffffff; --on-win: #ffffff; --on-loss: #ffffff;
  --gold: #EAB84C; --on-gold: #2A2410;
  --warn-bg: #FDF3DF; --warn-fg: #7A5312; --warn-line: #E3C87F; }
html[data-theme="dark"] body {
  --felt: #10241A; --felt-deep: #0B1A13; --on-felt: #E9F0EB;
  --on-felt-muted: #9FB4A8; --card: #1B2620; --fg: #E8EDEA; --muted: #97A79D;
  --line: #33413A; --accent: #6CA6DD; --accent-tint: #6CA6DD1F;
  --vul: #A62630; --nonvul: #2E4A38; --on-nonvul: #BFE3CC;
  --sp: #8C96FF; --he: #FF7B72; --di: #FFAB40; --cl: #57C957;
  --win: #3BB273; --loss: #E5665F; --push: #5B6961;
  --on-accent: #0B1A13; --on-win: #0B1A13; --on-loss: #0B1A13;
  --gold: #D9A93E; --on-gold: #241F0C;
  --warn-bg: #2E2612; --warn-fg: #E7C97E; --warn-line: #6B5A2A; }
html[data-theme="dark"] .card { border: 1px solid var(--line); box-shadow: none; }

/* text-size control */
html[data-scale="l"] body { font-size: 18px; }
html[data-scale="xl"] body { font-size: 20px; }

/* visible focus for everyone */
:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px;
                 border-radius: 6px; }
/* skip link */
.skip { position: absolute; inset-inline-start: -9999px; top: 8px; z-index: 200;
        background: var(--card); color: var(--fg); padding: 8px 14px;
        border-radius: 8px; border: 1px solid var(--line); }
.skip:focus { inset-inline-start: 12px; }

/* RTL: flip shell text/spacing to logical props (bridge diagrams stay LTR
   via dir="ltr" on their containers) */
.fbar { text-align: start; }
.fbar-sub { margin-left: 0; margin-inline-start: auto; }
.seg button { border-left: 0; border-inline-start: 1px solid var(--line); }
.seg button:first-child { border-inline-start: 0; }
button.typerow { text-align: start; }
.bidnote { padding: 10px 12px; padding-inline-end: 40px; }
.bidnote b { margin-right: 0; margin-inline-end: 6px; }
.bidnote .x { right: auto; inset-inline-end: 0; }
.notes ul { padding-left: 0; padding-inline-start: 18px; }
table.plain th, table.plain td { text-align: start; }
.legend i { margin: 0; margin-inline-start: 10px; margin-inline-end: 3px; }
.legend i:first-child { margin-inline-start: 0; }
button.typerow .tcount { text-align: end; }
.barrow .barval { text-align: start; }
/* bridge diagrams are LTR islands */
.hand, .fulldeal, .leadgrid, table.bidding, .candidates,
.wpl, .bartrack, .fdcompass { direction: ltr; }
/* bid/contract tokens are Latin — pin their internal order too */
.bidchip, .chip { direction: ltr; unicode-bidi: isolate; }
.ltr { direction: ltr; unicode-bidi: isolate; display: inline-block; }
/* engine explanations are English (or English-heavy) — render them LTR and
   left-aligned so number ranges and prose don't reorder in the RTL page */
.en { direction: ltr; unicode-bidi: isolate; text-align: left; }
#explanation, #meanings { direction: ltr; unicode-bidi: isolate;
  text-align: left; }


/* non-color cue inside the win/push/loss bar */
.wpl { position: relative; height: 16px; }
.wpl span { display: flex; align-items: center; justify-content: center;
            font-size: 10px; font-weight: 800; color: #fff; overflow: hidden; }

/* ===== global bottom navigation ===== */
.gnav { position: fixed; inset-inline: 0; bottom: 0; z-index: 90;
        display: flex; justify-content: center; gap: 4px;
        background: var(--card); border-top: 1px solid var(--line);
        padding: 6px 8px calc(6px + env(safe-area-inset-bottom));
        box-shadow: 0 -2px 12px #0000001a; }
.gnav .navwrap { display: flex; gap: 4px; width: 100%; max-width: 640px; }
.gnav a, .gnav button.navbtn { flex: 1; background: none; border: 0; cursor: pointer;
        font: inherit; color: var(--muted); text-decoration: none;
        display: flex; flex-direction: column; align-items: center; gap: 2px;
        padding: 6px 4px; border-radius: 10px; min-height: 48px;
        font-size: 11px; font-weight: 700; }
.gnav a .ico, .gnav button .ico { font-size: 20px; line-height: 1; }
.gnav a[aria-current="page"] { color: var(--accent); background: var(--accent-tint); }

/* settings sheet */
.sheet { position: fixed; inset: 0; z-index: 120; display: none;
         align-items: flex-end; justify-content: center;
         background: #0007; }
.sheet.open { display: flex; }
.sheet .panel { background: var(--card); color: var(--fg); width: 100%;
        max-width: 640px; border-radius: 16px 16px 0 0; padding: 20px 18px 28px;
        box-shadow: 0 -4px 24px #0005; }
.sheet h2 { margin-bottom: 12px; }
.setrow { display: flex; align-items: center; justify-content: space-between;
          gap: 12px; padding: 12px 0; border-top: 1px solid var(--line); }
.setrow:first-of-type { border-top: 0; }
.segctl { display: inline-flex; border: 1px solid var(--line); border-radius: 10px;
          overflow: hidden; }
.segctl button { font: inherit; border: 0; background: var(--card);
          color: var(--muted); padding: 8px 14px; cursor: pointer;
          border-inline-start: 1px solid var(--line); font-weight: 700; }
.segctl button:first-child { border-inline-start: 0; }
.segctl button[aria-pressed="true"] { background: var(--accent);
  color: var(--on-accent); }
.sheet .closebtn { width: 100%; margin-top: 16px; padding: 12px; border-radius: 10px;
          border: 1px solid var(--line); background: var(--card); color: var(--fg);
          font: inherit; font-weight: 700; cursor: pointer; }

/* session ribbon (recedes; never outshines the hand/auction) */
.sessribbon { display: flex; align-items: center; justify-content: space-between;
          gap: 8px; font-size: 12px; color: var(--on-felt-muted); margin: 2px 0 8px; }
.sessribbon .prog { flex: 1; height: 6px; border-radius: 99px;
          background: #ffffff2e; overflow: hidden; }
.sessribbon .prog > span { display: block; height: 100%; background: var(--gold); }

/* designed empty/error state */
.state { text-align: center; padding: 8px 4px; }
.state .em { font-size: 15px; color: var(--fg); font-weight: 700; margin-bottom: 4px; }

/* ===== opening-lead training modes: MP / IMP selection + banner ===== */
button.modecard { font: inherit; text-align: start; background: var(--card);
  color: var(--fg); border: 2px solid var(--line); border-radius: 12px;
  padding: 12px; cursor: pointer; display: flex; flex-direction: column;
  gap: 4px; min-height: 64px; }
button.modecard b { font-size: 17px; }
button.modecard small { color: var(--muted); font-size: 12px;
  line-height: 1.35; }
button.modecard[aria-pressed="true"] { border-color: var(--accent);
  background: var(--accent-tint); }
button.modecard[aria-pressed="true"] b { color: var(--accent); }
.modebanner { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.modechip { display: inline-block; font-size: 12px; font-weight: 800;
  letter-spacing: .08em; color: var(--on-accent); background: var(--accent);
  border-radius: 999px; padding: 3px 10px; }
/* the goal sentence is Hebrew with embedded Latin jargon (IMP/MP) — keep an
   RTL base direction and isolate it, or the whole sentence scrambles */
.modegoal { font-size: 13px; color: var(--muted); direction: rtl;
  unicode-bidi: isolate; }
/* the MP and IMP goal strings differ in length and wrapped to different
   heights, making the selector box jump on every MP<->IMP toggle. Reserve a
   constant two-line slot so switching modes never reflows. Scoped to the home
   div by id; the problem page reuses .modegoal as an inline banner, unaffected. */
#modegoal { min-height: 2.9em; }
.ctline { font-size: 14px; margin-top: 6px; }
/* the active mode's primary metric is visually emphasized */
table.plain td.emph, table.plain th.emph { background: var(--accent-tint);
  font-weight: 700; }
.resultline { font-size: 14px; margin: 3px 0; }
.resultline b { font-variant-numeric: tabular-nums; }

/* ===== makeover layer (v3): Hebrew-first chrome, home cards, learn-first
   verdicts, skeletons, dashboard tabs ===== */
/* Hebrew text carries no uppercase tracking — zero the Latin-era spacing */
.glabel, .typebadge, .tag, .modechip, table.bidding th small,
.fdhand .lbl .role { letter-spacing: 0; text-transform: none; }
/* home: two scenario cards replace the segmented control */
.scengrid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px;
            margin: 0 0 12px; align-items: stretch; }
/* both cards use OPAQUE backgrounds (a translucent tint would let the felt
   bleed through and make the SELECTED card look muddy). Unselected recedes
   via reduced opacity; selected pops with a solid accent border + ring. */
.scencard { background: var(--card); color: var(--fg);
  border: 2px solid var(--line); border-radius: 14px; padding: 14px 12px;
  cursor: pointer; display: flex; flex-direction: column; gap: 4px;
  opacity: .72; transition: opacity .12s, box-shadow .12s; }
.scencard > b { font-size: 17px; }
.scencard > small { color: var(--muted); font-size: 12px; line-height: 1.35; }
.scencard .sccount { font-size: 12px; color: var(--muted); margin-top: 2px;
                     font-variant-numeric: tabular-nums; }
.scencard[aria-checked="true"] { opacity: 1; border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, var(--card));
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 30%, transparent); }
.scencard[aria-checked="true"] > b { color: var(--accent); }
.modepills { display: flex; gap: 6px; margin-top: 8px; }
.modepills button.modecard { flex: 1; min-height: 0; padding: 8px;
  border-radius: 10px; background: var(--card); border: 1px solid var(--line);
  opacity: .8; }
.modepills button.modecard b { font-size: 15px; }
/* selected pill: solid accent fill + white text — unambiguous on the card */
.modepills button.modecard[aria-pressed="true"] { opacity: 1;
  background: var(--accent); border-color: var(--accent); }
.modepills button.modecard[aria-pressed="true"] b,
.modepills button.modecard[aria-pressed="true"] small { color: var(--on-accent); }
/* MP/IMP selector now sits below the scenario cards (UX-A-7); the reserved
   #modegoal height keeps its own box from jumping on an MP<->IMP toggle */
.modewrap { margin: 0 0 8px; }
.modewrap .modegoal { margin-top: 6px; }
/* loading skeletons */
.skl { height: 12px; border-radius: 6px; background: var(--line);
       margin: 12px 0; }
@media (prefers-reduced-motion: no-preference) {
  .skl { animation: shimmer 1.2s ease-in-out infinite; }
  @keyframes shimmer { 50% { opacity: .45; } }
}
/* inline Hebrew jargon explainer */
.infot { display: inline-block; margin-inline-start: 4px; color: var(--accent);
         font-style: normal; font-size: 13px; position: relative;
         background: none; border: 0; padding: 0; cursor: pointer; }
/* expand the tap target to ~24px without changing the glyph's size (UX-A-10) */
.infot::after { content: ""; position: absolute; inset: -8px; }
/* tap-to-explain: a dotted underline marks any term that opens a gloss
   card on tap — the same visual cue as tappable auction calls */
button.gloss { background: none; border: 0; padding: 0; margin: 0;
  font: inherit; color: inherit; cursor: pointer; position: relative;
  text-decoration: underline dotted 1.5px; text-underline-offset: 3px;
  text-decoration-color: var(--accent); }
/* taller tap target for the inline glossary term without shifting text layout */
button.gloss::after { content: ""; position: absolute; inset: -8px -2px; }
.scorechip[data-gloss] { cursor: pointer; }
button.typebadge { font: inherit; cursor: pointer; }
button.modechip { border: 0; font: inherit; cursor: pointer;
  font-size: 12px; font-weight: 800; }
#glossbox { position: fixed; inset-inline: 12px; z-index: 120;
  bottom: calc(76px + env(safe-area-inset-bottom)); }
.glosscard { background: var(--card); color: var(--fg);
  border: 1px solid var(--accent); border-radius: 12px;
  padding: 12px 14px; padding-inline-end: 46px; font-size: 14px;
  line-height: 1.5; box-shadow: 0 6px 24px #0005; position: relative; }
.glosscard b { margin-inline-end: 6px; }
.glosscard b:empty { display: none; }
.glosscard .x { position: absolute; inset-inline-end: 0; top: 0; width: 44px;
  height: 44px; border: 0; background: none; color: var(--muted);
  font-size: 16px; cursor: pointer; }
/* confirm sheet stays reachable above the bottom nav */
#confirm .confirmbox { position: sticky; bottom: 92px; z-index: 60;
                       box-shadow: 0 6px 24px #0004; }
/* verdict entrance */
@media (prefers-reduced-motion: no-preference) {
  #verdict { animation: rise .25s ease-out; }
  @keyframes rise { from { opacity: 0; transform: translateY(8px); } }
}
/* dashboard tabs */
.tabs { display: flex; margin: 0 0 12px; width: 100%; background: var(--card); }
.tabs button { flex: 1; padding: 10px 6px; }
.tabs button[aria-selected="true"] { background: var(--accent);
  color: var(--on-accent); }
.dtab[hidden] { display: none; }
/* tappable recent-miss rows */
ul.misslist { list-style: none; margin: 4px 0 0; padding: 0; }
ul.misslist li { border-top: 1px solid var(--line); }
ul.misslist li:first-child { border-top: 0; }
a.missrow { display: block; color: inherit; text-decoration: none;
            padding: 9px 2px; font-size: 13px; line-height: 1.45; }
a.missrow .go { color: var(--accent); font-weight: 700; white-space: nowrap; }
/* bottom-nav svg icons */
.gnav .ico svg { display: block; }
"""

_SCORE_JS = r"""
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
   and the page-normalized shape (verdict.corrected / accepted as an array). */
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
/* leads: MP grades tricks below best BLENDED with the matchpoint rank
   (distinct trick values — the second-best lead still beats most of the
   room); IMP grades expected IMPs below the mode's best, pure magnitude.
   No dead pin (leads have no dead concept) and no CI haircut (per-card CIs
   aren't published; ties already collapse into the accepted set at forge
   time).

   Tie invariant — "what the engine cannot distinguish, the score must not
   distinguish": cards the active mode ranks identically (same leading metric
   to display precision, i.e. interchangeable leads) MUST score the same. So
   every score input is a property of the tie-GROUP, not the individual card:
   the gap is charged on the rounded leading metric (equal-ranked cards share
   a cost, hence a base), and field leniency uses the group's TOTAL policy
   weight (the sum of the interchangeable cards' BEN softmax — the field's
   probability of finding that one idea) instead of the per-card softmax,
   which used to split otherwise-identical cards by a few points. */
function btScoreLead(P, card, mode) {
  mode = mode === "IMP" ? "IMP" : "MP";
  const v = (P && P.verdict) || {};
  const bm = v.by_mode && v.by_mode[mode];
  const accepted = (bm && bm.accepted && bm.accepted.length)
    ? bm.accepted : (v.accepted || []);
  const out = {kind: "lead", mode: mode,
               unit: mode === "IMP" ? "IMP" : "לקיחות", accepted: accepted};
  if (accepted.includes(card)) { out.score = 100; return out; }
  const rows = v.table || [];
  const row = rows.find(r => r.card === card);
  if (!row) { out.score = ERROR_MIN; out.fallback = true; return out; }
  const useImp = mode === "IMP" && row.exp_imps !== undefined;
  // the mode's leading metric at DISPLAY precision (2 decimals) — the tie key
  const keyOf = useImp
    ? r => (r.exp_imps === undefined ? null : Math.round(+r.exp_imps * 100))
    : r => (r.avg_def_tricks === undefined ? null
                                           : Math.round(+r.avg_def_tricks * 100));
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
    // round the trick gap to the same precision as the rank grouping, so a
    // tie-group shares one cost (and thus one base)
    out.cost = Math.max(0, -Math.round((+row.vs_best || 0) * 100) / 100);
    out.tau = SCORE_TAU.leadMP;
    const vals = [];
    for (const r of rows) {
      const q = keyOf(r);
      if (q !== null && !vals.includes(q)) vals.push(q);
    }
    vals.sort((a, b) => b - a);
    const idx = vals.indexOf(myKey);
    out.base = btCurve(out.cost, out.tau);
    if (vals.length > 1 && idx >= 0) {
      out.rank = idx + 1; out.groups = vals.length;
      const rankScore = SCORE_CAP * (vals.length - 1 - idx) / (vals.length - 1);
      out.base = (1 - MP_RANK_WEIGHT) * out.base + MP_RANK_WEIGHT * rankScore;
    }
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
  let gap = "פער " + (+parts.cost).toFixed(parts.unit === "IMP" ? 1 : 2) +
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
"""

_SHARED_JS = _SCORE_JS + """
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
/* ===== central Hebrew string table: UI chrome strings live here, so new
   features add a key instead of an inline literal ===== */
const HE = {
  brand: "מאמן הברידג'",
  home: "בית", practice: "תרגול", progress: "התקדמות", account: "חשבון",
  skip: "דלג לתוכן", mainNav: "ניווט ראשי", settings: "הגדרות",
  theme: "ערכת נושא", themeSystem: "מערכת", themeLight: "בהיר",
  themeDark: "כהה", textSize: "גודל טקסט", sizeS: "רגיל", sizeL: "גדול",
  sizeXL: "ענק",
  guestNote: "לא מחובר — התחבר כדי לשמור התקדמות",
  signIn: "התחבר עם Google", signOut: "התנתק", connected: "מחובר",
  close: "סגור", selectAll: "בחר הכל", clear: "נקה", problems: "בעיות",
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
  imp: ["IMP", "International Match Points \\u2014 סולם הניקוד במשחקי " +
    "קבוצות: הפרש הנקודות מול תוצאת הייחוס מתורגם לסולם מדורג של עד 24 " +
    "נקודות. כאן מוצג ממוצע על פני כל החלוקות המדומות."],
  mp: ["MP", "Matchpoints \\u2014 ניקוד תחרות זוגות: התוצאה מושווית לכל " +
    "שאר השולחנות, וכל לקיחה משנה. בהובלה, המטרה למקסם את הלקיחות בהגנה."],
  dd: ["Double-dummy", "ניתוח ממוחשב שבו כל 52 הקלפים גלויים והמשחק " +
    "מושלם משני הצדדים \\u2014 מדד ייחוס אובייקטיבי לכל חלוקה."],
  sd: ["תוצאה מתוקנת", "כל אפשרות נבדקה על אותן חלוקות מדומות התואמות " +
    "את המכרז; תיקון single-dummy מקרב את פתרון המחשב (שרואה את כל " +
    "הקלפים) למשחק אנושי, שרואה רק יד אחת ודומם."],
  panel: ["ציון", "ציון 0-100 לכל החלטה: 100 = הפעולה המיטבית או שקולה " +
    "לה; ככל שהעלות מול המיטבית גדלה הציון יורד; 0 = אפשרות שלא ניצחה " +
    "באף חלוקה מדומה."],
  ev: ["IMP צפוי", "הפער הממוצע ב-IMP מול האפשרות המיטבית, על פני כל " +
    "החלוקות המדומות. הסימן \\u00b1 הוא רווח בר-סמך של 95%."],
  win: ["זכייה / שוויון / הפסד", "אחוז החלוקות המדומות שבהן האפשרות " +
    "גוברת על האפשרות המיטבית האחרת, משתווה לה, או נופלת ממנה."],
  tricks: ["לקיחות צפויות", "מספר הלקיחות הממוצע שההגנה לוקחת נגד החוזה, " +
    "על פני כל החלוקות המדומות."],
  set: ["סיכוי הכשלה", "אחוז החלוקות שבהן החוזה נכשל \\u2014 המכריז לא " +
    "משיג את מספר הלקיחות הדרוש."],
  diff: ["רמת קושי", "דירוג אוטומטי מ-1 (קל) עד 5 (מומחה) לפי מורכבות " +
    "ההחלטה: גודל הפערים בין האפשרויות ורגישות התוצאה."],
  streak: ["רצף מיטבי", "כמה מהתשובות האחרונות שלך קיבלו ציון 100 ברצף."],
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
    '">\\u2715</button></div>';
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
const SUITS = {S: ["ss", "\\u2660\\uFE0E"], H: ["sh", "\\u2665\\uFE0E"],
               D: ["sd", "\\u2666\\uFE0E"], C: ["sc", "\\u2663\\uFE0E"]};
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
    // drop a few non-informative fragments; mirrors engine/explain.py
    // _FILLER_PARTS. GIB's names are already canonical, so this is minimal.
    if (["artificial", "forcing", "bidable suit", "calculated bid"]
        .includes(low))
      continue;
    if (low === "balanced") {
      if (denom !== "NT" && !name) name = "Balanced";
      continue;
    }
    if (/\\d+\\s*(\\+|-\\s*\\d+)?\\s*HCP/i.test(p)) continue;
    const m = /^(\\d+)\\s*\\+?\\s*!?([SHDC])$/.exec(p);
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
  const hcp = card.hcp;
  const pts = card.pts;
  if (hcp) {
    const [lo, hi] = hcp;
    if (hi >= 25) { if (lo > 0) frags.push(lo + "+"); }
    else frags.push(lo + "-" + hi);
  } else if (pts) {
    // no HCP band, but GIB stated total points — without this a limited pass
    // ("No suitable call -- 8- total points") rendered with no range at all,
    // which read as a missing explanation. Mirrors engine/explain.py.
    const [lo, hi] = pts;
    if (hi >= 25) { if (lo > 0) frags.push(lo + "+ pts"); }
    else frags.push(lo + "-" + hi + " pts");
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
    return `<th class="${cls}" title="${s} \\u2014 ${vlab}">${s}` +
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
    `<span class="on">${"\\u2605".repeat(lv)}</span>` +
    `<span class="off">${"\\u2605".repeat(5 - lv)}</span></span>` +
    `<b>${DIFF_NAMES[lv]} (${lv}/5)</b>`;
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
    '<span>תרגול \\u00b7 ' + done + '/' + s.size + '</span>' +
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
};
const NAV_ITEMS = [
  {id: "practice", href: "index.html", ico: ICO.spade, label: HE.home},
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
"""


def _taxonomy_he_json() -> str:
    """The Hebrew {type_id: [label, tooltip]} map, built from the taxonomy
    modules (the single source of truth) — bidding types from classify.py,
    opening-lead types from lead_classify.py."""
    from ..engine.classify import LABELS_HE, TOOLTIPS_HE
    from ..engine.lead_classify import LEAD_LABELS_HE, LEAD_TOOLTIPS_HE
    data = {}
    for tid, label in LABELS_HE.items():
        data[tid] = [label, TOOLTIPS_HE.get(tid, "")]
    for tid, label in LEAD_LABELS_HE.items():
        data[tid] = [label, LEAD_TOOLTIPS_HE.get(tid, "")]
    return json.dumps(data, ensure_ascii=False)


def _taxonomy_script() -> str:
    """Inline <script> that sets window.TAXONOMY_HE before bt-shared.js loads.
    _SHARED_JS derives TYPE_NAMES from it, so the Hebrew type labels/tooltips
    live in one place (the taxonomy modules) instead of a JS literal that had
    already drifted from them (ARCH-5). </ is escaped so a label could never
    close the script tag early."""
    return ('<script>window.TAXONOMY_HE = '
            + _taxonomy_he_json().replace('</', '<\\/') + ';</script>')


def _asset_ver(content: str) -> str:
    """A short content hash used as a cache-busting ``?v=`` query on the
    Python-generated assets (PERF-F-5). The asset filenames are stable (not
    content-hashed) and GitHub Pages serves them with a short max-age, so a
    returning visitor could otherwise pair a freshly-fetched HTML page with a
    still-cached OLD bt-shared.js/app.css. When Wave D moved score constants
    (REVIEW_MIN, ...) and shared helpers INTO bt-shared.js, that skew turned
    into a hard "REVIEW_MIN is not defined" on the dashboard and a stuck home
    page. Versioning the URL by content makes the pairing atomic: new HTML
    always requests the exact asset build it was generated with, and an
    unchanged asset keeps its URL (so the cache still hits)."""
    return hashlib.sha1(content.encode("utf-8")).hexdigest()[:8]


# Query-string versions for the two generated assets every page links. Derived
# from content, so they only change when the asset changes (see _asset_ver).
_CSS_HREF = f"app.css?v={_asset_ver(_CSS)}"
_SHARED_SRC = f"bt-shared.js?v={_asset_ver(_SHARED_JS)}"


def _index_html() -> str:
    return f"""<!DOCTYPE html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{_theme_head_script()}
<title>מאמן הברידג' — תרגול</title>
<link rel="stylesheet" href="{_CSS_HREF}">
{_head_preloads()}
<script type="module" src="bt-firebase.js"></script></head><body data-nav="practice">
<main id="main" tabindex="-1">
<h1><span style="opacity:.9">&spades;</span> מאמן הברידג'</h1>
<div class="scengrid" id="scenario" role="radiogroup"
     aria-label="בחירת תרחיש תרגול">
<div class="scencard" data-kind="bidding" role="radio" tabindex="0"
     aria-checked="true">
<b>תרגול הכרזה</b><small>ההכרזה שלך ליד השולחן</small>
<span class="sccount" id="count-bidding"></span>
</div>
<div class="scencard" data-kind="lead" role="radio" tabindex="-1"
     aria-checked="false">
<b>תרגול הובלה</b><small>איזה קלף להוביל נגד החוזה</small>
<span class="sccount" id="count-lead"></span>
</div>
</div>
<div class="modewrap" id="modewrap" hidden>
<div class="modepills" id="modes" role="group" aria-label="שיטת חישוב">
<button type="button" class="modecard" data-mode="MP" aria-pressed="true">
<b>MP</b><small>מקסימום לקיחות בהגנה</small></button>
<button type="button" class="modecard" data-mode="IMP" aria-pressed="false">
<b>IMP</b><small>הפרשי תוצאה גדולים</small></button>
</div>
<div class="modegoal" id="modegoal"></div>
</div>
<div class="card" id="filters">
<button type="button" class="fbar" id="fbar" aria-expanded="false"
        aria-controls="fbody">
<span class="fbar-main">בחירת דרגת קושי וסוג</span>
<span class="fbar-sub" id="fbar-sub"></span>
<span class="fbar-chev" aria-hidden="true">&#9662;</span>
</button>
<div class="fbody" id="fbody" hidden>
<div class="fgroup">
<div class="grow"><span class="glabel">דרגת קושי</span>
<button type="button" class="alllink" id="all-diff"></button></div>
<div class="seg" id="diff-seg"></div>
<div class="fhint" id="hint-diff" role="alert" hidden>בחר לפחות דרגת קושי אחת</div>
</div>
<div class="fgroup" id="type-group">
<div class="grow"><span class="glabel">סוג בעיה</span>
<button type="button" class="alllink" id="all-type"></button></div>
<div class="typelist" id="type-list"></div>
<div class="fhint" id="hint-type" role="alert" hidden>בחר לפחות סוג בעיה אחד</div>
</div>
</div>
</div>
<a class="big" id="deal" href="#">התחל תרגול &larr;</a>
<div class="card" id="stats" aria-label="טוען את מאגר הבעיות">
<div class="skl" style="width:60%"></div>
<div class="skl" style="width:85%"></div>
<div class="skl" style="width:40%"></div>
</div>
</main>
{_taxonomy_script()}
<script src="{_SHARED_SRC}"></script>
<script>
let INDEX = null;
let COUNTS = {{}};   // precomputed pool counts (PERF-F-6); rebuilt when INDEX loads
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
  document.querySelectorAll("#scenario .scencard").forEach(c => {{
    const on = c.dataset.kind === kind;
    c.setAttribute("aria-checked", on ? "true" : "false");
    c.tabIndex = on ? 0 : -1;   // roving tabindex for the radiogroup (UX-A-7)
  }});
  // the MP/IMP selector lives below the cards now, shown only for leads
  document.getElementById("modewrap").hidden = kind !== "lead";
  syncModeUi();
  // The choice above is already persisted (SCEN + localStorage) and reflected
  // in the UI. The facet build below needs the pool index; if a click lands
  // before it loads, stop here — init() calls setScenario(SCEN) once the index
  // arrives and rebuilds from the persisted choice (guards against a null-INDEX
  // crash in resolveFilters/poolFacets).
  if (!INDEX) return;
  FILTERS = resolveFilters(INDEX, loadCur(), kind);
  buildFilters(); applyFilterUi(); updateFacetCounts(); renderStats();
}}
/* MP / IMP selection pills (inside the lead scenario card) */
function syncModeUi() {{
  const m = leadMode();
  document.querySelectorAll("#modes .modecard").forEach(b =>
    b.setAttribute("aria-pressed", b.dataset.mode === m ? "true" : "false"));
  document.getElementById("modegoal").textContent = MODE_INFO[m].goal;
}}
document.querySelectorAll("#modes .modecard").forEach(b => b.onclick = () => {{
  setLeadMode(b.dataset.mode);
  syncModeUi();
  // mode is persisted (setLeadMode); the facet rebuild needs the index. If the
  // click lands before it loads, stop here — init() rebuilds once it arrives.
  if (!INDEX) return;
  // each mode serves its own generator's pool, so the facet options and
  // counts are rebuilt from that pool
  FILTERS = resolveFilters(INDEX, loadCur(), SCEN);
  buildFilters(); applyFilterUi(); updateFacetCounts(); renderStats();
}});
/* per-scenario waiting counts shown on the cards themselves */
function updateScenCounts() {{
  if (!INDEX) return;
  const s = store();
  const nb = scenTotal(COUNTS, "bidding");           // pool totals from COUNTS
  const mode = leadMode();
  const nl = scenTotal(COUNTS, "lead", mode);
  // waiting = not-yet-answered; store-dependent, so one pass over the index
  // (can't come from the precomputed COUNTS)
  let wb = 0, wl = 0;
  for (const p of INDEX.problems) {{
    if (s[p.id]) continue;
    const k = kindOf(p);
    if (k === "bidding") wb++;
    else if (k === "lead" && targetModeOf(p) === mode) wl++;
  }}
  document.getElementById("count-bidding").textContent =
    nb ? `${{wb}} ממתינות מתוך ${{nb}}` : "אין בעיות עדיין";
  document.getElementById("count-lead").textContent =
    nl ? `${{wl}} ממתינות מתוך ${{nl}}` : "אין בעיות במצב זה עדיין";
}}
function toggleFilter(list, value) {{
  const i = list.indexOf(value);
  if (i === -1) list.push(value); else list.splice(i, 1);
}}
function buildFilters() {{
  const f = facetsFrom(COUNTS, FILTERS.kind);
  const seg = document.getElementById("diff-seg");
  seg.style.setProperty("--n", f.levels.length || 1);
  seg.innerHTML = f.levels.map(lv =>
    `<button type="button" data-level="${{lv}}" aria-pressed="false">` +
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
/* Counts shown on each option are cross-filtered (facetCountsFrom, PERF-F-6):
   a difficulty segment counts only problems whose type is currently selected,
   and a type row counts only problems whose difficulty is currently selected.
   So picking "Hard" makes every type row show its Hard-only tally. Each axis
   ignores its own selection (standard faceting) so you can still see what
   turning an option back on would add. */
function updateFacetCounts() {{
  const c = facetCountsFrom(COUNTS, FILTERS);
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
      `${{b.querySelector(".tname").textContent}}, ${{n}} ${{HE.problems}}`);
  }});
}}
function applyFilterUi() {{
  const f = facetsFrom(COUNTS, FILTERS.kind);
  document.querySelectorAll("#diff-seg button").forEach(b => {{
    const on = FILTERS.levels.includes(+b.dataset.level);
    b.classList.toggle("active", on);
    b.setAttribute("aria-pressed", on ? "true" : "false");   // UX-A-8
  }});
  document.querySelectorAll("#type-list .typerow").forEach(b =>
    b.setAttribute("aria-pressed",
      FILTERS.types.includes(b.dataset.type) ? "true" : "false"));
  document.getElementById("all-diff").textContent =
    FILTERS.levels.length >= f.levels.length ? HE.clear : HE.selectAll;
  document.getElementById("all-type").textContent =
    FILTERS.types.length >= f.types.length ? HE.clear : HE.selectAll;
  // UX-I-5: an emptied axis shows an in-panel "choose at least one" hint so the
  // 0-problems state is escapable, not a silent dead end
  document.getElementById("hint-diff").hidden = FILTERS.levels.length > 0;
  document.getElementById("hint-type").hidden = FILTERS.types.length > 0;
}}
function persist() {{
  const f = facetsFrom(COUNTS, FILTERS.kind);
  const full = FILTERS.levels.length >= f.levels.length &&
    FILTERS.types.length >= f.types.length;
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
  if (!INDEX) return;   // facets need the pool index (see setScenario guard)
  const f = facetsFrom(COUNTS, FILTERS.kind);
  FILTERS.levels =
    FILTERS.levels.length >= f.levels.length ? [] : f.levels.slice();
  persist();
}};
document.getElementById("all-type").onclick = () => {{
  if (!INDEX) return;   // facets need the pool index (see setScenario guard)
  const f = facetsFrom(COUNTS, FILTERS.kind);
  FILTERS.types =
    FILTERS.types.length >= f.types.length ? [] : f.types.slice();
  persist();
}};
function renderStats() {{
  if (!INDEX) return;
  const s = store();
  const matching = INDEX.problems.filter(p => matchesFilters(p, FILTERS));
  let done = 0, scoreSum = 0;
  for (const p of matching) {{
    const rec = s[p.id];
    if (rec) {{ done++; scoreSum += btScoreOfAttempt(rec) || 0; }}
  }}
  const f = facetsFrom(COUNTS, FILTERS.kind);
  const kindTotal = scenTotal(COUNTS, FILTERS.kind, FILTERS.mode);
  const narrowed = FILTERS.levels.length < f.levels.length ||
    FILTERS.types.length < f.types.length;
  const label = FILTERS.kind === "lead"
    ? "בעיות הובלה (" + MODE_INFO[leadMode()].title + ")" : "בעיות הכרזה";
  if (FILTERS.kind === "lead" && !kindTotal) {{
    document.getElementById("stats").innerHTML =
      '<div class="state"><div class="em">עוד אין בעיות במצב ' +
      MODE_INFO[leadMode()].title + ' במאגר</div>' +
      '<div class="muted">בעיות חדשות יופיעו כאן לאחר ריצת המחולל.</div></div>';
    updateScenCounts();
    document.getElementById("fbar-sub").textContent = "";
    document.getElementById("fbar").classList.remove("on");
    const dl = document.getElementById("deal");
    dl.classList.add("off");
    dl.innerHTML = "אין בעיות במצב זה עדיין";
    return;
  }}
  const waiting = matching.length - done;
  let h = (narrowed
      ? `<b>${{matching.length}}</b> מתוך ${{kindTotal}} ${{label}} נבחרו `
      : `<b>${{kindTotal}}</b> ${{label}} במאגר `) +
    `<span class="pill" style="border-color:var(--line);color:var(--muted)">` +
    `${{waiting}} ממתינות לך</span>`;
  if (done) {{
    const avg = Math.round(scoreSum / done);
    h += `<div style="margin-top:8px">ההישג שלך: ציון ממוצע <b>${{avg}}</b> ` +
      `על ${{done}} שנענו · <a href="dashboard.html">להתקדמות המלאה &larr;</a></div>` +
      `<div class="wpl" role="img" aria-label="ציון ממוצע ${{avg}} מתוך 100">` +
      `<span class="w" style="width:${{avg}}%">${{avg}}</span></div>`;
  }} else if (Object.keys(s).length) {{
    h += `<div style="margin-top:8px" class="muted">` +
      `עוד לא ענית על אף אחת בבחירה הזו.</div>`;
  }} else {{
    // first run: a short explainer instead of empty stats
    h += `<div style="margin-top:8px" class="muted">ברוכים הבאים! ` +
      `בכל בעיה מוצגים יד ומכרז אמיתיים; בוחרים פעולה, והמערכת משווה ` +
      `אותה לאלפי חלוקות מדומות ומראה מה באמת עבד. ` +
      `בחרו תרחיש למעלה ולחצו על "התחל תרגול".</div>`;
  }}
  document.getElementById("stats").innerHTML = h;
  updateScenCounts();
  const fbar = document.getElementById("fbar");
  document.getElementById("fbar-sub").textContent =
    narrowed ? `${{matching.length}} מתוך ${{kindTotal}}` : "כל הבעיות";
  fbar.classList.toggle("on", narrowed);
  const deal = document.getElementById("deal");
  const none = !FILTERS.levels.length || !FILTERS.types.length;
  deal.classList.toggle("off", none);
  // a dead CTA must not be a keyboard focus trap / activatable link (UX-I-5)
  deal.setAttribute("aria-disabled", none ? "true" : "false");
  if (none) deal.setAttribute("tabindex", "-1");
  else deal.removeAttribute("tabindex");
  const dealLabel = FILTERS.kind === "lead"
    ? "התחל תרגול הובלה &larr;" : "התחל תרגול הכרזה &larr;";
  deal.innerHTML = none
    ? "בחר דרגת קושי וסוג"
    : dealLabel + (waiting
      ? ` <span style="font-weight:400;opacity:.85">(${{waiting}} ממתינות)` +
        `</span>`
      : "");
}}
async function init() {{
  try {{ INDEX = await fetchIndex(); }}
  catch (e) {{
    const box = document.getElementById("stats");
    box.removeAttribute("aria-label");   // was "loading…"; now an error
    box.innerHTML = loadErrorHtml("retry-load");
    box.querySelector("#retry-load").onclick = () => init();
    return;
  }}
  COUNTS = buildCounts(INDEX);   // one pass; all facet tallies derive from this
  const q = new URLSearchParams(location.search);
  const qk = q.get("kind");
  if (qk === "lead" || qk === "bidding") SCEN = qk;
  const qm = q.get("mode");
  if (qm === "IMP" || qm === "MP") setLeadMode(qm);
  setScenario(SCEN);
  const lv = q.get("lv"), ty = q.get("type");
  if (lv || ty) {{
    if (lv) FILTERS.levels = [+lv];
    if (ty) FILTERS.types = [ty];
    persist();
    document.getElementById("fbar").setAttribute("aria-expanded", "true");
    document.getElementById("fbody").removeAttribute("hidden");
  }}
}}
// radiogroup keyboard model (UX-A-7/UX-I-9): arrows move selection AND focus
// between the cards, Enter/Space selects; roving tabindex keeps one tab stop.
const SCENCARDS = [...document.querySelectorAll("#scenario .scencard")];
function moveScen(dir) {{
  const cur = Math.max(0, SCENCARDS.findIndex(c => c.dataset.kind === SCEN));
  const next = (cur + dir + SCENCARDS.length) % SCENCARDS.length;
  setScenario(SCENCARDS[next].dataset.kind);
  SCENCARDS[next].focus();
}}
SCENCARDS.forEach(c => {{
  c.addEventListener("click", () => setScenario(c.dataset.kind));
  c.addEventListener("keydown", ev => {{
    if (ev.key === "Enter" || ev.key === " ") {{
      ev.preventDefault(); setScenario(c.dataset.kind);
    }} else if (ev.key === "ArrowRight" || ev.key === "ArrowDown") {{
      ev.preventDefault(); moveScen(1);
    }} else if (ev.key === "ArrowLeft" || ev.key === "ArrowUp") {{
      ev.preventDefault(); moveScen(-1);
    }}
  }});
}});
document.getElementById("fbar").onclick = () => {{
  const bar = document.getElementById("fbar");
  const body = document.getElementById("fbody");
  const open = bar.getAttribute("aria-expanded") === "true";
  bar.setAttribute("aria-expanded", open ? "false" : "true");
  if (open) body.setAttribute("hidden", ""); else body.removeAttribute("hidden");
}};
document.getElementById("deal").onclick = () => {{
  if (!INDEX) return false;
  if (!FILTERS.levels.length || !FILTERS.types.length) return false;
  const id = pickUnseen(INDEX, FILTERS);
  if (!id) {{
    document.getElementById("stats").innerHTML =
      '<div class="state"><div class="em">ענית על כל הבעיות בבחירה שלך!</div>' +
      '<div class="muted">הרחב את הסינון, או חזור בקרוב למנה הבאה.</div></div>';
    return false;
  }}
  localStorage.setItem("bt_session", JSON.stringify({{
    kind: FILTERS.kind, size: SESSION_SIZE, count: 0, right: 0, sum: 0, scored: 0,
    startedAt: Date.now(),   // for TTL expiry (UX-I-6)
    mode: FILTERS.kind === "lead" ? leadMode() : null,
    levels: FILTERS.levels.slice(), types: FILTERS.types.slice()}}));
  location.href = routeFor(FILTERS.kind, id);
  return false;
}};
function renderSessionSummary() {{
  const explicit = new URLSearchParams(location.search).get("summary");
  const s = getSession();   // TTL-aware
  if (!s || !s.count) return;
  // show the summary once the run is COMPLETE, on any home entry (not only the
  // ?summary=1 auto-redirect) so it isn't lost when returning via the nav; the
  // blob is cleared only on an explicit action below, so a refresh keeps it
  // (UX-I-6).
  if (!explicit && (s.count || 0) < (s.size || SESSION_SIZE)) return;
  const kindLabel = s.kind === "lead" ? "הובלה" : "הכרזה";
  // score trail; bumpSession only ever stores id + score, so a scoreless item
  // (a legacy in-flight session) maps to the no-data fallback, not 0 (= dead)
  const items = (s.items || []).map((it, idx) => ({{...it, idx,
    sc: typeof it.score === "number" ? it.score : ERROR_MIN}}));
  const avg = items.length
    ? Math.round(items.reduce((t, i) => t + i.sc, 0) / items.length)
    : Math.round(100 * (s.right || 0) / s.count);
  const misses = items.filter(i => i.sc < REVIEW_MIN && i.id);
  const missHtml = misses.length
    ? `<div style="margin-top:10px;font-weight:700">לסקירה — החלטות מתחת ל־${{REVIEW_MIN}}</div>` +
      `<ul class="notes">` + misses.map(i =>
        `<li><a href="${{routeFor(s.kind || "bidding", i.id, {{retry: true}})}}">` +
        `בעיה ${{i.idx + 1}} בסבב (ציון ${{i.sc}}) &larr;</a></li>`).join("") + `</ul>`
    : `<div style="margin-top:8px">הכול מיטבי או קרוב לכך — כל הכבוד!</div>`;
  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML = `<h2>סיכום התרגול</h2>` +
    `<div style="margin-top:6px">ענית על <b>${{s.count}}</b> בעיות ${{kindLabel}} — ` +
    `ציון ממוצע <b>${{avg}}</b>.</div>` +
    `<div class="wpl" role="img" aria-label="ציון ממוצע ${{avg}} מתוך 100" style="margin-top:8px">` +
    `<span class="w" style="width:${{avg}}%">${{avg}}</span></div>` +
    missHtml +
    `<div style="display:flex;gap:8px;margin-top:8px">` +
    `<button type="button" class="big" id="again">עוד סבב &larr;</button>` +
    `<button type="button" class="alllink" id="sum-close">סגור</button></div>`;
  const main = document.getElementById("main");
  main.insertBefore(card, main.querySelector("#scenario"));
  // the run is cleared only when the user acts on the summary (not on render),
  // so refreshing the page doesn't make it vanish (UX-I-6)
  const endRun = () => localStorage.removeItem("bt_session");
  card.querySelector("#again").onclick = () => {{
    endRun(); card.remove();
    document.getElementById("deal").click();
  }};
  card.querySelector("#sum-close").onclick = () => {{
    endRun(); card.remove(); renderSessRibbon();
  }};
}}
if (document.readyState !== "loading") renderSessionSummary();
else addEventListener("DOMContentLoaded", renderSessionSummary);
// the page rendered from cache; refresh the counts once the background sync
// lands (T4) — e.g. answers from another device change the waiting counts.
window.addEventListener("bt-attempts-synced", () => {{
  if (INDEX) {{ updateScenCounts(); renderStats(); }}
}});
if (window.BT) window.BT.start(init);
else addEventListener("bt-ready", () => window.BT.start(init), {{once: true}});
</script>
</body></html>"""


def _problem_html() -> str:
    return f"""<!DOCTYPE html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{_theme_head_script()}
<title>בעיית הכרזה</title>
<link rel="stylesheet" href="{_CSS_HREF}">
{_head_preloads()}
<script type="module" src="bt-firebase.js"></script></head><body>
<main id="main" tabindex="-1">
<div class="topbar">
<a href="index.html">&rarr; דף הבית</a>
<span id="meta"></span>
</div>
<div class="sessribbon" id="sessribbon" hidden></div>
<div id="problem"><div class="card" aria-label="טוען את הבעיה">
<div class="skl" style="width:35%"></div>
<div class="skl" style="width:100%;height:120px"></div>
<div class="skl" style="width:70%"></div>
</div></div>
<div class="candidates" id="cands"></div>
<div id="confirm"></div>
<div id="verdict" class="card" role="status" aria-live="polite">
<h2 class="headline" id="headline" tabindex="-1"></h2>
<div class="scoreline" id="scoreline"></div>
<div class="subline" id="subline"></div>
<div class="diffline" id="diffline"></div>
<div id="fog"></div>
<div class="legend"><i style="background:var(--win)"></i><button
type="button" class="gloss" data-gloss="win">זכייה</button>
<i style="background:var(--push)"></i><button type="button" class="gloss"
data-gloss="win">שוויון</button>
<i style="background:var(--loss)"></i><button type="button" class="gloss"
data-gloss="win">הפסד</button></div>
<div id="opts"></div>
<details class="notes" id="more-box" style="display:none" open>
<summary>כל האפשרויות שנבדקו</summary><div id="opts-more"></div></details>
<div class="footnote" id="footnote"></div>
<div class="footnote" id="source"></div>
<button class="big" id="next">הבעיה הבאה &larr;</button>
<details class="notes" id="deal-box"><summary>החלוקה המלאה</summary>
<div id="fulldeal"></div></details>
<details class="notes" id="review-box" style="display:none">
<summary>סקירת המכרז, הכרזה אחר הכרזה</summary><ul id="review"></ul></details>
<details class="notes" id="meanings-box"><summary>משמעויות ההכרזות
במכרז</summary><ul id="meanings"></ul></details>
<details class="notes" id="prose-box" style="display:none">
<summary>ניתוח מלא</summary><div id="explanation"
style="white-space:pre-line;font-size:13px"></div></details>
<details class="notes" id="cmp-box" style="display:none" open>
<summary>טבלת השוואה: כל ההכרזות שנבדקו</summary>
<table id="ctable" class="plain"></table>
<p class="footnote">הציון בסולם הפאנל (0-100); עמודת ה־IMP היא הפער מול
ההכרזה המיטבית, לאחר תיקון single-dummy; עמודת BEN — הסיכוי שמנוע ההכרזות
היה בוחר בהכרזה זו.</p></details>
<details class="notes" id="raw-box"><summary>נתוני double-dummy גולמיים</summary>
<table id="rtable" class="plain"></table></details>
</div>
</main>
{_taxonomy_script()}
<script src="{_SHARED_SRC}"></script>
<script>
let P = null, INDEX = null, NOTES = [], OPTSHOWS = {{}};
// true while re-attempting an already-answered problem: the re-answer is
// recorded (attemptCount++) but keeps the first-attempt score and does NOT
// count toward the practice session.
let RETRYING = false;
function resetForRetry() {{
  RETRYING = true;
  document.getElementById("verdict").style.display = "none";
  const rb = document.getElementById("retry-answer");
  if (rb) rb.remove();
  document.querySelectorAll("button.cand").forEach(b => {{
    b.disabled = false;
    b.classList.remove("good", "near", "bad", "off", "chosen");
  }});
  const cf = document.getElementById("confirm");
  if (cf) cf.innerHTML = "";
  const turn = document.querySelector("table.bidding td.turn");
  if (turn) turn.innerHTML = "?";
  ARMED = null;
  document.getElementById("cands").scrollIntoView(
    {{block: "center", behavior: "smooth"}});
  const first = document.querySelector("button.cand");
  if (first) first.focus();   // move focus off the now-hidden verdict
}}
function stripNoise(t) {{
  return (t || "").replace(/Next call is usually[^]*?%\\)\\.\\s*/g, "")
                  .replace(/most common continuation:[^]*?%\\)\\.\\s*/g, "");
}}
function evHtml(row, isTop) {{
  const ci = row.ci !== undefined ?
    ` <small>\\u00b1${{(+row.ci).toFixed(1)}}</small>` : "";
  const ev = (+row.ev).toFixed(1);
  if (isTop) {{
    return `<span class="best">הטוב</span>` +
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
              `${{contractHtml(tok)}} ${{pct(share)}}</span>`);
  }}
  if (row.policy !== undefined)
    bits.push(`<span>${{glossHtml("ben", HE.engine)}} ` +
              `${{pct(row.policy)}}</span>`);
  bits.push(`<span>${{glossHtml("win", HE.wins)}} ` +
            `${{pct(row.p_gain)}}</span>`);
  return `<div class="chips">${{bits.join("")}}</div>`;
}}
function optRowHtml(row, i, chosen, accepted) {{
  const dead = (P.verdict.dead_options || []).some(d => d.bid === row.bid);
  const push = row.p_push !== undefined ? row.p_push
             : Math.max(0, 1 - row.p_gain - row.p_loss);
  const tags = (accepted.includes(row.bid)
                  ? '<span class="tag best">הטוב</span>' : "") +
               (row.bid === chosen ? '<span class="tag you">שלך</span>' : "");
  const shows = row.shows ? `<span class="shows en">${{row.shows}}</span>`
                          : '<span class="shows"></span>';
  // widths clamp missing probabilities to 0 (safeNum) and labels show an em
  // dash rather than "NaN%" (pct) — BUG-5.
  const gw = safeNum(row.p_gain) * 100, lw = safeNum(row.p_loss) * 100;
  const bar = `<div class="wpl" role="img" aria-label="זכייה ` +
    `${{pct(row.p_gain)}}, שוויון ${{pct(push)}}, הפסד ${{pct(row.p_loss)}}">` +
    `<span class="w" style="width:${{gw}}%">${{gw > 12 ? pct(row.p_gain) : ""}}</span>` +
    `<span class="l" style="width:${{lw}}%">${{lw > 12 ? pct(row.p_loss) : ""}}</span></div>`;
  const mine = row.bid === chosen && !accepted.includes(row.bid);
  return `<div class="opt${{mine ? " mine" : ""}}">` +
    `<div class="l1"><span class="bidchip">${{callHtml(row.bid)}}` +
    `${{dead ? "\\u2020" : ""}}</span>${{tags}}${{shows}}` +
    `<span class="ev">${{evHtml(row, i === 0)}}</span></div>` +
    `${{bar}}${{chipsHtml(row)}}</div>`;
}}
function reveal(chosen) {{
  const v = P.verdict;
  const sp = btScoreBidding(P, chosen);
  document.querySelectorAll("button.cand").forEach(b => {{
    const a = b.dataset.action;
    if (v.accepted.includes(a)) b.classList.add("good");
    else if (a === chosen) b.classList.add(sp.score >= NEAR_MIN ? "near" : "bad");
    else b.classList.add("off");
    if (a === chosen) b.classList.add("chosen");
    b.disabled = true;
  }});
  const turn = document.querySelector("table.bidding td.turn");
  if (turn) turn.innerHTML = callHtml(chosen);
  const ok = v.accepted.includes(chosen);
  const rows = v.corrected || [];
  const chip = btScoreChipHtml(sp.score);
  const band = BAND_HE[btBandOf(sp.score)];
  let head;
  if (v.toss_up) {{
    head = `${{chip}} ${{band}} — שקול: ` +
      `<span class="ltr">${{v.accepted.map(callHtml).join(" / ")}}</span> שניהם טובים`;
  }} else if (ok) {{
    head = `${{chip}} הכרזה מיטבית — ` +
           `<span class="ltr">${{callHtml(chosen)}}</span>`;
  }} else {{
    const mine = rows.find(r => r.bid === chosen);
    const gap = mine ? ` (${{(+mine.ev).toFixed(1)}} IMP)` : "";
    head = `${{chip}} ${{band}} — עדיף היה ` +
           `<span class="ltr">${{callHtml(v.accepted[0])}}${{gap}}</span>, בחרת ` +
           `<span class="ltr">${{callHtml(chosen)}}</span>`;
  }}
  document.getElementById("headline").innerHTML = head;
  document.getElementById("scoreline").textContent = btScoreExplain(sp);
  const n = (P.quality && P.quality.n_samples) ||
            (P.generator && P.generator.n_deals) || 0;
  document.getElementById("subline").innerHTML =
    glossHtml("imp", "IMP") + " \\u00b7 " + glossHtml("sd", "תוצאה מתוקנת") +
    (n ? ` \\u00b7 ${{n}} חלוקות מדומות` : "");
  document.getElementById("diffline").innerHTML = diffLineHtml(P);
  if (v.fog) document.getElementById("fog").innerHTML =
    '<div class="fog">\\u26a0 שתי שיטות ההערכה חלוקות כאן (\\u201cערפל ' +
    'double-dummy\\u201d) \\u2014 הוודאות נמוכה יותר.</div>';
  // learn-first: the best option and YOUR option up front, the rest folded
  const idx = rows.map((r, i) => ({{r, i}}));
  const main = idx.filter(x => x.i === 0 || x.r.bid === chosen);
  const rest = idx.filter(x => x.i !== 0 && x.r.bid !== chosen);
  document.getElementById("opts").innerHTML =
    main.map(x => optRowHtml(x.r, x.i, chosen, v.accepted)).join("");
  if (rest.length) {{
    document.getElementById("opts-more").innerHTML =
      rest.map(x => optRowHtml(x.r, x.i, chosen, v.accepted)).join("");
    document.getElementById("more-box").style.display = "block";
  }}
  const feet = [];
  if ((v.dead_options || []).length)
    feet.push("\\u2020 לא ניצחה באף חלוקה מדומה.");
  if ((v.flags || []).includes("doubled_heavy"))
    feet.push("חלק ניכר מהמרווח בהכפלה מניח הגנת double-dummy \\u2014 " +
              "התייחס למספר המדויק בזהירות.");
  if (P.explanations && P.explanations.note) {{
    const note = P.explanations.note;
    // an unmapped engine note stays English — isolate it so its final
    // period doesn't jump to the front of the RTL line
    feet.push(NOTE_HE[note.toLowerCase().trim()] ||
              `<span class="en">${{esc(note[0].toUpperCase() + note.slice(1))}}.</span>`);
  }}
  document.getElementById("footnote").innerHTML = feet.join(" ");
  if (P.source) {{
    const s = P.source;
    document.getElementById("source").innerHTML =
      `יד אמיתית: <b class="en">${{esc(s.teams)}}</b>, ` +
      `<span class="en">${{esc(s.event)}}</span>, לוח ${{esc(s.board)}}.`;
  }}
  // bid-by-bid review from the same terse grammar as the tap notes
  const items = [];
  const seats = ["N", "E", "S", "W"];
  let seat = P.dealer;
  P.auction.forEach((tok, j) => {{
    const who = seat === P.seat ? "אתה" : seat;
    if (NOTES[j])
      items.push(`<li><b>${{who}} <span class="ltr">${{callHtml(tok)}}` +
                 `</span></b> \\u2014 ` +
                 `<span class="en">${{NOTES[j]}}</span></li>`);
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
      `<li><b>${{esc(m.seat)}}</b>: ${{esc(m.meaning)}}</li>`).join("");
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
  // comparison table: rank / bid / panel score / IMP gap / win / push /
  // loss for EVERY candidate — mirrors the ranked-leads table on the
  // lead page
  if (rows.length) {{
    const pct = x => (x === undefined || Number.isNaN(x))
      ? "\\u2014" : Math.round(x * 100) + "%";
    let ct = "<tr><th>#</th><th>הכרזה</th>" +
      "<th>" + glossHtml("panel", "ציון") + "</th>" +
      '<th class="emph">' + glossHtml("ev", "IMP צפוי") + "</th>" +
      "<th>" + glossHtml("win", "זכייה") + "</th>" +
      "<th>" + glossHtml("win", "שוויון") + "</th>" +
      "<th>" + glossHtml("win", "הפסד") + "</th>" +
      "<th>" + glossHtml("ben", "BEN") + "</th></tr>";
    rows.forEach((r, i) => {{
      const push = r.p_push !== undefined ? r.p_push
        : (r.p_gain !== undefined && r.p_loss !== undefined
            ? Math.max(0, 1 - r.p_gain - r.p_loss) : undefined);
      const dead = (v.dead_options || []).some(d => d.bid === r.bid);
      const tags = (v.accepted.includes(r.bid)
                      ? ' <span class="tag best">הטוב</span>' : "") +
        (r.bid === chosen ? ' <span class="tag you">שלך</span>' : "");
      const ci = r.ci !== undefined ?
        ` <small>\\u00b1${{(+r.ci).toFixed(1)}}</small>` : "";
      const ev = (r.ev === undefined || r.ev === null) ? "\\u2014"
        : (r.ev >= 0 ? "+" : "\\u2212") + Math.abs(+r.ev).toFixed(1) + ci;
      ct += `<tr${{r.bid === chosen ? ' class="mine"' : ""}}` +
        `${{v.accepted.includes(r.bid) ? ' style="font-weight:700"' : ""}}>` +
        `<td>${{i + 1}}</td>` +
        `<td><span class="ltr">${{callHtml(r.bid)}}` +
        `${{dead ? "\\u2020" : ""}}</span>${{tags}}</td>` +
        `<td>${{btScoreBidding(P, r.bid).score}}</td>` +
        `<td class="ltr emph">${{ev}}</td>` +
        `<td>${{pct(r.p_gain)}}</td><td>${{pct(push)}}</td>` +
        `<td>${{pct(r.p_loss)}}</td><td>${{pct(r.policy)}}</td></tr>`;
    }});
    document.getElementById("ctable").innerHTML = ct;
    document.getElementById("cmp-box").style.display = "block";
  }}
  const rbox = document.getElementById("rtable");
  if (v.raw && v.raw.length) {{
    let h = "<tr><th>הכרזה</th><th>" + glossHtml("ev", "EV (IMP)") +
            "</th><th>" + glossHtml("win", "זכייה") + "</th>" +
            "<th>" + glossHtml("win", "הפסד") + "</th></tr>";
    for (const c of v.raw)
      h += `<tr><td><span class="ltr">${{callHtml(c.bid)}}</span></td>` +
           `<td>${{c.ev >= 0 ? "+" : ""}}` +
           `${{c.ev}} \\u00b1 ${{c.ci}}</td>` +
           `<td>${{pct(c.p_gain)}}</td>` +
           `<td>${{pct(c.p_loss)}}</td></tr>`;
    rbox.innerHTML = h;
  }} else document.getElementById("raw-box").style.display = "none";
  document.getElementById("verdict").style.display = "block";
  // let the user re-attempt an answered problem (the "review" loop). The
  // re-answer keeps the first score and doesn't touch the session.
  if (!document.getElementById("retry-answer")) {{
    const rb = document.createElement("button");
    rb.type = "button"; rb.className = "big"; rb.id = "retry-answer";
    rb.style.cssText = "background:var(--card);color:var(--accent);" +
      "border:1px solid var(--accent)";
    rb.textContent = "נסה שוב (לא ישפיע על הציון)";
    rb.onclick = resetForRetry;
    const vd = document.getElementById("verdict");
    const nx = document.getElementById("next");
    if (nx && nx.parentNode === vd) vd.insertBefore(rb, nx);
    else vd.appendChild(rb);
  }}
}}
function choose(action) {{
  if (store()[P.id] && !RETRYING) return;
  reveal(action);
  const rec = window.BT.gradeBidding(P, action);
  window.BT.record(P.id, rec);   // updates the cache synchronously (excluded below)
  if (!RETRYING) bumpSession(rec.score, P.id, "bidding");
  RETRYING = false;
  const hl = document.getElementById("headline");
  if (hl) hl.focus();
  // warm the next problem so the "next" tap navigates instantly (best-effort)
  (async () => {{
    const ses = getSession();
    if (ses && (ses.count || 0) >= ses.size) return;   // session done -> no next
    try {{ if (!INDEX) INDEX = await fetchIndex(); }} catch (e) {{ return; }}
    const s = getSession();
    const flt = (s && s.kind === "bidding")
      ? {{kind: "bidding", levels: s.levels, types: s.types}}
      : resolveFilters(INDEX, loadFilters(), "bidding");
    prefetchNext(INDEX, flt);
  }})();
}}
/* two-step selection: first tap shows what the bid means, a second
   (confirm) tap locks the answer in */
let ARMED = null;
function arm(btn) {{
  if (store()[P.id] && !RETRYING) return;
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
    (shows ? `<span class="shows en">${{shows}}</span>`
           : `<span class="shows">אין תיאור</span>`) + `</div>` +
    `<button class="big" id="go">הכרז <span class="ltr">${{callHtml(a)}}</span></button></div>`;
  document.getElementById("go").onclick = () => {{
    ARMED = null; box.innerHTML = "";
    choose(a);
  }};
}}
function normalize() {{
  const v = P.verdict;
  // tolerant of every stored accepted shape, with empties dropped so
  // callHtml(v.accepted[0]) in reveal() never crashes on undefined (BUG-4).
  v.accepted = normAccepted(v);
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
      // derive p_loss only when both inputs are present; otherwise leave it
      // undefined (pct/safeNum render that as "—"/0) rather than emit NaN when
      // p_push is missing — BUG-5.
      p_loss: r.p_loss !== undefined ? r.p_loss
            : (r.p_gain !== undefined && r.p_push !== undefined
                 ? Math.max(0, 1 - r.p_gain - r.p_push) : undefined),
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
  try {{ P = takePrefetch(id) || await window.BT.getProblem(id); }}
  catch (e) {{
    const box = document.getElementById("problem");
    box.removeAttribute("aria-label");   // was "loading…"; now an error
    box.innerHTML = loadErrorHtml("retry-load");
    box.querySelector("#retry-load").onclick = () => init();
    return;
  }}
  if (!P) {{ document.getElementById("problem").innerHTML =
    '<div class="card state"><div class="em">הבעיה לא נמצאה.</div>' +
    '<a class="big" href="index.html">חזרה לתרגול</a></div>'; return; }}
  normalize();
  document.getElementById("meta").textContent =
    `IMP \\u00b7 מחלק ${{P.dealer}} \\u00b7 אתה ${{P.seat}}`;
  document.getElementById("problem").innerHTML =
    `<div class="card">${{typeBadgeHtml(P)}}${{auctionTableHtml(P, NOTES)}}` +
    `<div id="bidnote"></div>` +
    // parity with the lead page's guidance (UX-I-4): tell new users the calls
    // in the auction are tappable
    `<p class="muted" style="margin:6px 0 0">הקש הכרזה במכרז כדי לראות ` +
    `את משמעותה.</p>` +
    `<div class="hand">${{handHtml(P.hand)}}</div></div>`;
  // tap a bid -> alert-style explanation strip under the auction
  let openNote = -1;
  document.querySelectorAll(".call.expl").forEach(el => {{
    el.setAttribute("role", "button"); el.setAttribute("tabindex", "0");
  }});
  document.querySelector("table.bidding").addEventListener("keydown", ev => {{
    if ((ev.key === "Enter" || ev.key === " ") && ev.target.closest(".call.expl")) {{
      ev.preventDefault(); ev.target.click();
    }}
  }});
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
    box.innerHTML = `<div class="bidnote"><b><span class="ltr">` +
      `${{callHtml(P.auction[openNote])}} (${{seat}})</span></b> ` +
      `<span class="en">${{NOTES[openNote]}}</span>` +
      `<button class="x" aria-label="${{HE.close}}">\\u2715</button></div>`;
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
    b.setAttribute("aria-label", callLabel(c));
    b.onclick = () => arm(b);
    cands.appendChild(b);
  }}
  document.getElementById("next").onclick = async () => {{
    const s = getSession();
    if (s && (s.count || 0) >= s.size) {{ location.href = "index.html?summary=1"; return; }}
    try {{ if (!INDEX) INDEX = await fetchIndex(); }}
    catch (e) {{
      const box = document.getElementById("problem");
      box.removeAttribute("aria-label");
      box.innerHTML = loadErrorHtml("retry-load");
      box.querySelector("#retry-load").onclick = () => init();
      return;
    }}
    const flt = (s && s.kind === "bidding")
      ? {{kind: "bidding", levels: s.levels, types: s.types}}
      : resolveFilters(INDEX, loadFilters(), "bidding");
    // use the prefetched next id if it's still unseen; else pick fresh
    const pf = readPrefetch();
    // use the prefetched id only if it still exists, is unseen, and matches the
    // active filter (it may have gone stale — seen elsewhere, or the filter/
    // mode changed in another tab since the prefetch).
    const pfp = pf && pf.id && INDEX.problems.find(p => p.id === pf.id);
    const nid = (pfp && !store()[pf.id] && matchesFilters(pfp, flt))
      ? pf.id : pickUnseen(INDEX, flt);
    if (!nid) {{ location.href = "index.html?summary=1"; return; }}
    location.href = "p.html?id=" + encodeURIComponent(nid);
  }};
  const prev = store()[P.id];
  const retryParam = new URLSearchParams(location.search).get("retry") === "1";
  // ?retry=1 (from the dashboard "review" links) lands on a clean, answerable
  // problem instead of replaying the prior answer.
  if (prev && !retryParam) reveal(prev.answer);
  else if (prev && retryParam) RETRYING = true;
}}
// if the background sync (T4) brings in an answer (e.g. from another device)
// after we've already rendered, reveal it — unless the user is mid-retry or
// the verdict is already showing.
window.addEventListener("bt-attempts-synced", () => {{
  if (!P) return;
  const prev = store()[P.id];
  const vd = document.getElementById("verdict");
  if (prev && !RETRYING && !ARMED && (!vd || vd.style.display === "none"))
    reveal(prev.answer);
}});
if (window.BT) window.BT.start(init);
else addEventListener("bt-ready", () => window.BT.start(init), {{once: true}});
</script>
</body></html>"""


_LEAD_JS = r"""
let P = null, INDEX = null, MODE = "MP", MODE_FALLBACK = false;
// true while re-attempting an already-answered problem (see the bidding page).
let RETRYING = false;
function resetForRetry() {
  RETRYING = true;
  document.getElementById("verdict").style.display = "none";
  const rb = document.getElementById("retry-answer");
  if (rb) rb.remove();
  document.querySelectorAll("button.cardbtn").forEach(b => {
    b.disabled = false;
    b.classList.remove("good", "near", "bad", "chosen");
  });
  const cf = document.getElementById("confirm");
  if (cf) cf.innerHTML = "";
  ARMED = null;
  document.getElementById("problem").scrollIntoView(
    {block: "center", behavior: "smooth"});
  const first = document.querySelector("button.cardbtn");
  if (first) first.focus();   // move focus off the now-hidden verdict
}
const RANKS = "23456789TJQKA";
/* ---- training-mode helpers: MP ranks by expected defensive tricks, IMP by
   expected IMP value. Every metric stays visible in both modes; only the
   ranking objective (and the emphasized column) changes. ---- */
function hasImpMetrics(p) {
  const t = (p.verdict && p.verdict.table) || [];
  return t.length > 0 && t[0].exp_imps !== undefined;
}
function acceptedFor(p, mode) {
  const bm = p.verdict && p.verdict.by_mode;
  if (bm && bm[mode] && bm[mode].accepted && bm[mode].accepted.length)
    return bm[mode].accepted;
  return (p.verdict && p.verdict.accepted) || [];
}
function recommendedFor(p, mode) {
  const bm = p.verdict && p.verdict.by_mode;
  if (bm && bm[mode] && bm[mode].recommended) return bm[mode].recommended;
  return acceptedFor(p, mode)[0];
}
function primaryOf(r, mode) {
  return mode === "IMP" ? r.exp_imps : r.avg_def_tricks;
}
function fmtPrimary(v, mode) {
  if (v === undefined || v === null) return "—";
  return mode === "IMP"
    ? (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2) + " IMP"
    : (+v).toFixed(2) + " לק׳";  // Hebrew geresh (bidi class R): an
      // ASCII apostrophe is neutral and flips to the wrong side of the
      // word inside the forced-LTR metric cells
}
/* the mode's ranked rows, best first (stored ranks; legacy rows fall back
   to the tricks order — legacy records are MP-only by construction) */
function modeTable(p, mode) {
  const rows = ((p.verdict && p.verdict.table) || []).slice();
  const rk = mode === "IMP" ? "rank_imp" : "rank_mp";
  if (rows.length && rows[0][rk] !== undefined)
    rows.sort((a, b) => a[rk] - b[rk]);
  else rows.sort((a, b) => primaryOf(b, mode) - primaryOf(a, mode));
  return rows;
}
/* Label one bar. A group of interchangeable cards (same suit, same result)
   shows as one line, e.g. "♥ 5/4/3"; a lone card keeps its normal form. */
function groupLabel(g) {
  if (g.cards.length === 1) return cardHtml(g.cards[0]);
  const ranks = g.cards.slice()
    .sort((a, b) => RANKS.indexOf(b[1]) - RANKS.indexOf(a[1]))
    .map(c => c[1] === "T" ? "10" : c[1]);
  return suitHtml(g.suit) + " " + ranks.join("/");
}
function reveal(chosen) {
  const v = P.verdict, acc = acceptedFor(P, MODE);
  const rows = modeTable(P, MODE);
  const sp = btScoreLead(P, chosen, MODE);
  document.querySelectorAll("button.cardbtn").forEach(b => {
    const a = b.dataset.action;
    if (acc.includes(a)) b.classList.add("good");
    else if (a === chosen) b.classList.add(sp.score >= NEAR_MIN ? "near" : "bad");
    if (a === chosen) b.classList.add("chosen");
    b.disabled = true;
  });
  const ok = acc.includes(chosen);
  const chip = btScoreChipHtml(sp.score);
  document.getElementById("headline").innerHTML = ok
    ? chip + ' הובלה מיטבית — <span class="ltr">' + cardHtml(chosen) + '</span>'
    : chip + ' ' + BAND_HE[btBandOf(sp.score)] + ' — עדיף היה <span class="ltr">' +
      acc.map(cardHtml).join(" / ") + '</span>';
  document.getElementById("scoreline").textContent = btScoreExplain(sp);
  document.getElementById("subhead").innerHTML = acc.length > 1
    ? 'טובות באותה מידה: <span class="ltr">' +
      acc.map(cardHtml).join(", ") + '</span>' : "";
  // your lead vs the active mode's recommendation, and your rank in it
  const rec = recommendedFor(P, MODE);
  const myIdx = rows.findIndex(r => r.card === chosen);
  document.getElementById("resid").innerHTML =
    '<div class="resultline">מצב: <b class="ltr">' +
    glossHtml(MODE === "IMP" ? "imp" : "mp", MODE_INFO[MODE].banner) +
    '</b> · <span class="modegoal">' + MODE_INFO[MODE].goal + '</span></div>' +
    '<div class="resultline">ההובלה שלך: <b class="ltr">' + cardHtml(chosen) + '</b></div>' +
    '<div class="resultline">ההובלה המומלצת (' + MODE_INFO[MODE].title +
    '): <b class="ltr">' + cardHtml(rec) + '</b></div>' +
    (myIdx >= 0 ? '<div class="resultline">הדירוג שלך: <b>' + (myIdx + 1) +
      '</b> מתוך ' + rows.length + '</div>' : "");
  // Group the ranked cards into per-suit buckets of equal outcome under the
  // ACTIVE mode's primary metric: cards in the same suit with the same value
  // are interchangeable, so they collapse into a single line (e.g. "♥ 5/4/3").
  const groups = [], byKey = {};
  rows.forEach(r => {
    const val = primaryOf(r, MODE);
    if (val === undefined) return;
    const key = r.card[0] + ":" + (+val).toFixed(2);
    let g = byKey[key];
    if (!g) { g = {suit: r.card[0], val: +val, cards: []};
              byKey[key] = g; groups.push(g); }
    g.cards.push(r.card);
  });
  // Always keep each suit's best line; also surface any higher-ranked
  // alternative that beats the weakest suit-best — a strong option that would
  // otherwise stay hidden behind its own suit's top card.
  const suitBest = {};
  groups.forEach(g => {
    if (!suitBest[g.suit] || g.val > suitBest[g.suit].val) suitBest[g.suit] = g;
  });
  const bests = Object.keys(suitBest).map(s => suitBest[s]);
  const bestSet = new Set(bests);
  const minBest = bests.length ? Math.min.apply(null, bests.map(g => g.val)) : 0;
  const MAX_BARS = 6;
  let picked = groups.filter(g => bestSet.has(g) || g.val > minBest);
  if (picked.length > MAX_BARS) {
    const extras = picked.filter(g => !bestSet.has(g));
    picked = bests.concat(extras.slice(0, Math.max(0, MAX_BARS - bests.length)));
  }
  const chosenGroup = groups.find(g => g.cards.indexOf(chosen) >= 0);
  if (chosenGroup && picked.indexOf(chosenGroup) < 0) picked.push(chosenGroup);
  picked.sort((a, b) => b.val - a.val);
  // bar widths: normalized to the picked range (IMP values can be negative)
  const maxv = picked.length ? Math.max.apply(null, picked.map(g => g.val)) : 1;
  const minv = picked.length ? Math.min.apply(null, picked.map(g => g.val)) : 0;
  document.getElementById("bars").innerHTML = picked.map(g => {
    const val = g.val, good = g.cards.some(c => acc.includes(c));
    const mine = g.cards.indexOf(chosen) >= 0;
    const pct = maxv > minv
      ? Math.round(4 + 96 * (val - minv) / (maxv - minv))
      : 100;
    // "(שלך)" sits in a fixed-width slot present on EVERY row — a
    // conditional flex item shortened only the chosen row's track,
    // leaving its bar misaligned with the others
    const you = '<span class="byou">' + (mine ? "(שלך)" : "") + '</span>';
    const mark = good ? '<span class="ok" aria-label="הטוב ביותר">✓</span> ' : "";
    return '<div class="barrow' + (mine ? " mine" : "") + '"><span class="bl">' + mark +
      '<span class="ltr">' + groupLabel(g) + '</span></span>' +
      '<span class="bartrack"><span class="' + (good ? "good" : "") +
      '" style="width:' + pct + '%"></span></span>' +
      '<span class="barval">' + fmtPrimary(val, MODE) + '</span>' + you + '</div>';
  }).join("");
  // Card explanation, built here in Hebrew from the verdict numbers (the pool
  // stores an English phrasing we intentionally don't surface).
  const noteFor = c => {
    const i = rows.findIndex(r => r.card === c);
    if (i < 0) return "";
    const r = rows[i];
    if (MODE === "IMP") {
      const a = fmtPrimary(r.exp_imps, "IMP");
      return acc.includes(c)
        ? "ההובלה המיטבית ל-IMP — ערך IMP צפוי של " + a +
          ", גבוה מכל קלף אחר."
        : "ערך IMP צפוי " + a + " (מדורג " + (i + 1) + " מתוך " +
          rows.length + ").";
    }
    const a = r.avg_def_tricks.toFixed(2);
    if (acc.includes(c))
      return "ההובלה המיטבית — ההגנה זוכה בממוצע ב־" + a +
             " לקיחות, יותר מכל קלף אחר.";
    const vs = (r.vs_best >= 0 ? "+" : "") + (r.vs_best || 0).toFixed(2);
    return "בממוצע " + a + " לקיחות בהגנה (" + vs +
           " מול ההובלה המיטבית · מדורג " + (i + 1) + " מתוך " +
           rows.length + ").";
  };
  let expl = noteFor(acc[0]);
  if (!ok) { const y = noteFor(chosen); if (y) expl += "\n\n" + y; }
  document.getElementById("lead-expl").textContent = expl;
  const lv = (P.classification && P.classification.difficulty_level) || P.difficulty;
  document.getElementById("difficulty").innerHTML =
    glossHtml("diff", "רמת קושי") + " " + lv + "/5";
  // ranked leads table: rank / lead / expected defensive tricks / expected
  // IMP value / set probability. The active mode's own metric column is the
  // leading (emphasized) one; every metric shows in BOTH modes.
  const mpEm = MODE === "MP" ? ' class="emph"' : "";
  const impEm = MODE === "IMP" ? ' class="emph"' : "";
  let rt = "<tr><th>#</th><th>קלף</th>" +
    "<th>" + glossHtml("panel", "ציון") + "</th>" +
    "<th" + mpEm + ">" + glossHtml("tricks", "לקיחות צפויות") + "</th>" +
    "<th" + impEm + ">" + glossHtml("ev", "IMP צפוי") + "</th>" +
    "<th>" + glossHtml("set", "סיכוי הכשלה") + "</th></tr>";
  rows.forEach((r, i) => {
    const g = acc.includes(r.card) ? ' style="font-weight:700"' : "";
    rt += "<tr" + g + "><td>" + (i + 1) + '</td><td><span class="ltr">' +
      cardHtml(r.card) + '</span></td>' +
      "<td>" + btScoreChipHtml(btScoreLead(P, r.card, MODE).score, true) +
      "</td>" +
      "<td" + mpEm + ">" + r.avg_def_tricks.toFixed(2) + "</td>" +
      '<td class="ltr' + (MODE === "IMP" ? " emph" : "") + '">' +
      (r.exp_imps === undefined ? "—"
        : (r.exp_imps >= 0 ? "+" : "−") + Math.abs(r.exp_imps).toFixed(2)) +
      "</td><td>" +
      (r.set_prob === undefined ? "—" : Math.round(r.set_prob * 100) + "%") +
      "</td></tr>";
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
  if (!document.getElementById("retry-answer")) {
    const rb = document.createElement("button");
    rb.type = "button"; rb.className = "big"; rb.id = "retry-answer";
    rb.style.cssText = "background:var(--card);color:var(--accent);" +
      "border:1px solid var(--accent)";
    rb.textContent = "נסה שוב (לא ישפיע על הציון)";
    rb.onclick = resetForRetry;
    const vd = document.getElementById("verdict");
    const nx = document.getElementById("next");
    if (nx && nx.parentNode === vd) vd.insertBefore(rb, nx);
    else vd.appendChild(rb);
  }
}
function commit(a) {
  if (store()[P.id] && !RETRYING) return;
  reveal(a);
  const rec = window.BT.gradeLead(P, a, MODE);
  window.BT.record(P.id, rec);   // updates the cache synchronously
  if (!RETRYING) bumpSession(rec.score, P.id, "lead");
  RETRYING = false;
  const hl = document.getElementById("headline");
  if (hl) hl.focus();
  // warm the next problem so the "next" tap navigates instantly (best-effort)
  (async () => {
    const ses = getSession();
    if (ses && (ses.count || 0) >= ses.size) return;   // session done -> no next
    try { if (!INDEX) INDEX = await fetchIndex(); } catch (e) { return; }
    const s = getSession();
    const flt = (s && s.kind === "lead")
      ? {kind: "lead", mode: s.mode || leadMode(),
         levels: s.levels, types: s.types}
      : resolveFilters(INDEX, loadLead(), "lead");
    prefetchNext(INDEX, flt);
  })();
}
/* two-step selection: first tap arms the card, a second (confirm) tap
   leads it \\u2014 so one stray tap never locks in a final answer */
let ARMED = null;
function arm(btn) {
  if (store()[P.id] && !RETRYING) return;
  const a = btn.dataset.action;
  const box = document.getElementById("confirm");
  document.querySelectorAll("button.cardbtn")
    .forEach(b => b.classList.remove("chosen"));
  if (ARMED === a) { ARMED = null; box.innerHTML = ""; return; }
  ARMED = a;
  btn.classList.add("chosen");
  box.innerHTML = '<div class="card confirmbox"><div class="l1">' +
    '<span class="bidchip">' + cardHtml(a) + '</span>' +
    '<span class="shows">להוביל קלף זה?</span></div>' +
    '<button class="big" id="go">הובל <span class="ltr">' + cardHtml(a) + '</span></button></div>';
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
  const q = new URLSearchParams(location.search);
  const id = q.get("id");
  try { P = takePrefetch(id) || await window.BT.getProblem(id); }
  catch (e) {
    const box = document.getElementById("problem");
    box.removeAttribute("aria-label");   // was "loading…"; now an error
    box.innerHTML = loadErrorHtml("retry-load");
    box.querySelector("#retry-load").onclick = () => init();
    return;
  }
  if (!P) { document.getElementById("problem").innerHTML =
    '<div class="card state"><div class="em">הבעיה לא נמצאה.</div>' +
    '<a class="big" href="index.html">חזרה לתרגול</a></div>'; return; }
  // active training mode: URL param wins, then the mode this problem was
  // forged for (each section serves its own generator's pool). A prior
  // answer replays in the mode it was graded in; a legacy problem without
  // IMP metrics falls back to MP (it must never be ranked by IMPs).
  const qm = q.get("mode");
  MODE = qm === "IMP" || qm === "MP" ? qm : targetModeOf(P);
  const prevAns = store()[P.id];
  if (prevAns && (prevAns.trainingMode === "MP" ||
                  prevAns.trainingMode === "IMP"))
    MODE = prevAns.trainingMode;
  if (MODE === "IMP" && !hasImpMetrics(P)) { MODE = "MP"; MODE_FALLBACK = true; }
  const meanings = (P.explanations && P.explanations.auction) || [];
  // contract is {level}{denom}{declarer}{doubled}, e.g. 4HE / 3NTWx / 6SSxx —
  // strip the declarer seat AND any double marker, then show a doubled tag.
  const cm = /^(\d(?:NT|[CDHS]))[NESW](x{0,2})$/.exec(P.contract);
  const callPart = cm ? cm[1] : P.contract.slice(0, -1);
  const dblTag = cm && cm[2] === "xx" ? " כפל כפליים"
               : cm && cm[2] === "x" ? " כפל" : "";
  const dblText = cm && cm[2] === "xx" ? "מוכפל כפליים"
                : cm && cm[2] === "x" ? "מוכפל" : "לא מוכפל";
  document.getElementById("meta").innerHTML =
    'חוזה <span class="ltr">' + callHtml(callPart) + '</span>' + dblTag +
    ' ע"י ' + P.declarer + " · אתה מוביל (" + P.leader + ")";
  // mode banner: the active mode, its objective, and the deal facts
  // (contract, declarer, vulnerability, doubling status) — always visible.
  const info = MODE_INFO[MODE];
  document.getElementById("modebanner").innerHTML =
    '<div class="modebanner"><button type="button" class="modechip" ' +
    'data-gloss="' + (MODE === "IMP" ? "imp" : "mp") + '">' + info.banner +
    '</button><span class="modegoal">' + info.goal + '</span></div>' +
    '<div class="ctline">חוזה <b class="ltr">' + callHtml(callPart) +
    '</b>' + dblTag + ' ע"י <b>' + P.declarer + '</b> · פגיעות: <b>' +
    vulLabel(P.vul) + '</b> · ' + dblText + '</div>' +
    (MODE_FALLBACK
      ? '<div class="fog">מדדי IMP אינם זמינים לבעיה זו (רשומה מדור ' +
        'קודם) — מוצג מצב MP.</div>' : "");
  document.getElementById("problem").innerHTML =
    '<div class="card">' + typeBadgeHtml(P) +
    completeAuctionTableHtml(P, meanings) +
    '<div id="bidnote"></div>' +
    '<p class="muted" style="margin:6px 0 0">הקש הכרזה כדי לראות את משמעותה · ' +
    'הקש קלף למטה כדי להוביל אותו.</p></div>';
  let openNote = -1;
  const tbl = document.querySelector("table.bidding");
  if (tbl) tbl.querySelectorAll(".call.expl").forEach(el => {
    el.setAttribute("role", "button"); el.setAttribute("tabindex", "0"); });
  if (tbl) tbl.addEventListener("keydown", ev => {
    if ((ev.key === "Enter" || ev.key === " ") && ev.target.closest(".call.expl")) {
      ev.preventDefault(); ev.target.click(); } });
  if (tbl) tbl.addEventListener("click", ev => {
    const el = ev.target.closest(".call.expl");
    const box = document.getElementById("bidnote");
    document.querySelectorAll(".call.open").forEach(c => c.classList.remove("open"));
    if (!el || +el.dataset.i === openNote) { openNote = -1; box.innerHTML = ""; return; }
    openNote = +el.dataset.i;
    el.classList.add("open");
    const a = meanings[openNote] || {};
    // prefer the terse grammar over the raw GIB prose, matching the
    // bidding page; both stay English by design
    const note = a.card ? terse(a.card, a.call) : (a.text || "");
    box.innerHTML = '<div class="bidnote"><b><span class="ltr">' +
      cardHtml_or_call(a.call) + ' (' + (a.seat || "") + ')</span></b> ' +
      '<span class="en">' + note + '</span>' +
      '<button class="x" aria-label="' + HE.close + '">✕</button></div>';
    box.querySelector(".x").onclick = () => {
      openNote = -1; box.innerHTML = "";
      document.querySelectorAll(".call.open").forEach(c => c.classList.remove("open"));
    };
  });
  const parts = P.hand.split(".");
  document.getElementById("grid").innerHTML = ["S", "H", "D", "C"].map((s, i) => {
    const btns = (parts[i] || "").split("").map(rk => {
      const face = rk === "T" ? "10" : rk;
      return '<button class="cardbtn" aria-label="' + cardLabel(s + rk) +
        '" data-action="' + s + rk + '">' + face + '</button>';
    }).join("");
    return '<div class="suitrow"><span class="s">' + suitHtml(s) + '</span>' +
      (btns || '<span class="muted">—</span>') + '</div>';
  }).join("");
  document.querySelectorAll("button.cardbtn").forEach(b => b.onclick = () => arm(b));
  document.getElementById("next").onclick = async () => {
    const s = getSession();
    if (s && (s.count || 0) >= s.size) { location.href = "index.html?summary=1"; return; }
    try { if (!INDEX) INDEX = await fetchIndex(); }
    catch (e) {
      const box = document.getElementById("problem");
      box.removeAttribute("aria-label");
      box.innerHTML = loadErrorHtml("retry-load");
      box.querySelector("#retry-load").onclick = () => init();
      return;
    }
    const flt = (s && s.kind === "lead")
      ? {kind: "lead", mode: s.mode || leadMode(),
         levels: s.levels, types: s.types}
      : resolveFilters(INDEX, loadLead(), "lead");
    const pf = readPrefetch();
    // use the prefetched id only if it still exists, is unseen, and matches the
    // active filter (it may have gone stale — seen elsewhere, or the filter/
    // mode changed in another tab since the prefetch).
    const pfp = pf && pf.id && INDEX.problems.find(p => p.id === pf.id);
    const nid = (pfp && !store()[pf.id] && matchesFilters(pfp, flt))
      ? pf.id : pickUnseen(INDEX, flt);
    if (!nid) { location.href = "index.html?summary=1"; return; }
    location.href = routeFor("lead", nid);
  };
  const prev = store()[P.id];
  const retryParam = new URLSearchParams(location.search).get("retry") === "1";
  if (prev && !retryParam) reveal(prev.answer);
  else if (prev && retryParam) RETRYING = true;
}
function cardHtml_or_call(tok) { return tok ? callHtml(tok) : ""; }
window.addEventListener("bt-attempts-synced", () => {
  if (!P) return;
  const prev = store()[P.id];
  const vd = document.getElementById("verdict");
  if (prev && !RETRYING && !ARMED && (!vd || vd.style.display === "none"))
    reveal(prev.answer);
});
if (window.BT) window.BT.start(init);
else addEventListener("bt-ready", () => window.BT.start(init), {once: true});
"""


def _lead_html() -> str:
    return (
        '<!DOCTYPE html>\n<html lang="he" dir="rtl"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        + _theme_head_script() + '\n'
        '<title>בעיית הובלה</title>\n<link rel="stylesheet" href="'
        + _CSS_HREF + '">\n'
        + _head_preloads() + '\n'
        '<script type="module" src="bt-firebase.js"></script></head>'
        '<body data-scenario="lead">\n<main id="main" tabindex="-1">\n'
        '<div class="topbar"><a href="index.html">&rarr; דף הבית</a>'
        '<span class="muted" id="meta"></span></div>\n'
        '<div class="sessribbon" id="sessribbon" hidden></div>\n'
        # loading skeletons (UX-I-4): match p.html so lead.html shows structure
        # instead of an empty felt while auth+Firestore resolve
        '<div class="card" id="modebanner">'
        '<div class="skl" style="width:45%"></div></div>\n'
        '<div id="problem">'
        '<div class="skl" style="width:35%"></div>'
        '<div class="skl" style="width:100%;height:120px"></div>'
        '<div class="skl" style="width:70%"></div></div>\n'
        '<div class="leadgrid" id="grid"></div>\n'
        '<div id="confirm"></div>\n'
        '<div id="verdict" class="card" style="display:none" role="status" '
        'aria-live="polite">\n'
        '<h2 class="headline" id="headline" tabindex="-1"></h2>\n'
        '<div class="scoreline" id="scoreline"></div>\n'
        '<p class="muted" id="subhead"></p>\n'
        '<div id="resid"></div>\n'
        '<div id="bars"></div>\n'
        '<p id="lead-expl" style="white-space:pre-line"></p>\n'
        '<div class="muted" id="difficulty"></div>\n'
        '<button class="big" id="next">ההובלה הבאה &larr;</button>\n'
        '<details open><summary>כל 13 ההובלות, מדורגות</summary>'
        '<table class="plain" id="ltable"></table>'
        '<p class="footnote">קלפים שווים במדד המוביל — כולם נכונים.</p>'
        '</details>\n'
        '<p class="footnote">ההמלצות מבוססות על הגרלת ידיים נסתרות '
        'וניתוח <button type="button" class="gloss" data-gloss="dd">'
        'double-dummy</button>; שיטת החישוב הפעילה קובעת את דירוג ההובלות.</p>\n'
        '<details><summary>החלוקה המלאה</summary>'
        '<div id="fulldeal"></div></details>\n'
        '</div>\n</main>\n' + _taxonomy_script() + '\n<script src="'
        + _SHARED_SRC + '"></script>\n<script>'
        + _LEAD_JS + '</script>\n</body></html>'
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
.band .bseg.opt { background: var(--win); color: var(--on-win); }
.band .bseg.near { background: var(--gold); color: var(--on-gold); }
.band .bseg.bl { background: var(--loss); color: var(--on-loss); }
.blegend { display: flex; gap: 12px; flex-wrap: wrap; font-size: 12px;
           color: var(--muted); }
.blegend i.sw { width: 10px; height: 10px; border-radius: 3px; display: inline-block;
                margin-inline-end: 4px; vertical-align: middle; }
.blegend i.opt { background: var(--win); } .blegend i.near { background: var(--gold); }
.blegend i.bl { background: var(--loss); }
.catrow { direction: rtl; }
.catrow .dbar { direction: ltr; }
.drill { border-top: 1px solid var(--line); }
/* drill rows are data rows, not captions — keep the text tone and let the
   accent chevron alone signal that they expand */
.drill > summary { cursor: pointer; padding: 2px 0; color: var(--fg);
                   font-weight: 400; }
.drill > summary .catrow { margin: 5px 0; }
.drill .drillbody { padding: 0 1.6em 6px; }
/* #dash content rides directly on the green felt: its cards reset to their own
   --fg, but the loading placeholder, the load-error line and the closing
   footnote are loose text. Default #dash to the on-felt tone (and the footnote
   to the muted on-felt tone) so they aren't dark-green-on-green — unreadable in
   light mode. */
#dash { color: var(--on-felt); }
#dash .dtab > .footnote { color: var(--on-felt-muted); }
"""

_DASHBOARD_JS = r"""
const MIN_N = 5, MIN_TREND = 8;
// cost-line units differ by scenario AND, for leads, by training mode
// (MP costs are tricks below best; IMP costs are IMPs below best). The
// distribution band itself groups by the panel score, not by raw cost.
const COST = { bidding: {unit: "IMP"}, lead: {unit: "לקיחה"},
               leadIMP: {unit: "IMP"} };
const SUIT_NAME = {S: "עלה", H: "לב", D: "יהלום", C: "תלתן"};
const RANKS = "AKQJT98765432";
function num(x) { return typeof x === "number" ? x : (parseFloat(x) || 0); }
function median(xs) {
  if (!xs.length) return 0;
  const s = [...xs].sort((a, b) => a - b), m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}
/* mean panel score with a 95% CI on the mean (replaces the Wilson
   proportion — the aggregate is now an average of 0-100 scores) */
function meanCI(xs) {
  const n = xs.length;
  const m = xs.reduce((s, x) => s + x, 0) / n;
  const sd = n > 1
    ? Math.sqrt(xs.reduce((s, x) => s + (x - m) * (x - m), 0) / (n - 1)) : 0;
  const h = 1.96 * sd / Math.sqrt(n);
  return {m, lo: Math.max(0, m - h), hi: Math.min(100, m + h)};
}
function tsMillis(a) {
  if (!a || !a.ts) return 0;
  if (typeof a.ts.toMillis === "function") return a.ts.toMillis();
  if (a.ts.seconds) return a.ts.seconds * 1000;
  return 0;
}
// Order first-attempts by their FIRST-attempt time. A re-answer now bumps `ts`
// (so incremental cross-device sync notices attemptCount updates — DB-M-9), but
// `firstTs` is written once at the first attempt and never moves. Fall back to
// `ts` for legacy docs that predate firstTs — there `ts` is still the first
// attempt's time, so ordering is unchanged for them.
function firstMs(a) { return tsMillis(a && a.firstTs ? {ts: a.firstTs} : a); }
// Ids still present in the pool index; attempts whose problem was deleted are
// marked "removed" instead of linking to a dead page (DB-M-9). null = unknown
// (index unavailable) -> treat every attempt as live, as before.
let LIVE_IDS = null;
function row(label, scores) {
  const n = scores.length;
  if (n < MIN_N)
    return `<div class="catrow"><span>${label}</span>` +
      `<span class="muted">אין מספיק נתונים</span>` +
      `<span class="muted">n=${n}</span></div>`;
  const c = meanCI(scores);
  return `<div class="catrow"><span>${label}</span>` +
    `<span class="dbar"><span style="width:${c.m}%"></span></span>` +
    `<span>${Math.round(c.m)} <span class="muted">(${Math.round(c.lo)}–` +
    `${Math.round(c.hi)}, n=${n})</span></span></div>`;
}
function diffRows(list) {
  const by = {};
  list.forEach(a => { const d = a.difficultyLevel || 0;
    (by[d] ??= []).push(btScoreOfAttempt(a)); });
  const out = [1, 2, 3, 4, 5].filter(d => by[d])
    .map(d => row(DIFF_NAMES[d] || ("רמה " + d), by[d])).join("");
  return out || '<div class="muted">אין נתונים</div>';
}
function typeRows(list) {
  const by = {};
  list.forEach(a => { const t = a.type || "—";
    (by[t] ??= []).push(btScoreOfAttempt(a)); });
  const es = Object.entries(by).sort((a, b) => b[1].length - a[1].length);
  return es.length
    ? es.map(([t, s]) => row((TYPE_NAMES[t] && TYPE_NAMES[t][0]) || t, s)).join("")
    : '<div class="muted">אין נתונים</div>';
}
function costBand(list, kind) {
  const cfg = COST[kind] || COST.bidding, n = list.length;
  if (!n) return "";
  let opt = 0, near = 0, bl = 0; const costs = [];
  list.forEach(a => { costs.push(num(a.gradedCost));
    const sc = btScoreOfAttempt(a);
    if (sc >= REVIEW_MIN) opt++; else if (sc >= ERROR_MIN) near++; else bl++; });
  const mean = costs.reduce((s, c) => s + c, 0) / n, med = median(costs), u = cfg.unit;
  const seg = (cls, v) => v
    ? `<span class="bseg ${cls}" style="width:${(v / n * 100).toFixed(1)}%">` +
      `${Math.round(v / n * 100)}%</span>` : "";
  const uHtml = u === "IMP" ? glossHtml("imp", "IMP") : u;
  return `<div class="costline">ממוצע <b>${mean.toFixed(1)}</b> ${uHtml} מתחת למיטבי ` +
    `<span class="muted">(חציון ${med.toFixed(1)})</span></div>` +
    `<div class="band" role="img" aria-label="מיטבי או קרוב ${opt}, סטייה ${near}, ` +
    `כשל ${bl} מתוך ${n}">` + seg("opt", opt) + seg("near", near) + seg("bl", bl) +
    '</div><div class="blegend">' +
    '<span><i class="sw opt"></i>מיטבי או קרוב (ציון 85+)</span>' +
    '<span><i class="sw near"></i>סטייה (40–84)</span>' +
    '<span><i class="sw bl"></i>כשל (0–39)</span></div>';
}
function suitRows(list) {
  const suits = {S: {all: [], c: {}}, H: {all: [], c: {}},
                 D: {all: [], c: {}}, C: {all: [], c: {}}};
  list.forEach(a => { const card = a.chosenCall || "", st = card[0], s = suits[st];
    if (!s) return;
    const sc = btScoreOfAttempt(a);
    s.all.push(sc);
    (s.c[card] ??= []).push(sc); });
  const order = ["S", "H", "D", "C"].filter(st => suits[st].all.length);
  if (!order.length) return '<div class="muted">אין נתונים</div>';
  return order.map(st => {
    const s = suits[st], label = suitHtml(st) + " " + SUIT_NAME[st];
    const cards = Object.keys(s.c)
      .sort((a, b) => RANKS.indexOf(a[1]) - RANKS.indexOf(b[1]))
      .map(c => row(cardHtml(c), s.c[c])).join("");
    return '<details class="drill"><summary>' + row(label, s.all) + '</summary>' +
      '<div class="drillbody">' + cards + '</div></details>';
  }).join("");
}
function scenarioCard(title, list, kind, costKey) {
  if (!list.length) return "";
  const cfg = COST[costKey || kind] || COST.bidding;
  let html = '<div class="card scen"><b>' + title + '</b> ' +
    '<span class="muted">' + (kind === "lead" && cfg.unit !== "IMP"
      ? "לקיחות" : glossHtml("imp", "IMP")) +
    ' · n=' + list.length + '</span>' +
    costBand(list, costKey || kind) +
    '<div class="subh">לפי דרגת קושי</div>' + diffRows(list);
  if (kind === "lead") {
    html += '<div class="subh">לפי סוג חוזה</div>' + typeRows(list) +
      '<div class="subh">לפי סדרת ההובלה</div>' + suitRows(list) +
      '<div class="muted" style="font-size:12px;margin-top:4px">' +
      'הקש סדרה כדי לראות את הקלפים.</div>';
  } else {
    html += '<div class="subh">לפי סוג בעיה</div>' + typeRows(list);
  }
  return html + '</div>';
}
function weakArea(scen) {
  let worst = null;
  const mean = xs => xs.reduce((s, x) => s + x, 0) / xs.length;
  const bt = {};
  scen.bidding.forEach(a => { const t = a.type; if (!t) return;
    (bt[t] ??= []).push(btScoreOfAttempt(a)); });
  for (const [t, xs] of Object.entries(bt)) if (xs.length >= MIN_N) {
    const m = mean(xs);
    if (!worst || m < worst.m) worst = {m, kind: "bidding",
      label: (TYPE_NAMES[t] && TYPE_NAMES[t][0]) || t,
      href: "index.html?kind=bidding&type=" + t};
  }
  const ld = {};
  scen.lead.forEach(a => { const d = a.difficultyLevel; if (!d) return;
    (ld[d] ??= []).push(btScoreOfAttempt(a)); });
  for (const [d, xs] of Object.entries(ld)) if (xs.length >= MIN_N) {
    const m = mean(xs);
    if (!worst || m < worst.m) worst = {m, kind: "lead",
      label: "הובלה — " + (DIFF_NAMES[d] || d),
      href: "index.html?kind=lead&lv=" + d};
  }
  return worst;
}
const OUTCOME_HE = {winner: "מנצחת", "accepted-alt": "חלופה קבילה",
  dead: "מתה", suboptimal: "לא אופטימלית"};
function render(attempts) {
  const el = document.getElementById("dash");
  if (!attempts.length) {
    el.innerHTML = '<div class="card state"><div class="em">עוד אין נתונים</div>' +
      '<a class="big" href="index.html">ענה על בעיה כדי להתחיל &larr;</a></div>';
    return;
  }
  const first = attempts.filter(a => a.isFirstAttempt !== false);
  const n = first.length;
  const avgAll = n
    ? first.reduce((s, a) => s + btScoreOfAttempt(a), 0) / n : 0;
  const recent = [...first].sort((a, b) => firstMs(b) - firstMs(a));
  let streak = 0;
  for (const a of recent) { if (btScoreOfAttempt(a) >= 100) streak++; else break; }
  // split first-attempts by scenario, and leads further by training mode
  // (cost units differ: MP grades in tricks, IMP in IMPs)
  const scen = {bidding: [], lead: []};
  for (const a of first) scen[a.kind === "lead" ? "lead" : "bidding"].push(a);
  const leadMP = scen.lead.filter(a => a.trainingMode !== "IMP");
  const leadIMP = scen.lead.filter(a => a.trainingMode === "IMP");
  const byKind = {};
  for (const a of first) { const kd = a.kind || "bidding";
    (byKind[kd] ??= []).push(btScoreOfAttempt(a)); }
  const chrono = [...first].sort((a, b) => firstMs(a) - firstMs(b));
  let trend = "";
  if (chrono.length >= MIN_TREND) {
    let cum = 0; const pts = [];
    chrono.forEach((a, i) => { cum += btScoreOfAttempt(a); pts.push(cum / (i + 1)); });
    const W = 300, H = 60, step = W / (pts.length - 1);
    const path = pts.map((y, i) =>
      `${i ? "L" : "M"}${(i * step).toFixed(1)},${(H - y * 0.6).toFixed(1)}`).join(" ");
    const last = Math.round(pts[pts.length - 1]);
    // cumulative mean score plus a rolling window: the cumulative line
    // flattens and hides recent change, so overlay a last-min(20, n/2) window
    const win = Math.max(MIN_TREND, Math.min(20, Math.round(chrono.length / 2)));
    const roll = chrono.map((a, i) => {
      const lo = Math.max(0, i - win + 1);
      let s = 0; for (let j = lo; j <= i; j++) s += btScoreOfAttempt(chrono[j]);
      return s / (i - lo + 1);
    });
    const rpath = roll.map((y, i) =>
      `${i ? "L" : "M"}${(i * step).toFixed(1)},${(H - y * 0.6).toFixed(1)}`).join(" ");
    trend = '<div class="card"><b>ציון לאורך זמן</b> ' +
      '<span class="muted">(ניסיון ראשון)</span><br>' +
      `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="ציון לאורך זמן, כעת ${last}" style="width:100%;height:auto;margin-top:6px">` +
      `<line x1="0" y1="${H - 30}" x2="${W}" y2="${H - 30}" stroke="#8884" ` +
      'stroke-dasharray="3"></line>' +
      `<path d="${rpath}" fill="none" stroke="var(--muted)" stroke-width="1.5" stroke-dasharray="4 3"></path>` +
      `<path d="${path}" fill="none" stroke="var(--accent)" stroke-width="2"></path>` +
      '</svg><div class="muted">' +
      '<span style="color:var(--accent)">■</span> מצטבר · ' +
      '<span>▨</span> חלון אחרון (' + win + ') · קו מקווקו = ציון 50 · כעת ' +
      last + '</div></div>';
  }
  const badge = m => {
    const t = TYPE_NAMES[m.type];
    const d = m.difficultyLevel;
    return (t ? `<span class="typebadge" style="margin:0">${t[0]}</span> ` : "") +
      (d ? `<span class="stars" style="font-size:12px"><span class="on">` +
        `${"★".repeat(d)}</span><span class="off">${"★".repeat(5 - d)}</span></span>` : "");
  };
  const misses = recent.filter(a => btScoreOfAttempt(a) < REVIEW_MIN).slice(0, 10);
  const missList = misses.length
    ? '<div class="card"><b>לשיפור — החלטות מתחת ל־' + REVIEW_MIN + '</b> <span class="muted">(הקש לחזרה)</span>' +
      '<ul class="misslist">' + misses.map(m => {
        // attempt fields are user-owned free text -> esc() before innerHTML
        // (SEC-A-6). A problem deleted from the pool becomes a non-link
        // "removed" row instead of a dead retry link (DB-M-9).
        const gone = LIVE_IDS && !LIVE_IDS.has(m.problemId);
        const body =
          `<div>${btScoreChipHtml(btScoreOfAttempt(m), true)} ${badge(m)}</div>` +
          `<div style="margin-top:4px">בחרת <b class="ltr">${esc(m.chosenCall)}</b> — ` +
          `${esc(OUTCOME_HE[m.outcomeClass] || m.outcomeClass)}` +
          (m.gradedCost ? `, עלות ≈ ${(+m.gradedCost).toFixed(1)}` : "") +
          (m.acceptedSet && m.acceptedSet.length
            ? `. מיטבי: <span class="ltr">${esc(m.acceptedSet.join(", "))}</span>` : "") +
          (gone ? ` <span class="go muted">בעיה שהוסרה</span></div>`
                : ` <span class="go">חזור לתרגל &larr;</span></div>`);
        return gone
          ? `<li><div class="missrow">${body}</div></li>`
          : `<li><a class="missrow" href="${routeFor(m.kind || "bidding", m.problemId, {retry: true})}">${body}</a></li>`;
      }).join("") + "</ul></div>"
    : "";
  const weak = weakArea(scen);
  const weakCard = weak
    ? '<div class="card"><b>מה כדאי לתרגל</b>' +
      `<div style="margin:6px 0 8px">הנקודה החלשה שלך: <b>${weak.label}</b> ` +
      `(ציון ממוצע ${Math.round(weak.m)}).</div>` +
      `<a class="big" href="${weak.href}">תרגל ${SESSION_SIZE} כאלה &larr;</a></div>`
    : "";
  const statCard =
    '<div class="card"><div class="statgrid">' +
    `<div class="stat"><b>${n < MIN_N ? "—" : Math.round(avgAll)}</b>` +
    `<span class="muted">${glossHtml("panel", "ציון ממוצע")}</span></div>` +
    `<div class="stat"><b>${streak}</b>` +
    `<span class="muted">${glossHtml("streak", "רצף מיטבי")}</span></div>` +
    `<div class="stat"><b>${n}</b><span class="muted">בעיות שנענו</span></div>` +
    `<div class="stat"><b>${attempts.length}</b><span class="muted">סה"כ ניסיונות</span></div>` +
    '</div></div>';
  const byKindCard = '<div class="card"><b>לפי תרחיש</b>' +
    Object.keys(byKind).map(kd =>
      row(kd === "lead" ? "הובלה" : "הכרזה", byKind[kd])).join("") +
    '</div>';
  const footnote =
    '<p class="footnote">ניסיון ראשון בלבד. לכל החלטה ציון 0–100: ' +
    '100 = הפעולה המיטבית (או שקולה לה), 0 = אפשרות שלא ניצחה באף חלוקה, ' +
    'ובתווך הציון יורד עם העלות מול הפעולה המיטבית — IMP בהכרזה ובהובלת ' +
    'IMP, לקיחות בהובלת MP — בסולם המותאם לתנודת הלוח. ' +
    'ממוצעים מוסתרים עד לפחות ' + MIN_N + ' ניסיונות; הטווח בסוגריים הוא ' +
    'רווח בר־סמך 95% של הממוצע. “מתחת למיטבי” = העלות הגולמית; ' +
    'תשובה מיטבית נספרת כאפס.</p>';
  // three tabbed panels: overview / bidding / leads
  const tabs = [
    ["overview", "סקירה"], ["bidding", "הכרזה"], ["lead", "הובלה"],
  ];
  el.innerHTML =
    '<div class="segctl tabs" role="tablist">' + tabs.map(([id, lbl], i) =>
      `<button role="tab" data-tab="${id}" aria-selected="${i === 0}">${lbl}` +
      `</button>`).join("") + '</div>' +
    `<div class="dtab" data-panel="overview">` +
      statCard + weakCard + trend + byKindCard + missList + footnote + '</div>' +
    `<div class="dtab" data-panel="bidding" hidden>` +
      (scenarioCard("הכרזה", scen.bidding, "bidding") ||
       '<div class="card muted">עוד אין נתוני הכרזה.</div>') + '</div>' +
    `<div class="dtab" data-panel="lead" hidden>` +
      (scenarioCard("הובלה · MP", leadMP, "lead") +
       scenarioCard("הובלה · IMP", leadIMP, "lead", "leadIMP") ||
       "") +
      (leadMP.length || leadIMP.length ? ""
        : '<div class="card muted">עוד אין נתוני הובלה.</div>') + '</div>';
  el.querySelector(".tabs").addEventListener("click", ev => {
    const b = ev.target.closest("button[data-tab]");
    if (!b) return;
    el.querySelectorAll(".tabs button").forEach(x =>
      x.setAttribute("aria-selected", x === b ? "true" : "false"));
    el.querySelectorAll(".dtab").forEach(p =>
      p.hidden = p.dataset.panel !== b.dataset.tab);
  });
}
async function init() {
  try {
    // Learn which problems still exist so deleted ones can be flagged in the
    // miss list (DB-M-9). Cheap: the index is stamp-cached (T10). If it fails,
    // LIVE_IDS stays null and every attempt is treated as live (prior behavior).
    try {
      const idx = await window.BT.fetchIndex();
      LIVE_IDS = new Set((idx.problems || []).map(p => p.id));
    } catch (e) { LIVE_IDS = null; }
    render(await window.BT.allAttempts());
  } catch (e) {
    const el = document.getElementById("dash");
    el.innerHTML = 'לא ניתן לטעון את הנתונים שלך: <span class="en"></span>';
    el.querySelector(".en").textContent = e.message;
  }
}
// refresh the dashboard once the background sync (T4) lands
window.addEventListener("bt-attempts-synced", async () => {
  try { render(await window.BT.allAttempts()); } catch (e) { /* keep prior */ }
});
if (window.BT) window.BT.start(init);
else addEventListener("bt-ready", () => window.BT.start(init), {once: true});
"""


def _dashboard_html() -> str:
    return (
        '<!DOCTYPE html>\n<html lang="he" dir="rtl"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        + _theme_head_script() + '\n'
        '<title>ההתקדמות שלי</title>\n'
        '<link rel="stylesheet" href="' + _CSS_HREF + '">\n<style>' + _DASHBOARD_CSS +
        '</style>\n' + _head_preloads() +
        '\n<script type="module" src="bt-firebase.js"></script></head>'
        '<body data-nav="progress">\n<main id="main" tabindex="-1">\n'
        '<div class="topbar"><a href="index.html">&rarr; דף הבית</a>'
        '<span class="muted">ההתקדמות שלי</span></div>\n'
        '<h1>ההתקדמות שלי</h1>\n<div id="dash" class="muted">טוען&hellip;</div>\n'
        + _taxonomy_script() + '\n<script src="'
        + _SHARED_SRC + '"></script>\n<script>'
        + _DASHBOARD_JS + '</script>\n</body></html>'
    )


# Static ES-module assets copied verbatim next to the generated pages.
_ASSET_FILES = ("firebase-config.js", "bt-logic.js", "bt-firebase.js")


def write_app(out_dir: str | Path) -> None:
    from importlib import resources
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(_index_html(), encoding="utf-8")
    (out / "p.html").write_text(_problem_html(), encoding="utf-8")
    (out / "lead.html").write_text(_lead_html(), encoding="utf-8")
    (out / "dashboard.html").write_text(_dashboard_html(), encoding="utf-8")
    # Emit the shared CSS/JS as external files (T2/PERF-F-4): every page links
    # them instead of inlining ~73 KB, so the browser caches them once and each
    # page's HTML shrinks to a few KB. The Python constants stay the source of
    # truth (keeps them lint/test-visible); this just writes them out. Loaded as
    # a classic <script> before each page's inline bootstrap, so its top-level
    # functions are defined when the page code runs.
    # NOTE: the asset names are stable (not content-hashed). On GitHub Pages
    # (max-age=600, no custom headers) a returning visitor can briefly hold a
    # new page with a cached-stale bt-shared.js within the ~10-min window after
    # a deploy — self-healing, low impact here. Content-hashed filenames
    # (finding PERF-F-5, not in this scope) would eliminate it and enable
    # long-lived caching.
    (out / "app.css").write_text(_CSS, encoding="utf-8")
    (out / "bt-shared.js").write_text(_SHARED_JS, encoding="utf-8")
    web = resources.files("bridge_trainer") / "web"
    for name in _ASSET_FILES:
        (out / name).write_text((web / name).read_text(encoding="utf-8"),
                                encoding="utf-8")
    (out / ".nojekyll").write_text("")
