"""Report layer: AnalysisResult -> facts dict -> Hebrew RTL HTML report.

Two-stage by design (spec 4.3): build_facts() emits every number, table and
deal as a structured dict — computed entirely in code. render_report() fills
the fixed report structure (spec 4.1) from those facts with Hebrew
templates: zero marginal cost, deterministic, and the permanent fallback.
The optional LLM narrator (llm_narrator.py) may replace the three PROSE
sections only; tables, numbers and deals always come from here.
"""
from __future__ import annotations

import html
import json
from dataclasses import asdict

import numpy as np

from ..domain.auction import Auction, side_of
from .pipeline import AnalysisResult
from .systems.interpreter import call_he

SUIT_GLYPH = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}
RED = ("H", "D")
SEAT_HE = {"N": "צפון", "E": "מזרח", "S": "דרום", "W": "מערב"}
KIND_HE = {"typical": "תרחיש טיפוסי (חציון)",
           "best": "תרחיש מוצלח (אחוזון 97)",
           "failure": "תרחיש כישלון אופייני (אחוזון 10)",
           "disaster": "תרחיש אסון (אחוזון 2)"}


def vul_he(vul: str, my_seat: str) -> str:
    if vul == "None":
        return "ללא פגיעות"
    if vul == "Both":
        return "שני הצדדים פגיעים"
    return "אנחנו פגיעים" if vul == side_of(my_seat) else "הם פגיעים"


def token_html(tok: str) -> str:
    if tok in ("P", "X", "XX", "—"):
        return {"P": "פאס", "X": "דאבל", "XX": "רידאבל", "—": "—"}[tok]
    denom = tok[1:]
    if denom == "NT":
        return f'<span class="ltr">{tok}</span>'
    cls = ' class="red"' if denom in RED else ""
    return f'<span class="ltr">{tok[0]}<span{cls}>{SUIT_GLYPH[denom]}</span></span>'


def contract_html(spec: str) -> str:
    """'4SEx' / 'Pass-out' -> pretty HTML."""
    if spec in ("Pass-out", "P"):
        return "כולם פאס"
    doubled = spec.endswith("x")
    body = spec[:-1] if doubled else spec
    decl = body[-1]
    tok = body[:-1]
    return (token_html(tok) + ("&#8288;X" if doubled else "")
            + f' <small>({SEAT_HE[decl]})</small>')


def hand_html(pbn: str) -> str:
    parts = pbn.split(".")
    segs = []
    for s, holding in zip("SHDC", parts):
        cls = ' class="red"' if s in RED else ""
        segs.append(f'<span{cls}>{SUIT_GLYPH[s]}</span>'
                    f'<span class="cards">{html.escape(holding) or "—"}</span>')
    return '<span class="hand ltr">' + " ".join(segs) + "</span>"


def hand_box(pbn: str, hcp: int) -> str:
    """The hero's hand as a clear standalone diagram (owner fix #1)."""
    rows = []
    for suit, holding in zip("SHDC", pbn.split(".")):
        cls = ' class="red"' if suit in RED else ""
        cards = " ".join(holding) if holding else "—"
        rows.append(f'<div class="hb-row"><span{cls}>{SUIT_GLYPH[suit]}'
                    f'</span><span class="hb-cards">{cards}</span></div>')
    return ('<div class="handbox" dir="ltr">' + "".join(rows) +
            f'</div><div class="hb-hcp">{hcp} נק"ג</div>')


def _hcp_of(pbn: str) -> int:
    pts = {"A": 4, "K": 3, "Q": 2, "J": 1}
    return sum(pts.get(ch, 0) for ch in pbn)


