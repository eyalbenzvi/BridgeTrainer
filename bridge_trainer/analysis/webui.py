"""The analyze page: Hebrew RTL single-file UI served by analysis/server.py.

Follows the app's existing design language (webapp.py): green-felt page,
white cards, BBO-style red ♥/♦. New components built here because the
existing app has no input components (its problems are pre-made): a visual
52-card picker (spec 2.1), a real bidding box (spec 2.4), per-call meaning
overrides (spec 2.3) and decision-point selection. Auction legality in JS
mirrors validate/auction_state.py (level/denom ordering, X/XX rules,
three-passes-end detection).
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
label { margin-inline-end:6px; }
.row { display:flex; flex-wrap:wrap; gap:10px 18px; align-items:center;
  margin:6px 0; }
/* ---- card picker ---- */
.suitrow { display:flex; align-items:center; gap:4px; margin:4px 0;
  direction:ltr; }
.suitrow .glyph { width:22px; font-size:18px; text-align:center; }
.suitrow .cnt { width:56px; direction:rtl; font-size:11px;
  color:var(--muted); text-align:right; }
.cardbtn { width:34px; height:40px; border-radius:6px; font-weight:700;
  font-size:14px; padding:0; border:1px solid var(--line); background:#fff; }
.cardbtn.sel { background:var(--accent); color:#fff; border-color:var(--accent); }
.cardbtn.gone { visibility:hidden; }
#handsum { font-weight:600; }
#handsum.bad { color:var(--he-red); }
/* ---- bidding box ---- */
.bbox { direction:ltr; display:grid; grid-template-columns:repeat(5,1fr);
  gap:4px; max-width:330px; }
.bbox button { height:36px; font-weight:700; padding:0; }
.bbox button.used { background:#eee; }
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
.ovr { border:1px dashed var(--line); border-radius:8px; padding:8px;
  margin:6px 0; }
.ovr summary { cursor:pointer; }
.dp-list label { display:inline-flex; align-items:center; gap:4px;
  border:1px solid var(--line); border-radius:8px; padding:4px 10px;
  margin:3px; cursor:pointer; }
.dp-list input:checked + span { font-weight:700; color:var(--accent); }
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
  <label>שיטת הכרזה:</label>
  <select id="system"><option value="two_over_one">2/1 Game Force</option>
    <option value="sayc">SAYC</option></select>
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
<h2>3. המכרז בפועל</h2>
<div class="auction-strip" id="strip"></div>
<div id="turnline"></div>
<div class="bbox" id="bbox"></div>
<div class="bcalls">
  <button id="btn-p">פס</button><button id="btn-x">דאבל</button>
  <button id="btn-xx">רידאבל</button><button id="btn-undo">↩ בטל</button>
</div>
<div class="note" id="auction-note" hidden></div>
</div>

<div class="card" id="step-ovr">
<h2>4. משמעויות מותאמות (רשות)</h2>
<p class="ltr" style="direction:rtl;color:var(--muted);font-size:13px">
כברירת מחדל כל הכרזה מתפרשת לפי השיטה. פתח הכרזה כדי לדרוס את
פרשנותה (הסכם מיוחד): טווח נק', אורכי סדרות, והערה חופשית.</p>
<div id="ovr-list"><span style="color:var(--muted)">הזן מכרז תחילה.</span></div>
</div>

<div class="card" id="step-dp">
<h2>5. נקודות החלטה לניתוח</h2>
<div class="dp-list" id="dp-list"><span style="color:var(--muted)">
בחר לאחר השלמת המכרז (אפשר יותר מאחת).</span></div>
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

<script>
"use strict";
const SUITS = ["S","H","D","C"];
const GLYPH = {S:"♠",H:"♥",D:"♦",C:"♣"};
const RANKS = "AKQJT98765432";
const SEAT_HE = {N:"צפון",E:"מזרח",S:"דרום",W:"מערב"};
const SEATS = ["N","E","S","W"];
const DENOMS = ["C","D","H","S","NT"];

/* ---------- card picker ---------- */
const sel = new Set();
function buildPicker() {
  const root = document.getElementById("picker");
  root.innerHTML = "";
  for (const s of SUITS) {
    const row = document.createElement("div");
    row.className = "suitrow";
    const g = document.createElement("span");
    g.className = "glyph" + (s === "H" || s === "D" ? " red" : "");
    g.textContent = GLYPH[s];
    row.appendChild(g);
    for (const r of RANKS) {
      const b = document.createElement("button");
      b.className = "cardbtn"; b.textContent = r;
      b.dataset.card = s + r;
      if (s === "H" || s === "D") b.classList.add("red");
      b.onclick = () => { toggleCard(s + r); };
      row.appendChild(b);
    }
    const cnt = document.createElement("span");
    cnt.className = "cnt"; cnt.id = "cnt-" + s;
    row.appendChild(cnt);
    root.appendChild(row);
  }
  refreshPicker();
}
function toggleCard(card) {
  if (sel.has(card)) sel.delete(card);
  else if (sel.size < 13) sel.add(card);
  refreshPicker();
}
function refreshPicker() {
  document.querySelectorAll(".cardbtn").forEach(b => {
    b.classList.toggle("sel", sel.has(b.dataset.card));
    b.disabled = !sel.has(b.dataset.card) && sel.size >= 13;
  });
  for (const s of SUITS) {
    const n = [...sel].filter(c => c[0] === s).length;
    document.getElementById("cnt-" + s).textContent = n + " נבחרו";
  }
  const sum = document.getElementById("handsum");
  sum.textContent = `(${sel.size}/13)`;
  sum.classList.toggle("bad", sel.size !== 13);
  refreshGo();
}
function handPBN() {
  return SUITS.map(s =>
    RANKS.split("").filter(r => sel.has(s + r)).join("")).join(".");
}
document.getElementById("quickfill").onclick = () => {
  const t = document.getElementById("quick").value.trim().toUpperCase();
  const parts = t.split(".");
  if (parts.length !== 4) { alert("פורמט: סדרות מופרדות בנקודה, ♠.♥.♦.♣"); return; }
  const chosen = [];
  for (let i = 0; i < 4; i++)
    for (const ch of parts[i]) {
      const r = ch === "1" ? null : ch === "0" ? "T" : ch;
      if (!r || !RANKS.includes(r)) { alert("קלף לא חוקי: " + ch); return; }
      chosen.push(SUITS[i] + r);
    }
  if (chosen.length !== 13) { alert("צריך בדיוק 13 קלפים (יש " + chosen.length + ")"); return; }
  if (new Set(chosen).size !== 13) { alert("קלף כפול בהזנה"); return; }
  sel.clear(); chosen.forEach(c => sel.add(c));
  refreshPicker();
};
document.getElementById("clearhand").onclick = () => { sel.clear(); refreshPicker(); };

/* ---------- auction state (mirrors validate/auction_state.py) ---------- */
let auction = [];           // tokens
function dealer() { return document.getElementById("dealer").value; }
function heroSeat() { return document.getElementById("seat").value; }
function seatOf(i) { return SEATS[(SEATS.indexOf(dealer()) + i) % 4]; }
function replayState() {
  let level = 0, denom = "", lastBidSeat = "", doubled = 0, tp = 0;
  auction.forEach((tok, i) => {
    if (tok === "P") tp += 1;
    else if (tok === "X") { doubled = 1; tp = 0; }
    else if (tok === "XX") { doubled = 2; tp = 0; }
    else { level = +tok[0]; denom = tok.slice(1); doubled = 0; tp = 0;
           lastBidSeat = seatOf(i); }
  });
  const finished = (auction.length >= 4 && level === 0 && tp >= 4) ||
                   (level > 0 && tp >= 3);
  return {level, denom, lastBidSeat, doubled, tp, finished,
          turn: seatOf(auction.length)};
}
function sameSide(a, b) {
  return ("NS".includes(a)) === ("NS".includes(b));
}
function isLegal(tok) {
  const st = replayState();
  if (st.finished) return false;
  if (tok === "P") return true;
  if (tok === "X") return st.level > 0 && st.doubled === 0 &&
    !sameSide(st.lastBidSeat, st.turn);
  if (tok === "XX") return st.level > 0 && st.doubled === 1 &&
    sameSide(st.lastBidSeat, st.turn);
  const lvl = +tok[0], dn = tok.slice(1);
  if (st.level === 0) return true;
  return lvl > st.level ||
    (lvl === st.level && DENOMS.indexOf(dn) > DENOMS.indexOf(st.denom));
}
function addCall(tok) {
  if (!isLegal(tok)) return;
  auction.push(tok);
  refreshAuction();
}
document.getElementById("btn-p").onclick = () => addCall("P");
document.getElementById("btn-x").onclick = () => addCall("X");
document.getElementById("btn-xx").onclick = () => addCall("XX");
document.getElementById("btn-undo").onclick = () => {
  auction.pop(); refreshAuction();
};
function buildBBox() {
  const box = document.getElementById("bbox");
  box.innerHTML = "";
  for (let lvl = 1; lvl <= 7; lvl++)
    for (const dn of DENOMS) {
      const b = document.createElement("button");
      const red = dn === "H" || dn === "D";
      b.innerHTML = lvl + (dn === "NT" ? "NT"
        : `<span${red ? ' class="red"' : ""}>${GLYPH[dn]}</span>`);
      b.dataset.tok = lvl + dn;
      b.onclick = () => addCall(lvl + dn);
      box.appendChild(b);
    }
}
function tokHtml(tok) {
  if (tok === "P") return "פס";
  if (tok === "X") return "X";
  if (tok === "XX") return "XX";
  const dn = tok.slice(1);
  if (dn === "NT") return tok;
  const red = dn === "H" || dn === "D";
  return tok[0] + `<span${red ? ' class="red"' : ""}>${GLYPH[dn]}</span>`;
}
let decisionPoints = new Set();
function refreshAuction() {
  const st = replayState();
  // strip
  const strip = document.getElementById("strip");
  strip.innerHTML = SEATS.map(s =>
    `<div class="hdr">${SEAT_HE[s]}${s === heroSeat() ? " (אתה)" : ""}</div>`
  ).join("");
  const pad = SEATS.indexOf(dealer());
  for (let i = 0; i < pad; i++) strip.innerHTML += "<div></div>";
  auction.forEach((tok, i) => {
    const hero = seatOf(i) === heroSeat();
    const dp = decisionPoints.has(i);
    strip.innerHTML += `<div class="cell${hero ? " hero" : ""}` +
      `${dp ? " dp" : ""}">${tokHtml(tok)}</div>`;
  });
  // turn line / end detection
  const tl = document.getElementById("turnline");
  const note = document.getElementById("auction-note");
  if (st.finished) {
    tl.innerHTML = "";
    note.hidden = false;
    note.textContent = auction.length >= 4 && st.level === 0
      ? "המכרז הסתיים: כולם פסו (אין משחק)."
      : "המכרז הושלם (שלושה פסים רצופים) — בחר נקודות החלטה בסעיף 5.";
  } else {
    note.hidden = true;
    tl.innerHTML = "תור: <b>" + SEAT_HE[st.turn] +
      (st.turn === heroSeat() ? " (אתה)" : "") + "</b>";
  }
  // bidding box legality
  document.querySelectorAll("#bbox button").forEach(b => {
    b.disabled = !isLegal(b.dataset.tok);
  });
  document.getElementById("btn-p").disabled = !isLegal("P");
  document.getElementById("btn-x").disabled = !isLegal("X");
  document.getElementById("btn-xx").disabled = !isLegal("XX");
  document.getElementById("btn-undo").disabled = auction.length === 0;
  refreshOverrides();
  refreshDecisionPoints(st);
  refreshGo();
}
/* ---------- overrides ---------- */
const overrides = {};   // index -> {hcp:[lo,hi]|null, suits:{}, note}
function refreshOverrides() {
  const root = document.getElementById("ovr-list");
  if (!auction.length) {
    root.innerHTML = '<span style="color:var(--muted)">הזן מכרז תחילה.</span>';
    return;
  }
  root.innerHTML = "";
  auction.forEach((tok, i) => {
    if (tok === "P" && !(i in overrides)) return;  // passes rarely overridden
    const d = document.createElement("details");
    d.className = "ovr";
    const has = i in overrides;
    d.innerHTML = `<summary>הכרזה ${i + 1}: ${tokHtml(tok)} של ` +
      `${SEAT_HE[seatOf(i)]}` +
      (has ? ' <span class="badge">הסכם אישי</span>' : "") + `</summary>` +
      `<div class="row"><label>נק' מ-</label>` +
      `<input type="number" min="0" max="40" id="ov-${i}-lo" size="3">` +
      `<label>עד</label>` +
      `<input type="number" min="0" max="40" id="ov-${i}-hi" size="3">` +
      SUITS.map(s => `<label class="${s === "H" || s === "D" ? "red" : ""}">` +
        `${GLYPH[s]}</label><input type="number" min="0" max="13" ` +
        `id="ov-${i}-${s}-lo" style="width:52px" placeholder="מינ'">` +
        `<input type="number" min="0" max="13" id="ov-${i}-${s}-hi" ` +
        `style="width:52px" placeholder="מקס'">`).join("") +
      `</div><div class="row"><label>הערה:</label>` +
      `<input type="text" id="ov-${i}-note" size="40" ` +
      `placeholder="למשל: 3♣ כאן = מזמין ולא מנע"></div>` +
      `<div class="row"><button data-save="${i}">שמור דריסה</button>` +
      `<button data-clear="${i}">נקה</button></div>`;
    root.appendChild(d);
    if (has) {
      const o = overrides[i];
      if (o.hcp) {
        d.querySelector(`#ov-${i}-lo`).value = o.hcp[0];
        d.querySelector(`#ov-${i}-hi`).value = o.hcp[1];
      }
      for (const s of SUITS) if (o.suits && o.suits[s]) {
        d.querySelector(`#ov-${i}-${s}-lo`).value = o.suits[s][0];
        d.querySelector(`#ov-${i}-${s}-hi`).value = o.suits[s][1];
      }
      if (o.note) d.querySelector(`#ov-${i}-note`).value = o.note;
    }
  });
  root.querySelectorAll("button[data-save]").forEach(b => b.onclick = () => {
    const i = +b.dataset.save;
    const v = id => document.getElementById(id).value;
    const lo = v(`ov-${i}-lo`), hi = v(`ov-${i}-hi`);
    const o = {suits: {}, note: v(`ov-${i}-note`).trim()};
    if (lo !== "" && hi !== "") o.hcp = [+lo, +hi];
    for (const s of SUITS) {
      const a = v(`ov-${i}-${s}-lo`), c = v(`ov-${i}-${s}-hi`);
      if (a !== "" && c !== "") o.suits[s] = [+a, +c];
    }
    if (!o.hcp && !Object.keys(o.suits).length && !o.note) delete overrides[i];
    else overrides[i] = o;
    refreshOverrides();
  });
  root.querySelectorAll("button[data-clear]").forEach(b => b.onclick = () => {
    delete overrides[+b.dataset.clear]; refreshOverrides();
  });
}
/* ---------- decision points ---------- */
function refreshDecisionPoints(st) {
  const root = document.getElementById("dp-list");
  const heroIdx = auction.map((t, i) => i).filter(i => seatOf(i) === heroSeat());
  if (!st.finished || !heroIdx.length) {
    root.innerHTML = '<span style="color:var(--muted)">בחר לאחר השלמת ' +
      'המכרז (אפשר יותר מאחת).</span>';
    decisionPoints.clear();
    return;
  }
  root.innerHTML = "";
  for (const i of heroIdx) {
    const l = document.createElement("label");
    l.innerHTML = `<input type="checkbox" data-i="${i}"` +
      `${decisionPoints.has(i) ? " checked" : ""}>` +
      `<span>הכרזה ${i + 1}: ${tokHtml(auction[i])}</span>`;
    root.appendChild(l);
  }
  root.querySelectorAll("input").forEach(c => c.onchange = () => {
    const i = +c.dataset.i;
    if (c.checked) decisionPoints.add(i); else decisionPoints.delete(i);
    refreshAuction();
  });
}
function refreshGo() {
  document.getElementById("go").disabled =
    sel.size !== 13 || !replayState().finished || decisionPoints.size === 0;
}
document.getElementById("dealer").onchange = refreshAuction;
document.getElementById("seat").onchange = refreshAuction;

/* ---------- analyze ---------- */
document.getElementById("go").onclick = async () => {
  const status = document.getElementById("status");
  const go = document.getElementById("go");
  go.disabled = true;
  status.innerHTML = '<span class="spin"></span> מריץ סימולציה ' +
    '(דגימה אדפטיבית + דאבל-דאמי) — זה יכול לקחת עד דקה לכל נקודת החלטה...';
  const vulSel = document.getElementById("vul").value;
  const us = "NS".includes(heroSeat()) ? "NS" : "EW";
  const vul = {none: "None", both: "Both",
               us: us, them: us === "NS" ? "EW" : "NS"}[vulSel];
  const body = {
    dealer: dealer(), vul, my_seat: heroSeat(), my_hand: handPBN(),
    auction, system: document.getElementById("system").value,
    scoring: document.getElementById("scoring").value,
    decision_indices: [...decisionPoints].sort((a, b) => a - b),
    overrides,
    narration: document.getElementById("narration").value,
  };
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
  go.disabled = false;
  refreshGo();
};
function showResults(reports) {
  const res = document.getElementById("results");
  res.hidden = false;
  const tabs = document.getElementById("tabs");
  tabs.innerHTML = "";
  reports.forEach((rep, k) => {
    const b = document.createElement("button");
    b.innerHTML = `נקודת החלטה ${rep.decision_index + 1} ` +
      `(${tokHtml(rep.actual)})`;
    b.onclick = () => activate(k);
    tabs.appendChild(b);
  });
  window._reports = reports;
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
buildPicker(); buildBBox(); refreshAuction();
</script></body></html>
"""


def analyze_page() -> str:
    return PAGE
