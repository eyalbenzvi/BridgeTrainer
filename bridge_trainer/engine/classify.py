"""LLM problem-type classifier: assigns each published problem exactly one
of a FIXED 10-category bridge taxonomy (synthesized from the de-facto
taxonomies in the judgment literature: Lawrence's *Judgment at Bridge*
chapters, Robson & Segal's *The Contested Auction*, Cohen's LOTT framing —
BridgeWinners and the Master Solvers Club publish no typology of their own).

Categories describe WHAT MAKES THE PROBLEM HARD, not the auction stage.
The classifier sees the hero hand, the auction with the engine's call
meanings, vulnerability, the candidate calls and the winning call, and must
answer with one category id plus a one-sentence reason (stored for audit).

Backends (both take the same ``(prompt, model)`` shape, so classify_records
is backend-agnostic):
  * ``run_github_models`` — the default. OpenAI-compatible chat completions
    over HTTPS against the GitHub Models inference API, authenticated with the
    workflow's ``GITHUB_TOKEN`` (needs ``permissions: models: read``). This is
    what lets classification run in a GitHub Actions workflow with no Claude
    Code session and no paid tokens.
  * ``run_claude_cli`` — the original headless ``claude`` CLI, for running the
    classifier by hand inside a Claude Code session.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request

CLAUDE_MODEL = "claude-sonnet-5"
# GitHub Models model id — must be "{publisher}/{model}". A "low" tier model is
# plenty for a 10-way enum classification and gets the larger free-tier budget
# (~150 requests/day vs ~50 for "high" models).
GITHUB_MODEL = "openai/gpt-4.1-mini"
GITHUB_MODELS_URL = "https://models.github.ai/inference/chat/completions"

# The default backend model. Classification now runs in a GitHub Actions
# workflow, so the default backend is GitHub Models. (classify_pool.py imports
# MODEL; --backend claude overrides it to CLAUDE_MODEL.)
MODEL = GITHUB_MODEL
TIMEOUT_S = 300

# Bidding problems per model call. A big batch is a false economy on EITHER
# backend, and for the SAME reason the whole-pool call once "hung" on the
# claude CLI: one call must GENERATE one JSON object per problem, and the
# GitHub Models free tier hard-caps output at 4,000 tokens/request — past that
# the JSON array is truncated mid-array and the parse fails (identical symptom,
# different cause). Per-problem accuracy also drifts as one prompt juggles more
# problems. So we keep chunks SMALL (5): the extra HTTP requests are trivial
# against the free-tier budget (~150 requests/day for a low-tier model dwarfs
# any realistic forge batch), classify_pool.py saves each record as its chunk
# returns (an interrupted run resumes), and classify_records() automatically
# HALVES any chunk whose call still fails — so a stray truncation self-heals.
DEFAULT_CHUNK_SIZE = 5

TAXONOMY = [
    ("open_or_pass", "Opening Decision", "החלטת פתיחה",
     "First decision of the auction: whether to open a borderline hand, and"
     " which non-preemptive opening fits (seat/vulnerability adjustments,"
     " rule-of-20 hands, awkward shapes)."),
    ("preempt_decision", "Preempt or Not / How High", "הכרזת מנע",
     "Whether to choose an obstructive action and at what level: preemptive"
     " openings, weak jump overcalls, preemptive raises — a weak/shapely"
     " hand where the candidates differ mainly in obstruction level."),
    ("enter_auction", "Overcall, Double, or Stay Out", "כניסה למכרז",
     "Whether to enter the opponents' auction at all, and with which entry"
     " vehicle: simple overcall vs takeout double vs 1NT vs pass, including"
     " balancing/reopening decisions."),
    ("compete_or_sell", "Part-Score Battle", "קרב חוזה חלקי",
     "In a contested auction, whether to bid once more, pass, or push the"
     " opponents higher (Law of Total Tricks territory): competitive"
     " raises, rebidding in competition, advancer's raise-or-pass."),
    ("invite_or_game", "Invitation / Game Decision", "הזמנה או משחק מלא",
     "Constructive valuation of how high: sign off, invite, or bid game;"
     " making or accepting game tries; evaluating fit, fillers and shape."),
    ("slam_try", "Slam Decision", "ניסיון סלם",
     "Whether and how to move toward slam, or whether to accept partner's"
     " try: control-bids, keycard vs blast, quantitative raises, signing"
     " off with wasted values."),
    ("choice_of_strain", "Choice of Strain / Preference", "בחירת שליט",
     "The level is (roughly) settled; the problem is WHERE: 3NT vs 4-major"
     " vs 5-minor, which of two suits, simple or false preference, pass"
     " partner's second suit or correct."),
    ("double_or_bid", "Double Decision", "להכפיל או להכריז",
     "The pivotal candidate is a double (penalty, negative, responsive,"
     " action) or handling one: double vs bid on vs pass, leaving in or"
     " pulling partner's double."),
    ("sacrifice_decision", "Save or Defend", "הקרבה",
     "Whether your side should deliberately outbid their making contract"
     " for a minus score: advance saves, 5-over-4/5-over-5 decisions,"
     " vulnerability arithmetic, forcing-pass responses."),
    ("describe_hand", "Constructive Rebid / Descriptive Choice", "תיאור היד",
     "Uncontested constructive auctions where the issue is which call best"
     " describes strength and shape (not yet the final level/strain):"
     " opener's rebid problems, responder's choice among options, fourth"
     " suit forcing vs direct raise, splinter vs Jacoby 2NT."),
]

TYPE_IDS = [t[0] for t in TAXONOMY]
LABELS_HE = {t[0]: t[2] for t in TAXONOMY}
LABELS_EN = {t[0]: t[1] for t in TAXONOMY}

# Hebrew one-line tooltip per bidding type — the question shown under the type
# badge in the web UI. Kept here (not duplicated in webapp.py) so the labels and
# tooltips have a single source of truth; webapp._taxonomy_he_json() injects
# them as window.TAXONOMY_HE (ARCH-5).
TOOLTIPS_HE = {
    "open_or_pass": "לפתוח יד גבולית, או לפאס — ובאיזו פתיחה?",
    "preempt_decision": "להפריע או לא — ועד איזו רמה?",
    "enter_auction": "אוברקול, כפל, או להישאר בחוץ?",
    "compete_or_sell": "להכריז עוד פעם, לפאס, או לדחוף אותם גבוה יותר?",
    "invite_or_game": "לעצור, להזמין, או להכריז משחק מלא?",
    "slam_try": "להתקדם לסלאם, או להסתפק במשחק מלא?",
    "choice_of_strain": "הרמה סגורה — אבל היכן: איזו סדרה, או ללא־שליט?",
    "double_or_bid": "כפל, להמשיך להכריז, או לפאס?",
    "sacrifice_decision": "לדרוס את החוזה שלהם במחיר מינוס, או להגן?",
    "describe_hand": "איזו הכרזה בונה מתארת הכי טוב את הכוח והצורה?",
}

TIE_BREAK = """\
- If a double (X) is among the candidates and is the winning call or the \
main foil, prefer double_or_bid.
- A weak hand with an obstruction motive beats compete_or_sell: prefer \
preempt_decision.
- Deliberate minus-score logic (outbidding their making contract to save) \
beats compete_or_sell: prefer sacrifice_decision.
- If both level and strain are open, classify by the axis on which the \
candidate calls actually differ."""

_SUITS = ("S", "H", "D", "C")
_GLYPHS = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}


def pretty_hand(pbn: str) -> str:
    return " ".join(f"{_GLYPHS[s]}{h or '—'}"
                    for s, h in zip(_SUITS, pbn.split(".")))


def _auction_lines(rec: dict) -> list[str]:
    stem = rec.get("explanations", {}).get("stem", [])
    if stem:
        return [e["text"] for e in stem]
    seats = "NESW"
    d = seats.index(rec["dealer"])
    return [f"{t} ({seats[(d + j) % 4]})"
            for j, t in enumerate(rec["auction"])]


def _taxonomy_block() -> str:
    return "\n".join(f"{i + 1}. {tid} — {name}: {desc}"
                     for i, (tid, name, _, desc) in enumerate(TAXONOMY))


def _problem_facts(rec: dict) -> str:
    """The per-problem decision facts (hand, auction, candidates, winner)
    shared by the single-problem and batch prompts."""
    cands = ", ".join(f"{c['call']} (engine policy {c['policy']:.0%})"
                      for c in rec["candidates"])
    winner = rec["verdict"]["accepted"]
    auction = "\n".join(f"  {ln}" for ln in _auction_lines(rec)) or \
        "  (hero opens the auction)"
    return f"""Scoring: {rec.get('scoring_form', 'IMPs')}. Both sides play \