# ---------------------------------------------------------------------------
def build_facts(res: AnalysisResult) -> dict:
    """Everything the report shows, as JSON-serializable computed facts."""
    req = res.request
    auction = Auction.from_tokens(req.dealer, req.auction)
    seats = [s for s, _ in auction.calls_with_seats()]

    calls = []
    for m in res.meanings:
        calls.append({
            "index": m.index, "seat": m.seat, "seat_he": SEAT_HE[m.seat],
            "token": m.token, "he": m.he, "note": m.note,
            "is_fallback": m.is_fallback, "is_override": m.is_override,
            "is_decision": m.index == req.decision_index,
            "is_hero_side": side_of(m.seat) == side_of(req.my_seat),
        })

    policies = {}
    for name, pol in res.policies.items():
        rows = []
        for cand in res.candidates:
            cr = pol.corrected.result_for(cand)
            rr = pol.raw.result_for(cand)
            diff = pol.corrected.imp_matrix[(cand, cr.best_alternative)]
            median = float(np.median(diff))
            rows.append({
                "action": cand,
                "ev_imp": round(cr.ev_vs_best_alt, 2),
                "ev_imp_raw": round(rr.ev_vs_best_alt, 2),
                "ci": round(cr.ci_half_width, 2),
                "vs": cr.best_alternative,
                "p_gain": round(cr.p_gain, 4),
                "p_loss": round(cr.p_loss, 4),
                "p_push": round(cr.p_push, 4),
                "p_big_gain": round(cr.p_big_gain, 4),
                "p_big_loss": round(cr.p_big_loss, 4),
                "median_imp": round(median, 1),
                "mp_pct": round(pol.mp_pct[cand], 1),
                "top_contracts": pol.contract_freqs[cand],
                "ben_p": round(res.ben_prior.get(cand, 0.0), 4),
                "user_added": cand in res.user_added,
            })
        rows.sort(key=lambda r: (-r["mp_pct"] if req.scoring == "MP"
                                 else -r["ev_imp"]))
        policies[name] = {
            "he": pol.he, "he_desc": pol.he_desc, "rows": rows,
            "top_action": pol.top_action,
            "toss_up": pol.corrected.toss_up,
            "toss_up_with": pol.corrected.toss_up_with,
        }

    seat_of_decision = (seats[req.decision_index]
                        if req.decision_index < len(seats) else req.my_seat)
    return {
        "meta": {
            "dealer": req.dealer, "dealer_he": SEAT_HE[req.dealer],
            "my_seat": req.my_seat, "my_seat_he": SEAT_HE[req.my_seat],
            "vul": req.vul, "vul_he": vul_he(req.vul, req.my_seat),
            "system": req.system, "scoring": req.scoring,
            "scoring_he": ("ניקוד IMP" if req.scoring == "IMP"
                           else "טופ-בוטום (Matchpoints)"),
            "seed": res.seed, "n_deals": res.n_deals,
            "ess": round(res.ess, 1),
            "acceptance_rate": round(res.acceptance_rate, 6),
            "stopped_early": res.stopped_early,
            "shortfall": res.shortfall, "ci_widen": round(res.ci_widen, 3),
            "elapsed_s": round(res.elapsed_s, 1),
            "in_dd_fog": res.in_dd_fog,
        },
        "hand": {"pbn": req.my_hand, "hcp": _hcp_of(req.my_hand)},
        "auction": calls,
        "decision": {"index": req.decision_index, "actual": res.actual_call,
                     "seat_of_decision": seat_of_decision},
        "candidates": res.candidates,
        "policies": policies,
        "recommended": res.recommended,
        "actual_was_recommended": (res.actual_call is not None
                                   and res.actual_call == res.recommended),
        "stability": {"stable": res.stable, "note": res.stability_note},
        "top_pair": {"a": res.top_pair[0], "b": res.top_pair[1],
                     "mean_imp": round(res.top_pair_mean_imp, 2),
                     "ci": round(res.top_pair_ci, 2)},
        "partner_responses": {
            c: res.policies["realistic"].partner_response_freqs[c]
            for c in res.candidates},
        "representative": [asdict(r) for r in res.representative],
        "transparency_notes": list(res.transparency_notes),
    }


# ---------------------------------------------------------------------------
# Hebrew template narration (default + fallback; spec 4.3)

def narrate_situation(facts: dict) -> str:
    reads = []
    for c in facts["auction"]:
        if c["index"] >= facts["decision"]["index"]:
            break
        if c["he"]:
            reads.append(f"{token_html(c['token'])} של {c['seat_he']} — "
                         f"{c['he']}")
    if not reads:
        return ""
    return ("<p>קריאת המכרז: " + "; ".join(reads) + ".</p>")


def _imp_ci(ev: float, ci: float) -> str:
    return f'<span class="ltr">{ev:+.2f} ±{ci:.2f} IMP</span>'


