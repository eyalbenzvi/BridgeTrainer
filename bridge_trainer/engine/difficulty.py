"""Difficulty classification for published problems (expert-reviewed v2).

Construct: DiffScore estimates the probability that a competent club player
gets the problem WRONG. It is deliberately NOT the cost of an error (that is
``quality.stakes``) and NOT editorial interest (``quality.interest``).

    DiffScore = 50*INSTINCT + 30*CLOSENESS + 20*STRUCTURE      (0-100)

INSTINCT   "the field's compass points wrong": how little policy mass the
           winning call carries, plus a bonus when the natural compass is
           actively misleading (trap: the policy argmax loses; dissonance:
           the winner loses more layouts than it wins, or win-rate overruled
           the EV edge). Trap and dissonance are mutually exclusive by
           construction, so the bonus stays binary.
CLOSENESS  how nearly tied the decision is, measured twice for variance
           reduction: the IMP EV gap (noisy) and the per-layout win-rate
           margin (well measured), averaged.
STRUCTURE  five cheap indicators of situational complexity: contested
           auction, deep stem, declare/defend flip, doubled contracts,
           and a low-frequency winning action (Pass/X/XX).

Levels 1-5 use FIXED cut points so a problem's label never changes as the
pool grows. The level is computed once, at publication, and stored in the
record. Near a cut point the label is stabilized by recomputing the score
on the two sample halves (when the record carries ``quality.half_stats``)
and taking the median of the three levels.
"""
from __future__ import annotations

from statistics import median

CUTS = (35.0, 47.0, 57.0, 68.0)   # level = 1 + #cuts below score
GAP_SPAN = 2.5                    # acceptance band width (verdict.GAP_MAX)
WINRATE_SPAN = 0.40               # win-rate margin that reads as "one-sided"
DEEP_STEM = 4                     # non-pass stem calls that read as "deep"
FLIP_MIN = 0.25
DOUBLED_MIN = 0.15
BOUNDARY_GUARD = 3.0              # score points from a cut => split-half check

W_INSTINCT, W_CLOSENESS, W_STRUCTURE = 50.0, 30.0, 20.0
W_POLICY, W_MISLEAD = 0.7, 0.3

SEATS = "NESW"


def _level(score: float) -> int:
    return 1 + sum(score >= c for c in CUTS)


def _contested(auction: list[str], dealer: str, seat: str) -> bool:
    hero = SEATS.index(seat)
    dealer_i = SEATS.index(dealer)
    return any(t != "P" and (dealer_i + j - hero) % 2 == 1
               for j, t in enumerate(auction))


def _dissonant(accepted: str, quality: dict,
               p_top: float, p_second: float) -> bool:
    """The natural verdict points away from the winner: win-rate overruled
    a sub-0.5-IMP EV edge, or the EV winner loses more layouts than it wins
    ("right in the long run, wrong most nights")."""
    if "win-rate over" in quality.get("winner_by", ""):
        return True
    top2 = quality.get("top2") or []
    return bool(top2) and accepted == top2[0] and p_top < p_second


def _closeness(gap: float, p_top: float, p_second: float) -> float:
    ev_close = 1.0 - min(max(gap, 0.0) / GAP_SPAN, 1.0)
    wr_close = 1.0 - min(abs(p_top - p_second) / WINRATE_SPAN, 1.0)
    return 0.5 * ev_close + 0.5 * wr_close


def _score(instinct_policy: float, misled: bool, closeness: float,
           structure: float) -> float:
    instinct = W_POLICY * instinct_policy + W_MISLEAD * float(misled)
    return (W_INSTINCT * instinct + W_CLOSENESS * closeness
            + W_STRUCTURE * structure)


def difficulty_classification(rec: dict) -> dict:
    """Compute {"difficulty_score", "difficulty_level"} from a published
    problem record (the dict built by maker.build_record). Pure function of
    stored evidence; safe to backfill onto existing records."""
    q = rec["quality"]
    accepted = rec["verdict"]["accepted"]
    if not accepted:  # legacy toss-up records: rate as the closest possible
        accepted = (q.get("top2") or [""])[0]

    policy = {c["call"]: float(c["policy"]) for c in rec["candidates"]}
    total = sum(policy.values())
    p_norm = policy.get(accepted, 0.0) / total if total > 0 else 0.0
    instinct_policy = 1.0 - p_norm

    gap = float(q["gap_imps"])
    p_top = float(q.get("p_top_wins", 0.0))
    p_second = float(q.get("p_second_wins", 0.0))
    misled = bool(q.get("trap")) or _dissonant(accepted, q, p_top, p_second)
    closeness = _closeness(gap, p_top, p_second)

    structure = (
        float(_contested(rec["auction"], rec["dealer"], rec["seat"]))
        + float(sum(1 for t in rec["auction"] if t != "P") >= DEEP_STEM)
        + float(float(q.get("flip", 0.0)) >= FLIP_MIN)
        + float(float(q.get("doubled_share", 0.0)) >= DOUBLED_MIN)
        + float(accepted in ("P", "X", "XX"))
    ) / 5.0

    score = _score(instinct_policy, misled, closeness, structure)
    level = _level(score)

    # boundary stabilization: near a cut, the median level of (full, half1,
    # half2) decides — "would this label replicate under resampling?"
    halves = q.get("half_stats")
    if halves and min(abs(score - c) for c in CUTS) < BOUNDARY_GUARD:
        levels = [level]
        for h in halves:
            h_top = float(h["p_top_wins"])
            h_second = float(h["p_second_wins"])
            h_misled = bool(q.get("trap")) or _dissonant(
                accepted, q, h_top, h_second)
            levels.append(_level(_score(
                instinct_policy, h_misled,
                _closeness(float(h["gap_imps"]), h_top, h_second),
                structure)))
        level = int(median(levels))

    return {"difficulty_score": round(score, 1), "difficulty_level": level}
