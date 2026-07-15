"""Duplicate bridge scoring and the IMP table. Golden-tested against endplay."""
from __future__ import annotations

_TRICK_VALUE = {"C": 20, "D": 20, "H": 30, "S": 30}


def contract_score(level: int, denom: str, doubled: int,
                   vul: bool, tricks: int) -> int:
    """Duplicate score for declarer's side. doubled: 0/1/2 (x/xx).

    level 0 = passed out -> 0.
    """
    if level == 0:
        return 0
    need = level + 6
    if tricks < need:
        return -_penalty(need - tricks, doubled, vul)

    if denom == "NT":
        trick_pts = 40 + 30 * (level - 1)
        per_over = 30
    else:
        trick_pts = _TRICK_VALUE[denom] * level
        per_over = _TRICK_VALUE[denom]
    trick_pts *= (1 << doubled)

    score = trick_pts
    score += (500 if vul else 300) if trick_pts >= 100 else 50
    if level == 6:
        score += 750 if vul else 500
    elif level == 7:
        score += 1500 if vul else 1000
    if doubled:
        score += 50 * doubled  # the insult

    overtricks = tricks - need
    if overtricks > 0:
        if doubled:
            score += overtricks * (200 if vul else 100) * doubled
        else:
            score += overtricks * per_over
    return score


def _penalty(down: int, doubled: int, vul: bool) -> int:
    if not doubled:
        return down * (100 if vul else 50)
    if vul:
        pen = 200 + (down - 1) * 300
    else:
        # 100, 300, 500, then 300 per trick from the 4th
        steps = [100, 200, 200] + [300] * max(0, down - 3)
        pen = sum(steps[:down])
    return pen * doubled  # xx doubles the doubled penalty


IMP_BOUNDS = (20, 50, 90, 130, 170, 220, 270, 320, 370, 430, 500, 600, 750,
              900, 1100, 1300, 1500, 1750, 2000, 2250, 2500, 3000, 3500, 4000)


def imps(diff: float) -> int:
    """Score difference (my perspective) -> IMPs, standard WBF table."""
    sign = 1 if diff >= 0 else -1
    a = abs(diff)
    return sign * sum(1 for b in IMP_BOUNDS if a >= b)