def narrate_candidate(facts: dict, row: dict, is_top: bool) -> str:
    """One tight paragraph per candidate — the tables carry the rest."""
    scoring_mp = facts["meta"]["scoring"] == "MP"
    vs = token_html(row["vs"])
    bits = []
    if scoring_mp:
        bits.append(f'ממוצע <span class="ltr">{row["mp_pct"]:.0f}%</span> '
                    f"במאצ'פוינטס מול שדה החלופות.")
    verb = "מרוויחה" if row["ev_imp"] >= 0 else "מפסידה"
    bits.append(
        f"מול {vs} הפעולה {verb} בממוצע "
        f"{_imp_ci(row['ev_imp'], row['ci'])} — "
        f'רווח <span class="ltr">{row["p_gain"] * 100:.0f}%</span>, '
        f'הפסד <span class="ltr">{row["p_loss"] * 100:.0f}%</span>.')
    if row["p_big_loss"] >= 0.08:
        bits.append(
            f'ב-<span class="ltr">{row["p_big_loss"] * 100:.0f}%</span> '
            f'מהחלוקות ההפסד כבד (<span class="ltr">5+ IMP</span>).')
    if row["top_contracts"]:
        tc = ", ".join(
            f'{contract_html(c)} <span class="ltr">{share * 100:.0f}%</span>'
            for c, share in row["top_contracts"][:3])
        bits.append(f"חוזים שכיחים: {tc}.")
    return "<p>" + " ".join(bits) + "</p>"


def narrate_conclusion(facts: dict) -> str:
    rec = token_html(facts["recommended"])
    actual_tok = facts["decision"]["actual"]
    actual = token_html(actual_tok) if actual_tok else ""
    tp = facts["top_pair"]
    real = facts["policies"]["realistic"]
    scoring_mp = facts["meta"]["scoring"] == "MP"
    lines = []
    # A single bottom line, always: the recommendation, with its measured
    # margin as data (owner decision — no "either is fine" hedging).
    metric = (f'<span class="ltr">{real["rows"][0]["mp_pct"]:.0f}%</span> '
              "במאצ'פוינטס" if scoring_mp else
              _imp_ci(tp["mean_imp"], tp["ci"]))
    lines.append(
        f"ההמלצה: {rec} — {metric} מול "
        f"החלופה הקרובה ביותר ({token_html(tp['b'])}).")
    if actual_tok is None:
        pass   # stem-only mode: the user's choice is unknown by design
    elif facts["actual_was_recommended"]:
        lines.append(f"ההכרזה שבחרת בפועל ({actual}) תואמת את ההמלצה.")
    else:
        row = next((r for r in real["rows"]
                    if r["action"] == facts["decision"]["actual"]), None)
        if row is not None:
            gap = (f'<span class="ltr">{row["mp_pct"]:.0f}%</span> מול '
                   f'<span class="ltr">{real["rows"][0]["mp_pct"]:.0f}%</span>'
                   if scoring_mp else
                   f'פער ממוצע של <span class="ltr">'
                   f'{abs(row["ev_imp"]):.2f} IMP</span>')
            lines.append(
                f"ההכרזה שבחרת בפועל ({actual}) אינה ההמלצה — {gap} "
                f"מול הפעולה המובילה.")
    return "<p>" + "</p>\n<p>".join(lines) + "</p>"


def narrate_all(facts: dict) -> dict:
    """The three prose sections, template-generated (no LLM, zero cost)."""
    real = facts["policies"]["realistic"]
    cands = {}
    for i, row in enumerate(real["rows"]):
        cands[row["action"]] = narrate_candidate(facts, row, i == 0)
    return {
        "situation_html": narrate_situation(facts),
        "candidates_html": cands,
        "conclusion_html": narrate_conclusion(facts),
        "narrator": "template",
    }


# ---------------------------------------------------------------------------
# Full HTML document

