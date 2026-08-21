"""The analyze page served by the LOCAL server (analysis/server.py).

The interactive input components (52-card picker, bidding box, auction
legality, overrides, decision points) live in the shared asset
web/bt-analyze-ui.js, used verbatim by the deployed site's analyze.html as
well — one implementation, two submission paths. This page's own script is
only the local glue: POST /api/analyze and render the returned reports.
"""
from __future__ import annotations

PAGE = """<!DOCTYPE html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ניתוח הכרזה — BridgeTrainer</title>
<style>
:root { --felt:#2E6B4F; --felt-deep:#24573F; --card:#fff; --fg:#1C2B24;
  --muted:#5C6B62; --line:#D9E0DA; --accent:#2B6CB0; --accent-tint:#2B6CB014;
  --he-red:#C8102E; --win:#1A7A43; --gold:#EAB84C;
  --warn-bg:#FDF3DF; --warn-fg:#7A5312; --warn-line:#E3C87F; }
* { box-sizing:border-box; }
body { font-family:"Segoe UI","Heebo",Arial,"Noto Sans Hebrew",sans-serif;
  max-width:760px; margin:0 auto; padding:14px; color:var(--fg);
  background:radial-gradient(120% 90% at 50% 0%,var(--felt),var(--felt-deep))
    fixed; font-size:15px; line-height:1.5; }
h1 { color:#fff; font-size:21px; margin:.3em 0; }
h2 { font-size:16px; margin:0 0 10px; }
.card { background:var(--card); border-radius:14px; padding:14px 16px;
  margin:12px 0; box-shadow:0 1px 3px #0003; }
.red { color:var(--he-red); }
.ltr { direction:ltr; unicode-bidi:isolate; }
button { font:inherit; cursor:pointer; border-radius:8px;
  border:1px solid var(--line); background:#fff; padding:4px 10px; }
button:disabled { opacity:.35; cursor:default; }
button.primary { background:var(--accent); color:#fff; border:none;
  font-weight:700; padding:10px 22px; font-size:16px; }
select,input[type=text],input[type=number] { font:inherit; padding:4px 8px;
  border:1px solid var(--line); border-radius:8px; }
input[type=number] { width:64px; }
label { margin-inline-end:6px; }
.row { display:flex; flex-wrap:wrap; gap:10px 18px; align-items:center;
  margin:6px 0; }
.suitrow { display:flex; align-items:center; gap:4px; margin:4px 0;
  direction:ltr; }
.suitrow .glyph { width:22px; font-size:18px; text-align:center; }
.suitrow .cnt { width:56px; direction:rtl; font-size:11px;
  color:var(--muted); text-align:right; }
.cardbtn { width:34px; height:40px; border-radius:6px; font-weight:700;
  font-size:14px; padding:0; border:1px solid var(--line); background:#fff; }
.cardbtn.sel { background:var(--accent); color:#fff;
  border-color:var(--accent); }
#handsum { font-weight:600; }
#handsum.bad { color:var(--he-red); }
.bbox { direction:ltr; display:grid; grid-template-columns:repeat(5,1fr);
  gap:4px; max-width:330px; }
.bbox button { height:36px; font-weight:700; padding:0; }
.ss { color:#2838C8; } .sh { color:#C8102E; }
.sd { color:#BC5A00; } .sc { color:#1A7A1A; }
.ss,.sh,.sd,.sc { font-variant-emoji:text; }
table.bidding { width:100%; max-width:440px; border-collapse:collapse;
  font-size:16px; border-radius:10px; overflow:hidden; direction:ltr; }
table.bidding th { padding:5px 4px 4px; font-weight:600; font-size:13px;
  width:25%; border:0; }
table.bidding th.v { background:#B3252F; color:#fff; }
table.bidding th.nv { background:#E6F4EA; color:#1C5C34; }
table.bidding th.me { box-shadow:inset 0 -3px 0 #EAB84C; }
table.bidding th small { display:block; font-weight:400; font-size:10px; }
table.bidding th sup.d { font-size:9px; border:1px solid currentColor;
  border-radius:999px; padding:0 3px; margin-left:3px; }
table.bidding td { text-align:center; padding:0;
  border-top:1px solid #D9E0DA; }
table.bidding td .call { display:block; min-height:32px; line-height:32px;
  font-weight:600; }
table.bidding td.turn { background:#FdF6E3; font-weight:700;
  outline:2px solid #EAB84C; }
.hand-preview { direction:ltr; display:inline-block; margin:10px 2px;
  padding:8px 14px; border:1px solid #D9E0DA; border-radius:10px;
  background:#fff; font-weight:600; font-size:16px; }
.hand-preview .srow { line-height:1.55; }
.hand-preview .cd { margin-right:.18em; }
.adv { margin-top:12px; border:1px solid #D9E0DA; border-radius:10px;
  padding:8px 12px; background:#2B6CB014; }
.adv-title { font-weight:600; font-size:13.5px; margin-bottom:4px; }
.adv-sub { font-weight:400; font-size:12px; color:#5C6B62; }
.adv-row { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
.plan-row { display:flex; flex-wrap:wrap; gap:8px; align-items:end;
  background:#fff; border:1px solid #D9E0DA; border-radius:10px;
  padding:6px 10px; margin:6px 0; }
.pl-field { display:flex; flex-direction:column; gap:2px; font-size:12px;
  color:#5C6B62; }
.extras-row { margin-top:8px; }
#btn-extras.on { outline:2px solid #2B6CB0; background:#2B6CB014; }
#extras-chips .chip { display:inline-block; background:#2B6CB014;
  border:1px solid #2B6CB0; border-radius:999px; padding:2px 10px;
  margin:2px 4px; cursor:pointer; font-weight:600; direction:ltr; }
.plan-row { margin:6px 0; font-size:13.5px; }
.plan-row select { margin:0 3px; }
.bcalls { display:flex; gap:6px; margin-top:8px; }
.bcalls button { flex:1; height:36px; font-weight:700; }
.auction-strip { direction:ltr; display:grid;
  grid-template-columns:repeat(4,1fr); gap:2px; margin:10px 0;
  max-width:420px; }
.auction-strip .hdr { text-align:center; font-size:12px;
  color:var(--muted); }
.auction-strip .cell { text-align:center; border:1px solid var(--line);
  border-radius:6px; padding:2px 0; min-height:26px; background:#fff; }
.auction-strip .cell.hero { background:var(--accent-tint); }
.auction-strip .cell.dp { outline:2px solid var(--accent); font-weight:700; }
.badge { display:inline-block; border-radius:999px; padding:1px 10px;
  font-size:12px; font-weight:600; background:var(--warn-bg);
  color:var(--warn-fg); }
.note { background:var(--warn-bg); color:var(--warn-fg);
  border:1px solid var(--warn-line); border-radius:8px; padding:6px 10px;
  font-size:13px; margin:6px 0; }
#status { color:#fff; margin:8px 4px; min-height:22px; }
iframe.report { width:100%; height:75vh; border:1px solid var(--line);
  border-radius:10px; background:#fff; }
.tabs { display:flex; gap:6px; margin-bottom:6px; flex-wrap:wrap; }
.tabs button.active { background:var(--accent); color:#fff; }
.spin { display:inline-block; width:14px; height:14px; border-radius:50%;
  border:2px solid #fff8; border-top-color:#fff; vertical-align:middle;
  animation:sp 1s linear infinite; }
@keyframes sp { to { transform:rotate(360deg); } }
</style></head><body>
<h1>ניתוח הכרזה</h1>

<div class="card" id="step-hand">
<h2>1. היד שלך <span id="handsum">(0/13)</span></h2>
<div id="picker"></div>
<div class="hand-preview" id="hand-preview" hidden></div>
<div class="row">
  <label>הזנה מהירה (PBN):</label>
  <input type="text" id="quick" class="ltr" size="26"
         placeholder="AQ2.KJ3.KQ54.A32">
  <button id="quickfill">מלא מהטקסט</button>
  <button id="clearhand">נקה</button>
</div>
</div>

<div class="card" id="step-cond">
<h2>2. תנאי המשחק</h2>
<div class="row">
  <label>המושב שלך:</label>
  <select id="seat"><option value="S">דרום</option>
    <option value="N">צפון</option><option value="E">מזרח</option>
    <option value="W">מערב</option></select>
  <label>המחלק:</label>
  <select id="dealer"><option value="N">צפון</option>
    <option value="E">מזרח</option><option value="S">דרום</option>
    <option value="W">מערב</option></select>
  <label>פגיעות:</label>
  <select id="vul"><option value="none">ללא</option>
    <option value="us">שלנו</option><option value="them">שלהם</option>
    <option value="both">שני הצדדים</option></select>
</div>
<div class="row">
  <label>סוג תחרות:</label>
  <select id="scoring"><option value="IMP">מפגשי (IMP)</option>
    <option value="MP">ניקוד מקסימלי (MP)</option></select>
  <label>ניסוח הדוח:</label>
  <select id="narration">
    <option value="template">תבניות — חינם, ללא LLM</option>
    <option value="llm">LLM (קריאה אחת, זול; נופל לתבניות אם אין מפתח)</option>
  </select>
</div>
</div>

<div class="card" id="step-auction">
<h2>3. המכרז — עד תורך</h2>
<p style="color:var(--muted);font-size:13px">
הזן את ההכרזות מתחילת המכרז ו<b>עצור כשמגיע תורך</b> — את ההכרזה שעליה
תישאל אל תזין (היא מסומנת ?), ואין להזין פאסים בסופו.</p>
<div class="auction-strip" id="strip"></div>
<div id="turnline"></div>
<div class="bbox" id="bbox"></div>
<div class="bcalls">
  <button id="btn-p">פאס</button><button id="btn-x">דאבל</button>
  <button id="btn-xx">רידאבל</button><button id="btn-undo">↩ בטל</button>
</div>
<div class="note" id="auction-note" hidden></div>
<div class="adv" id="extras-area" hidden>
  <div class="adv-title">בדיקת הכרזה נוספת <span class="adv-sub">(רשות · עד 4)</span></div>
  <div class="adv-row"><select id="extra-select"></select>
  <button id="extra-add">הוסף</button><span id="extras-chips"></span></div>
</div>
<div class="adv" id="plans-area" hidden>
  <div class="adv-title">תוכניות המשך <span class="adv-sub">(רשות)</span></div>
  <div id="plans-box"></div>
  <button id="btn-plan-add" class="adv-add">+ הוסף כלל</button>
</div>
</div>
</div>

<div style="text-align:center">
<button class="primary" id="go" disabled>נתח ▶</button>
<div id="status"></div>
</div>

<div class="card" id="results" hidden>
<h2>דוחות הניתוח</h2>
<div class="tabs" id="tabs"></div>
<div class="row" id="dl-row"></div>
<iframe class="report" id="frame"></iframe>
</div>

<script src="/assets/bt-analyze-ui.js"></script>
<script>
"use strict";
const UI = window.BTAnalyzeUI;
UI.init({onChange: () => {
  document.getElementById("go").disabled = !UI.ready();
}});

document.getElementById("go").onclick = async () => {
  const status = document.getElementById("status");
  const go = document.getElementById("go");
  go.disabled = true;
  status.innerHTML = '<span class="spin"></span> מריץ סימולציה ' +
    '(דגימה אדפטיבית + דאבל-דאמי) — זה יכול לקחת עד דקה לכל נקודת החלטה...';
  const vulSel = document.getElementById("vul").value;
  const us = "NS".includes(UI.heroSeat()) ? "NS" : "EW";
  const vul = {none: "None", both: "Both",
               us: us, them: us === "NS" ? "EW" : "NS"}[vulSel];
  // stem-only flow: the analyzed call is the NEXT one after the entered
  // auction (decision_index == auction length)
  const auction = UI.auction();
  const body = {
    dealer: UI.dealer(), vul, my_seat: UI.heroSeat(),
    my_hand: UI.handPBN(), auction,
    scoring: document.getElementById("scoring").value,
    decision_indices: [auction.length],
    narration: document.getElementById("narration").value,
  };
  const extras = UI.extraCandidates();
  if (extras.length) body.extra_candidates = extras;
  const plans = UI.plans();
  if (plans.length) body.plans = plans;
  try {
    const r = await fetch("/api/analyze", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body)});
    const data = await r.json();
    if (!r.ok || !data.ok) throw new Error(data.error || r.statusText);
    showResults(data.reports);
    status.textContent = "";
  } catch (e) {
    status.textContent = "שגיאה: " + e.message;
  }
  go.disabled = !UI.ready();
};
function showResults(reports) {
  const res = document.getElementById("results");
  res.hidden = false;
  const tabs = document.getElementById("tabs");
  tabs.innerHTML = "";
  reports.forEach((rep, k) => {
    const b = document.createElement("button");
    b.innerHTML = rep.actual
      ? `נקודת החלטה ${rep.decision_index + 1} (${UI.tokHtml(rep.actual)})`
      : `הכרזה ${rep.decision_index + 1} — מה להכריז?`;
    b.onclick = () => activate(k);
    tabs.appendChild(b);
  });
  function activate(k) {
    tabs.querySelectorAll("button").forEach((b, i) =>
      b.classList.toggle("active", i === k));
    document.getElementById("frame").src = reports[k].html_url;
    const dl = document.getElementById("dl-row");
    dl.innerHTML = `<a href="${reports[k].html_url}" target="_blank">` +
      `פתח בחלון מלא</a>` +
      (reports[k].pdf_url ? ` · <a href="${reports[k].pdf_url}" ` +
        `download>הורד PDF</a>` : " · (PDF לא זמין — הדפס מהדפדפן)") +
      ` · <a href="${reports[k].json_url}" download>נתוני JSON</a>`;
  }
  activate(0);
  res.scrollIntoView({behavior: "smooth"});
}
</script></body></html>
"""


def analyze_page() -> str:
    return PAGE
