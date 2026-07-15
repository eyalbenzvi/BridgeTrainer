"""Golden tests: contract scoring table (vs endplay) and the IMP table."""
import pytest
from endplay.types import Contract, Denom, Penalty, Player, Vul

from bridge_trainer.scoring.tables import contract_score, imps

_DENOMS = {"C": Denom.clubs, "D": Denom.diamonds, "H": Denom.hearts,
           "S": Denom.spades, "NT": Denom.nt}
_PENALTIES = {0: Penalty.passed, 1: Penalty.doubled, 2: Penalty.redoubled}


@pytest.mark.parametrize("level", [1, 2, 3, 4, 5, 6, 7])
@pytest.mark.parametrize("denom", ["C", "D", "H", "S", "NT"])
@pytest.mark.parametrize("doubled", [0, 1, 2])
@pytest.mark.parametrize("vul", [False, True])
def test_score_matches_endplay_full_grid(level, denom, doubled, vul):
    for tricks in range(0, 14):
        ours = contract_score(level, denom, doubled, vul, tricks)
        c = Contract(level=level, denom=_DENOMS[denom], declarer=Player.south,
                     penalty=_PENALTIES[doubled], result=tricks - (level + 6))
        theirs = c.score(Vul.both if vul else Vul.none)
        assert ours == theirs, (
            f"{level}{denom} x{doubled} vul={vul} tricks={tricks}: "
            f"{ours} != endplay {theirs}")


def test_passed_out_scores_zero():
    assert contract_score(0, "", 0, True, 0) == 0


# Hand-picked golden values (independent of endplay).
GOLDEN_SCORES = [
    (3, "S", 0, False, 9, 140),
    (3, "S", 0, False, 8, -50),
    (3, "H", 1, True, 8, -200),    # 3Hx down 1 vul
    (3, "H", 1, True, 9, 730),     # 3Hx= vul
    (3, "S", 1, False, 9, 530),    # 3Sx= NV (doubled into game)
    (4, "H", 0, True, 10, 620),
    (3, "NT", 0, False, 9, 400),
    (6, "S", 0, True, 12, 1430),
    (7, "NT", 1, True, 13, 2490),
    (1, "C", 2, False, 7, 230),    # 1Cxx= NV
    (2, "S", 1, False, 4, -800),   # 2Sx down 4 NV
    (5, "D", 1, True, 7, -1100),   # 5Dx down 4 vul
]


@pytest.mark.parametrize("level,denom,doubled,vul,tricks,expected", GOLDEN_SCORES)
def test_golden_scores(level, denom, doubled, vul, tricks, expected):
    assert contract_score(level, denom, doubled, vul, tricks) == expected


GOLDEN_IMPS = [
    (0, 0), (10, 0), (20, 1), (40, 1), (50, 2), (-50, -2), (90, 3),
    (110, 3), (430, 10), (450, 10), (500, 11), (750, 13), (1100, 15),
    (2000, 19), (3999, 23), (4000, 24), (9999, 24), (-9999, -24),
]


@pytest.mark.parametrize("diff,expected", GOLDEN_IMPS)
def test_imp_table(diff, expected):
    assert imps(diff) == expected
