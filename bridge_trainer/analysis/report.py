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
           "disaster": "תרחיש אסון (הגרוע במדגם)"}


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
        return "עובר (ללא משחק)"
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
            "scoring_he": ("מפגשי (IMP)" if req.scoring == "IMP"
                           else "ניקוד מקסימלי (Matchpoints)"),
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
    m = facts["meta"]
    lines = []
    lines.append(
        f"אתה יושב ב{m['my_seat_he']}, המחלק {m['dealer_he']}, "
        f"{m['vul_he']}, {_engine_label(facts)}, "
        f"סוג התחרות: {m['scoring_he']}. "
        f"בידך {hand_html(facts['hand']['pbn'])} "
        f"({facts['hand']['hcp']} נק').")
    reads = []
    for c in facts["auction"]:
        if c["index"] >= facts["decision"]["index"]:
            break
        if c["token"] == "P" and not c["he"]:
            continue
        who = ("השותף" if c["is_hero_side"]
               and c["seat"] != facts["meta"]["my_seat"] else
               c["seat_he"])
        if c["he"]:
            reads.append(f"{token_html(c['token'])} של {who} — {c['he']}")
    if reads:
        lines.append("קריאת המכרז עד נקודת ההחלטה: " +
                     "; ".join(reads) + ".")
    lines.append(
        "חשוב לזכור שגם פאס נושא מידע: טווחי הנקודות והאורכים של כל "
        "המושבים החבויים נגזרו מכל ההכרזות שקדמו להחלטה, כולל הפסים.")
    return "<p>" + "</p>\n<p>".join(lines) + "</p>"


def narrate_candidate(facts: dict, row: dict, is_top: bool) -> str:
    """Template prose for one candidate: what the stats say and WHY."""
    scoring_mp = facts["meta"]["scoring"] == "MP"
    a = token_html(row["action"])
    vs = token_html(row["vs"])
    bits = []
    if scoring_mp:
        bits.append(
            f"במאצ'פוינטס {a} משיג בממוצע {row['mp_pct']:.0f}% מול שדה "
            f"החלופות שנבדקו — "
            + ("הציון הגבוה במדגם." if is_top else "פחות מהחלופה המובילה."))
    if row["ev_imp"] >= 0:
        bits.append(
            f"מול החלופה הקשה ביותר שלו ({vs}) הפעולה מרוויחה בממוצע "
            f"{row['ev_imp']:+.2f} IMP (רווח סמך ±{row['ci']:.2f}).")
    else:
        bits.append(
            f"מול {vs} הפעולה מפסידה בממוצע {abs(row['ev_imp']):.2f} IMP "
            f"(רווח סמך ±{row['ci']:.2f}).")
    bits.append(
        f"היא זוכה ב-{row['p_gain'] * 100:.0f}% מהחלוקות, מפסידה "
        f"ב-{row['p_loss'] * 100:.0f}%, ושוויון ב-{row['p_push'] * 100:.0f}%.")
    if row["p_big_loss"] >= 0.08:
        bits.append(
            f"שימו לב לזנב הסיכון: ב-{row['p_big_loss'] * 100:.0f}% "
            f"מהחלוקות ההפסד חד (5+ IMP) — הפעולה תנודתית, והמחיר "
            f"כשהיא נכשלת גבוה.")
    elif row["p_big_gain"] >= 0.15:
        bits.append(
            f"פרופיל הרווח נוטה לזכיות גדולות: ב-{row['p_big_gain'] * 100:.0f}% "
            f"מהחלוקות הרווח הוא 5+ IMP.")
    if row["top_contracts"]:
        tc = ", ".join(
            f"{contract_html(c)} ({share * 100:.0f}%)"
            for c, share in row["top_contracts"][:3])
        bits.append(f"החוזים השכיחים בהמשך (מדיניות ריאלית): {tc}.")
    resp = facts["partner_responses"].get(row["action"]) or []
    resp = [(t, s) for t, s in resp if s >= 0.05]
    if len(resp) > 1:
        rr = ", ".join(f"{token_html(t)} ({s * 100:.0f}%)" for t, s in resp)
        bits.append(f"תגובות השותף מתפזרות: {rr}.")
    return "<p>" + " ".join(bits) + "</p>"


