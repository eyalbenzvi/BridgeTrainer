"""Static quiz-site generator: `trainer publish`.

Runs every problem in the bank and emits a self-contained, mobile-friendly
static site (no server, deployable to GitHub Pages):

    site/index.html            problem list + your progress
    site/<id>/index.html       quiz page: pick a call, then the verdict reveals
    site/<id>/report.html      the full analysis report

Answers are tracked client-side in localStorage — fine for personal use and
keeps the site fully static.
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path

from ..domain.auction import partner_of
from ..domain.interfaces import GenerationBudget
from .report import render_report
from .runner import RunResult, run_problem

_SUIT_GLYPHS = {"S": "&#9824;", "H": '<span class="red">&#9829;</span>',
                "D": '<span class="red">&#9830;</span>', "C": "&#9827;"}

_BASE_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font-family: -apple-system, "Segoe UI", Roboto, Georgia, serif;
       max-width: 640px; margin: 0 auto; padding: 1em;
       background: #fdfdf8; color: #1a1a2e; }
@media (prefers-color-scheme: dark) {
  body { background: #16161e; color: #e4e4ec; }
  .card, .verdict { background: #1f1f2a !important; }
  th { background: #2a2a38 !important; }
  td, th { border-color: #444 !important; }
}
h1 { font-size: 1.3em; }
.red { color: #d3455b; }
.card { background: #fff; border: 1px solid #8884; border-radius: 10px;
        padding: 1em; margin: .8em 0; }
table { border-collapse: collapse; width: 100%; overflow-x: auto;
        display: block; }
th, td { border: 1px solid #ccc; padding: .4em .5em; font-size: .85em;
         text-align: left; }
th { background: #f0f0f5; }
a { color: #3673b5; }
.muted { color: #888; font-size: .85em; }
"""

_QUIZ_CSS = _BASE_CSS + """
.hand { font-size: 1.5em; line-height: 1.5; letter-spacing: .06em; }
.auction { font-size: 1.15em; margin: .6em 0; }
.candidates { display: flex; flex-direction: column; gap: .6em; margin: 1em 0; }
button.cand { font-size: 1.15em; padding: .8em; border-radius: 10px;
              border: 2px solid #8886; background: inherit; color: inherit;
              cursor: pointer; text-align: left; }
button.cand:active { transform: scale(.99); }
button.cand.chosen { border-color: #3673b5; }
button.cand.good { border-color: #2c9e5f; background: #2c9e5f22; }
button.cand.bad { border-color: #d3455b; background: #d3455b22; }
#verdict { display: none; }
.headline { font-size: 1.2em; font-weight: bold; margin: .4em 0; }
.fog { background: #ffdd5733; border: 1px solid #cca42f88; border-radius: 8px;
       padding: .6em .8em; margin: .6em 0; }
.pill { display: inline-block; border-radius: 999px; padding: .1em .7em;
        font-size: .8em; border: 1px solid #8886; }
"""


@dataclass
class PublishedEntry:
    id: str
    title: str
    category: str
    n_deals: int


def _auction_html(problem) -> str:
    return " &ndash; ".join(
        f"({c.token})" if seat not in (problem.my_seat,
                                       partner_of(problem.my_seat))
        else c.token
        for seat, c in problem.auction.calls_with_seats()) + " &ndash; ?"


def _hand_html(hand: str) -> str:
    parts = hand.split(".")
    return "<br>".join(f"{_SUIT_GLYPHS[s]} {html.escape(p) or '&mdash;'}"
                       for s, p in zip("SHDC", parts))


def _quiz_payload(result: RunResult) -> dict:
    def comp_rows(comp):
        return [{
            "action": c.action, "label": c.label,
            "ev": round(c.ev_vs_best_alt, 2),
            "ci": round(c.ci_half_width, 2),
            "vs": c.best_alternative,
            "p_gain": round(c.p_gain, 3), "p_loss": round(c.p_loss, 3),
        } for c in comp.candidates]

    corr = result.corrected
    accepted = [corr.candidates[0].action]
    if corr.toss_up:
        accepted += corr.toss_up_with
    return {
        "id": result.problem.id,
        "accepted": accepted,
        "toss_up": corr.toss_up,
        "fog": result.in_dd_fog,
        "corrected": comp_rows(corr),
        "raw": comp_rows(result.raw),
    }


def render_quiz(result: RunResult) -> str:
    p = result.problem
    payload = json.dumps(_quiz_payload(result)).replace("<", "\\u003c")
    buttons = "".join(
        f'<button class="cand" data-action="{html.escape(c.call)}" '
        f'onclick="choose(this)">{html.escape(c.call)} &mdash; '
        f'{html.escape(c.label)}</button>'
        for c in p.candidates)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(p.title)}</title>
<style>{_QUIZ_CSS}</style></head><body>
<p><a href="../index.html">&larr; all problems</a></p>
<h1>{html.escape(p.title)}</h1>
<div class="card">
<div class="muted">Dealer {p.dealer} &middot; Vul {p.vul} &middot; IMPs &middot;
you are {p.my_seat}</div>
<div class="auction">{_auction_html(p)}</div>
<div class="hand">{_hand_html(p.my_hand)}</div>
</div>
<div class="candidates">{buttons}</div>
<div id="verdict" class="card">
<div class="headline" id="headline"></div>
<div id="fog"></div>
<table id="vtable"></table>
<p class="muted">Corrected view (single-dummy smeared). EV is IMPs vs the
candidate's toughest rival.</p>
<p><a href="report.html">Full report &rarr;</a>
&nbsp;&middot;&nbsp; <a href="#" onclick="return retry()">retry</a></p>
</div>
<script>
const V = {payload};
const KEY = "bt_answers";
function store() {{ try {{ return JSON.parse(localStorage.getItem(KEY)) || {{}}; }}
                    catch (e) {{ return {{}}; }} }}
