"""Optional LLM narration layer — minimal by design (spec 4.3).

ONE API call per report, prose sections only: the model receives the fully
computed facts JSON and returns Hebrew prose for sections 1, 2 and 7. All
tables, numbers and deals stay code-generated (report.py); the model is
told it may not introduce any number that is not in the facts.

Cost controls:
  * model: claude-haiku-4-5 — the cheapest current model; per the task
    spec, escalate one tier only if quality proves insufficient in use.
  * prompt caching: the fixed instruction block carries cache_control, so
    repeat analyses pay cache-read prices on the static prefix.
  * no extended thinking — the heavy inference already happened in code.
  * hard max_tokens ceiling.

Failure of any kind (no API key, no SDK, network, bad JSON) falls back
transparently to the template narrator — the report always renders.
"""
from __future__ import annotations

import json
import os

from .report import narrate_all

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 3000

SYSTEM_PROMPT = """\
You are an expert bridge analyst writing in HEBREW for a serious club
player. You receive a JSON object with fully computed simulation facts
about one bidding decision. Write analytic prose in the voice of a
professional bridge report: direct, concrete, explaining WHY each action
wins or loses structurally (fit, values, vulnerability, risk profile), not
just repeating numbers.

STRICT RULES:
- Hebrew only. Right-to-left prose. Bridge terms may stay in English/
  symbols (IMP, 3NT, X).
- Use ONLY numbers that appear in the facts JSON. Never invent, round
  differently, or extrapolate a number.
- Do not contradict the recommendation in facts.recommended.
- Output VALID JSON only, with exactly these keys:
  {"situation_html": "<p>...</p>",
   "candidates_html": {"<action token>": "<p>...</p>", ...},
   "conclusion_html": "<p>...</p>"}
  HTML paragraphs only (<p>, <b>, <small>); no headings, no tables.
- candidates_html must contain one entry per action in facts.candidates.
- situation_html: read the auction like an expert (what each call and each
  PASS implies about the hidden hands), ending with what the decision
  hinges on.
- conclusion_html: the bottom line, the margin vs the runner-up including
  the confidence interval, whether the user's actual call matches, and the
  stability-across-policies verdict from facts.stability.note.
"""


def llm_narrate(facts: dict) -> dict:
    """Single-call LLM narration; template fallback on ANY failure."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return narrate_all(facts)
    try:
        import anthropic
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                # static prefix cached across analyses (spec 4.3)
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{
                "role": "user",
                "content": json.dumps(facts, ensure_ascii=False),
            }],
        )
        text = "".join(b.text for b in response.content
                       if b.type == "text").strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text[text.index("{"):text.rindex("}") + 1]
        prose = json.loads(text)
        usage = getattr(response, "usage", None)
        out = {
            "situation_html": prose["situation_html"],
            "candidates_html": dict(prose["candidates_html"]),
            "conclusion_html": prose["conclusion_html"],
            "narrator": "llm",
        }
        if usage is not None:
            out["llm_usage"] = {
                "model": MODEL,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_read_input_tokens":
                    getattr(usage, "cache_read_input_tokens", 0),
                "cache_creation_input_tokens":
                    getattr(usage, "cache_creation_input_tokens", 0),
            }
        # every candidate must be covered; template-fill any gap
        fallback = narrate_all(facts)
        for cand in facts["candidates"]:
            out["candidates_html"].setdefault(
                cand, fallback["candidates_html"].get(cand, ""))
        return out
    except Exception:
        return narrate_all(facts)


def estimate_prompt_tokens(facts: dict) -> dict:
    """Local cost estimate for DECISIONS.md (no API needed): ~4 chars per
    token is a serviceable approximation for mixed Hebrew/JSON text."""
    static = len(SYSTEM_PROMPT)
    dynamic = len(json.dumps(facts, ensure_ascii=False))
    return {
        "static_chars": static, "dynamic_chars": dynamic,
        "approx_static_tokens": static // 4,
        "approx_dynamic_tokens": dynamic // 3,
        "approx_output_tokens_cap": MAX_TOKENS,
    }