standard 2/1 Game Force.
Vulnerability: {rec['vul']} (seats: NS / EW). Dealer: {rec['dealer']}.
Hero sits {rec['seat']} and holds: {pretty_hand(rec['hand'])}
Auction so far (with the engine's call meanings):
{auction}
Hero must now choose among: {cands}
The simulation verdict says the winning call is: {winner}"""


def classification_prompt(rec: dict) -> str:
    return f"""You are an expert bridge player and teacher. Classify the \
following bidding problem into exactly ONE category of the fixed taxonomy.
Classify by what the DECISION is about, not by the auction stage.

## Taxonomy
{_taxonomy_block()}

## Tie-break rules
{TIE_BREAK}

## Problem
{_problem_facts(rec)}

Respond with ONLY a JSON object, no other text:
{{"type": "<one of: {', '.join(TYPE_IDS)}>", "reason": "<one short sentence>"}}"""


def batch_classification_prompt(recs: list[dict]) -> str:
    """One prompt covering MANY problems, so a chunk is classified in a
    single ``claude`` CLI invocation (the CLI's cold start — Node runtime,
    agent harness, MCP handshake — is paid once per chunk, not once per
    problem).

    Each problem is tagged with its record id; the model must answer with a
    JSON array of one ``{"id", "type", "reason"}`` object per problem."""
    problems = "\n\n".join(
        f"### Problem {i + 1} (id: {rec['id']})\n{_problem_facts(rec)}"
        for i, rec in enumerate(recs))
    return f"""You are an expert bridge player and teacher. Classify EACH of \
the following {len(recs)} bidding problems into exactly ONE category of the \
fixed taxonomy. Classify by what the DECISION is about, not by the auction \
stage. Judge every problem independently.

## Taxonomy
{_taxonomy_block()}

## Tie-break rules
{TIE_BREAK}

## Problems
{problems}

Respond with ONLY a JSON array — one object per problem, using each \
problem's given id, no other text:
[{{"id": "<problem id>", "type": "<one of: {', '.join(TYPE_IDS)}>", \
"reason": "<one short sentence>"}}, ...]"""


def run_github_models(prompt: str, model: str = GITHUB_MODEL,
                      timeout: int = TIMEOUT_S) -> str:
    """Classify via the GitHub Models inference API (OpenAI-compatible chat
    completions). No paid tokens: it runs on the free inference tier.

    Auth: ``GITHUB_TOKEN`` — the token a GitHub Actions job exposes once granted
    ``permissions: models: read`` — or ``GITHUB_MODELS_TOKEN`` (a PAT with
    ``models:read``) for local runs / when the automatic token lacks the scope.

    Response parsing is left to parse_response/parse_batch_response, which pull
    the JSON out of arbitrary text: no ``response_format`` is requested because
    the batch prompt asks for a JSON *array*, which json_object mode rejects.
    temperature 0 for reproducible classifications; max_tokens bounded well
    under the free tier's 4,000-token output cap (chunks are small — see
    DEFAULT_CHUNK_SIZE)."""
    token = (os.environ.get("GITHUB_MODELS_TOKEN")
             or os.environ.get("GITHUB_TOKEN"))
    if not token:
        raise RuntimeError(
            "GitHub Models backend needs GITHUB_TOKEN or GITHUB_MODELS_TOKEN; "
            "in a workflow grant the job `permissions: models: read`.")
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 2000,
    }).encode()
    req = urllib.request.Request(
        GITHUB_MODELS_URL, data=body, method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json",
                 "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise RuntimeError(f"GitHub Models HTTP {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"GitHub Models request failed: {e.reason}")
    try:
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(
            f"GitHub Models: unexpected response shape: {str(payload)[:300]}")


def run_claude_cli(prompt: str, model: str = CLAUDE_MODEL,
                   timeout: int = TIMEOUT_S) -> str:
    # The prompt goes in on stdin, not argv: a whole-pool prompt can approach
    # ARG_MAX (~2 MB) and blow up as a single argument. Feeding it on stdin
    # (which is then closed) also guarantees the headless CLI never blocks
    # waiting on a TTY — a stuck read would otherwise hang until the timeout.
    out = subprocess.run(
        ["claude", "-p", "--model", model],
        input=prompt, capture_output=True, text=True, timeout=timeout)
    if out.returncode != 0:
        raise RuntimeError(f"claude CLI failed: {out.stderr.strip()[:500]}")
    return out.stdout


def parse_response(text: str) -> dict:
    """Extract and validate the {"type", "reason"} object."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"no JSON object in response: {text[:200]!r}")
    obj = json.loads(text[start:end + 1])
    if obj.get("type") not in TYPE_IDS:
        raise ValueError(f"unknown type {obj.get('type')!r}")
    return {"type": obj["type"], "type_reason": str(obj.get("reason", ""))}


