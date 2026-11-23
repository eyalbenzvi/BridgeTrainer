
"use strict";
const UI = window.BTAnalyzeUI;
const $ = (id) => document.getElementById(id);
let UNSUB = null;
const RANKS = "AKQJT98765432";
const G = {S: "♠", H: "♥", D: "♦", C: "♣"};
const C = {S: "ss", H: "sh", D: "sd", C: "sc"};

function cardHtml(card) {
  if (!card) return "";
  return '<span class="' + C[card[0]] + '">' + G[card[0]] + "</span>" +
    (card[1] === "T" ? "10" : card[1]);
}
function groupHtml(cards) {
  if (!cards || !cards.length) return "";
  if (cards.length === 1) return cardHtml(cards[0]);
  return '<span class="' + C[cards[0][0]] + '">' + G[cards[0][0]] +
    "</span>" + cards.map((c) => c[1] === "T" ? "10" : c[1]).join("/");
}

// the optional "my actual lead" select follows the entered hand
function refreshActual() {
  const box = $("actual-lead");
  const keep = box.value;
  const pbn = UI.handSize() === 13 ? UI.handPBN() : "";
  const cards = [];
  if (pbn) pbn.split(".").forEach((h, i) => {
    for (const r of h) cards.push("SHDC"[i] + r);
  });
  box.innerHTML = '<option value="">— לא צוין —</option>' + cards.map((c) =>
    '<option value="' + c + '">' + G[c[0]] + (c[1] === "T" ? "10" : c[1]) +
    "</option>").join("");
  if (cards.includes(keep)) box.value = keep;
}

function refreshGo() {
  $("go").disabled = !UI.ready();
  refreshActual();
}

function init() {
  UI.init({onChange: refreshGo, mode: "lead"});
  $("go").onclick = submit;
  if (UNSUB) UNSUB();
  UNSUB = window.BT.watchAnalyses(renderList);
  refreshGo();
}

async function submit() {
  const st = $("an-status");
  $("go").disabled = true;
  const vulSel = $("vul").value;
  const us = "NS".includes(UI.heroSeat()) ? "NS" : "EW";
  const vul = {none: "None", both: "Both",
               us: us, them: us === "NS" ? "EW" : "NS"}[vulSel];
  try {
    const lreq = {
      kind: "lead", dealer: UI.dealer(), vul: vul, my_seat: UI.heroSeat(),
      my_hand: UI.handPBN(), auction: UI.auction(),
      scoring: $("scoring").value,
    };
    const act = $("actual-lead").value;
    if (act) lreq.actual_lead = act;
    await window.BT.submitAnalysis(lreq);
    UI.reset();
    st.textContent = "הבקשה נשלחה! החישוב רץ בענן — בדרך כלל דקה-שתיים " +
      "(עד ~10 דקות במסלול הגיבוי); הרשימה למטה תתעדכן לבד כשהדוח מוכן.";
    $("queue-card").scrollIntoView({behavior: "smooth"});
  } catch (e) {
    console.error(e);
    st.textContent = "השליחה נכשלה: " + (e.message || e);
  }
  refreshGo();
}

const STATUS_HE = {pending: "ממתין בתור", running: "מחשב...",
                   done: "מוכן", error: "שגיאה"};

function handInline(pbn) {
  return (pbn || "").split(".").map((cards, i) => {
    const st = "SHDC"[i];
    return '<span class="' + C[st] + '">' + G[st] + "</span>" +
      (cards || "—");
  }).join(" ");
}

function contractHtml(spec) {
  // '4HS' / '3NTWx' -> 4♥ (S)
  const m = /^(\d)(NT|[SHDC])([NESW])(x*)$/.exec(spec || "");
  if (!m) return "";
  return UI.tokHtml(m[1] + m[2]) + (m[4] ? m[4].toUpperCase() : "") +
    " (" + {N: "צפון", E: "מזרח", S: "דרום", W: "מערב"}[m[3]] + ")";
}

