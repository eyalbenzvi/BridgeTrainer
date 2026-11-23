"""Hebrew RTL HTML report for an opening-lead analysis (lead_analysis.py).

Same look as the bidding report (shares its CSS and hand/auction helpers);
every number comes from the facts dict — the prose is fixed templates.
"""
from __future__ import annotations

import html

from .report import (_CSS, RED, SEAT_HE, SUIT_GLYPH, _hcp_of, contract_html,
                     hand_box, token_html, vul_he)

SUIT_NAME_HE = {"S": "ספייד", "H": "הארט", "D": "דיאמונד", "C": "קלאב"}
VERDICT_HE = {"best": "הטובה ביותר", "close": "שקולה",
              "worse": "נחותה"}

_LEAD_CSS = """
.lead-card { font-weight: 700; white-space: nowrap; }
td.cardcell { text-align: center; direction: ltr; }
tr.close td { background: #FdF6E3; }
.hist { display: flex; align-items: flex-end; gap: 2px; height: 46px;
  direction: ltr; }
.hist .b { width: 18px; background: var(--accent); border-radius: 3px 3px 0 0;
  opacity: .75; }
.hist .b.set { background: var(--win); }
.hist-lbl { display: flex; gap: 2px; direction: ltr; font-size: 10.5px;
  color: var(--muted); }
.hist-lbl span { width: 18px; text-align: center; }
.histbox { display: inline-block; margin: 6px 14px 6px 0;
  vertical-align: top; }
"""


def card_html(card: str) -> str:
    s, r = card[0], card[1]
    cls = ' class="red"' if s in RED else ""
    return (f'<span class="lead-card ltr"><span{cls}>{SUIT_GLYPH[s]}</span>'
            f'{"10" if r == "T" else r}</span>')


def group_html(cards: list) -> str:
    """['H7','H5','H2'] -> ♥7/5/2 (equivalent cards share one row)."""
    if len(cards) == 1:
        return card_html(cards[0])
    s = cards[0][0]
    cls = ' class="red"' if s in RED else ""
    ranks = "/".join("10" if c[1] == "T" else c[1] for c in cards)
    return (f'<span class="lead-card ltr"><span{cls}>{SUIT_GLYPH[s]}</span>'
            f'{ranks}</span>')


def _unit(facts: dict) -> str:
    return "לקיחות" if facts["meta"]["scoring"] == "MP" else "IMP"


def _diff_html(row: dict, facts: dict) -> str:
    if row["verdict"] == "best":
        return "—"
    return (f'<span class="ltr">{row["diff"]:+.2f} ± {row["diff_ci"]:.2f}'
            f'</span>')


def _auction_table(facts: dict) -> str:
    m = facts["meta"]
    order = ["W", "N", "E", "S"]
    out = ['<div class="tablewrap"><table class="auction-grid"><tr>']
    for s in order:
        mark = " (אתה)" if s == m["my_seat"] else ""
        side = "NS" if s in "NS" else "EW"
        cls = "vul" if m["vul"] in (side, "Both") else "nv"
        out.append(f'<th class="{cls}">{SEAT_HE[s]}{mark}</th>')
    out.append("</tr><tr>")
    col = order.index(m["dealer"])
    out.extend("<td></td>" for _ in range(col))
    for tok in facts["auction"]:
        if col == 4:
            out.append("</tr><tr>")
            col = 0
        out.append(f"<td>{token_html(tok)}</td>")
        col += 1
    out.extend("<td></td>" for _ in range(col, 4))
    out.append("</tr></table></div>")
    out.append('<p class="small">אדום — צד פגיע; ירוק — צד לא פגיע.</p>')
    return "".join(out)


def _contract_spec(fc: dict) -> str:
    # contract_html wants '4SEx' (single x marks doubled)
    tok = f"{fc['level']}{fc['denom']}"
    return tok + fc["declarer"] + ("x" if fc["doubled"] else "")