def classify_record(rec: dict, run=run_github_models, model: str = MODEL,
                    retries: int = 1) -> dict:
    """Return {"type", "type_reason"} for one problem record."""
    prompt = classification_prompt(rec)
    last_err = None
    for _ in range(retries + 1):
        try:
            return parse_response(run(prompt, model=model))
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
            prompt += ("\n\nYour previous answer was invalid "
                       f"({e}). Respond with ONLY the JSON object.")
    raise ValueError(f"classification failed after retries: {last_err}")


def parse_batch_response(text: str, valid_ids: set[str] | None = None) -> dict:
    """Extract the JSON array and return {id: {"type", "type_reason"}} for
    every well-formed, in-enum entry. Malformed or unknown-type entries are
    skipped (the caller retries whatever ids are still missing). ``valid_ids``,
    when given, drops entries whose id was not in the batch."""
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        raise ValueError(f"no JSON array in response: {text[:200]!r}")
    arr = json.loads(text[start:end + 1])
    out = {}
    for obj in arr:
        if not isinstance(obj, dict):
            continue
        pid, typ = obj.get("id"), obj.get("type")
        if typ not in TYPE_IDS:
            continue
        if valid_ids is not None and pid not in valid_ids:
            continue
        out[pid] = {"type": typ, "type_reason": str(obj.get("reason", ""))}
    return out


