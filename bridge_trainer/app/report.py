"""Static HTML report for one problem run. Self-contained: inline CSS/JS,
no external assets."""
from __future__ import annotations

import html
from pathlib import Path

import numpy as np

from ..domain.auction import SEATS
from ..scoring.comparison import ComparisonResult
from . import htmlfmt
from .runner import RunResult


def _bar(value: float, max_value: float, cls: str = "") -> str:
    pct = 0 if max_value <= 0 else 100.0 * value / max_value
    return (f'<div class="bar {cls}"><div class="fill" '
            f'style="width:{pct:.1f}%"></div></div>')


def _candidate_table(comp: ComparisonResult) -> str:
    rows = []
    for c in comp.candidates:
        rows.append(f"""<tr>
<td><b>{html.escape(c.label)}</b></td>
<td>{c.ev_vs_best_alt:+.2f} &plusmn; {c.ci_half_width:.2f}</td>
<td>{html.escape(c.best_alternative)}</td>
<td>{c.p_gain:.1%}</td><td>{c.p_push:.1%}</td><td>{c.p_loss:.1%}</td>
<td>{c.p_big_gain:.1%}</td><td>{c.p_big_loss:.1%}</td>
<td>{c.ess:.0f}</td>
</tr>""")
    return f"""<table>
<tr><th>Action</th><th>EV vs best alt (IMPs)</th><th>Best alt</th>
<th>P(gain)</th><th>P(push)</th><th>P(loss)</th>
<th>P(&ge;+5)</th><th>P(&le;&minus;5)</th><th>ESS</th></tr>
{''.join(rows)}</table>"""


def _verdict_block(comp: ComparisonResult, title: str) -> str:
    if comp.toss_up:
        tied = ", ".join([comp.candidates[0].label] +
                         [comp.result_for(a).label for a in comp.toss_up_with])
        head = f"Toss-up: {html.escape(tied)}"
        sub = "difference is within the CI or below 0.5 IMPs (INV7)"
    else:
        top = comp.candidates[0]
        head = f"{html.escape(top.label)}"
        sub = (f"{top.ev_vs_best_alt:+.2f} IMPs (&plusmn;{top.ci_half_width:.2f}) "
               f"vs {html.escape(top.best_alternative)}")
    return (f'<div class="verdict"><div class="vtitle">{title}</div>'
            f'<div class="vhead">{head}</div>'
            f'<div class="vsub">{sub}</div>{_candidate_table(comp)}</div>')


def _audit_section(result: RunResult) -> str:
    """HCP histograms + suit-length distributions per hidden seat, weighted."""
    weights = np.array([wd.weight for wd in result.deals])
    seat_words = {"N": "north", "E": "east", "S": "south", "W": "west"}
    hidden = [s for s in SEATS if s != result.problem.my_seat]
    blocks = []
    for seat in hidden:
        word = seat_words[seat]
        hcps = np.array([f[f"{word}_hcp"] for f in result.features])
        hist = []
        max_w = 0.0
        buckets = []
        for lo in range(0, 24, 3):
            m = (hcps >= lo) & (hcps <= lo + 2)
            w = float(weights[m].sum())
            buckets.append((f"{lo}-{lo+2}", w))
            max_w = max(max_w, w)
        w_hi = float(weights[hcps >= 24].sum())
        buckets.append(("24+", w_hi))
        max_w = max(max_w, w_hi)
        for label, w in buckets:
            share = w / weights.sum()
            hist.append(f"<tr><td>{label}</td><td class=barcell>"
                        f"{_bar(w, max_w)}</td><td>{share:.1%}</td></tr>")

        suit_rows = []
        for suit, sw in (("S", "spades"), ("H", "hearts"),
                         ("D", "diamonds"), ("C", "clubs")):
            lens = np.array([f[f"{word}_{sw}"] for f in result.features])
            mean = float(np.average(lens, weights=weights))
            dist = []
            for L in range(int(lens.min()), int(lens.max()) + 1):
                share = float(weights[lens == L].sum() / weights.sum())
                if share >= 0.005:
                    dist.append(f"{L}:{share:.0%}")
            suit_rows.append(f"<tr><td>{htmlfmt.SUIT_GLYPHS[suit]}</td>"
                             f"<td>{mean:.2f}</td>"
                             f"<td>{' &nbsp; '.join(dist)}</td></tr>")

        blocks.append(f"""<div class="audit-seat">
<h4>{word.title()} ({seat})</h4>
<table class="mini"><tr><th>HCP</th><th></th><th>share</th></tr>{''.join(hist)}</table>
<table class="mini"><tr><th>suit</th><th>mean len</th><th>length distribution</th></tr>
{''.join(suit_rows)}</table>
</div>""")
    return '<div class="audit">' + "".join(blocks) + "</div>"


