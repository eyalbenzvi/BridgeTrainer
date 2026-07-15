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
       background: #fdfdf8; color: #1a1a2e; }
@media (prefers-color-scheme: dark) {
  body { background: #16161e; color: #e4e4ec; }
  .card { background: #1f1f2a; }
  th { background: #2a2a38 !important; }
  td, th { border-color: #444 !important; }
}
h1 { font-size: 1.3em; }
.red { color: #d3455b; }
.card { background: #fff; border: 1px solid #8884; border-radius: 10px;
        padding: 1em; margin: .8em 0; }
table { border-collapse: collapse; width: 100%; display: block;
        overflow-x: auto; }
th, td { border: 1px solid #ccc; padding: .4em .5em; font-size: .85em;
         text-align: left; }
th { background: #f0f0f5; }
a { color: #3673b5; }
.muted { color: #888; font-size: .85em; }
.hand { font-size: 1.5em; line-height: 1.5; letter-spacing: .06em; }
.auction { font-size: 1.15em; margin: .6em 0; }
.candidates { display: flex; flex-direction: column; gap: .6em; margin: 1em 0; }
button.cand { font-size: 1.15em; padding: .8em; border-radius: 10px;
              border: 2px solid #8886; background: inherit; color: inherit;
              cursor: pointer; text-align: left; }
button.cand.chosen { border-color: #3673b5; }
button.cand.good { border-color: #2c9e5f; background: #2c9e5f22; }
button.cand.bad { border-color: #d3455b; background: #d3455b22; }
#verdict { display: none; }
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
function auctionHtml(p) {
  const seats = ["N","E","S","W"];
  const mine = p.seat, partner = seats[(seats.indexOf(mine) + 2) % 4];
  let seat = p.dealer;
  const parts = p.auction.map(tok => {
    const t = (seat === mine || seat === partner) ? tok : `(${tok})`;
    seat = seats[(seats.indexOf(seat) + 1) % 4];
    return t;
  });
  return parts.join(" \\u2013 ") + " \\u2013 ?";
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
<div class="candidates" id="cands"></div>
<div id="verdict" class="card">
<div class="headline" id="headline"></div>
<div id="fog"></div>
<table id="vtable"></table>
<p class="muted">Corrected view (single-dummy smeared). EV is IMPs vs the
candidate's toughest rival. <span id="quality"></span></p>
<button class="big" id="next">Next deal &rarr;</button>
<details><summary class="muted">Raw double-dummy view</summary>
<table id="rtable"></table></details>
</div>
<script>{_SHARED_JS}
let P = null, INDEX = null;
function rowsHtml(rows) {{
  let h = "<tr><th>Action</th><th>EV vs best alt</th><th>P(gain)</th>" +
          "<th>P(loss)</th></tr>";
  for (const c of rows) {{
    h += `<tr><td>${{c.action}}</td><td>${{c.ev >= 0 ? "+" : ""}}${{c.ev}}` +
         ` \\u00b1 ${{c.ci}} vs ${{c.vs}}</td>` +
         `<td>${{Math.round(c.p_gain * 100)}}%</td>` +
         `<td>${{Math.round(c.p_loss * 100)}}%</td></tr>`;
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
  document.getElementById("rtable").innerHTML = rowsHtml(v.raw);
  const q = P.quality || {{}};
  document.getElementById("quality").textContent =
    `Simulated ${{P.generator.n_deals}} layouts (ESS ${{Math.round(q.ess || 0)}}).`;
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
  document.getElementById("meta").textContent =
    `Dealer ${{P.dealer}} \\u00b7 Vul ${{P.vul}} \\u00b7 IMPs \\u00b7 you are ${{P.seat}}`;
  document.getElementById("problem").innerHTML =
    `<div class="card"><div class="auction">${{auctionHtml(P)}}</div>` +
    `<div class="hand">${{handHtml(P.hand)}}</div></div>`;
  const cands = document.getElementById("cands");
  for (const c of P.candidates) {{
    const b = document.createElement("button");
    b.className = "cand"; b.dataset.action = c;
    b.textContent = c === "P" ? "Pass" : (c === "X" ? "Double" : c);
    b.onclick = () => choose(b);
    cands.appendChild(b);
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
