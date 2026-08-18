// Shared UI logic for the bidding-analysis input flow, used by BOTH front
// ends: the deployed site's analyze.html (submits to Firestore, computed by
// the GitHub Actions worker) and the local `trainer analyze` page (submits
// to the local server). Classic script, exposes window.BTAnalyzeUI.
//
// The host page provides the skeleton elements by id (picker, quick,
// quickfill, clearhand, handsum, seat, dealer, strip, turnline, bbox,
// btn-p/btn-x/btn-xx/btn-undo, auction-note, ovr-list, dp-list) and calls
// BTAnalyzeUI.init({onChange}). Auction legality mirrors
// validate/auction_state.py (bid ordering, X/XX rules, three passes end).
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
  const overrides = {};          // index -> {hcp?, suits, note}
  const decisionPoints = new Set();
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
  function addCall(tok) {
    if (!isLegal(tok)) return;
    auction.push(tok);
    refreshAuction();
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
    if (tok === "P") return "פס";
    if (tok === "X" || tok === "XX") return tok;
    const dn = tok.slice(1);
    if (dn === "NT") return tok;
    const red = dn === "H" || dn === "D";
    return tok[0] + `<span${red ? ' class="red"' : ""}>${GLYPH[dn]}</span>`;
  }
  function refreshAuction() {
    const st = replayState();
    const strip = $("strip");
    strip.innerHTML = SEATS.map((s) =>
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
    const tl = $("turnline");
    const note = $("auction-note");
    if (st.finished) {
      tl.innerHTML = "";
      note.hidden = false;
      note.textContent = auction.length >= 4 && st.level === 0
        ? "המכרז הסתיים: כולם פסו (אין משחק)."
        : "המכרז הושלם (שלושה פסים רצופים) — בחר נקודות החלטה למטה.";
    } else {
      note.hidden = true;
      tl.innerHTML = "תור: <b>" + SEAT_HE[st.turn] +
        (st.turn === heroSeat() ? " (אתה)" : "") + "</b>";
    }
    document.querySelectorAll("#bbox button").forEach((b) => {
      b.disabled = !isLegal(b.dataset.tok);
    });
    $("btn-p").disabled = !isLegal("P");
    $("btn-x").disabled = !isLegal("X");
    $("btn-xx").disabled = !isLegal("XX");
    $("btn-undo").disabled = auction.length === 0;
    // drop decision points / overrides that fell off the end after an undo
    for (const i of [...decisionPoints]) {
      if (i >= auction.length || seatOf(i) !== heroSeat())
        decisionPoints.delete(i);
    }
    for (const k of Object.keys(overrides))
      if (+k >= auction.length) delete overrides[k];
    refreshOverrides();
    refreshDecisionPoints(st);
    onChange();
  }

  /* ---------- overrides ---------- */
  function refreshOverrides() {
    const root = $("ovr-list");
    if (!root) return;
    if (!auction.length) {
      root.innerHTML =
        '<span style="color:var(--muted)">הזן מכרז תחילה.</span>';
      return;
    }
    root.innerHTML = "";
    auction.forEach((tok, i) => {
      if (tok === "P" && !(i in overrides)) return;
      const d = document.createElement("details");
      d.className = "ovr";
      const has = i in overrides;
      d.innerHTML = `<summary>הכרזה ${i + 1}: ${tokHtml(tok)} של ` +
        `${SEAT_HE[seatOf(i)]}` +
        (has ? ' <span class="badge">הסכם אישי</span>' : "") + `</summary>` +
        `<div class="row"><label>נק' מ-</label>` +
        `<input type="number" min="0" max="40" id="ov-${i}-lo">` +
        `<label>עד</label>` +
        `<input type="number" min="0" max="40" id="ov-${i}-hi">` +
        SUITS.map((s) =>
          `<label class="${s === "H" || s === "D" ? "red" : ""}">` +
          `${GLYPH[s]}</label><input type="number" min="0" max="13" ` +
          `id="ov-${i}-${s}-lo" placeholder="מינ'">` +
          `<input type="number" min="0" max="13" id="ov-${i}-${s}-hi" ` +
          `placeholder="מקס'">`).join("") +
        `</div><div class="row"><label>הערה:</label>` +
        `<input type="text" id="ov-${i}-note" size="34" maxlength="140" ` +
        `placeholder="למשל: 3♣ כאן = מזמין ולא מנע"></div>` +
        `<div class="row"><button type="button" data-save="${i}">` +
        `שמור דריסה</button>` +
        `<button type="button" data-clear="${i}">נקה</button></div>`;
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
    root.querySelectorAll("button[data-save]").forEach((b) =>
      (b.onclick = () => {
        const i = +b.dataset.save;
        const v = (id) => $(id).value;
        const lo = v(`ov-${i}-lo`), hi = v(`ov-${i}-hi`);
        const o = { suits: {}, note: v(`ov-${i}-note`).trim() };
        if (lo !== "" && hi !== "") o.hcp = [+lo, +hi];
        for (const s of SUITS) {
          const a = v(`ov-${i}-${s}-lo`), c = v(`ov-${i}-${s}-hi`);
          if (a !== "" && c !== "") o.suits[s] = [+a, +c];
        }
        if (!o.hcp && !Object.keys(o.suits).length && !o.note)
          delete overrides[i];
        else overrides[i] = o;
        refreshOverrides();
        onChange();
      }));
    root.querySelectorAll("button[data-clear]").forEach((b) =>
      (b.onclick = () => {
        delete overrides[+b.dataset.clear];
        refreshOverrides();
        onChange();
      }));
  }

  /* ---------- decision points ---------- */
  function refreshDecisionPoints(st) {
    const root = $("dp-list");
    if (!root) return;
    const heroIdx = auction.map((t, i) => i)
      .filter((i) => seatOf(i) === heroSeat());
    if (!st.finished || !heroIdx.length) {
      root.innerHTML = '<span style="color:var(--muted)">בחר לאחר ' +
        'השלמת המכרז (אפשר יותר מאחת).</span>';
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
    root.querySelectorAll("input").forEach((c) =>
      (c.onchange = () => {
        const i = +c.dataset.i;
        if (c.checked) decisionPoints.add(i);
        else decisionPoints.delete(i);
        refreshAuction();
      }));
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
      refreshAuction();
    },
    handSize: () => sel.size,
    handPBN,
    auction: () => auction.slice(),
    replayState,
    decisionPoints: () => [...decisionPoints].sort((a, b) => a - b),
    overrides: () => JSON.parse(JSON.stringify(overrides)),
    dealer,
    heroSeat,
    tokHtml,
    ready() {
      return sel.size === 13 && replayState().finished &&
        decisionPoints.size > 0;
    },
  };
})();
