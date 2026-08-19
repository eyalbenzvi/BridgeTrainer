// Shared UI logic for the bidding-analysis input flow, used by BOTH front
// ends: the deployed site's analyze.html (submits to Firestore, computed by
// the GitHub Actions worker) and the local `trainer analyze` page (submits
// to the local server). Classic script, exposes window.BTAnalyzeUI.
//
// The host page provides the skeleton elements by id (picker, quick,
// quickfill, clearhand, handsum, seat, dealer, strip, turnline, bbox,
// btn-p/btn-x/btn-xx/btn-undo, auction-note) and calls
// BTAnalyzeUI.init({onChange}). Auction legality mirrors
// validate/auction_state.py (bid ordering, X/XX rules, three passes end).
//
// INPUT MODEL (user-requested): the auction is entered UP TO the hero's
// turn and STOPS there — the analyzed call itself is never entered and
// there are no trailing passes. ready() is true exactly when the hand is
// complete and it is the hero's turn in an unfinished auction.
"use strict";
(function () {
  const SUITS = ["S", "H", "D", "C"];
  const GLYPH = { S: "♠", H: "♥", D: "♦", C: "♣" };
  const RANKS = "AKQJT98765432";
  const SEAT_HE = { N: "צפון", E: "מזרח", S: "דרום", W: "מערב" };
  const SEATS = ["N", "E", "S", "W"];
  const DENOMS = ["C", "D", "H", "S", "NT"];

  const sel = new Set();
  let auction = [];
  let onChange = () => {};
  const $ = (id) => document.getElementById(id);

  /* ---------- card picker ---------- */
  function buildPicker() {
    const root = $("picker");
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
        b.type = "button";
        b.className = "cardbtn";
        b.textContent = r;
        b.dataset.card = s + r;
        if (s === "H" || s === "D") b.classList.add("red");
        b.onclick = () => toggleCard(s + r);
        row.appendChild(b);
      }
      const cnt = document.createElement("span");
      cnt.className = "cnt";
      cnt.id = "cnt-" + s;
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
    document.querySelectorAll(".cardbtn").forEach((b) => {
      b.classList.toggle("sel", sel.has(b.dataset.card));
      b.disabled = !sel.has(b.dataset.card) && sel.size >= 13;
    });
    for (const s of SUITS) {
      const n = [...sel].filter((c) => c[0] === s).length;
      const el = $("cnt-" + s);
      if (el) el.textContent = n + " נבחרו";
    }
    const sum = $("handsum");
    if (sum) {
      sum.textContent = `(${sel.size}/13)`;
      sum.classList.toggle("bad", sel.size !== 13);
    }
    onChange();
  }
  function handPBN() {
    return SUITS.map((s) =>
      RANKS.split("").filter((r) => sel.has(s + r)).join("")).join(".");
  }
  function quickFill() {
    const t = $("quick").value.trim().toUpperCase();
    const parts = t.split(".");
    if (parts.length !== 4) {
      alert("פורמט: סדרות מופרדות בנקודה, ♠.♥.♦.♣"); return;
    }
    const chosen = [];
    for (let i = 0; i < 4; i++)
      for (const ch of parts[i]) {
        const r = ch === "0" ? "T" : ch;
        if (!RANKS.includes(r)) { alert("קלף לא חוקי: " + ch); return; }
        chosen.push(SUITS[i] + r);
      }
    if (chosen.length !== 13) {
      alert("צריך בדיוק 13 קלפים (יש " + chosen.length + ")"); return;
    }
    if (new Set(chosen).size !== 13) { alert("קלף כפול בהזנה"); return; }
    sel.clear(); chosen.forEach((c) => sel.add(c));
    refreshPicker();
  }

  /* ---------- auction state ---------- */
  function dealer() { return $("dealer").value; }
  function heroSeat() { return $("seat").value; }
  function seatOf(i) { return SEATS[(SEATS.indexOf(dealer()) + i) % 4]; }
  function replayState() {
    let level = 0, denom = "", lastBidSeat = "", doubled = 0, tp = 0;
    auction.forEach((tok, i) => {
      if (tok === "P") tp += 1;
      else if (tok === "X") { doubled = 1; tp = 0; }
      else if (tok === "XX") { doubled = 2; tp = 0; }
      else {
        level = +tok[0]; denom = tok.slice(1); doubled = 0; tp = 0;
        lastBidSeat = seatOf(i);
      }
    });
    const finished = (auction.length >= 4 && level === 0 && tp >= 4) ||
                     (level > 0 && tp >= 3);
    return { level, denom, lastBidSeat, doubled, tp, finished,
             turn: seatOf(auction.length) };
  }
  function sameSide(a, b) { return "NS".includes(a) === "NS".includes(b); }
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
  /* user-added candidates: calls to test IN ADDITION to the engine menu
     (the engine's policy can starve a mainstream call — e.g. 3NT over a
     preempt — below the menu floor; the rollout evaluates it fine) */
  let extras = [];
  let extrasMode = false;
  const MAX_EXTRAS = 4;
  function toggleExtra(tok) {
    const i = extras.indexOf(tok);
    if (i >= 0) extras.splice(i, 1);
    else if (extras.length < MAX_EXTRAS && isLegal(tok)) extras.push(tok);
    refreshExtras();
  }
  function refreshExtras() {
    const row = $("extras-row");
    if (!row) return;
    const st = replayState();
    const heroTurn = !st.finished && st.turn === heroSeat();
    row.hidden = !heroTurn;
    if ($("plans-area")) $("plans-area").hidden = !heroTurn;
    if (!heroTurn && extrasMode) extrasMode = false;
    if (heroTurn) extras = extras.filter(isLegal);
    const btn = $("btn-extras");
    btn.classList.toggle("on", extrasMode);
    $("extras-note").hidden = !extrasMode;
    $("extras-chips").innerHTML = extras.map((t) =>
      `<span class="chip" data-tok="${t}">${tokHtml(t)} ✕</span>`).join("");
    document.querySelectorAll("#extras-chips .chip").forEach((c) => {
      c.onclick = () => toggleExtra(c.dataset.tok);
    });
  }
  function addCall(tok) {
    if (!isLegal(tok)) return;
    if (extrasMode) { toggleExtra(tok); return; }
    auction.push(tok);
    refreshAuction();
  }

  /* continuation plans: rows of "if I bid C and partner replies R, I bid M"
     — the simulation forces M over the engine's choice at the hero's first
     re-turn (owner spec, round 5) */
  const MAX_PLANS = 6;
  const ALL_CALLS = ["P", "X", "XX"].concat((() => {
    const out = [];
    for (let l = 1; l <= 7; l++)
      for (const d of ["C", "D", "H", "S", "NT"]) out.push(l + d);
    return out;
  })());
  function callText(t) { return t === "P" ? "פאס" : t; }
  function planSelect(cls) {
    const s = document.createElement("select");
    s.className = cls;
    s.innerHTML = '<option value="">—</option>' + ALL_CALLS.map((t) =>
      `<option value="${t}">${callText(t)}</option>`).join("");
    return s;
  }
  function addPlanRow() {
    const box = $("plans-box");
    if (!box || box.children.length >= MAX_PLANS) return;
    const row = document.createElement("div");
    row.className = "plan-row";
    row.appendChild(document.createTextNode("אם אכריז "));
    row.appendChild(planSelect("pl-cand"));
    row.appendChild(document.createTextNode(" ושותף ישיב "));
    row.appendChild(planSelect("pl-reply"));
    row.appendChild(document.createTextNode(" — אכריז "));
    row.appendChild(planSelect("pl-mine"));
    const del = document.createElement("button");
    del.type = "button";
    del.textContent = "✕";
    del.onclick = () => row.remove();
    row.appendChild(del);
    box.appendChild(row);
  }
  function plansList() {
    const out = [];
    document.querySelectorAll("#plans-box .plan-row").forEach((row) => {
      const c = row.querySelector(".pl-cand").value;
      const r = row.querySelector(".pl-reply").value;
      const m = row.querySelector(".pl-mine").value;
      if (c && r && m) out.push([c, r, m]);
    });
    return out.slice(0, MAX_PLANS);
  }
  function buildBBox() {
    const box = $("bbox");
    box.innerHTML = "";
    for (let lvl = 1; lvl <= 7; lvl++)
      for (const dn of DENOMS) {
        const b = document.createElement("button");
        b.type = "button";
        const red = dn === "H" || dn === "D";
        b.innerHTML = lvl + (dn === "NT" ? "NT"
          : `<span${red ? ' class="red"' : ""}>${GLYPH[dn]}</span>`);
        b.dataset.tok = lvl + dn;
        b.onclick = () => addCall(lvl + dn);
        box.appendChild(b);
      }
  }
  function tokHtml(tok) {
    if (tok === "P") return "פאס";
    if (tok === "X" || tok === "XX") return tok;
    const dn = tok.slice(1);
    if (dn === "NT") return tok;
    const red = dn === "H" || dn === "D";
    return tok[0] + `<span${red ? ' class="red"' : ""}>${GLYPH[dn]}</span>`;
  }
  function refreshAuction() {
    const st = replayState();
    const heroTurn = !st.finished && st.turn === heroSeat();
    const strip = $("strip");
    strip.innerHTML = SEATS.map((s) =>
      `<div class="hdr">${SEAT_HE[s]}${s === heroSeat() ? " (אתה)" : ""}</div>`
    ).join("");
    const pad = SEATS.indexOf(dealer());
    for (let i = 0; i < pad; i++) strip.innerHTML += "<div></div>";
    auction.forEach((tok, i) => {
      const hero = seatOf(i) === heroSeat();
      strip.innerHTML += `<div class="cell${hero ? " hero" : ""}">` +
        tokHtml(tok) + "</div>";
    });
    if (heroTurn) {
      // the decision cell: the analyzed call, never entered by the user
      strip.innerHTML += '<div class="cell hero dp">?</div>';
    }
    const tl = $("turnline");
    const note = $("auction-note");
    if (st.finished) {
      tl.innerHTML = "";
      note.hidden = false;
      note.textContent = "המכרז שהוזן כבר הסתיים — יש לעצור בתורך, לפני " +
        "ההכרזה שעליה תישאל. בטל את ההכרזות האחרונות (↩).";
    } else if (heroTurn) {
      note.hidden = false;
      note.textContent = "תורך! ההכרזה הבאה (?) היא שתנותח — אל תזין " +
        'אותה. אפשר ללחוץ "נתח".';
      tl.innerHTML = "";
    } else {
      note.hidden = true;
      tl.innerHTML = "תור: <b>" + SEAT_HE[st.turn] + "</b>";
    }
    document.querySelectorAll("#bbox button").forEach((b) => {
      b.disabled = !isLegal(b.dataset.tok);
    });
    $("btn-p").disabled = !isLegal("P");
    $("btn-x").disabled = !isLegal("X");
    $("btn-xx").disabled = !isLegal("XX");
    $("btn-undo").disabled = auction.length === 0;
    refreshExtras();
    onChange();
  }

  /* ---------- public API ---------- */
  window.BTAnalyzeUI = {
    init(opts) {
      onChange = (opts && opts.onChange) || (() => {});
      buildPicker();
      buildBBox();
      $("btn-p").onclick = () => addCall("P");
      $("btn-x").onclick = () => addCall("X");
      $("btn-xx").onclick = () => addCall("XX");
      $("btn-undo").onclick = () => { auction.pop(); refreshAuction(); };
      $("quickfill").onclick = quickFill;
      $("clearhand").onclick = () => { sel.clear(); refreshPicker(); };
      $("dealer").onchange = refreshAuction;
      $("seat").onchange = refreshAuction;
      if ($("btn-extras"))
        $("btn-extras").onclick = () => {
          extrasMode = !extrasMode;
          refreshExtras();
        };
      if ($("btn-plan-add"))
        $("btn-plan-add").onclick = () => {
          $("plans-note").hidden = false;
          addPlanRow();
        };
      refreshAuction();
    },
    handSize: () => sel.size,
    handPBN,
    auction: () => auction.slice(),
    replayState,
    dealer,
    heroSeat,
    tokHtml,
    ready() {
      const st = replayState();
      return sel.size === 13 && !st.finished && st.turn === heroSeat();
    },
    extraCandidates: () => extras.filter(isLegal),
    plans: plansList,
  };
})();
