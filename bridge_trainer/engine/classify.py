"""LLM problem-type classifier: assigns each published problem exactly one
of a FIXED 10-category bridge taxonomy (synthesized from the de-facto
taxonomies in the judgment literature: Lawrence's *Judgment at Bridge*
chapters, Robson & Segal's *The Contested Auction*, Cohen's LOTT framing —
BridgeWinners and the Master Solvers Club publish no typology of their own).

Categories describe WHAT MAKES THE PROBLEM HARD, not the auction stage.
The classifier sees the hero hand, the auction with the engine's call
meanings, vulnerability, the candidate calls and the winning call, and must
answer with one category id plus a one-sentence reason (stored for audit).

Backend: the ``claude`` CLI in headless mode (problems are generated inside
Claude Code sessions at this stage), model claude-sonnet-5.
"""
from __future__ import annotations

import json
import subprocess

MODEL = "claude-sonnet-5"
TIMEOUT_S = 300

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


def classification_prompt(rec: dict) -> str:
    taxonomy = "\n".join(f"{i + 1}. {tid} — {name}: {desc}"
                         for i, (tid, name, _, desc) in enumerate(TAXONOMY))
    cands = ", ".join(f"{c['call']} (engine policy {c['policy']:.0%})"
                      for c in rec["candidates"])
    winner = rec["verdict"]["accepted"]
    auction = "\n".join(f"  {ln}" for ln in _auction_lines(rec)) or \
        "  (hero opens the auction)"
    return f"""You are an expert bridge player and teacher. Classify the \
following bidding problem into exactly ONE category of the fixed taxonomy.
Classify by what the DECISION is about, not by the auction stage.

## Taxonomy
{taxonomy}

## Tie-break rules
{TIE_BREAK}

## Problem
Scoring: {rec.get('scoring_form', 'IMPs')}. Both sides play standard 2/1 \
Game Force.
Vulnerability: {rec['vul']} (seats: NS / EW). Dealer: {rec['dealer']}.
Hero sits {rec['seat']} and holds: {pretty_hand(rec['hand'])}
Auction so far (with the engine's call meanings):
{auction}
Hero must now choose among: {cands}
The simulation verdict says the winning call is: {winner}

Respond with ONLY a JSON object, no other text:
{{"type": "<one of: {', '.join(TYPE_IDS)}>", "reason": "<one short sentence>"}}"""


def run_claude_cli(prompt: str, model: str = MODEL) -> str:
    out = subprocess.run(
        ["claude", "-p", prompt, "--model", model],
        capture_output=True, text=True, timeout=TIMEOUT_S)
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


def classify_record(rec: dict, run=run_claude_cli, model: str = MODEL,
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