def narrate_conclusion(facts: dict) -> str:
    rows = facts["rows"]
    best = rows[0]
    unit = _unit(facts)
    out = [f'<p><b>ההובלה המומלצת: {group_html(best["cards"])}</b>'
           + (" (כל הקלפים האלה שקולים בדאבל-דאמי)"
              if len(best["cards"]) > 1 else "") + "</p>"]
    out.append(
        f'<p>ההגנה לוקחת בממוצע <b class="ltr">'
        f'{best["exp_def_tricks"]:.2f}</b> לקיחות, וסיכוי להכשיל את '
        f'החוזה (<span class="ltr">{facts["to_set"]}</span> לקיחות) הוא '
        f'<b class="ltr">{best["set_prob"] * 100:.0f}%</b>.</p>')
    alt = facts.get("alt_suit")
    if alt:
        diff = -alt["diff"]
        if alt["verdict"] == "close":
            out.append(
                f'<p>ההכרעה צמודה: ההובלה הטובה ביותר מסדרה אחרת, '
                f'{group_html(alt["cards"])}, נחותה רק ב-'
                f'<span class="ltr">{diff:.2f} ± {alt["diff_ci"]:.2f}</span>'
                f' {unit} — בתוך רעש הסימולציה. שתיהן סבירות.</p>')
        else:
            out.append(
                f'<p>החלופה הטובה ביותר מסדרה אחרת, '
                f'{group_html(alt["cards"])}, מפסידה בממוצע '
                f'<b class="ltr">{diff:.2f}</b> {unit} '
                f'(<span class="ltr">± {alt["diff_ci"]:.2f}</span>) — '
                f'הפרש מובהק.</p>')
    act = facts.get("actual_lead")
    if act:
        row = next((r for r in rows if act in r["cards"]), None)
        if row is not None:
            if row["verdict"] == "best":
                out.append(f'<p>ההובלה שלך בפועל, {card_html(act)}, היא '
                           f'ההובלה המומלצת. ✔</p>')
            elif row["verdict"] == "close":
                out.append(f'<p>ההובלה שלך בפועל, {card_html(act)}, שקולה '
                           f'להובלה המומלצת (הפרש בתוך הרעש).</p>')
            else:
                out.append(
                    f'<p>ההובלה שלך בפועל, {card_html(act)}, עולה בממוצע '
                    f'<b class="ltr">{-row["diff"]:.2f}</b> {unit} לעומת '
                    f'ההובלה המומלצת.</p>')
    ben = facts.get("ben_top")
    if ben and ben not in best["cards"]:
        out.append(f'<p class="small">לשם השוואה: ההובלה האינטואיטיבית של '
                   f'המנוע (לפי רשת ההובלות שלו, לפני הסימולציה) היא '
                   f'{card_html(ben)}.</p>')
    return "".join(out)


def _results_table(facts: dict) -> str:
    mp = facts["meta"]["scoring"] == "MP"
    unit = _unit(facts)
    head = ("<tr><th>הובלה</th><th class='num'>לקיחות הגנה</th>"
            "<th class='num'>סיכוי הכשלה</th>"
            "<th class='num'>IMP צפוי</th>"
            f"<th class='num'>הפרש מהטובה ({unit})</th>"
            "<th>הערכה</th><th class='num'>מנוע</th></tr>")
    out = ['<div class="tablewrap"><table>', head]
    for r in facts["rows"]:
        cls = {"best": "rec", "close": "close"}.get(r["verdict"], "")
        if r["is_actual"]:
            cls += " actual"
        out.append(
            f'<tr class="{cls.strip()}"><td class="cardcell">'
            f'{group_html(r["cards"])}</td>'
            f'<td class="num">{r["exp_def_tricks"]:.2f}</td>'
            f'<td class="num">{r["set_prob"] * 100:.0f}%</td>'
            f'<td class="num">{r["exp_imps"]:+.2f}</td>'
            f'<td class="num">{_diff_html(r, facts)}</td>'
            f'<td>{VERDICT_HE[r["verdict"]]}</td>'
            f'<td class="num">{r["ben_p"] * 100:.0f}%</td></tr>')
    out.append("</table></div>")
    out.append(
        '<p class="small">"IMP צפוי" — '
        'מול ממוצע כל ההובלות על אותה חלוקה. ההפרש מחושב בזוגות על '
        'אותן חלוקות, עם רווח סמך 95%; הדירוג לפי '
        + ("לקיחות ההגנה (ניקוד מקסימלי)." if mp
           else "ה-IMP הצפוי (מפגשים).")
        + ' "מנוע" — משקל ההובלה ברשת ההובלות של המנוע. ★ — ההובלה '
        'שלך בפועל.</p>')
    return "".join(out)