def narrate_conclusion(facts: dict) -> str:
    rec = token_html(facts["recommended"])
    actual_tok = facts["decision"]["actual"]
    actual = token_html(actual_tok) if actual_tok else ""
    tp = facts["top_pair"]
    real = facts["policies"]["realistic"]
    scoring_mp = facts["meta"]["scoring"] == "MP"
    lines = []
    if real["toss_up"]:
        tied = " / ".join(token_html(t) for t in
                          [real["top_action"]] + real["toss_up_with"])
        lines.append(
            f"השורה התחתונה: המדגם אינו מפריד בין {tied} — ההפרש "
            f"({tp['mean_imp']:+.2f} IMP) קטן מרווח הסמך (±{tp['ci']:.2f}) "
            f"או מסף המשמעות המעשית (0.5 IMP). זו החלטה שקולה באמת, "
            f"ואף בחירה אינה טעות.")
    else:
        metric = (f"{real['rows'][0]['mp_pct']:.0f}% במאצ'פוינטס"
                  if scoring_mp else
                  f"{tp['mean_imp']:+.2f} IMP (רווח סמך ±{tp['ci']:.2f})")
        lines.append(
            f"השורה התחתונה: {rec} היא הפעולה המומלצת — {metric} מול "
            f"החלופה הקרובה ביותר ({token_html(tp['b'])}).")
    if actual_tok is None:
        pass   # stem-only mode: the user's choice is unknown by design
    elif facts["actual_was_recommended"]:
        lines.append(f"ההכרזה שבחרת בפועל ({actual}) תואמת את ההמלצה.")
    else:
        row = next((r for r in real["rows"]
                    if r["action"] == facts["decision"]["actual"]), None)
        if row is not None:
            gap = (f"{row['mp_pct']:.0f}% מול "
                   f"{real['rows'][0]['mp_pct']:.0f}%" if scoring_mp else
                   f"פער ממוצע של {abs(row['ev_imp']):.2f} IMP")
            lines.append(
                f"ההכרזה שבחרת בפועל ({actual}) אינה ההמלצה — {gap} "
                f"מול הפעולה המובילה.")
    lines.append(facts["stability"]["note"])
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
.tablewrap { overflow-x: auto; max-width: 100%; }
table { border-collapse: collapse; width: 100%; margin: 10px 0;
        font-size: 13.5px; }
th, td { border: 1px solid var(--line); padding: 5px 8px;
         text-align: right; }