function choose(btn) {{
  const s = store();
  if (s[V.id]) return;
  const action = btn.dataset.action;
  s[V.id] = {{ answer: action,
               correct: V.accepted.includes(action), ts: Date.now() }};
  localStorage.setItem(KEY, JSON.stringify(s));
  reveal(action);
}}
function reveal(chosen) {{
  document.querySelectorAll("button.cand").forEach(b => {{
    const a = b.dataset.action;
    if (V.accepted.includes(a)) b.classList.add("good");
    else if (a === chosen) b.classList.add("bad");
    if (a === chosen) b.classList.add("chosen");
    b.disabled = true;
  }});
  const ok = V.accepted.includes(chosen);
  let head = ok ? "\\u2713 Good call" : "\\u2717 Not this time";
  if (V.toss_up) head += " \\u2014 it's a toss-up: " + V.accepted.join(", ");
  document.getElementById("headline").textContent = head;
  if (V.fog) document.getElementById("fog").innerHTML =
    '<div class="fog">\\u26a0 Raw and corrected verdicts disagree \\u2014 ' +
    'inside the DD fog. Trust this one less.</div>';
  let rows = "<tr><th>Action</th><th>EV vs best alt</th><th>P(gain)</th>" +
             "<th>P(loss)</th></tr>";
  for (const c of V.corrected) {{
    rows += `<tr><td>${{c.label}}</td><td>${{c.ev >= 0 ? "+" : ""}}${{c.ev}}` +
            ` \\u00b1 ${{c.ci}} vs ${{c.vs}}</td>` +
            `<td>${{Math.round(c.p_gain * 100)}}%</td>` +
            `<td>${{Math.round(c.p_loss * 100)}}%</td></tr>`;
  }}
  document.getElementById("vtable").innerHTML = rows;
  document.getElementById("verdict").style.display = "block";
}}
function retry() {{
  const s = store(); delete s[V.id];
  localStorage.setItem(KEY, JSON.stringify(s));
  location.reload(); return false;
}}
const prev = store()[V.id];
if (prev) reveal(prev.answer);
</script>
</body></html>"""


def render_index(entries: list[PublishedEntry], generated_at: str) -> str:
    items = "".join(f"""<a class="card problem" href="{html.escape(e.id)}/index.html"
 data-id="{html.escape(e.id)}">
<b>{html.escape(e.title)}</b>
<span class="pill">{html.escape(e.category) or 'uncategorized'}</span>
<span class="pill status" data-id="{html.escape(e.id)}"></span>
</a>""" for e in entries)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bridge Bidding Trainer</title>
<style>{_BASE_CSS}
a.card {{ display: block; text-decoration: none; color: inherit; }}
.pill {{ display: inline-block; border-radius: 999px; padding: .1em .7em;
        font-size: .8em; border: 1px solid #8886; margin-left: .4em; }}
</style></head><body>
<h1>Bridge Bidding Trainer</h1>
<p class="muted">{len(entries)} problem{'s' if len(entries) != 1 else ''}
&middot; published {generated_at}
&middot; <a href="#" onclick="return resetAll()">reset progress</a></p>
{items}
<script>
const KEY = "bt_answers";
function store() {{ try {{ return JSON.parse(localStorage.getItem(KEY)) || {{}}; }}
                    catch (e) {{ return {{}}; }} }}
const s = store();
document.querySelectorAll(".status").forEach(el => {{
  const rec = s[el.dataset.id];
  if (rec) {{
    el.textContent = rec.correct ? "\\u2713 " + rec.answer
                                 : "\\u2717 " + rec.answer;
    el.style.borderColor = rec.correct ? "#2c9e5f" : "#d3455b";
  }} else {{ el.textContent = "new"; }}
}});
function resetAll() {{
  if (confirm("Clear all recorded answers?")) {{
    localStorage.removeItem(KEY); location.reload();
  }}
  return false;
}}
</script>
</body></html>"""


def publish(
    problems_dir: str | Path = "problems",
    out_dir: str | Path = "site",
    seed: int = 42,
    n_override: int | None = None,
    use_cache: bool = True,
    cache_dir: str | Path = ".trainer_cache",
    budget: GenerationBudget | None = None,
) -> list[PublishedEntry]:
    problems_dir, out_dir = Path(problems_dir), Path(out_dir)
    paths = sorted(problems_dir.glob("*.yaml"))
    if not paths:
        raise FileNotFoundError(f"no problem files in {problems_dir}")
    entries = []
    for path in paths:
        result = run_problem(path, seed=seed, n_override=n_override,
                             use_cache=use_cache, cache_dir=cache_dir,
                             budget=budget)
        pdir = out_dir / result.problem.id
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "index.html").write_text(render_quiz(result), encoding="utf-8")
        (pdir / "report.html").write_text(render_report(result), encoding="utf-8")
        entries.append(PublishedEntry(
            id=result.problem.id,
            title=result.problem.title,
            category=result.problem.category,
            n_deals=len(result.deals),
        ))
    import datetime
    stamp = datetime.date.today().isoformat() + f" (seed {seed})"
    (out_dir / "index.html").write_text(render_index(entries, stamp),
                                        encoding="utf-8")
    (out_dir / ".nojekyll").write_text("")
    return entries