def _hist_html(row: dict, to_set: int) -> str:
    hist = row["hist"]
    ks = [k for k, v in enumerate(hist) if v > 0.005]
    if not ks:
        return ""
    lo, hi = min(ks), max(ks)
    top = max(hist[lo:hi + 1]) or 1.0
    bars, lbls = [], []
    for k in range(lo, hi + 1):
        h = int(round(44 * hist[k] / top))
        cls = "b set" if k >= to_set else "b"
        bars.append(f'<div class="{cls}" style="height:{h}px" '
                    f'title="{k}: {hist[k] * 100:.0f}%"></div>')
        lbls.append(f"<span>{k}</span>")
    return (f'<div class="histbox"><div>{group_html(row["cards"])}</div>'
            f'<div class="hist">{"".join(bars)}</div>'
            f'<div class="hist-lbl">{"".join(lbls)}</div></div>')


def render_lead_report(facts: dict) -> str:
    m = facts["meta"]
    fc = facts["contract"]
    scoring_he = ("ניקוד מקסימלי (MP)" if m["scoring"] == "MP"
                  else "מפגשים (IMP)")
    parts = [f"""<!DOCTYPE html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ניתוח הובלה — BridgeTrainer</title>
<style>{_CSS}{_LEAD_CSS}</style></head><body>
<h1>דוח ניתוח הובלת פתיחה</h1>
<div class="subtitle">BridgeTrainer · {scoring_he} ·
{vul_he(m['vul'], m['my_seat'])} · מחלק: {SEAT_HE[m['dealer']]} ·
מנוע Ben</div>"""]
    parts.append(f'<div class="rec-banner">{narrate_conclusion(facts)}'
                 f'</div>')

    parts.append('<h2>1. היד, המכרז והחוזה</h2><div class="card">')
    parts.append(hand_box(facts["hand"]["pbn"], _hcp_of(facts["hand"]["pbn"])))
    parts.append(_auction_table(facts))
    parts.append(
        f'<p>החוזה: <b>{contract_html(_contract_spec(fc))}</b>'
        + (" — רידאבל" if fc["doubled"] == "xx" else "")
        + f'. אתה ({SEAT_HE[m["my_seat"]]}) מוביל; כדי להכשיל צריך '
        f'<span class="ltr">{facts["to_set"]}</span> לקיחות הגנה.</p>')
    for n in facts["notes"]:
        parts.append(f'<div class="note">{html.escape(n)}</div>')
    parts.append("</div>")

    parts.append('<h2>2. כל ההובלות</h2><div class="card">')
    parts.append(_results_table(facts))
    parts.append("</div>")

    parts.append('<h2>3. התפלגות לקיחות ההגנה</h2><div class="card">')
    parts.append('<p class="small">לכל אחת מההובלות המובילות: בכמה '
                 'מהחלוקות ההגנה לוקחת כל מספר לקיחות. עמודה ירוקה — '
                 'החוזה מוכשל.</p>')
    for r in facts["rows"][:4]:
        parts.append(_hist_html(r, facts["to_set"]))
    parts.append("</div>")

    parts.append('<h2>4. איך חושב</h2><div class="card"><p class="small">'
                 f'המנוע דגם <span class="ltr">{m["n_samples"]}</span> '
                 'חלוקות של שלוש הידיים הנסתרות, התואמות את היד שלך ואת '
                 'המכרז כפי שהמנוע מבין אותו (התאמה: '
                 f'<span class="ltr">{m["quality"] * 100:.0f}%</span>). '
                 'כל הובלה נפתרה בדאבל-דאמי על אותן חלוקות בדיוק, כך '
                 'שההשוואה בין ההובלות הוגנת. קלפים נמוכים (7 ומטה) '
                 'באותה סדרה נחשבים הובלה אחת — בחר ביניהם לפי הסכמי '
                 'ההובלה שלכם. דאבל-דאמי מניח שהכרוז יודע היכן כל '
                 'הקלפים, ולכן מעט מחמיר עם הובלות "פסיביות". '
                 f'<span class="ltr">seed {m["seed"]} · '
                 f'{m["elapsed_s"]:.0f}s</span></p></div>')
    parts.append("</body></html>")
    return "\n".join(parts)
