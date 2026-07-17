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
function pickUnseen(index) {
  const s = store();
  const unseen = index.problems.filter(p => !s[p.id]);
  if (!unseen.length) return null;
  return unseen[Math.floor(Math.random() * unseen.length)].id;
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
"""


def _index_html() -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bridge Bidding Trainer</title>
<style>{_CSS}</style></head><body>
<h1>Bridge Bidding Trainer</h1>
<button class="big" id="deal">Deal me a hand &rarr;</button>
<div class="card" id="stats">Loading the problem pool&hellip;</div>
<p class="muted">Every problem is a random deal, bid to a genuine decision
point, its verdict backed by a full double-dummy simulation. The pool grows
in batches. <a href="#" id="reset">Reset progress</a></p>
<script>{_SHARED_JS}
let INDEX = null;
async function init() {{
  try {{ INDEX = await fetchIndex(); }}
  catch (e) {{
    document.getElementById("stats").textContent =
      "The problem pool is still being generated \\u2014 check back shortly.";
    return;
  }}
  const s = store();
  let done = 0, right = 0;
  for (const p of INDEX.problems) {{
    const rec = s[p.id];
    if (rec) {{ done++; if (rec.correct) right++; }}
  }}
  document.getElementById("stats").innerHTML =
    `<b>${{INDEX.count}}</b> problems in the pool ` +
    `<span class="pill">${{INDEX.count - done}} waiting for you</span><br>` +
    (done ? `Your record: <b>${{right}}</b> / ${{done}} answered` :
            "You haven't answered any yet.");
}}
document.getElementById("deal").onclick = () => {{
  if (!INDEX) return;
  const id = pickUnseen(INDEX);
  if (!id) {{
    alert("You've answered every problem in the pool! " +
          "More will be added in the next batch.");
    return;
  }}
  location.href = "p.html?id=" + encodeURIComponent(id);
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
    const nid = pickUnseen(INDEX);
    if (!nid) {{ location.href = "index.html"; return; }}
    location.href = "p.html?id=" + encodeURIComponent(nid);
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
    (out / ".nojekyll").write_text("")
