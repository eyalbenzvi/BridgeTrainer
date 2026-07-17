"""The static web app that consumes the problem pool.

Two pages, no build step, no framework:
  index.html  — "Deal me a hand" (random unseen problem) + progress stats
  p.html?id=X — renders one problem document fetched from data/problems/X.json

Answers live in localStorage under key "bt_pool" ({id: {answer, correct,
ts}}). The pool itself is data/ next to these pages; the producer appends to
it continuously, so the app sees new problems without any redeploy.
"""
from __future__ import annotations

from pathlib import Path

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font-family: -apple-system, "Segoe UI", Roboto, Georgia, serif;
       max-width: 640px; margin: 0 auto; padding: 1em;
       background: var(--bg); color: var(--fg);
       --bg: #fdfdf8; --fg: #1a1a2e; --card: #ffffff;
       --th: #f0f0f5; --border: #ccc; }
@media (prefers-color-scheme: dark) {
  body { --bg: #16161e; --fg: #e4e4ec; --card: #1f1f2a;
         --th: #2a2a38; --border: #444; }
}
h1 { font-size: 1.3em; }
.red { color: #d3455b; }
.card { background: var(--card); color: var(--fg);
        border: 1px solid #8884; border-radius: 10px;
        padding: 1em; margin: .8em 0; }
table { border-collapse: collapse; width: 100%; display: block;
        overflow-x: auto; }
th, td { border: 1px solid var(--border); padding: .4em .5em;
         font-size: .85em; text-align: left; }
th { background: var(--th); }
a { color: #3673b5; }
.muted { color: #888; font-size: .85em; }
.hand { font-size: 1.5em; line-height: 1.5; letter-spacing: .06em; }
/* Bidding diagram: explicit colors in BOTH themes so it never inherits an
   unreadable background; one round of four calls per row; You act last. */
table.bidding { display: table; width: 100%; margin: .2em 0 .8em;
                border-collapse: collapse; background: #ffffff;
                color: #16161e; font-size: 1.1em; border-radius: 8px; }
table.bidding th, table.bidding td { border: 1px solid #b9b9c4;
  text-align: center; padding: .45em .2em; width: 25%; font-size: 1em; }
table.bidding th { background: #e8e8f0; color: #333; font-weight: 600; }
table.bidding th small { font-weight: normal; color: #777; }
table.bidding th.me { background: #3673b5; color: #fff; }
table.bidding td.them { color: #8a5200; background: #fff7e8; }
table.bidding td.us { color: #16161e; font-weight: 600; }
table.bidding td.dim { color: #aaa; }
table.bidding td.turn { background: #3673b5; color: #fff;
                        font-weight: bold; font-size: 1.15em; }
@media (prefers-color-scheme: dark) {
  table.bidding { background: #23232e; color: #f2f2f6;
                  border-color: #555; }
  table.bidding th, table.bidding td { border-color: #4a4a58; }
  table.bidding th { background: #30303e; color: #d8d8e2; }
  table.bidding td.them { color: #ffc46b; background: #2b2620; }
  table.bidding td.us { color: #f2f2f6; }
  table.bidding td.dim { color: #666; }
}
table.bidding .red { color: #d3455b; }
.candidates { display: flex; flex-direction: column; gap: .6em; margin: 1em 0; }
button.cand { font-size: 1.15em; padding: .8em; border-radius: 10px;
              border: 2px solid #8886; background: inherit; color: inherit;
              cursor: pointer; text-align: left; }
button.cand.chosen { border-color: #3673b5; }
button.cand.good { border-color: #2c9e5f; background: #2c9e5f22; }
button.cand.bad { border-color: #d3455b; background: #d3455b22; }
#verdict { display: none; }
#explanation { white-space: pre-line; }
.notes ul { margin: 8px 0 0; padding-left: 18px; }
.notes li { margin: 7px 0; line-height: 1.35; }
.notes summary { cursor: pointer; }
.headline { font-size: 1.2em; font-weight: bold; margin: .4em 0; }
.fog { background: #ffdd5733; border: 1px solid #cca42f88; border-radius: 8px;
       padding: .6em .8em; margin: .6em 0; }
a.big, button.big { display: block; width: 100%; text-align: center;
  font-size: 1.25em; padding: .9em; border-radius: 12px; margin: 1em 0;
  background: #3673b5; color: #fff; text-decoration: none; font-weight: bold;
  border: none; cursor: pointer; }
.topbar { display: flex; justify-content: space-between; align-items: baseline; }
.pill { display: inline-block; border-radius: 999px; padding: .1em .7em;
        font-size: .8em; border: 1px solid #8886; margin-left: .3em; }
details { margin: .8em 0; }
/* opening-lead card grid: the hand IS the answer input, one row per suit */
.leadgrid { margin: 1em 0; }
.suitrow { display: flex; align-items: center; flex-wrap: wrap; gap: .4em;
           margin: .35em 0; }
.suitrow .suit { font-size: 1.4em; width: 1.3em; text-align: center; }
button.cardbtn { min-width: 2.6em; min-height: 2.75em; font-size: 1.15em;
  padding: .5em .3em; border-radius: 8px; border: 2px solid #8886;
  background: inherit; color: inherit; cursor: pointer; }
button.cardbtn.chosen { border-color: #3673b5; }
button.cardbtn.good { border-color: #2c9e5f; background: #2c9e5f22; }
button.cardbtn.bad { border-color: #d3455b; background: #d3455b22; }
/* clickable calls in a completed auction */
table.bidding td.biddable { cursor: pointer; text-decoration: underline dotted;
  text-underline-offset: 3px; }
table.bidding td.lead { background: #3673b5; color: #fff; }
#bid-meaning { min-height: 1.3em; margin: .3em 0 0; }
/* reveal: horizontal bars instead of a wall of decimals */
.bar-wrap { display: flex; align-items: center; gap: .5em; margin: .35em 0; }
.bar-label { width: 3em; font-size: 1.05em; }
.bar-track { flex: 1; background: #8882; border-radius: 6px; height: 1.25em; }
.bar-fill { background: #3673b5; height: 100%; border-radius: 6px; }
.bar-fill.good { background: #2c9e5f; }
.bar-val { width: 5.5em; text-align: right; font-size: .85em;
           font-variant-numeric: tabular-nums; }
/* segmented mode toggle on the home page */
.seg { display: inline-flex; border: 1px solid #8886; border-radius: 999px;
       overflow: hidden; margin: .2em 0 .6em; }
.seg button { border: none; background: inherit; color: inherit;
  padding: .45em 1em; cursor: pointer; font-size: .95em; }
.seg button.on { background: #3673b5; color: #fff; }
"""

_SHARED_JS = """
const KEY = "bt_pool";
function store() { try { return JSON.parse(localStorage.getItem(KEY)) || {}; }
                   catch (e) { return {}; } }
function saveStore(s) { localStorage.setItem(KEY, JSON.stringify(s)); }
async function fetchIndex() {
  const r = await fetch("data/index.json", {cache: "no-cache"});
  if (!r.ok) throw new Error("no pool index");
  return r.json();
}
function pickUnseen(index, mode) {
  const s = store();
  let unseen = index.problems.filter(p => !s[p.id]);
  if (mode && mode !== "either")
    unseen = unseen.filter(p => (p.type || "bidding") === mode);
  if (!unseen.length) return null;
  return unseen[Math.floor(Math.random() * unseen.length)];
}
function problemUrl(e) {
  const page = (e.type || "bidding") === "lead" ? "lead.html" : "p.html";
  return page + "?id=" + encodeURIComponent(e.id);
}
const SUIT_HTML = {S: "\\u2660", H: '<span class="red">\\u2665</span>',
                   D: '<span class="red">\\u2666</span>', C: "\\u2663"};
function handHtml(hand) {
  const parts = hand.split(".");
  return ["S","H","D","C"].map((s, i) =>
    `${SUIT_HTML[s]} ${parts[i] || "\\u2014"}`).join("<br>");
}
function callHtml(tok) {
  if (tok === "P") return "Pass";
  if (tok === "X") return "X";
  if (tok === "XX") return "XX";
  const denom = tok.slice(1);
  if (denom === "NT") return tok;
  return tok[0] + SUIT_HTML[denom];
}
function auctionTableHtml(p) {
  const seats = ["N","E","S","W"];
  const hero = p.seat, partner = seats[(seats.indexOf(hero) + 2) % 4];
  // Columns: LHO, partner, RHO, You — your decision closes each row.
  const order = [1, 2, 3, 0].map(
    i => seats[(seats.indexOf(hero) + i) % 4]);
  const head = order.map(s => {
    if (s === hero) return "<th class=me>You</th>";
    if (s === partner) return `<th class=us>${s}<br><small>pard</small></th>`;
    return `<th class=them>${s}</th>`;
  }).join("");
  const cells = [];
  for (let i = 0; i < order.indexOf(p.dealer); i++)
    cells.push('<td class=dim>\\u2013</td>');
  let seat = p.dealer;
  for (const tok of p.auction) {
    const cls = (seat === hero || seat === partner) ? "us" : "them";
    cells.push(`<td class=${cls}>${callHtml(tok)}</td>`);
    seat = seats[(seats.indexOf(seat) + 1) % 4];
  }
  cells.push('<td class=turn>?</td>');
  while (cells.length % 4) cells.push("<td></td>");
  let rows = "";
  for (let i = 0; i < cells.length; i += 4)
    rows += "<tr>" + cells.slice(i, i + 4).join("") + "</tr>";
  return `<table class="bidding"><tr>${head}</tr>${rows}</table>`;
}
function cardHtml(tok) {  // "SK" -> spade glyph + rank (T shown as 10)
  const r = tok[1] === "T" ? "10" : tok[1];
  return SUIT_HTML[tok[0]] + " " + r;
}
// A COMPLETE auction in true seat order N-E-S-W. Real calls carry a
// data-idx so the page can make every bid clickable (its meaning lives in
// P.explanations.auction[idx]). The player on lead gets the blue column.
function completeAuctionTableHtml(P) {
  const seats = ["N", "E", "S", "W"];
  const dummy = seats[(seats.indexOf(P.declarer) + 2) % 4];
  const head = seats.map(s => {
    if (s === P.leader) return `<th class=me>${s}<br><small>lead</small></th>`;
    if (s === P.declarer) return `<th>${s}<br><small>decl</small></th>`;
    if (s === dummy) return `<th>${s}<br><small>dummy</small></th>`;
    return `<th>${s}</th>`;
  }).join("");
  const meanings = (P.explanations && P.explanations.auction) || [];
  const cells = [];
  for (let i = 0; i < seats.indexOf(P.dealer); i++)
    cells.push('<td class=dim>\\u2013</td>');
  P.auction.forEach((tok, gi) => {
    const has = meanings[gi] && meanings[gi].text;
    const cls = has ? "biddable" : "";
    cells.push(`<td class="${cls}" data-idx="${gi}">${callHtml(tok)}</td>`);
  });
  while (cells.length % 4) cells.push("<td></td>");
  let rows = "";
  for (let i = 0; i < cells.length; i += 4)
    rows += "<tr>" + cells.slice(i, i + 4).join("") + "</tr>";
  return `<table class="bidding"><tr>${head}</tr>${rows}</table>`;
}
"""


def _index_html() -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bridge Trainer</title>
<style>{_CSS}</style></head><body>
<h1>Bridge Trainer</h1>
<div class="seg" id="mode" role="group" aria-label="Problem type">
  <button data-mode="bidding">Bidding</button>
  <button data-mode="lead">Opening lead</button>
  <button data-mode="either">Either</button>
</div>
<button class="big" id="deal">Deal me a hand &rarr;</button>
<div class="card" id="stats">Loading the problem pool&hellip;</div>
<p class="muted">Each problem is a random deal backed by a full double-dummy
simulation: bidding problems ask for your call at a genuine decision point;
opening-lead problems ask which card to lead. The pool grows in batches.
<a href="#" id="reset">Reset progress</a></p>
<script>{_SHARED_JS}
const MODE_KEY = "bt_mode";
let INDEX = null;
let MODE = localStorage.getItem(MODE_KEY) || "either";
function labelFor(m) {{
  return m === "bidding" ? "Deal me a bidding problem \\u2192"
       : m === "lead" ? "Deal me a lead problem \\u2192"
       : "Deal me a hand \\u2192";
}}
function paintMode() {{
  document.querySelectorAll("#mode button").forEach(b =>
    b.classList.toggle("on", b.dataset.mode === MODE));
  document.getElementById("deal").innerHTML = labelFor(MODE);
  renderStats();
}}
function renderStats() {{
  if (!INDEX) return;
  const s = store();
  const bucket = {{bidding: {{n: 0, done: 0, right: 0}},
                   lead: {{n: 0, done: 0, right: 0}}}};
  for (const p of INDEX.problems) {{
    const t = (p.type || "bidding");
    if (!bucket[t]) bucket[t] = {{n: 0, done: 0, right: 0}};
    bucket[t].n++;
    const rec = s[p.id];
    if (rec) {{ bucket[t].done++; if (rec.correct) bucket[t].right++; }}
  }}
  const line = (name, b) => b.n ?
    `${{name}}: <b>${{b.right}}</b> / ${{b.done}} answered ` +
    `<span class="pill">${{b.n - b.done}} left</span>` : "";
  const rows = [line("Bidding", bucket.bidding), line("Opening lead", bucket.lead)]
    .filter(Boolean).join("<br>");
  document.getElementById("stats").innerHTML =
    `<b>${{INDEX.count}}</b> problems in the pool<br>` +
    (rows || "You haven't answered any yet.");
}}
async function init() {{
  try {{ INDEX = await fetchIndex(); }}
  catch (e) {{
    document.getElementById("stats").textContent =
      "The problem pool is still being generated \\u2014 check back shortly.";
    return;
  }}
  paintMode();
}}
document.querySelectorAll("#mode button").forEach(b => b.onclick = () => {{
  MODE = b.dataset.mode; localStorage.setItem(MODE_KEY, MODE); paintMode();
}});
document.getElementById("deal").onclick = () => {{
  if (!INDEX) return;
  const e = pickUnseen(INDEX, MODE);
  if (!e) {{
    alert("You've answered every problem in this mode! " +
          "Try another mode or check back after the next batch.");
    return;
  }}
  location.href = problemUrl(e);
}};
document.getElementById("reset").onclick = () => {{
  if (confirm("Clear all recorded answers?")) {{
    localStorage.removeItem(KEY); location.reload();
  }}
  return false;
}};
init();
</script>
</body></html>"""


def _problem_html() -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bidding problem</title>
<style>{_CSS}</style></head><body>
<div class="topbar">
<a href="index.html">&larr; home</a>
<span class="muted" id="meta"></span>
</div>
<div id="problem"></div>
<details class="card notes" id="auction-notes" style="display:none">
<summary class="muted">What the auction showed, bid by bid</summary>
<ul id="auction-notes-list"></ul></details>
<details class="card notes" id="option-notes" style="display:none">
<summary class="muted">What would each bid show?</summary>
<ul id="option-notes-list"></ul></details>
<div class="candidates" id="cands"></div>
<div id="verdict" class="card">
<div class="headline" id="headline"></div>
<div id="fog"></div>
<p id="explanation"></p>
<table id="vtable"></table>
<p class="muted">Corrected view (single-dummy smeared). EV is IMPs vs the
candidate's toughest rival. <span id="quality"></span></p>
<div class="muted" id="source"></div>
<button class="big" id="next">Next deal &rarr;</button>
<details id="meanings-box"><summary class="muted">Assumed meanings of the
auction</summary><ul id="meanings"></ul></details>
<details><summary class="muted">Raw double-dummy view</summary>
<table id="rtable"></table></details>
</div>
<script>{_SHARED_JS}
let P = null, INDEX = null;
function rowsHtml(rows) {{
  let h = "<tr><th>Action</th><th>EV (IMPs)</th><th>Wins</th>" +
          "<th>Loses</th><th>No difference</th></tr>";
  for (const c of rows) {{
    const push = c.p_push !== undefined ? c.p_push
               : Math.max(0, 1 - c.p_gain - c.p_loss);
    h += `<tr><td>${{c.action}}</td><td>${{c.ev >= 0 ? "+" : ""}}${{c.ev}}` +
         ` \\u00b1 ${{c.ci}} vs ${{c.vs}}</td>` +
         `<td>${{Math.round(c.p_gain * 100)}}%</td>` +
         `<td>${{Math.round(c.p_loss * 100)}}%</td>` +
         `<td>${{Math.round(push * 100)}}%</td></tr>`;
  }}
  return h;
}}
function reveal(chosen) {{
  const v = P.verdict;
  document.querySelectorAll("button.cand").forEach(b => {{
    const a = b.dataset.action;
    if (v.accepted.includes(a)) b.classList.add("good");
    else if (a === chosen) b.classList.add("bad");
    if (a === chosen) b.classList.add("chosen");
    b.disabled = true;
  }});
  const ok = v.accepted.includes(chosen);
  let head = ok ? "\\u2713 Good call" : "\\u2717 Not this time";
  if (v.toss_up) head += " \\u2014 toss-up: " + v.accepted.join(", ");
  document.getElementById("headline").textContent = head;
  if (v.fog) document.getElementById("fog").innerHTML =
    '<div class="fog">\\u26a0 Raw and corrected verdicts disagree \\u2014 ' +
    'inside the DD fog. Trust this one less.</div>';
  document.getElementById("vtable").innerHTML = rowsHtml(v.corrected);
  const rbox = document.getElementById("rtable");
  if (v.raw && v.raw.length) rbox.innerHTML = rowsHtml(v.raw);
  else if (rbox.closest("details")) rbox.closest("details").style.display = "none";
  const q = P.quality || {{}};
  document.getElementById("quality").textContent =
    `Simulated ${{P.generator.n_deals}} layouts (ESS ${{Math.round(q.ess || 0)}}).`;
  if (P.explanation)
    document.getElementById("explanation").textContent = P.explanation;
  if (P.source) {{
    const s = P.source;
    document.getElementById("source").innerHTML =
      `Real deal: <b>${{s.teams}}</b>, ${{s.event}}, board ${{s.board}}.`;
  }}
  if (P.meanings && P.meanings.length) {{
    document.getElementById("meanings").innerHTML = P.meanings.map(m =>
      `<li><b>${{m.seat}}</b>: ${{m.meaning}}</li>`).join("");
  }} else {{
    document.getElementById("meanings-box").style.display = "none";
  }}
  document.getElementById("verdict").style.display = "block";
}}
function choose(btn) {{
  const s = store();
  if (s[P.id]) return;
  const action = btn.dataset.action;
  s[P.id] = {{ answer: action,
               correct: P.verdict.accepted.includes(action), ts: Date.now() }};
  saveStore(s);
  reveal(action);
}}
async function init() {{
  const id = new URLSearchParams(location.search).get("id");
  const r = await fetch("data/problems/" + encodeURIComponent(id) + ".json");
  if (!r.ok) {{ document.getElementById("problem").textContent =
                "Problem not found."; return; }}
  P = await r.json();
  // --- normalize ben-forge records (engine pool) to the page's shape ---
  if (P.generator && P.generator.engine) {{
    const v = P.verdict;
    if (!Array.isArray(v.accepted))
      v.accepted = v.toss_up ? v.toss_up_set : [v.accepted];
    v.fog = v.fog || (v.flags || []).includes("dd_fog");
    if (v.table && !v.corrected) {{
      const top = v.table[0] ? v.table[0].bid : "";
      v.corrected = v.table.map(r => ({{ action: r.bid,
        ev: r.ev_imp_vs_top, ci: r.ci, vs: r.vs || top,
        p_gain: r.p_gain,
        p_loss: r.p_loss !== undefined ? r.p_loss
              : Math.max(0, 1 - r.p_gain - r.p_push),
        p_push: r.p_push }}));
      v.raw = [];
    }}
    P.generator.n_deals = P.generator.n_deals || P.generator.samples;
    if (P.explanations) {{
      if (!P.explanation)
        P.explanation = (P.explanations.options || []).map(o => o.text)
          .join("\\n\\n") + (P.explanations.note
            ? "\\n\\n(" + P.explanations.note + ")" : "");
      if (!P.auction_notes)
        P.auction_notes = (P.explanations.stem || []).map(
          e => e.text.replace(/^[^:]*:\s*/, ""));
      if (!P.option_notes && P.explanations.options) {{
        P.option_notes = {{}};
        for (const o of P.explanations.options)
          P.option_notes[o.bid] =
            o.text.split(". ")[0].replace(/^[^\\u2014]*\\u2014\\s*/, "") + ".";
      }}
    }}
  }}
  document.getElementById("meta").textContent =
    `Dealer ${{P.dealer}} \\u00b7 Vul ${{P.vul}} \\u00b7 IMPs \\u00b7 you are ${{P.seat}}` +
    (P.category && P.category !== "other" ? ` \\u00b7 ${{P.category}}` : "");
  document.getElementById("problem").innerHTML =
    `<div class="card">${{auctionTableHtml(P)}}` +
    `<div class="hand">${{handHtml(P.hand)}}</div></div>`;
  const cands = document.getElementById("cands");
  for (const cand of P.candidates) {{
    const c = cand.call || cand;
    const b = document.createElement("button");
    b.className = "cand"; b.dataset.action = c;
    b.innerHTML = c === "X" ? "Double" : callHtml(c);
    b.onclick = () => choose(b);
    cands.appendChild(b);
  }}
  if (P.auction_notes && P.auction_notes.length === P.auction.length) {{
    const seats = ["N", "E", "S", "W"];
    let seat = P.dealer, items = "";
    P.auction.forEach((tok, i) => {{
      const who = seat === P.seat ? "You" : seat;
      if (P.auction_notes[i])
        items += `<li><b>${{who}} ${{callHtml(tok)}}</b> \\u2014 ` +
                 `${{P.auction_notes[i]}}</li>`;
      seat = seats[(seats.indexOf(seat) + 1) % 4];
    }});
    document.getElementById("auction-notes-list").innerHTML = items;
    document.getElementById("auction-notes").style.display = "block";
  }}
  if (P.option_notes) {{
    document.getElementById("option-notes-list").innerHTML =
      P.candidates.map(cand => {{
        const c = cand.call || cand;
        const n = P.option_notes[c];
        if (!n) return "";
        const shows = n.shows || n;
        const pline = n.partner ? `<br><small class="muted">Partner: ` +
                                  `${{n.partner}}</small>` : "";
        return `<li><b>${{c === "X" ? "Double" : callHtml(c)}}</b> \\u2014 ` +
               `${{shows}}${{pline}}</li>`;
      }}).join("");
    document.getElementById("option-notes").style.display = "block";
  }}
  document.getElementById("next").onclick = async () => {{
    if (!INDEX) INDEX = await fetchIndex();
    const e = pickUnseen(INDEX, "bidding");
    if (!e) {{ location.href = "index.html"; return; }}
    location.href = problemUrl(e);
  }};
  const prev = store()[P.id];
  if (prev) reveal(prev.answer);
}}
init();
</script>
</body></html>"""


def _lead_html() -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Opening lead problem</title>
<style>{_CSS}</style></head><body>
<div class="topbar">
<a href="index.html">&larr; home</a>
<span class="muted" id="meta"></span>
</div>
<div id="problem"></div>
<div class="candidates leadgrid" id="grid"></div>
<div id="verdict" class="card">
<div class="headline" id="headline"></div>
<p class="muted" id="subhead"></p>
<div id="bars"></div>
<p id="lead-expl" style="white-space:pre-line"></p>
<div class="muted" id="difficulty"></div>
<button class="big" id="next">Next deal &rarr;</button>
<details><summary class="muted">All 13 leads, ranked</summary>
<table id="ltable"></table>
<p class="muted">Average defensive tricks over a full double-dummy
simulation. Cards tied for the most are all correct.</p></details>
<details><summary class="muted">The full deal</summary>
<div id="fulldeal"></div></details>
</div>
<script>{_SHARED_JS}
let P = null, INDEX = null;
function wireAuction() {{
  const meanings = (P.explanations && P.explanations.auction) || [];
  const box = document.getElementById("bid-meaning");
  document.querySelectorAll("#problem td.biddable").forEach(td => {{
    td.onclick = () => {{
      const m = meanings[+td.dataset.idx];
      document.querySelectorAll("#problem td.lead").forEach(
        x => x.classList.remove("lead"));
      td.classList.add("lead");
      box.innerHTML = m && m.text
        ? `<b>${{m.seat}} ${{callHtml(m.call)}}</b> \\u2014 ${{m.text}}`
        : "";
    }};
  }});
}}
function gridHtml(hand) {{
  const parts = hand.split(".");
  return ["S", "H", "D", "C"].map((s, i) => {{
    const btns = (parts[i] || "").split("").map(r => {{
      const tok = s + r, face = r === "T" ? "10" : r;
      return `<button class="cardbtn" data-action="${{tok}}">${{face}}</button>`;
    }}).join("");
    return `<div class="suitrow"><span class="suit">${{SUIT_HTML[s]}}</span>`
         + (btns || '<span class="muted">\\u2014</span>') + `</div>`;
  }}).join("");
}}
function avgOf(card) {{
  const r = P.verdict.table.find(x => x.card === card);
  return r ? r.avg_def_tricks : 0;
}}
function barsHtml(chosen) {{
  const table = P.verdict.table, acc = P.verdict.accepted;
  const maxv = table.length ? table[0].avg_def_tricks : 1;
  const seen = new Set(), picked = [];
  for (const r of table) {{                 // best card of each suit
    if (!seen.has(r.card[0])) {{ seen.add(r.card[0]); picked.push(r.card); }}
  }}
  if (!picked.includes(chosen)) picked.push(chosen);   // always show yours
  return picked.map(card => {{
    const v = avgOf(card), good = acc.includes(card);
    const pct = maxv > 0 ? Math.max(4, Math.round(v / maxv * 100)) : 0;
    const you = card === chosen ? ' <span class="muted">(your lead)</span>' : "";
    return `<div class="bar-wrap"><span class="bar-label">${{cardHtml(card)}}</span>`
      + `<span class="bar-track"><span class="bar-fill ${{good ? "good" : ""}}"`
      + ` style="width:${{pct}}%"></span></span>`
      + `<span class="bar-val">${{v.toFixed(2)}} tr${{you}}</span></div>`;
  }}).join("");
}}
function reveal(chosen) {{
  const v = P.verdict, acc = v.accepted;
  document.querySelectorAll("button.cardbtn").forEach(b => {{
    const a = b.dataset.action;
    if (acc.includes(a)) b.classList.add("good");
    else if (a === chosen) b.classList.add("bad");
    if (a === chosen) b.classList.add("chosen");
    b.disabled = true;
  }});
  const ok = acc.includes(chosen);
  document.getElementById("headline").innerHTML = ok
    ? "\\u2713 Best lead \\u2014 " + cardHtml(chosen)
    : "\\u2717 Better was " + acc.map(cardHtml).join(" or ");
  document.getElementById("subhead").innerHTML = acc.length > 1
    ? "Equally best: " + acc.map(cardHtml).join(", ")
    : "";
  document.getElementById("bars").innerHTML = barsHtml(chosen);
  const notes = (P.explanations && P.explanations.cards) || [];
  const noteFor = c => (notes.find(x => x.card === c) || {{}}).text || "";
  let expl = noteFor(acc[0]);
  if (!ok) {{ const y = noteFor(chosen); if (y) expl += "\\n\\n" + y; }}
  document.getElementById("lead-expl").textContent = expl;
  document.getElementById("difficulty").textContent =
    "Difficulty " + (P.difficulty || "?") + "/5";
  let rt = "<tr><th>Card</th><th>Avg def. tricks</th><th>vs best</th>" +
           "<th>BEN</th></tr>";
  for (const r of v.table) {{
    const g = acc.includes(r.card) ? ' style="font-weight:bold"' : "";
    rt += `<tr${{g}}><td>${{cardHtml(r.card)}}</td>` +
          `<td>${{r.avg_def_tricks.toFixed(2)}}</td>` +
          `<td>${{r.vs_best >= 0 ? "+" : ""}}${{r.vs_best.toFixed(2)}}</td>` +
          `<td>${{Math.round((r.ben_softmax || 0) * 100)}}%</td></tr>`;
  }}
  document.getElementById("ltable").innerHTML = rt;
  if (P.full_deal) {{
    document.getElementById("fulldeal").innerHTML = ["N", "E", "S", "W"]
      .map(s => `<div><b>${{s}}</b>: ${{handHtml(P.full_deal[s])}}</div>`)
      .join("<br>");
  }}
  document.getElementById("verdict").style.display = "block";
}}
function choose(btn) {{
  const s = store();
  if (s[P.id]) return;
  const a = btn.dataset.action;
  s[P.id] = {{ answer: a, correct: P.verdict.accepted.includes(a),
               ts: Date.now() }};
  saveStore(s);
  reveal(a);
}}
async function init() {{
  const id = new URLSearchParams(location.search).get("id");
  const r = await fetch("data/problems/" + encodeURIComponent(id) + ".json");
  if (!r.ok) {{ document.getElementById("problem").textContent =
                "Problem not found."; return; }}
  P = await r.json();
  document.getElementById("meta").innerHTML =
    `Contract ${{callHtml(P.contract.slice(0, P.contract[1] === "N" ? 3 : 2))}}`
    + ` by ${{P.declarer}} \\u00b7 Vul ${{P.vul}} \\u00b7 you lead (${{P.leader}})`;
  document.getElementById("problem").innerHTML =
    `<div class="card">${{completeAuctionTableHtml(P)}}` +
    `<p class="muted">Tap any call to see what it showed.</p>` +
    `<p id="bid-meaning"></p>` +
    `<div class="hand">${{handHtml(P.hand)}}</div>` +
    `<p class="muted">Tap a card to lead it.</p></div>`;
  wireAuction();
  const grid = document.getElementById("grid");
  grid.innerHTML = gridHtml(P.hand);
  grid.querySelectorAll("button.cardbtn").forEach(
    b => b.onclick = () => choose(b));
  document.getElementById("next").onclick = async () => {{
    if (!INDEX) INDEX = await fetchIndex();
    const e = pickUnseen(INDEX, "lead");
    if (!e) {{ location.href = "index.html"; return; }}
    location.href = problemUrl(e);
  }};
  const prev = store()[P.id];
  if (prev) reveal(prev.answer);
}}
init();
</script>
</body></html>"""


def write_app(out_dir: str | Path) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(_index_html(), encoding="utf-8")
    (out / "p.html").write_text(_problem_html(), encoding="utf-8")
    (out / "lead.html").write_text(_lead_html(), encoding="utf-8")
    (out / ".nojekyll").write_text("")
