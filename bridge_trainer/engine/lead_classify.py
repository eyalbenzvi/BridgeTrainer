"""Deterministic problem-type categories for opening-lead problems.

Unlike bidding problems (engine/classify.py — an LLM classifier over the
judgment literature's taxonomy), a lead problem's category is a MECHANICAL
fact of the final contract: what you are leading against. So it is computed
directly from the contract string — no model, exact, and trivially
backfilled onto every existing record.

One category per problem, mirroring the single ``classification.type`` that
bidding problems carry. A doubled contract takes precedence over the
level/strain buckets: leading against a doubled contract is its own skill
(Lightner / lead-directing signals), so it forms one group regardless of
level or strain.
"""
from __future__ import annotations

# id, English label, Hebrew label, one-line Hebrew description
LEAD_TAXONOMY = [
    ("lead_part_score", "Part-score", "חוזה חלקי",
     "הובלה נגד חוזה חלקי (מתחת למשחק מלא)."),
    ("lead_3nt", "3NT", "3NT",
     "הובלה נגד משחק ללא שליט."),
    ("lead_suit_game", "Suit game", "משחק בשליט",
     "הובלה נגד משחק מלא בשליט (4 בגבוה / 5 בנמוך)."),
    ("lead_slam", "Slam", "סלם",
     "הובלה נגד סלם (רמה 6 או 7)."),
    ("lead_doubled", "Doubled", "חוזה מוכפל",
     "הובלה נגד חוזה מוכפל."),
]

LEAD_TYPE_IDS = [t[0] for t in LEAD_TAXONOMY]
LEAD_LABELS_EN = {t[0]: t[1] for t in LEAD_TAXONOMY}
LEAD_LABELS_HE = {t[0]: t[2] for t in LEAD_TAXONOMY}

# Ben's 32-card lead encoding (mirrors engine/ben.lead_code32, kept here as a
# pure, TensorFlow-free copy so the verdict gate and offline tooling can dedupe
# equivalent cards without importing the engine). Spot cards 7..2 fold into one
# "low card per suit" slot, so a suit's low spots share a single policy mass.
_RANKS = "AKQJT98765432"


def lead_code32(token: str) -> int:
    """Return Ben's 32-card lead code for a card token like 'HK' or 'S7'."""
    return "SHDC".index(token[0]) * 8 + min(_RANKS.index(token[1]), 7)


def answer_policy_mass(best_cards, softmax: dict) -> float:
    """BEN's opening-lead policy mass on the ANSWER (tied-best) set, deduped by
    32-card code: touching honors count separately (distinct codes) but folded
    low spots (e.g. H3/H2) share one code and are counted once. This is the
    correct 'how sure is BEN of the answer' measure for the C1 obvious gate."""
    seen, mass = set(), 0.0
    for c in best_cards:
        code = lead_code32(c)
        if code not in seen:
            seen.add(code)
            mass += softmax.get(c, 0.0)
    return mass

_MAJORS = ("H", "S")
_MINORS = ("C", "D")


def classify_contract(level: int, denom: str, doubled: str = "") -> str:
    """Return the lead category id for a final contract.

    ``doubled`` is "" / "x" / "xx". A doubled contract is ``lead_doubled``
    regardless of level or strain (its own defensive skill). Otherwise:

      * ``lead_slam``       — level 6 or 7, any strain
      * ``lead_3nt``        — notrump game (3NT, and the rare 4NT/5NT)
      * ``lead_suit_game``  — 4+ in a major or 5+ in a minor, below slam
      * ``lead_part_score`` — everything else below game
    """
    if doubled:
        return "lead_doubled"
    if level >= 6:
        return "lead_slam"
    if denom == "NT":
        return "lead_3nt" if level >= 3 else "lead_part_score"
    if (denom in _MAJORS and level >= 4) or (denom in _MINORS and level >= 5):
        return "lead_suit_game"
    return "lead_part_score"


def parse_contract(contract: str) -> tuple[int, str, str]:
    """Split a stored contract string into (level, denom, doubled).

    Format is ``{level}{denom}{declarer}{doubled}`` (conventions.contract_str):
    ``'4HE'`` -> (4, 'H', ''); ``'3NTWx'`` -> (3, 'NT', 'x');
    ``'6SSxx'`` -> (6, 'S', 'xx'). The declarer seat (last non-double char)
    is not needed for categorization and is dropped.
    """
    level = int(contract[0])
    rest = contract[1:]
    doubled = ""
    if rest.endswith("xx"):
        doubled, rest = "xx", rest[:-2]
    elif rest.endswith("x"):
        doubled, rest = "x", rest[:-1]
    denom = rest[:-1]          # everything but the trailing declarer seat
    return level, denom, doubled


def classify_lead_record(rec: dict) -> str:
    """Category id from a stored lead record's ``contract`` string."""
    return classify_contract(*parse_contract(rec["contract"]))