th { background: var(--accent-tint); font-weight: 600; }
td.num, th.num { text-align: center; direction: ltr; }
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
<div class="subtitle">BridgeTrainer · {m['scoring_he']} ·
{_engine_label(facts)} ·
{m['vul_he']} · מחלק: {m['dealer_he']} ·
מנסח: {'LLM' if p.get('narrator') == 'llm' else 'תבניות (ללא LLM)'}</div>""")

    # 1 -----------------------------------------------------------------
    parts.append('<h2>1. תיאור המצב וקריאת המכרז</h2><div class="card">')
    parts.append(p["situation_html"])
    parts.append(_auction_table(facts))
    fallback_rows = [c for c in facts["auction"]
                     if (c["is_fallback"] or c["is_override"]) and c["note"]]
    if facts["transparency_notes"] or fallback_rows:
        parts.append("<h3>הערות שקיפות על פרשנות המכרז</h3>")
        for n in facts["transparency_notes"]:
            parts.append(f'<div class="note">{html.escape(n)}</div>')
    parts.append("</div>")

    # 2 -----------------------------------------------------------------
    parts.append('<h2>2. הפעולות המועמדות — ניתוח</h2>')
    for i, row in enumerate(real["rows"]):
        star = " ★ (ההכרזה שלך בפועל)" \
            if row["action"] == facts["decision"]["actual"] else ""
        rec = " — הפעולה המומלצת" \
            if row["action"] == facts["recommended"] else ""
        parts.append(f'<div class="card"><h3>{token_html(row["action"])}'
                     f'{rec}{star}</h3>')
        parts.append(p["candidates_html"].get(
            row["action"], narrate_candidate(facts, row, i == 0)))
        parts.append("</div>")

    # 3 -----------------------------------------------------------------
    parts.append('<h2>3. טבלת תוצאות הסימולציה</h2><div class="card">')
    parts.append(_results_table(facts, "realistic"))
    parts.append(
        f'<p class="small">מדגם בפועל: {m["n_deals"]} חלוקות '
        f'(מדגם אפקטיבי ESS: {m["ess"]}); '
        + ("הדגימה נעצרה מוקדם — ההפרש בין שתי הפעולות המובילות הוכרע "
           "סטטיסטית. " if m["stopped_early"] else
           "הדגימה מוצתה עד התקרה. ")
        + ("עמודת ה-IMP מחושבת מול החלופה הקשה ביותר של כל פעולה, "
           "בניקוד דאבל-דאמי על חוזה הרולאאוט."
           if len(facts["policies"]) == 1 else
           'עמודת ה-IMP מחושבת מול החלופה הקשה ביותר של כל פעולה, לאחר '
           'כיול single-dummy; עמודת DD גולמי מוצגת לצידה (INV5).')
        + "</p>")
    if m["in_dd_fog"]:
        parts.append('<div class="note">אזהרת "ערפל DD": ההמלצה לפי הציון '
                     'הגולמי ולפי הציון המכויל שונה — הבעיה נמצאת בטווח '
                     'שבו הנחת המשחק המושלם משנה את התשובה.</div>')
    parts.append("<h3>" + ("אמינות מנוע ההמשכים"
                           if len(facts["policies"]) == 1
                           else "יציבות בין מדיניות ההמשך") + "</h3>")
    badge = ('<span class="badge stable">מסקנה יציבה</span>'
             if facts["stability"]["stable"]
             else '<span class="badge fragile">רגיש להנחות</span>')
    parts.append(f"<p>{badge} {html.escape(facts['stability']['note'])}</p>")
    parts.append(_policy_summary_table(facts))
    parts.append("</div>")

    # 4 -----------------------------------------------------------------
    parts.append('<h2>4. טבלאות תדירויות מפתח</h2><div class="card">')
    parts.append("<h3>תגובת השותף הראשונה (מדיניות ריאלית)</h3>")
    parts.append(_partner_response_table(facts))
    parts.append("<h3>החוזים הסופיים השכיחים</h3>")
    parts.append(_contracts_table(facts))
    parts.append("</div>")

    # 5 -----------------------------------------------------------------
    parts.append('<h2>5. חלוקות מייצגות מהסימולציה</h2>')
    rec_tok, alt_tok = facts["top_pair"]["a"], facts["top_pair"]["b"]
    for rep in facts["representative"]:
        parts.append('<div class="card">')
        parts.append(f'<h3>{KIND_HE.get(rep["kind"], rep["kind"])}</h3>')
        parts.append(_deal_diagram(rep["hands"], facts["meta"]["my_seat"]))
        parts.append(
            f'<p>{token_html(rec_tok)} מוביל ל-{contract_html(rep["contract_top"])} '
            f'(ציון {rep["score_top"]:+.0f}); '
            f'{token_html(alt_tok)} מוביל ל-{contract_html(rep["contract_alt"])} '
            f'(ציון {rep["score_alt"]:+.0f}). '
            f'הפרש: <b class="ltr">{rep["imp_swing"]:+.0f} IMP</b> '
            f'לטובת {token_html(rec_tok if rep["imp_swing"] >= 0 else alt_tok)}.</p>')
        for tok, cont in ((rec_tok, rep.get("cont_top")),
                          (alt_tok, rep.get("cont_alt"))):
            parts.append(f'<p class="small">המשך משוער אחרי '
                         f'{token_html(tok)}: {_continuation_html(cont)}</p>')
        parts.append("</div>")

    # 6 -----------------------------------------------------------------
    parts.append('<h2>6. סייגים על הסימולציה</h2><div class="card"><ul>')
    parts.append(
        f"<li>גודל מדגם: {m['n_deals']} חלוקות (ESS {m['ess']}), "
        f"שיעור קבלה בדגימה {m['acceptance_rate'] * 100:.3f}%. "
        f"רווח הסמך של ההפרש המוביל: ±{facts['top_pair']['ci']:.2f} IMP "
        f"(95%).</li>")
    if m["shortfall"]:
        parts.append(
            f"<li>הדגימה לא השלימה את התקרה (חסרות {m['shortfall']} "
            f"חלוקות) — רווחי הסמך הורחבו פי {m['ci_widen']}.</li>")
    if len(facts["policies"]) == 1:
        parts.append(
            "<li>הניקוד הוא דאבל-דאמי גולמי על החוזה שאליו הגיע המכרז "
            "המדומה בכל חלוקה. דאבל-דאמי מחמיא מעט לכרוז (במיוחד ב-NT); "
            "מכיוון שהוא מוחל באופן זהה על כל המועמדים, ההשוואה ביניהם "
            "יציבה יותר מהערכים המוחלטים.</li>")
    else:
        parts.append(
            "<li>תוצאות דאבל-דאמי מחמיאות לכרוז (במיוחד ב-NT); הציונים "
            "המוצגים עברו כיול single-dummy סימטרי לפי טבלה נערכת "
            "(bridge_trainer/dd/correction_table.yaml), ושתי הרמות — "
            "גולמי ומכויל — מוצגות בטבלת התוצאות.</li>")
    if len(facts["policies"]) == 1:
        only = next(iter(facts["policies"].values()))
        parts.append(
            f"<li>המשכי המכרז: {html.escape(only['he'])} — הדגימה, "
            "הכרזות ההמשך של כל ארבעת המושבים והחוזה הסופי בכל חלוקה "
            "מגיעים ממנוע ההכרזות הנוירוני, לא מחוקים ידניים. עקביות "
            "המכרז עם שיטת המנוע מוצגת בסעיף 3.</li>")
    else:
        parts.append(
            "<li>המשכי המכרז חושבו תחת שלוש מדיניות (שמרנית / ריאלית / "
            "חסם עליון רואה-קלפים); כל הפרמטרים ב-analysis/policies.yaml. "
            "בכל המדיניות היריבים מכפילים עונשין חוזה בגובה 4+ עם סטאק "
            "בשליט.</li>")
    if scoring_mp:
        parts.append(
            "<li>במאצ'פוינטס ה\"שדה\" מקורב על ידי תוצאות החלופות שנבדקו "
            "על אותה חלוקה — קירוב מקובל בהעדר נתוני שדה אמיתיים.</li>")
    parts.append(
        f"<li>ריצה דטרמיניסטית: seed {m['seed']}; זמן חישוב "
        f"{m['elapsed_s']} שניות.</li>")
    parts.append("</ul></div>")

    # 7 -----------------------------------------------------------------
    parts.append('<h2>7. מסקנה</h2><div class="card">')
    parts.append(p["conclusion_html"])
    parts.append("</div>")

    parts.append('<p class="small">הדוח הופק על ידי מנוע הניתוח של '
                 'BridgeTrainer: כל המספרים חושבו בסימולציה מקומית '
                 '(דאבל-דאמי + כיול), ללא מודל שפה בשכבת החישוב.</p>')
    parts.append("</body></html>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
def _engine_label(facts: dict) -> str:
    if len(facts["policies"]) == 1:
        return html.escape(next(iter(facts["policies"].values()))["he"])
    m = facts["meta"]
    return "שיטה: " + ("SAYC" if m["system"] == "sayc" else "2/1 Game Force")


def _auction_table(facts: dict) -> str:
    rows_calls = facts["auction"]
    dealer = facts["meta"]["dealer"]
    order = ["W", "N", "E", "S"]
    out = ['<div class="tablewrap"><table class="auction-grid"><tr>']
    for s in order:
        mark = " (אתה)" if s == facts["meta"]["my_seat"] else ""
        out.append(f"<th>{SEAT_HE[s]}{mark}</th>")
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
    out.append('<p class="small">ריחוף/מגע על הכרזה מציג את פרשנותה. '
               'ההכרזה המנותחת מסומנת במסגרת.</p>')
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
    head = ["פעולה", "IMP ממוצע", "רווח סמך"] + \
        ([] if single else ["DD גולמי"]) + ["% זכייה", "% הפסד", "חציון"]
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
        cells = [token_html(row["action"]) +
                 f' <small>מול {token_html(row["vs"])}</small>',
                 f"{row['ev_imp']:+.2f}",
                 f"±{row['ci']:.2f}"] + \
            ([] if single else [f"{row['ev_imp_raw']:+.2f}"]) + \
            [f"{row['p_gain'] * 100:.0f}%",
             f"{row['p_loss'] * 100:.0f}%",
             f"{row['median_imp']:+.1f}"]
        if scoring_mp:
            cells.insert(1, f"{row['mp_pct']:.1f}%")
        out.append(f"<tr{cls}>" + "".join(
            f'<td class="num">{c}</td>' for c in cells) + "</tr>")
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
           "<th>חוזים סופיים (מדיניות ריאלית)</th></tr>"]
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
        return "שלושה פאסים — ההכרזה נשארת."
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
