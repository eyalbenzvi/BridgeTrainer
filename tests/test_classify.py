import json
from pathlib import Path

import pytest

from bridge_trainer.engine.classify import (
    TAXONOMY, TYPE_IDS, batch_classification_prompt, classification_prompt,
    classify_record, classify_records, parse_batch_response, parse_response,
    pretty_hand)

# The problem bank lives in Firestore now (data/problems is no longer
# committed); tests read a representative record from a checked-in fixture.
SAMPLE = Path(__file__).parent / "fixtures" / "ben1_sample.json"


def test_taxonomy_is_fixed_and_unique():
    assert len(TAXONOMY) == 10
    assert len(set(TYPE_IDS)) == 10


def test_pretty_hand_handles_void():
    assert pretty_hand("AKJT62..985.Q986") == "♠AKJT62 ♥— ♦985 ♣Q986"


def test_prompt_contains_the_decision_facts():
    rec = json.loads(SAMPLE.read_text())
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

    rec = json.loads(SAMPLE.read_text())
    out = classify_record(rec, run=flaky)
    assert out["type"] == "slam_try"
    assert len(calls) == 2
    assert "invalid" in calls[1]


def test_classify_record_gives_up_after_retries():
    rec = json.loads(SAMPLE.read_text())
    with pytest.raises(ValueError):
        classify_record(rec, run=lambda p, model: "never json", retries=1)


def _two_recs():
    rec = json.loads(SAMPLE.read_text())
    a = {**rec, "id": "ben1-aaaa"}
    b = {**rec, "id": "ben1-bbbb"}
    return a, b


def test_batch_prompt_lists_every_problem_by_id():
    a, b = _two_recs()
    prompt = batch_classification_prompt([a, b])
    for tid in TYPE_IDS:
        assert tid in prompt
    assert "ben1-aaaa" in prompt and "ben1-bbbb" in prompt
    assert prompt.count(pretty_hand(a["hand"])) == 2   # one facts block each


def test_parse_batch_response_keeps_valid_drops_unknown():
    out = parse_batch_response(
        'noise [{"id":"x","type":"slam_try","reason":"r"},'
        '{"id":"y","type":"bogus","reason":"r"}] tail',
        valid_ids={"x", "y"})
    assert out == {"x": {"type": "slam_try", "type_reason": "r"}}


def test_classify_records_one_call_for_whole_batch():
    a, b = _two_recs()
    calls = []

    def run(prompt, model):
        calls.append(prompt)
        return ('[{"id":"ben1-aaaa","type":"compete_or_sell","reason":"p"},'
                '{"id":"ben1-bbbb","type":"invite_or_game","reason":"q"}]')

    out = classify_records([a, b], run=run)
    assert len(calls) == 1                       # the CLI is loaded once
    assert out["ben1-aaaa"]["type"] == "compete_or_sell"
    assert out["ben1-bbbb"]["type"] == "invite_or_game"


def test_classify_records_retries_only_missing_ids():
    a, b = _two_recs()
    calls = []

    def run(prompt, model):
        calls.append(prompt)
        if len(calls) == 1:                      # first pass: only 'a' comes back
            return '[{"id":"ben1-aaaa","type":"slam_try","reason":"p"}]'
        assert "ben1-bbbb" in prompt and "ben1-aaaa" not in prompt
        return '[{"id":"ben1-bbbb","type":"open_or_pass","reason":"q"}]'

    out = classify_records([a, b], run=run, retries=1)
    assert len(calls) == 2
    assert set(out) == {"ben1-aaaa", "ben1-bbbb"}
