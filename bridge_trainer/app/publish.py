"""Static quiz-site generator: `trainer publish`.

Runs every problem in the bank and emits a self-contained, mobile-friendly
static site (no server, deployable to GitHub Pages):

    site/index.html               problem list + your progress
    site/<id>/index.html          redirect to your first unanswered deal
    site/<id>/v<k>/index.html     deal k: pick a call, verdict reveals,
                                  "Next deal" jumps to an unseen variant
    site/<id>/v<k>/report.html    the full analysis report for that deal

"Next deal" support: a problem with `my_hand_class` + `variants: N` gets N
seeded variants. Variant 0 is the authored hand; each further variant deals
my seat a fresh hand from the class and re-runs the whole simulation, so
every deal is a genuinely new, DD-solved problem. Answers are tracked
client-side in localStorage (key: "<id>/v<k>").
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..bank.schema import load_problem
from ..dealing.myhand import sample_my_hand
from ..domain.interfaces import GenerationBudget
from . import htmlfmt
from .report import render_report
from .runner import RunResult, run_problem

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
.pill { display: inline-block; border-radius: 999px; padding: .1em .7em;
        font-size: .8em; border: 1px solid #8886; margin-left: .4em; }
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
a.next { display: block; text-align: center; font-size: 1.15em;
         padding: .8em; border-radius: 10px; margin: .8em 0;
         background: #3673b5; color: #fff; text-decoration: none;
         font-weight: bold; }
.topbar { display: flex; justify-content: space-between; align-items: baseline; }
"""


@dataclass
class PublishedEntry:
    id: str
    title: str
    category: str
    n_deals: int
    variants: int


def _quiz_payload(result: RunResult, k: int, total: int) -> dict:
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
        "pid": result.problem.id,
        "k": k,
        "total": total,
        "accepted": accepted,
        "toss_up": corr.toss_up,
        "fog": result.in_dd_fog,
        "corrected": comp_rows(corr),
        "raw": comp_rows(result.raw),
    }


def render_quiz(result: RunResult, k: int, total: int) -> str:
    p = result.problem
    payload = json.dumps(_quiz_payload(result, k, total)).replace("<", "\\u003c")
    buttons = "".join(
        f'<button class="cand" data-action="{html.escape(c.call)}" '
        f'onclick="choose(this)">{html.escape(c.call)} &mdash; '
        f'{html.escape(c.label)}</button>'
        for c in p.candidates)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(p.title)} &mdash; deal {k + 1}</title>
<style>{_QUIZ_CSS}</style></head><body>
<div class="topbar">
<a href="../../index.html">&larr; all problems</a>
<span class="muted">deal {k + 1} / {total}</span>
</div>
<h1>{html.escape(p.title)}</h1>
<div class="card">
<div class="muted">Dealer {p.dealer} &middot; Vul {p.vul} &middot; IMPs &middot;
you are {p.my_seat}</div>
<div class="auction">{htmlfmt.auction_html(p)}</div>
<div class="hand">{htmlfmt.hand_html(p.my_hand, suit_sep="<br>", glyph_sep=" ", dash="&mdash;")}</div>
</div>
<div class="candidates">{buttons}</div>
<div id="verdict" class="card">
<div class="headline" id="headline"></div>
<div id="fog"></div>
<table id="vtable"></table>
<p class="muted">Corrected view (single-dummy smeared). EV is IMPs vs the
candidate's toughest rival.</p>
<a class="next" id="next" href="#">Next deal &rarr;</a>
<p><a href="report.html">Full report &rarr;</a>
&nbsp;&middot;&nbsp; <a href="#" onclick="return retry()">retry</a></p>
</div>
<script>
const V = {payload};
const KEY = "bt_answers";
const VID = V.pid + "/v" + V.k;
function store() {{ try {{ return JSON.parse(localStorage.getItem(KEY)) || {{}}; }}
                    catch (e) {{ return {{}}; }} }}