def _breakdown_section(result: RunResult) -> str:
    if not result.breakdowns:
        return ""
    parts = ["<h2>Conditional breakdowns (corrected scores)</h2>"]
    for bd in result.breakdowns:
        pairs = list(bd.rows[0].ev_by_pair) if bd.rows else []
        header = "".join(f"<th>{html.escape(p)}</th>" for p in pairs)
        rows = []
        for r in bd.rows:
            cells = "".join(f"<td>{r.ev_by_pair[p]:+.2f}</td>" for p in pairs)
            rows.append(f"<tr><td>{html.escape(r.bucket)}</td>"
                        f"<td>{r.weight_share:.1%}</td><td>{r.n}</td>{cells}</tr>")
        parts.append(f"""<h4>{html.escape(bd.label)}</h4>
<table><tr><th>value</th><th>weight share</th><th>deals</th>{header}</tr>
{''.join(rows)}</table>""")
    return "".join(parts)


def _disaster_section(result: RunResult) -> str:
    if not result.disasters:
        return ""
    top = result.corrected.candidates[0]
    rows = []
    for d in result.disasters:
        hands = d.pbn.split(":", 1)[1].split()
        diagram = "<br>".join(
            f"<b>{seat}</b>: {htmlfmt.hand_html(h)}"
            for seat, h in zip("NESW", hands))
        rows.append(f"""<div class="disaster">
<div class="deal">{diagram}</div>
<div>{d.imp_swing:+.0f} IMPs &mdash; {html.escape(d.contract_top)}
({d.score_top:+.0f}) vs {html.escape(d.contract_alt)} ({d.score_alt:+.0f})</div>
</div>""")
    return (f"<h2>Disaster deals for {html.escape(top.label)}</h2>"
            + "".join(rows))