def classify_records(recs: list[dict], run=run_github_models, model: str = MODEL,
                     chunk_size: int | None = DEFAULT_CHUNK_SIZE,
                     retries: int = 1, log=lambda _m: None) -> dict:
    """Classify many records with as few CLI invocations as possible.

    Sends ``chunk_size``-sized chunks in one prompt each, so the ``claude``
    CLI cold start is paid once per chunk rather than once per problem. Pass
    ``chunk_size=None`` (or 0) to force the whole pool into a single call —
    fastest to load, but a large pool then generates one huge JSON array that
    can time out or truncate mid-array (the "hang" this default guards
    against).

    Resilience: a chunk whose CLI call hangs (timeout), errors, or comes back
    unparseable is SPLIT in half and each half retried on its own, so one bad
    stretch can't take down the rest. A single problem that still fails is
    simply omitted. Returns {id: {"type", "type_reason"}}; omitted ids are
    left unclassified for a later run to pick up.
    """
    if not recs:
        return {}
    size = chunk_size or len(recs)
    queue = [recs[i:i + size] for i in range(0, len(recs), size)]
    results: dict = {}
    while queue:
        chunk = queue.pop(0)
        pending = list(chunk)
        split = False
        for attempt in range(retries + 1):
            if not pending:
                break
            ids = {r["id"] for r in pending}
            prompt = batch_classification_prompt(pending)
            if attempt:
                prompt += ("\n\nYour previous answer was missing or invalid "
                           "for some problems. Respond with ONLY the JSON "
                           "array, one object per problem shown above.")
            try:
                got = parse_batch_response(run(prompt, model=model), ids)
            except (subprocess.TimeoutExpired, RuntimeError,
                    ValueError, json.JSONDecodeError) as e:
                # A hung/failed CLI or an unparseable (often truncated) batch:
                # retrying the SAME size rarely helps, so halve it and requeue
                # the halves. Down to a single problem we give up and omit it.
                if len(pending) > 1:
                    mid = len(pending) // 2
                    queue[:0] = [pending[:mid], pending[mid:]]
                    log(f"  batch of {len(pending)} failed "
                        f"({str(e)[:80]}); split into {mid}+{len(pending) - mid}")
                    split = True
                    break
                log(f"  {pending[0]['id']}: failed ({str(e)[:80]})")
                got = {}
            results.update(got)
            pending = [r for r in pending if r["id"] not in results]
        if not split and pending:
            log(f"  {len(pending)} unclassified after {retries + 1} tries: "
                f"{[r['id'] for r in pending]}")
    return results
