
"use strict";
const UI = window.BTAnalyzeUI;
const $ = (id) => document.getElementById(id);
let UNSUB = null, ROWS = [];

function refreshGo() {
  $("go").disabled = !UI.ready();
}

function init() {
  UI.init({onChange: refreshGo});
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
    // stem-only flow: the auction stops at the hero's turn; the analyzed
    // call is the NEXT one (decision_index == auction length)
    const auction = UI.auction();
    const req = {
      dealer: UI.dealer(), vul: vul, my_seat: UI.heroSeat(),
      my_hand: UI.handPBN(), auction: auction,
      decision_index: auction.length,
      scoring: $("scoring").value, narration: "template",
    };
    const extras = UI.extraCandidates();
    if (extras.length) req.extra_candidates = extras;
    // Firestore rejects nested arrays -> ship plans as {c,r,m} maps
    const plans = UI.plans();
    if (plans.length)
      req.plans = plans.map(([c, r, m]) => ({c: c, r: r, m: m}));
    await window.BT.submitAnalysis(req);
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

function rowMeta(r) {
  const q = r.req || {};
  const when = r.createdAt && r.createdAt.seconds
    ? new Date(r.createdAt.seconds * 1000).toLocaleString("he-IL") : "";
  // stem-only requests have no entered call at the decision index — label
  // the row by the last stem call instead ("אחרי 3♥")
  const entered = (q.auction || [])[q.decision_index];
  const last = (q.auction || [])[(q.auction || []).length - 1];
  const call = entered ? UI.tokHtml(entered)
    : (last ? "אחרי " + UI.tokHtml(last) : "פתיחה");
  return {when, call, hand: q.my_hand || ""};
}

function handInline(pbn) {
  const G = {S: "♠", H: "♥", D: "♦", C: "♣"};
  const C = {S: "ss", H: "sh", D: "sd", C: "sc"};
  return pbn.split(".").map((cards, i) => {
    const st = "SHDC"[i];
    return '<span class="' + C[st] + '">' + G[st] + "</span>" +
      (cards || "—");
  }).join(" ");
}

function renderList(rows) {
  ROWS = rows;
  const ul = $("an-list");
  if (!rows.length) {
    ul.innerHTML = '<li><span class="an-meta">אין עדיין ניתוחים. ' +
      'מלא את הטופס למעלה ולחץ "נתח".</span></li>';
    return;
  }
  ul.innerHTML = "";
  for (const r of rows) {
    const li = document.createElement("li");
    const m = rowMeta(r);
    let rec = "";
    if (r.status === "done" && r.summary) {
      rec = '<span class="an-rec">המלצה: ' +
        UI.tokHtml(r.summary.recommended) + "</span>" +
        '<span class="an-meta">' + (r.summary.n_deals || "?") +
        " חלוקות</span>";
    } else if (r.status === "error") {
      rec = '<span class="an-meta">' + (r.error || "") + "</span>";
    }
    li.innerHTML =
      '<div class="an-line1"><span class="chip ' + r.status + '">' +
      (STATUS_HE[r.status] || r.status) + "</span>" +
      "<span>" + m.call + "</span>" + rec + "</div>" +
      '<div class="an-hand">' + handInline(m.hand) + "</div>" +
      '<div class="an-meta">' + m.when + "</div>" +
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
    const fname = "bridge-analysis-" + id.slice(0, 8) + ".html";
    // download: a self-contained HTML file — opens in any browser, no
    // sign-in needed by the recipient
    $("an-download").onclick = () => {
      const blob = new Blob([rep.html], {type: "text/html"});
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = fname;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    };
    // share: the report FILE itself via the system share sheet (WhatsApp
    // etc. on mobile); falls back to download where files can't be shared
    $("an-share").onclick = async () => {
      const file = new File([rep.html], fname, {type: "text/html"});
      if (navigator.canShare && navigator.canShare({files: [file]})) {
        try {
          await navigator.share({files: [file],
                                 title: "ניתוח הכרזה — BridgeTrainer"});
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