_CSS = """
:root {
  --felt: #2E6B4F; --card: #ffffff; --fg: #1C2B24; --muted: #5C6B62;
  --line: #D9E0DA; --accent: #2B6CB0; --accent-tint: #2B6CB014;
  --he-red: #C8102E; --win: #1A7A43; --loss: #C8102E;
  --gold-bg: #FdF6E3; --rec-bg: #E6F4EA;
  --warn-bg: #FDF3DF; --warn-fg: #7A5312; --warn-line: #E3C87F;
}
* { box-sizing: border-box; }
body {
  font-family: "Segoe UI", "Heebo", "Assistant", Arial, "Noto Sans Hebrew",
               sans-serif;
  direction: rtl; max-width: 860px; margin: 0 auto; padding: 20px;
  background: #F2F6F3; color: var(--fg); font-size: 15px; line-height: 1.65;
}
h1 { font-size: 24px; margin: 0 0 4px; }
h2 { font-size: 18px; margin: 26px 0 8px; border-bottom: 2px solid var(--felt);
     padding-bottom: 4px; }
h3 { font-size: 15px; margin: 16px 0 6px; }
.subtitle { color: var(--muted); font-size: 13px; margin-bottom: 18px; }
.card { background: var(--card); border-radius: 12px; padding: 16px 20px;
        margin: 12px 0; box-shadow: 0 1px 3px #0002; }
.red { color: var(--he-red); }
.ltr { direction: ltr; unicode-bidi: isolate; }
.hand .cards { letter-spacing: 1px; font-weight: 600; margin-inline: 2px; }
.handbox { display: inline-block; border: 1px solid var(--line);
  border-radius: 10px; background: var(--gold-bg); padding: 10px 16px;
  font-size: 18px; line-height: 1.5; }
.handbox .hb-row { display: flex; gap: 10px; align-items: baseline; }
.handbox .hb-cards { font-weight: 700; letter-spacing: 2px;
  font-family: "Segoe UI", Arial, sans-serif; }
.hb-hcp { color: var(--muted); font-size: 13px; margin-top: 4px; }
.rec-banner { background: var(--rec-bg); border-right: 5px solid var(--win);
  border-radius: 8px; padding: 12px 16px; margin: 14px 0; font-size: 16px; }
.rec-banner p { margin: 4px 0; }
.auction-grid th.vul { background: #C8102E1f; color: #8F1020; }
.auction-grid th.nv { background: #E6F4EA; color: #1A7A43; }
.tablewrap { overflow-x: auto; max-width: 100%; }
table { border-collapse: collapse; width: 100%; margin: 10px 0;
        font-size: 13.5px; }
th, td { border: 1px solid var(--line); padding: 5px 8px;
         text-align: right; }
th { background: var(--accent-tint); font-weight: 600; }
td.num, th.num { text-align: center; direction: ltr; }
td.act { text-align: center; direction: rtl; font-weight: 600; }
td.act small.vs { display: block; font-weight: 400; font-size: 11px;
                  color: var(--muted); }
tr.rec { background: var(--rec-bg); font-weight: 600; }
tr.actual td:first-child::after { content: " ★"; color: var(--accent); }
.auction-grid { direction: ltr; }
.auction-grid th { text-align: center; }
.auction-grid td { text-align: center; min-width: 64px; }
.auction-grid td.decision { outline: 2px solid var(--accent);
                            background: var(--accent-tint); font-weight: 700; }
.deal-diagram { direction: ltr; display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 4px;
  max-width: 560px; margin: 8px auto; font-size: 13px; }
.deal-diagram .seatbox { border: 1px solid var(--line); border-radius: 8px;
  padding: 6px 8px; background: #fff; overflow-wrap: anywhere; }
.deal-diagram .seatname { font-size: 11px; color: var(--muted); }
.deal-diagram .mid { display: flex; align-items: center; justify-content:
  center; background: var(--felt); color: #fff; border-radius: 8px;
  font-size: 12px; text-align: center; padding: 4px; }
.note { background: var(--warn-bg); color: var(--warn-fg);
        border: 1px solid var(--warn-line); border-radius: 8px;
        padding: 8px 12px; margin: 8px 0; font-size: 13.5px; }
.badge { display: inline-block; border-radius: 999px; padding: 1px 10px;
         font-size: 12px; font-weight: 600; }
.badge.stable { background: var(--rec-bg); color: var(--win); }
.badge.fragile { background: var(--warn-bg); color: var(--warn-fg); }
.small { font-size: 12.5px; color: var(--muted); }
.freq-bar { background: var(--accent-tint); height: 10px; border-radius: 5px;
            display: inline-block; vertical-align: middle; }
@media print {
  body { background: #fff; padding: 0; font-size: 12px; }
  .card { box-shadow: none; border: 1px solid var(--line);
          break-inside: avoid; }
  h2 { break-after: avoid; }
  /* tables must FIT the page — smaller type and padding, wrappable cells */
  table { font-size: 10.5px; }
  th, td { padding: 3px 5px; }
  .tablewrap { overflow-x: visible; }
  .deal-diagram { font-size: 11px; }
}
"""


