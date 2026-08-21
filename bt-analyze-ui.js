// Shared UI logic for the bidding-analysis input flow, used by BOTH front
// ends: the deployed site's analyze.html (submits to Firestore, computed by
// the cloud worker) and the local `trainer analyze` page (submits to the
// local server). Classic script, exposes window.BTAnalyzeUI.
//
// The host page provides the skeleton elements by id (picker, hand-preview,
// quick, quickfill, clearhand, handsum, seat, dealer, vul, strip, turnline,
// bbox, btn-p/btn-x/btn-xx/btn-undo, auction-note, extra-select/extra-add/
// extras-chips, plans-box/btn-plan-add) and calls BTAnalyzeUI.init(...).
// Auction legality mirrors validate/auction_state.py.
//
// INPUT MODEL: the auction is entered UP TO the hero's turn and STOPS there
// — the analyzed call itself is never entered and there are no trailing
// passes. ready() is true exactly when the hand is complete and it is the
// hero's turn in an unfinished auction.
"use strict";
(function () {
  const SUITS = ["S", "H", "D", "C"];
  const GLYPH = { S: "♠", H: "♥", D: "♦", C: "♣" };
  const SUIT_CLS = { S: "ss", H: "sh", D: "sd", C: "sc" };
  const RANKS = "AKQJT98765432";
  const SEAT_HE = { N: "צפון", E: "מזרח", S: "דרום", W: "מערב" };
  const SEATS = ["N", "E", "S", "W"];   // bidding rotation
  const COLS = ["W", "N", "E", "S"];    // display columns (rotation order)
  const DENOMS = ["C", "D", "H", "S", "NT"];

  const sel = new Set();
  let auction = [];
  let onChange = () => {};
  const $ = (id) => document.getElementById(id);

  function suitHtml(s) {
    return `<span class="${SUIT_CLS[s]}">${GLYPH[s]}</span>`;
  }

  /* ---------- card picker + live hand preview ---------- */
  function buildPicker() {
    const root = $("picker");
    root.innerHTML = "";
    for (const s of SUITS) {
      const row = document.createElement("div");
      row.className = "suitrow";
      const g = document.createElement("span");
      g.className = "glyph " + SUIT_CLS[s];
      g.textContent = GLYPH[s];
      row.appendChild(g);
      for (const r of RANKS) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "cardbtn " + SUIT_CLS[s];
        b.textContent = r === "T" ? "10" : r;
        b.dataset.card = s + r;
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
    const pv = $("hand-preview");
    if (pv) {
      pv.hidden = sel.size === 0;
      pv.innerHTML = SUITS.map((s) => {
        const cards = RANKS.split("").filter((r) => sel.has(s + r))
          .map((r) => `<span class="cd">${r === "T" ? "10" : r}</span>`)
          .join("");
        return `<div class="srow">${suitHtml(s)} ${cards || "—"}</div>`;
      }).join("");
    }
    onChange();
  }
  function handPBN() {
    return SUITS.map((s) =>
      RANKS.split("").filter((r) => sel.has(s + r)).join("")).join(".");
  }
  // Quick fill accepts ".", "," and spaces as suit separators, "-" as a
  // void, and "x"/"X" as "the lowest card still free in that suit".
  function quickFill() {
    const t = $("quick").value.trim().toUpperCase();
    const parts = t.split(/[.,\s]+/).filter((p) => p !== "");
    if (parts.length !== 4) {
      alert("פורמט: ארבע סדרות (♠ ♥ ♦ ♣) מופרדות בנקודה/פסיק/רווח; " +
            '"-" לסדרה חסרה'); return;
    }
    const chosen = new Set();
    const wildcards = [];      // [suit, ...] resolved lowest-first at the end
    for (let i = 0; i < 4; i++) {
      if (parts[i] === "-") continue;                    // void
      for (const ch of parts[i]) {
        const r = ch === "0" ? "T" : ch;
        if (r === "X") { wildcards.push(SUITS[i]); continue; }
        if (!RANKS.includes(r)) { alert("קלף לא חוקי: " + ch); return; }
        if (chosen.has(SUITS[i] + r)) { alert("קלף כפול בהזנה"); return; }
        chosen.add(SUITS[i] + r);
      }
    }
    for (const s of wildcards) {   // x -> lowest free card in the suit
      const free = RANKS.split("").reverse()
        .find((r) => !chosen.has(s + r));
      if (!free) { alert("יותר מ-13 קלפים בסדרת " + GLYPH[s]); return; }
      chosen.add(s + free);
    }
    if (chosen.size !== 13) {
      alert("צריך בדיוק 13 קלפים (יש " + chosen.size + ")"); return;
    }
    sel.clear(); chosen.forEach((c) => sel.add(c));
    refreshPicker();
  }

  /* ---------- auction state ---------- */
  function dealer() { return $("dealer").value; }
  function heroSeat() { return $("seat").value; }
  function seatOf(i) { return SEATS[(SEATS.indexOf(dealer()) + i) % 4]; }
  function vulSeats() {
    const v = $("vul") ? $("vul").value : "none";
    const us = "NS".includes(heroSeat()) ? "NS" : "EW";
    if (v === "both") return "NESW";
    if (v === "us") return us;
    if (v === "them") return us === "NS" ? "EW" : "NS";
    return "";
  }
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
  function addCall(tok) {
    if (!isLegal(tok)) return;
    auction.push(tok);
    refreshAuction();
  }

  const ALL_CALLS = ["P", "X", "XX"].concat((() => {
    const out = [];
    for (let l = 1; l <= 7; l++)
      for (const d of DENOMS) out.push(l + d);
    return out;
  })());
  function callText(t) {
    return t === "P" ? "פאס" : (t === "X" ? "דאבל"
      : (t === "XX" ? "רידאבל" : t));
  }

  /* ---------- user-added candidates (a plain select, not a mode) ---------
     the engine's policy can starve a mainstream call (a 0.9% 3NT over a
     preempt) below the menu floor; adding it here forces it into the
     evaluated menu. */
  let extras = [];
  const MAX_EXTRAS = 4;
  function legalCalls() { return ALL_CALLS.filter(isLegal); }
  function refreshExtras() {
    const box = $("extra-select");
    if (!box) return;
    const st = replayState();
    const heroTurn = !st.finished && st.turn === heroSeat();
    const area = $("extras-area");
    if (area) area.hidden = !heroTurn;
    if ($("plans-area")) $("plans-area").hidden = !heroTurn;
    if (!heroTurn) return;
    extras = extras.filter(isLegal);
    const keep = box.value;
    const opts = legalCalls().filter((t) => !extras.includes(t));
    box.innerHTML = '<option value="">בחר הכרזה…</option>' + opts.map((t) =>
      `<option value="${t}">${callText(t)}</option>`).join("");
    if (opts.includes(keep)) box.value = keep;
    const add = $("extra-add");
    if (add) add.disabled = extras.length >= MAX_EXTRAS;
    $("extras-chips").innerHTML = extras.map((t) =>
      `<span class="chip" data-tok="${t}" role="button">` +
      `${tokHtml(t)} <b>✕</b></span>`).join("");
    document.querySelectorAll("#extras-chips .chip").forEach((c) => {
      c.onclick = () => {
        extras = extras.filter((t) => t !== c.dataset.tok);
        refreshExtras();
      };
    });
    refreshPlanCandidates();
  }
  function addExtra() {
    const tok = $("extra-select").value;
    if (!tok || extras.includes(tok) || extras.length >= MAX_EXTRAS) return;
    extras.push(tok);
    $("extra-select").value = "";
    refreshExtras();
  }

  /* ---------- continuation plans -----------------------------------------
     "if I bid C and partner replies R, I bid M" — the simulation forces M
     over the engine's choice at the hero's first re-turn. */
  const MAX_PLANS = 6;
  function planSelect(cls, opts, label) {
    const wrap = document.createElement("label");
    wrap.className = "pl-field";
    wrap.innerHTML = `<span>${label}</span>`;
    const s = document.createElement("select");
    s.className = cls;
    s.innerHTML = '<option value="">—</option>' + opts.map((t) =>
      `<option value="${t}">${callText(t)}</option>`).join("");
    wrap.appendChild(s);
    return wrap;
  }
  function addPlanRow() {
    const box = $("plans-box");
    if (!box || box.children.length >= MAX_PLANS) return;
    const row = document.createElement("div");
    row.className = "plan-row";
    row.appendChild(planSelect("pl-cand", legalCalls(), "אם אכריז"));
    row.appendChild(planSelect("pl-reply", ALL_CALLS, "ושותף ישיב"));
    row.appendChild(planSelect("pl-mine", ALL_CALLS, "אכריז"));
    const del = document.createElement("button");
    del.type = "button";
    del.className = "pl-del";
    del.textContent = "✕";
    del.title = "הסר כלל";
    del.onclick = () => row.remove();
    row.appendChild(del);
    box.appendChild(row);
  }
  // the auction changed -> the legal candidate set changed; refresh the
  // candidate select of every plan row, keeping still-legal picks
  function refreshPlanCandidates() {
    const legal = legalCalls();
    document.querySelectorAll("#plans-box .pl-cand").forEach((s) => {
      const keep = s.value;
      s.innerHTML = '<option value="">—</option>' + legal.map((t) =>
        `<option value="${t}">${callText(t)}</option>`).join("");
      if (legal.includes(keep)) s.value = keep;
    });
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

  /* ---------- bidding box + auction table ---------- */
  function buildBBox() {
    const box = $("bbox");
    box.innerHTML = "";
    for (let lvl = 1; lvl <= 7; lvl++)
      for (const dn of DENOMS) {
        const b = document.createElement("button");
        b.type = "button";
        b.innerHTML = lvl + (dn === "NT" ? "NT" : suitHtml(dn));
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
    return tok[0] + suitHtml(dn);
  }
  function auctionTableHtml(pendingCell) {
    const vul = vulSeats();
    const head = COLS.map((s) => {
      const cls = (vul.includes(s) ? "v" : "nv") +
        (s === heroSeat() ? " me" : "");
      return `<th class="${cls}">${SEAT_HE[s]}` +
        (s === dealer() ? '<sup class="d">D</sup>' : "") +
        `<small>${s === heroSeat() ? "אתה" : "&nbsp;"}</small></th>`;
    }).join("");
    const cells = [];
    for (let i = 0; i < COLS.indexOf(dealer()); i++) cells.push("<td></td>");
    auction.forEach((tok) => {
      cells.push(`<td><span class="call">${tokHtml(tok)}</span></td>`);
    });
    if (pendingCell) cells.push('<td class="turn">?</td>');
    while (cells.length % 4) cells.push("<td></td>");
    let rows = "";
    for (let i = 0; i < cells.length; i += 4)
      rows += "<tr>" + cells.slice(i, i + 4).join("") + "</tr>";
    return `<table class="bidding"><tr>${head}</tr>${rows}</table>`;
  }
  function refreshAuction() {
    const st = replayState();
    const heroTurn = !st.finished && st.turn === heroSeat();
    $("strip").innerHTML = auctionTableHtml(heroTurn);
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
      if ($("vul")) $("vul").addEventListener("change", refreshAuction);
      if ($("extra-add")) $("extra-add").onclick = addExtra;
      if ($("btn-plan-add")) $("btn-plan-add").onclick = addPlanRow;
      refreshAuction();
    },
    handSize: () => sel.size,
    handPBN,
    auction: () => auction.slice(),
    replayState,
    dealer,
    heroSeat,
    tokHtml,
    suitHtml,
    ready() {
      const st = replayState();
      return sel.size === 13 && !st.finished && st.turn === heroSeat();
    },
    extraCandidates: () => extras.filter(isLegal),
    plans: plansList,
    reset() {
      sel.clear();
      auction = [];
      extras = [];
      const pb = $("plans-box");
      if (pb) pb.innerHTML = "";
      if ($("quick")) $("quick").value = "";
      refreshPicker();
      refreshAuction();
    },
  };
})();
