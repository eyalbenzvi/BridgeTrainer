import json
from pathlib import Path

import pytest

from bridge_trainer.engine.classify import (
    TAXONOMY, TYPE_IDS, classification_prompt, classify_record,
    parse_response, pretty_hand)

POOL = Path(__file__).parent.parent / "data" / "problems"


def test_taxonomy_is_fixed_and_unique():
    assert len(TAXONOMY) == 10
    assert len(set(TYPE_IDS)) == 10


def test_pretty_hand_handles_void():
    assert pretty_hand("AKJT62..985.Q986") == "♠AKJT62 ♥— ♦985 ♣Q986"


def test_prompt_contains_the_decision_facts():
    rec = json.loads(next(iter(sorted(POOL.glob("*.json")))).read_text())
    prompt = classification_prompt(rec)
    for tid in TYPE_IDS:
        assert tid in prompt
    assert pretty_hand(rec["hand"]) in prompt
    assert rec["verdict"]["accepted"] in prompt
    for c in rec["candidates"]:
        assert c["call"] in prompt


def test_parse_response_accepts_json_with_noise():
    out = parse_response(
        'Sure!\n{"type": "compete_or_sell", "reason": "part-score battle"}')
    assert out == {"type": "compete_or_sell",
                   "type_reason": "part-score battle"}


def test_parse_response_rejects_unknown_type():
    with pytest.raises(ValueError):
        parse_response('{"type": "bogus", "reason": "x"}')


def test_classify_record_retries_then_succeeds():
    calls = []

    def flaky(prompt, model):
        calls.append(prompt)
        if len(calls) == 1:
            return "not json"
        return '{"type": "slam_try", "reason": "keycard decision"}'

    rec = json.loads(next(iter(sorted(POOL.glob("*.json")))).read_text())
    out = classify_record(rec, run=flaky)
    assert out["type"] == "slam_try"
    assert len(calls) == 2
    assert "invalid" in calls[1]


def test_classify_record_gives_up_after_retries():
    rec = json.loads(next(iter(sorted(POOL.glob("*.json")))).read_text())
    with pytest.raises(ValueError):
        classify_record(rec, run=lambda p, model: "never json", retries=1)