def render_report(facts: dict, prose: dict | None = None) -> str:
    """The full RTL Hebrew HTML report (spec 4.1 structure, 4.2 design)."""
    p = prose or narrate_all(facts)
    m = facts["meta"]
    real = facts["policies"]["realistic"]
    scoring_mp = m["scoring"] == "MP"

    parts: list[str] = []
    parts.append(f"""<!DOCTYPE html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ניתוח הכרזה — BridgeTrainer</title>
<style>{_CSS}</style></head><body>
<h1>דוח ניתוח הכרזה</h1>
<div class="subtitle">BridgeTrainer · {m['scoring_he']} · {m['vul_he']} ·
מחלק: {m['dealer_he']} · {_engine_label(facts)}</div>""")

    # the bottom line first — one recommendation, no hedging
    parts.append(f'<div class="rec-banner">{p["conclusion_html"]}</div>')

    # 1 -----------------------------------------------------------------
    parts.append('<h2>1. היד והמכרז</h2><div class="card">')
    parts.append(hand_box(facts["hand"]["pbn"], facts["hand"]["hcp"]))
    parts.append(_auction_table(facts))
    parts.append(p["situation_html"])
    for n in facts["transparency_notes"]:
        parts.append(f'<div class="note">{html.escape(n)}</div>')
    parts.append("</div>")

    # 2 -----------------------------------------------------------------
    # a summary card for candidates the engine takes seriously (policy
    # >= 2%) or that EARNED it in the simulation (top 3 by result) or that
    # the user asked about; the rest still appear in the table.
    parts.append('<h2>2. הפעולות המועמדות</h2>')
    skipped = []
    for i, row in enumerate(real["rows"]):
        in_summary = (i < 3 or row.get("ben_p", 1.0) >= 0.02
                      or row.get("user_added")
                      or row["action"] == facts["decision"]["actual"]
                      or row["action"] == facts["recommended"])
        if not in_summary:
            skipped.append(row["action"])
            continue
        star = " ★ (ההכרזה שלך בפועל)" \
            if row["action"] == facts["decision"]["actual"] else ""
        rec = " — הפעולה המומלצת" \
            if row["action"] == facts["recommended"] else ""
        added = " (מועמדת שהוספת)" if row.get("user_added") else ""
        parts.append(f'<div class="card"><h3>{token_html(row["action"])}'
                     f'{rec}{star}{added}</h3>')
        parts.append(p["candidates_html"].get(
            row["action"], narrate_candidate(facts, row, i == 0)))
        parts.append("</div>")
    if skipped:
        parts.append(
            '<p class="small">מועמדות נוספות שנבדקו מופיעות בטבלה בסעיף '
            '3: ' + ", ".join(token_html(t) for t in skipped) + '.</p>')

    # 3 -----------------------------------------------------------------
    parts.append('<h2>3. תוצאות הסימולציה</h2><div class="card">')
    parts.append(_results_table(facts, "realistic"))
    parts.append(
        f'<p class="small">מדגם: <span class="ltr">{m["n_deals"]}</span> '
        f'חלוקות · התאמת המכרז לשיטת המנוע: '
        f'<span class="ltr">{m["acceptance_rate"] * 100:.0f}%</span> · '
        f'<span class="ltr">seed {m["seed"]}</span> · '
        f'<span class="ltr">{m["elapsed_s"]:.0f}</span> שניות. '
        f'ה-IMP מחושב מול החלופה החזקה ביותר לכל פעולה, בניקוד '
        f'דאבל-דאמי; ההמשכים בכל חלוקה הוכרזו על ידי המנוע עבור כל '
        f'ארבעת המושבים עד סוף המכרז.</p>')
    parts.append("</div>")

    # 4 -----------------------------------------------------------------
    parts.append('<h2>4. שכיחויות מפתח</h2><div class="card">')
    parts.append("<h3>תגובת השותף הראשונה</h3>")
    parts.append(_partner_response_table(facts))
    parts.append("<h3>החוזים הסופיים השכיחים</h3>")
    parts.append(_contracts_table(facts))
    parts.append("</div>")

    # 5 -----------------------------------------------------------------
    parts.append('<h2>5. חלוקות מייצגות</h2>')
    rec_tok, alt_tok = facts["top_pair"]["a"], facts["top_pair"]["b"]
    for rep in facts["representative"]:
        parts.append('<div class="card">')
        parts.append(f'<h3>{KIND_HE.get(rep["kind"], rep["kind"])}</h3>')
        parts.append(_deal_diagram(rep["hands"], facts["meta"]["my_seat"]))
        parts.append(
            f'<p>{token_html(rec_tok)} מוביל ל-{contract_html(rep["contract_top"])} '
            f'(<span class="ltr">{rep["score_top"]:+.0f}</span>); '
            f'{token_html(alt_tok)} מוביל ל-{contract_html(rep["contract_alt"])} '
            f'(<span class="ltr">{rep["score_alt"]:+.0f}</span>). '
            f'הפרש: <b class="ltr">{rep["imp_swing"]:+.0f} IMP</b> '
            f'לטובת {token_html(rec_tok if rep["imp_swing"] >= 0 else alt_tok)}.</p>')
        for tok, cont in ((rec_tok, rep.get("cont_top")),
                          (alt_tok, rep.get("cont_alt"))):
            parts.append(f'<p class="small">המשך משוער אחרי '
                         f'{token_html(tok)}: {_continuation_html(cont)}</p>')
        parts.append("</div>")

    parts.append("</body></html>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
def _engine_label(facts: dict) -> str:
    if len(facts["policies"]) == 1:
        return "מנוע Ben"
    m = facts["meta"]
    return "שיטה: " + ("SAYC" if m["system"] == "sayc" else "2/1 Game Force")


def _auction_table(facts: dict) -> str:
    rows_calls = facts["auction"]
    dealer = facts["meta"]["dealer"]
    vul = facts["meta"]["vul"]
    order = ["W", "N", "E", "S"]
    out = ['<div class="tablewrap"><table class="auction-grid"><tr>']
    for s in order:
        mark = " (אתה)" if s == facts["meta"]["my_seat"] else ""
        side = "NS" if s in "NS" else "EW"
        cls = "vul" if vul in (side, "Both") else "nv"
        out.append(f'<th class="{cls}">{SEAT_HE[s]}{mark}</th>')
    out.append("</tr><tr>")
    pad = order.index(dealer)
    for _ in range(pad):
        out.append("<td></td>")
    col = pad
    for c in rows_calls:
        if col == 4:
            out.append("</tr><tr>")
            col = 0
        cls = ' class="decision"' if c["is_decision"] else ""
        title = html.escape(c["he"] or "")
        out.append(f'<td{cls} title="{title}">{token_html(c["token"])}</td>')
        col += 1
    if facts["decision"]["index"] == len(rows_calls):
        # stem-only mode: the analyzed call is the NEXT one — show it as "?"
        if col == 4:
            out.append("</tr><tr>")
            col = 0
        out.append('<td class="decision" title="ההכרזה המנותחת">?</td>')
        col += 1
    for _ in range(col, 4):
        out.append("<td></td>")
    out.append("</tr></table></div>")
    out.append('<p class="small">אדום — צד פגיע; ירוק — צד לא פגיע. '
               'התור המנותח מסומן ?.</p>')
    # call-by-call meanings list — only when glosses exist (the Ben path
    # carries no per-call system glosses by owner decision)
    if any(c["he"] for c in rows_calls):
        out.append("<details><summary>משמעויות ההכרזות, אחת-אחת</summary><ul>")
        for c in rows_calls:
            flag = ""
            if c["is_override"]:
                flag = ' <span class="badge fragile">הסכם אישי</span>'
            elif c["is_fallback"]:
                flag = ' <span class="badge fragile">ברירת מחדל</span>'
            out.append(f"<li>{SEAT_HE[c['seat']]}: {token_html(c['token'])} — "
                       f"{c['he'] or '—'}{flag}</li>")
        out.append("</ul></details>")
    return "".join(out)


def _results_table(facts: dict, policy: str) -> str:
    pol = facts["policies"][policy]
    scoring_mp = facts["meta"]["scoring"] == "MP"
    # short headers — the table must fit a phone screen and a printed page.
    # single-engine (Ben) facts carry one score level, so no raw-DD column.
    single = len(facts["policies"]) == 1
    head = ["פעולה", "IMP ממוצע", "בר-סמך"] + \
        ([] if single else ["DD גולמי"]) + ["% רווח", "% הפסד", "חציון"]
    if scoring_mp:
        head.insert(1, "MP %")
    out = ['<div class="tablewrap"><table><tr>'] + \
        [f"<th class='num'>{h}</th>" for h in head]
    out.append("</tr>")
    for row in pol["rows"]:
        classes = []
        if row["action"] == facts["recommended"]:
            classes.append("rec")
        if row["action"] == facts["decision"]["actual"]:
            classes.append("actual")
        cls = f' class="{" ".join(classes)}"' if classes else ""
        act = (token_html(row["action"]) +
               f'<small class="vs">מול {token_html(row["vs"])}</small>')
        cells = [act,
                 f"{row['ev_imp']:+.2f}",
                 f"±{row['ci']:.2f}"] + \
            ([] if single else [f"{row['ev_imp_raw']:+.2f}"]) + \
            [f"{row['p_gain'] * 100:.0f}%",
             f"{row['p_loss'] * 100:.0f}%",
             f"{row['median_imp']:+.1f}"]
        if scoring_mp:
            cells.insert(1, f"{row['mp_pct']:.1f}%")
        tds = [f'<td class="act">{cells[0]}</td>'] + \
            [f'<td class="num">{c}</td>' for c in cells[1:]]
        out.append(f"<tr{cls}>" + "".join(tds) + "</tr>")
    out.append("</table></div>")
    return "".join(out)


def _policy_summary_table(facts: dict) -> str:
    out = ['<div class="tablewrap"><table><tr><th>מנוע ההמשכים</th>'
           "<th>תיאור</th><th class='num'>הפעולה המובילה</th></tr>"]
    for name, pol in facts["policies"].items():
        out.append(f"<tr><td>{pol['he']}</td><td>{pol['he_desc']}</td>"
                   f"<td class='num'>{token_html(pol['top_action'])}</td></tr>")
    out.append("</table></div>")
    return "".join(out)


def _partner_response_table(facts: dict) -> str:
    out = ['<div class="tablewrap"><table><tr><th>הפעולה</th>'
           "<th>תגובות השותף (שכיחות)</th></tr>"]
    for cand in facts["candidates"]:
        rows = facts["partner_responses"].get(cand) or []
        cells = []
        for tok, share in rows:
            if share < 0.02:
                continue
            w = max(3, int(share * 120))
            cells.append(f'{token_html(tok)} '
                         f'<span class="freq-bar" style="width:{w}px"></span> '
                         f'<span class="ltr">{share * 100:.0f}%</span>')
        out.append(f"<tr><td>{token_html(cand)}</td>"
                   f"<td>{' &nbsp; '.join(cells) or '—'}</td></tr>")
    out.append("</table></div>")
    return "".join(out)


def _contracts_table(facts: dict) -> str:
    pol = facts["policies"]["realistic"]
    out = ['<div class="tablewrap"><table><tr><th>הפעולה</th>'
           "<th>חוזים סופיים (שכיחות במדגם)</th></tr>"]
    for row in pol["rows"]:
        cells = [f"{contract_html(c)} <span class='ltr'>"
                 f"{share * 100:.0f}%</span>"
                 for c, share in row["top_contracts"] if share >= 0.02]
        out.append(f"<tr><td>{token_html(row['action'])}</td>"
                   f"<td>{' &nbsp;·&nbsp; '.join(cells) or '—'}</td></tr>")
    out.append("</table></div>")
    return "".join(out)


def _continuation_html(cont: list | None) -> str:
    """(seat, call) pairs -> 'מערב: פאס · צפון: 5♣ · ...' (trailing passes
    were already trimmed by the pipeline)."""
    if not cont:
        return "שלושה פאסים — סוף המכרז."
    bits = [f"{SEAT_HE[s]}: {token_html(t)}" for s, t in cont]
    return " · ".join(bits) + " · ואז פאסים עד הסוף."


def _deal_diagram(hands: dict, my_seat: str) -> str:
    def box(seat):
        me = " (אתה)" if seat == my_seat else ""
        return (f'<div class="seatbox"><div class="seatname">'
                f'{SEAT_HE[seat]}{me}</div>{hand_html(hands[seat])}</div>')
    return ('<div class="deal-diagram">'
            f'<div></div>{box("N")}<div></div>'
            f'{box("W")}<div class="mid">♠♥♦♣</div>{box("E")}'
            f'<div></div>{box("S")}<div></div>'
            "</div>")


def facts_to_json(facts: dict) -> str:
    return json.dumps(facts, ensure_ascii=False, indent=1)