function renderList(rows) {
  rows = rows.filter((r) => r.req && r.req.kind === "lead");
  const ul = $("an-list");
  if (!rows.length) {
    ul.innerHTML = '<li><span class="an-meta">אין עדיין ניתוחי הובלה. ' +
      'מלא את הטופס למעלה ולחץ "נתח".</span></li>';
    return;
  }
  ul.innerHTML = "";
  for (const r of rows) {
    const q = r.req || {};
    const li = document.createElement("li");
    const when = r.createdAt && r.createdAt.seconds
      ? new Date(r.createdAt.seconds * 1000).toLocaleString("he-IL") : "";
    let rec = "";
    if (r.status === "done" && r.summary) {
      rec = '<span class="an-rec">המלצה: ' +
        groupHtml(r.summary.recommended_cards ||
                  [r.summary.recommended]) + "</span>" +
        '<span class="an-meta">' + (r.summary.n_deals || "?") +
        " חלוקות</span>";
    } else if (r.status === "error") {
      rec = '<span class="an-meta">' + (r.error || "") + "</span>";
    }
    const vs = r.summary && r.summary.contract
      ? "נגד " + contractHtml(r.summary.contract) : "הובלת פתיחה";
    li.innerHTML =
      '<div class="an-line1"><span class="chip ' + r.status + '">' +
      (STATUS_HE[r.status] || r.status) + "</span>" +
      "<span>" + vs + "</span>" + rec + "</div>" +
      '<div class="an-hand">' + handInline(q.my_hand) + "</div>" +
      '<div class="an-meta">' + when +
      (q.actual_lead ? " · הובלת בפועל: " + cardHtml(q.actual_lead) : "") +
      "</div>" +
      '<div class="an-actions">' +
      (r.status === "done"
        ? '<button data-open="' + r.id + '">פתח דוח</button>' : "") +
      '<button data-del="' + r.id + '">מחק</button></div>';
    ul.appendChild(li);
  }
  ul.querySelectorAll("button[data-open]").forEach((b) =>
    (b.onclick = () => openReport(b.dataset.open)));
  ul.querySelectorAll("button[data-del]").forEach((b) =>
    (b.onclick = async () => {
      if (!confirm("למחוק את הניתוח?")) return;
      try { await window.BT.deleteAnalysis(b.dataset.del); }
      catch (e) { alert("מחיקה נכשלה: " + e.message); }
    }));
}

async function openReport(id) {
  const card = $("viewer-card");
  card.hidden = false;
  $("an-close").onclick = () => { card.hidden = true; };
  $("an-frame").srcdoc =
    "<p style='font-family:sans-serif'>טוען את הדוח...</p>";
  card.scrollIntoView({behavior: "smooth"});
  try {
    const rep = await window.BT.getAnalysisReport(id);
    if (!rep || !rep.html) throw new Error("הדוח לא נמצא");
    $("an-frame").srcdoc = rep.html;
    const fname = "bridge-lead-analysis-" + id.slice(0, 8) + ".html";
    $("an-download").onclick = () => {
      const blob = new Blob([rep.html], {type: "text/html"});
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = fname;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    };
    $("an-share").onclick = async () => {
      const file = new File([rep.html], fname, {type: "text/html"});
      if (navigator.canShare && navigator.canShare({files: [file]})) {
        try {
          await navigator.share({files: [file],
                                 title: "ניתוח הובלה — BridgeTrainer"});
          return;
        } catch (e) { if (e.name === "AbortError") return; }
      }
      $("an-download").click();
    };
  } catch (e) {
    $("an-frame").srcdoc = "<p>שגיאה בטעינת הדוח: " +
      (e.message || e) + "</p>";
  }
}

if (window.BT) window.BT.start(init);
else addEventListener("bt-ready", () => window.BT.start(init), {once: true});
