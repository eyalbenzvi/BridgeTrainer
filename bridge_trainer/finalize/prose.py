"""Post-verdict explanation pipeline (backlog group E).

Explanations are authored AFTER the DD verdict exists and are linted
against the record before they ship. The b1 editor found texts written
pre-verdict ("the simulation will show..."), texts arguing for the
option the verdict rejects, blowouts described as close decisions, and
checkable hand facts that were simply wrong. Everything checkable is
checked here; attach_explanation() is the only sanctioned way to put
prose on a record.
"""
from __future__ import annotations

import re

from ..dealing.features import HCP_BY_RANK, parse_hand_pbn

FUTURE_SIM = re.compile(
    r"\b(simulation|verdict|double.?dummy|dd)\b[^.!?]{0,60}\bwill\b",
    re.IGNORECASE)
TOSS_UP_WORDS = re.compile(
    r"toss.?up|too close|dead heat|cannot separate|can't separate|"
    r"either .{0,40}(is|works|scores)|photo finish", re.IGNORECASE)
CLOSE_WORDS = re.compile(
    r"\bclose\b|coin.?flip|classic .{0,20}decision|"
    r"the question is whether", re.IGNORECASE)
CROWN_WORDS = re.compile(
    r"\bclear(ly)? (best|winner|right)|stands out|landslide|no contest",
    re.IGNORECASE)
GARBLED = [
    "plus-showing calls",
    "consumes your side",
    "flagged as such",
    "is flagged",
]
SHAPE_CLAIM = re.compile(r"\b(\d)[-=](\d)[-=](\d)[-=](\d)\b")
_WORD_NUMS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen seventeen eighteen nineteen "
    "twenty".split())}
COUNT_CLAIM = re.compile(r"\b(\d{1,2}|[a-z]+)[- ]count\b", re.IGNORECASE)
GEOMETRY = re.compile(
    r"\b(behind|in front of|over|under) (the )?"
    r"(opener|opening bidder|doubler|declarer|dummy|overcaller)\b",
    re.IGNORECASE)

BLOWOUT_EV = 4.0
BLOWOUT_P = 0.85


class ProseError(ValueError):
    pass


def _hand_facts(hand: str) -> tuple[int, list[int]]:
    cards = parse_hand_pbn(hand)
    hcp = int(sum(HCP_BY_RANK[c % 13] for c in cards))
    lengths = [sum(1 for c in cards if c // 13 == i) for i in range(4)]
    return hcp, lengths


def lint_explanation(text: str, record: dict) -> tuple[list[str], list[str]]:
    """Returns (errors, warnings) for a candidate explanation body.

    The body is the prose only — deviation ⚠ lines and the at-the-table
    line are appended mechanically afterwards, so referring to flags in
    prose is a duplication error, not a requirement.
    """
    errors: list[str] = []
    warnings: list[str] = []
    verdict = record["verdict"]
    accepted = verdict["accepted"]
    toss_up = verdict["toss_up"]
    margin = abs(float(record["difficulty"]))
    top = verdict["corrected"][0]

    if FUTURE_SIM.search(text):
        errors.append("refers to the simulation/verdict as pending "
                      "(future tense) — explanations are written after "
                      "the verdict")

    for opt in record["candidates"]:
        if opt not in text:
            errors.append(f"option {opt!r} is never addressed")

    if toss_up:
        if not TOSS_UP_WORDS.search(text):
            errors.append("verdict is a toss-up but the text never says "
                          "the options cannot be separated")
        if CROWN_WORDS.search(text):
            errors.append("verdict is a toss-up but the text crowns a "
                          "clear winner")
    else:
        if accepted[0] not in text:
            errors.append(f"winner {accepted[0]!r} never named")

    if (margin >= BLOWOUT_EV or top["p_gain"] >= BLOWOUT_P) \
            and CLOSE_WORDS.search(text):
        errors.append(f"margin is {margin} IMPs (p_gain {top['p_gain']}) "
                      f"but the text calls the decision close")

    for phrase in GARBLED:
        if phrase in text:
            errors.append(f"forbidden phrase {phrase!r} (garbled or "
                          f"duplicates the auto-appended flag lines)")

    hcp, lengths = _hand_facts(record["hand"])
    for m in SHAPE_CLAIM.finditer(text):
        claimed = [int(g) for g in m.groups()]
        if sum(claimed) == 13 and claimed != lengths \
                and sorted(claimed) != sorted(lengths):
            errors.append(f"shape claim {m.group(0)!r} does not match the "
                          f"hero hand ({'-'.join(map(str, lengths))})")
    for m in COUNT_CLAIM.finditer(text):
        raw = m.group(1).lower()
        val = int(raw) if raw.isdigit() else _WORD_NUMS.get(raw)
        if val is not None and val != hcp and not _in_any_band(val, record):
            errors.append(f"claim {m.group(0)!r} matches neither the hero "
                          f"hand ({hcp} HCP) nor any concealed seat's range")
    if "balanced" in text.lower() and min(lengths) <= 1:
        warnings.append("says 'balanced' while the hero hand has a "
                        "singleton/void — verify the referent")
    for m in GEOMETRY.finditer(text):
        warnings.append(f"positional claim {m.group(0)!r} — verify against "
                        f"the seating rotation")

    dev = set(record.get("deviations") or [])
    if set(accepted) & dev and not re.search(r"card|deviat|off.?card",
                                             text, re.IGNORECASE):
        errors.append("an accepted option deviates from the card but the "
                      "text never reconciles judgment with the system")

    return errors, warnings


def _in_any_band(val: int, record: dict) -> bool:
    for m in record.get("meanings") or []:
        spec = m.get("hcp")
        if spec and spec[0] <= val <= spec[1]:
            return True
    return False


def render_full_explanation(body: str, record: dict) -> str:
    """Body + mechanical ⚠/ℹ deviation lines + the at-the-table line."""
    out = body.rstrip()
    for opt, spec in sorted((record.get("deviations") or {}).items()):
        glyph = "⚠" if spec.get("kind") == "card_violation" else "ℹ"
        out += f"\n{glyph} {opt} — {spec['note']}"
    src = record.get("source") or {}
    rooms = src.get("room_calls") or {}
    contracts = src.get("room_contracts") or {}
    if rooms.get("o") and rooms.get("c"):
        out += (f"\nAt the table: one room chose {rooms['o']} "
                f"(reaching {contracts.get('o') or '?'}), the other "
                f"{rooms['c']} (reaching {contracts.get('c') or '?'}).")
    return out


def attach_explanation(record: dict, body: str) -> dict:
    """Lint the body against the finished record, then install it.

    Raises ProseError listing every lint error; warnings are stored in
    record['quality']['prose_warnings'].
    """
    errors, warnings = lint_explanation(body, record)
    if errors:
        raise ProseError("explanation rejected:\n- " + "\n- ".join(errors))
    record["explanation"] = render_full_explanation(body, record)
    record.setdefault("quality", {})["prose_warnings"] = warnings
    return record