function nextUnseen() {{
  const s = store();
  for (let d = 1; d <= V.total; d++) {{
    const j = (V.k + d) % V.total;
    if (!s[V.pid + "/v" + j]) return j;
  }}
  return (V.k + 1) % V.total;  // all answered: just cycle
}}
function choose(btn) {{
  const s = store();
  if (s[VID]) return;
  const action = btn.dataset.action;
  s[VID] = {{ answer: action,
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
  document.getElementById("next").href = "../v" + nextUnseen() + "/index.html";
  document.getElementById("verdict").style.display = "block";
}}
function retry() {{
  const s = store(); delete s[VID];
  localStorage.setItem(KEY, JSON.stringify(s));
  location.reload(); return false;
}}
const prev = store()[VID];
if (prev) reveal(prev.answer);
</script>
</body></html>"""


def render_problem_redirect(pid: str, title: str, total: int) -> str:
    """<id>/index.html: jump to the first deal you haven't answered."""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{_BASE_CSS}</style></head><body>
<p class="muted">Picking your next deal&hellip;
<a id="fallback" href="v0/index.html">continue</a></p>
<script>
const PID = {json.dumps(pid)}, TOTAL = {total};
let s = {{}};
try {{ s = JSON.parse(localStorage.getItem("bt_answers")) || {{}}; }} catch (e) {{}}
let target = 0;
for (let j = 0; j < TOTAL; j++) {{
  if (!s[PID + "/v" + j]) {{ target = j; break; }}
}}
location.replace("v" + target + "/index.html");
</script>
</body></html>"""


def render_index(entries: list[PublishedEntry], generated_at: str) -> str:
    manifest = json.dumps([{"id": e.id, "total": e.variants} for e in entries])
    items = "".join(f"""<a class="card problem" href="{html.escape(e.id)}/index.html"
 data-id="{html.escape(e.id)}" data-total="{e.variants}">
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
a.deal {{ display: block; text-align: center; font-size: 1.25em;
         padding: .9em; border-radius: 12px; margin: 1em 0;
         background: #3673b5; color: #fff; text-decoration: none;
         font-weight: bold; }}
</style></head><body>
<h1>Bridge Bidding Trainer</h1>
<a class="deal" href="#" onclick="return dealMe()">Deal me a hand &rarr;</a>
<p class="muted">New deals are generated daily &middot; published {generated_at}
&middot; <a href="#" onclick="return resetAll()">reset progress</a></p>
{items}
<script>
const MANIFEST = {manifest};
const KEY = "bt_answers";
function store() {{ try {{ return JSON.parse(localStorage.getItem(KEY)) || {{}}; }}
                    catch (e) {{ return {{}}; }} }}
function dealMe() {{
  const s = store(), unseen = [];
  for (const p of MANIFEST)
    for (let j = 0; j < p.total; j++)
      if (!s[p.id + "/v" + j]) unseen.push(p.id + "/v" + j);
  if (!unseen.length) {{
    alert("You've answered every deal! New ones are generated daily " +
          "\\u2014 come back tomorrow, or reset your progress.");
    return false;
  }}
  const pick = unseen[Math.floor(Math.random() * unseen.length)];
  location.href = pick + "/index.html";
  return false;
}}
const s = store();
document.querySelectorAll("a.problem").forEach(card => {{
  const id = card.dataset.id, total = parseInt(card.dataset.total);
  let done = 0, right = 0;
  for (let j = 0; j < total; j++) {{
    const rec = s[id + "/v" + j];
    if (rec) {{ done++; if (rec.correct) right++; }}
  }}
  const el = card.querySelector(".status");
  if (done === 0) el.textContent = total + " deals";
  else {{
    el.textContent = "\\u2713 " + right + " / " + done + " of " + total;
    el.style.borderColor = right === done ? "#2c9e5f" : "#cca42f";
  }}
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
    variants_override: int | None = None,
    grow_per_day: int = 0,
    grow_anchor: str | None = None,
) -> list[PublishedEntry]:
    """grow_per_day/grow_anchor: continuous generation. Each problem with a
    hand class gains grow_per_day fresh deals per UTC day since the anchor
    date (YYYY-MM-DD) — deterministic within a day, so CI republishes are
    stable and only the newest deals ever need computing."""
    import datetime

    problems_dir, out_dir = Path(problems_dir), Path(out_dir)
    paths = sorted(problems_dir.glob("*.yaml"))
    if not paths:
        raise FileNotFoundError(f"no problem files in {problems_dir}")
    grown = 0
    if grow_per_day and grow_anchor:
        anchor = datetime.date.fromisoformat(grow_anchor)
        today = datetime.datetime.now(datetime.timezone.utc).date()
        grown = max(0, (today - anchor).days) * grow_per_day
    entries = []
    for path in paths:
        first = None
        spec = load_problem(path)
        total = spec.variants
        if spec.my_hand_class is not None:
            total += grown
        if variants_override:
            total = min(variants_override, total)
        for k in range(total):
            seed_k = seed + k
            my_hand = None
            if k > 0:
                rng = np.random.default_rng([seed_k, 777])
                my_hand = sample_my_hand(spec.my_hand_class, rng)
            result = run_problem(path, seed=seed_k, n_override=n_override,
                                 use_cache=use_cache, cache_dir=cache_dir,
                                 budget=budget, my_hand_override=my_hand)
            vdir = out_dir / result.problem.id / f"v{k}"
            vdir.mkdir(parents=True, exist_ok=True)
            (vdir / "index.html").write_text(
                render_quiz(result, k, total), encoding="utf-8")
            (vdir / "report.html").write_text(
                render_report(result), encoding="utf-8")
            if first is None:
                first = result
        entry = PublishedEntry(
            id=first.problem.id,
            title=first.problem.title,
            category=first.problem.category,
            n_deals=len(first.deals),
            variants=total,
        )
        (out_dir / entry.id / "index.html").write_text(
            render_problem_redirect(entry.id, entry.title, total),
            encoding="utf-8")
        entries.append(entry)
    stamp = datetime.date.today().isoformat() + f" (seed {seed})"
    (out_dir / "index.html").write_text(render_index(entries, stamp),
                                        encoding="utf-8")
    (out_dir / ".nojekyll").write_text("")
    return entries
