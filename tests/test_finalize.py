"""Finalization documents: validation + end-to-end record building."""
import pytest

from bridge_trainer.finalize.schema import (FinalizationError, build_record,
                                            validate_finalization)

HANDS = {"N": "KQJT42.3.K2.Q543", "E": "A75.9864.T963.87",
         "S": "K93.752.A854.T62", "W": "8.AKQJT.QJ7.AKJ9"}

DOC = dict(
    dilemma=True,
    options=["P", "3S"],
    meanings={
        "W": {"note": "1H opener", "hcp": [11, 19, [[10, 10, 0.4]]],
              "suits": {"H": [5, 7, []]}},
        "N": {"note": "1S overcall", "hcp": [8, 16, []],
              "suits": {"S": [5, 7, []]}},
        "E": {"note": "weak raise", "hcp": [2, 9, []],
              "suits": {"H": [4, 5, []]}},
    },
    projections={
        "P": [{"else": {"contract": "3HW"}}],
        "3S": [{"when": "lho_hcp >= 17", "contract": "4HW"},
               {"else": {"contract": "3SN"}}],
    },
    explanation="Compete or defend on the eight-card fit.",
)


def test_validation_rejections():
    with pytest.raises(FinalizationError):
        validate_finalization({**DOC, "dilemma": False}, "S")
    with pytest.raises(FinalizationError):
        validate_finalization({**DOC, "options": ["P"]}, "S")
    with pytest.raises(FinalizationError):
        validate_finalization({**DOC, "options": ["P", "8H"]}, "S")
    with pytest.raises(FinalizationError):  # projections must match options
        validate_finalization({**DOC, "options": ["P", "3S", "X"]}, "S")
    bad_tree = {**DOC, "projections": {"P": [{"when": "lho_hcp > 5",
                                              "contract": "3HW"}],
                                       "3S": DOC["projections"]["3S"]}}
    with pytest.raises(ValueError):  # tree must end with else
        validate_finalization(bad_tree, "S")
    with pytest.raises(FinalizationError):  # meanings can't cover the hero
        validate_finalization(
            {**DOC, "meanings": {**DOC["meanings"],
                                 "S": {"hcp": [0, 40, []]}}}, "S")
    validate_finalization(DOC, "S")  # the good doc passes


def test_build_record_end_to_end():
    rec = build_record(
        problem_id="t1", dealer="W", vul="EW", hero="S", hands=HANDS,
        stem=["1H", "1S", "3H"], doc=DOC, n_deals=60, seed=5)
    assert rec["candidates"] == ["P", "3S"]
    assert rec["seat"] == "S" and rec["hand"] == HANDS["S"]
    v = rec["verdict"]
    assert set(v["accepted"]) <= {"P", "3S"}
    assert {r["action"] for r in v["corrected"]} == {"P", "3S"}
    assert rec["explanation"]
    assert rec["meanings"][0]["meaning"]


def test_build_record_deterministic():
    a = build_record(problem_id="t1", dealer="W", vul="EW", hero="S",
                     hands=HANDS, stem=["1H", "1S", "3H"], doc=DOC,
                     n_deals=60, seed=5)
    b = build_record(problem_id="t1", dealer="W", vul="EW", hero="S",
                     hands=HANDS, stem=["1H", "1S", "3H"], doc=DOC,
                     n_deals=60, seed=5)
    a.pop("created_at"), b.pop("created_at")
    assert a == b