def render_report(result: RunResult, user_answer: str | None = None) -> str:
    p = result.problem
    d = result.diagnostics
    auction_html = htmlfmt.auction_html(p)

    fog = ('<div class="fog">&#9888; Raw and corrected verdicts disagree '
           '&mdash; this problem is <b>inside the DD fog</b>. Trust it less.</div>'
           if result.in_dd_fog else "")

    shortfall_note = ""
    if d.shortfall:
        shortfall_note = (
            f'<div class="warn">Generation shortfall: {d.shortfall} deals '
            f'missing (budget hit). CIs widened by '
            f'&times;{result.ci_widen:.2f} (INV7).</div>')

    unrecognized = ""
    if d.unrecognized_calls:
        items = "".join(f"<li>{html.escape(u)}</li>" for u in d.unrecognized_calls)
        unrecognized = (f'<div class="warn">Unrecognized calls (constraints '
                        f'not applied):<ul>{items}</ul></div>')

    answer_note = ""
    if user_answer:
        comp = result.corrected
        top_action = comp.candidates[0].action
        ok = (user_answer == top_action
              or (comp.toss_up and user_answer in
                  [top_action] + comp.toss_up_with))
        cls = "good" if ok else "bad"
        answer_note = (f'<div class="answer {cls}">Your answer: '
                       f'<b>{html.escape(user_answer)}</b></div>')

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(p.title)}</title>
<style>
body {{ font-family: Georgia, serif; max-width: 900px; margin: 2em auto;
       padding: 0 1em; color: #1a1a2e; }}
table {{ display: block; overflow-x: auto; max-width: 100%;
        width: fit-content; }}
h1 {{ font-size: 1.5em; }}
.red {{ color: #c0392b; }}
.banner {{ background: #fdf6e3; border: 1px solid #e0d5b8; padding: .6em 1em;
          border-radius: 6px; margin: 1em 0; }}
.problem {{ font-size: 1.15em; margin: 1em 0; }}
table {{ border-collapse: collapse; margin: .8em 0; }}
th, td {{ border: 1px solid #ccc; padding: .35em .7em; text-align: left;
         font-size: .92em; }}
th {{ background: #f0f0f5; }}
.verdict {{ border: 2px solid #2c6e49; border-radius: 8px; padding: 1em;
           margin: 1em 0; }}
.vtitle {{ text-transform: uppercase; font-size: .8em; color: #666; }}
.vhead {{ font-size: 1.4em; font-weight: bold; }}
.vsub {{ color: #444; }}
.fog, .warn {{ background: #fff3cd; border: 1px solid #e0c060;
              padding: .6em 1em; border-radius: 6px; margin: .8em 0; }}
.answer {{ padding: .5em 1em; border-radius: 6px; margin: .8em 0; }}
.answer.good {{ background: #e6f4ea; border: 1px solid #7cb28f; }}
.answer.bad {{ background: #fdecea; border: 1px solid #d99; }}
.audit {{ display: flex; gap: 1.5em; flex-wrap: wrap; }}
.audit-seat {{ flex: 1 1 260px; }}
table.mini td, table.mini th {{ font-size: .8em; padding: .15em .45em; }}
.bar {{ background: #eee; height: .8em; width: 120px; border-radius: 3px; }}
.bar .fill {{ background: #4a7ba6; height: 100%; border-radius: 3px; }}
.barcell {{ min-width: 130px; }}
.disaster {{ border: 1px solid #d99; border-radius: 6px; padding: .7em 1em;
            margin: .6em 0; }}
.deal {{ font-size: .9em; margin-bottom: .4em; }}
.meta {{ color: #777; font-size: .8em; margin-top: 2em;
        border-top: 1px solid #ddd; padding-top: .6em; }}
button.toggle {{ font-size: 1em; padding: .3em .9em; cursor: pointer; }}
.hidden {{ display: none; }}
</style></head><body>
<h1>{html.escape(p.title)}</h1>
<div class="problem">
<b>{html.escape(p.my_seat)}</b> holds: {htmlfmt.hand_html(p.my_hand)}<br>
Dealer {p.dealer}, Vul {p.vul} &middot; IMPs<br>
Auction: {auction_html}
</div>
<div class="banner"><b>Opponents assumed:</b>
{html.escape(p.opps_system.name)} &mdash; {html.escape(p.opps_system.description)}
&nbsp;|&nbsp; <b>Our system:</b> {html.escape(p.our_system.name)}</div>
{answer_note}
{fog}
{shortfall_note}
{unrecognized}
<p><button class="toggle" onclick="toggleView()">Toggle raw / corrected</button></p>
<div id="view-corrected">{_verdict_block(result.corrected,
    "Verdict — single-dummy corrected")}</div>
<div id="view-raw" class="hidden">{_verdict_block(result.raw,
    "Verdict — raw double-dummy")}</div>
{_breakdown_section(result)}
{_disaster_section(result)}
<h2>Generation diagnostics</h2>
<table>
<tr><th>attempts</th><td>{d.attempts:,}</td></tr>
<tr><th>acceptance rate</th><td>{d.acceptance_rate:.4%}</td></tr>
<tr><th>deals generated</th><td>{len(result.deals)}
 (shortfall {d.shortfall})</td></tr>
<tr><th>effective sample size</th><td>{d.effective_sample_size:.0f}</td></tr>
<tr><th>generation wall clock</th><td>{d.elapsed_s:.2f}s
 (cache {'hit' if result.cache_hit else 'miss'})</td></tr>
<tr><th>total run wall clock</th><td>{result.elapsed_s:.2f}s</td></tr>
</table>
<h2>Sample audit</h2>
{_audit_section(result)}
<div class="meta">
seed {result.seed} &middot; constraint hash {result.constraint_hash} &middot;
cache key {result.cache_key[:20]}&hellip; &middot;
versions: {html.escape(', '.join(f'{k} {v}' for k, v in result.versions.items()))}
</div>
<script>
function toggleView() {{
  document.getElementById('view-raw').classList.toggle('hidden');
  document.getElementById('view-corrected').classList.toggle('hidden');
}}
</script>
</body></html>"""


def write_report(result: RunResult, out_dir: str | Path,
                 user_answer: str | None = None) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{result.problem.id}_seed{result.seed}.html"
    path.write_text(render_report(result, user_answer), encoding="utf-8")
    return path
