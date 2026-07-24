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


def test_classify_records_splits_chunk_on_hang():
    # A chunk whose CLI call hangs (TimeoutExpired) is split in half and each
    # half retried on its own, so one bad batch can't sink the rest.
    import subprocess
    a, b = _two_recs()
    calls = []

    def run(prompt, model):
        calls.append(prompt)
        if calls[-1].count("(id: ") == 2:               # the full 2-problem batch
            raise subprocess.TimeoutExpired("claude", 300)
        pid = "ben1-aaaa" if "ben1-aaaa" in prompt else "ben1-bbbb"
        return f'[{{"id":"{pid}","type":"slam_try","reason":"r"}}]'

    out = classify_records([a, b], run=run, chunk_size=2, retries=0)
    assert set(out) == {"ben1-aaaa", "ben1-bbbb"}       # both recovered
    assert len(calls) == 3                              # 1 failed batch + 2 singles


def test_classify_records_omits_single_that_keeps_failing():
    import subprocess
    a, _ = _two_recs()

    def run(prompt, model):
        raise subprocess.TimeoutExpired("claude", 300)

    out = classify_records([a], run=run, retries=0)
    assert out == {}                                    # omitted, no crash


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


# --- GitHub Models backend (default; runs in the Actions workflow) ---------

class _FakeResp:
    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_run_github_models_posts_openai_shape_and_returns_content(monkeypatch):
    import urllib.request

    from bridge_trainer.engine import classify

    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["auth"] = req.headers["Authorization"]
        captured["body"] = json.loads(req.data.decode())
        return _FakeResp(json.dumps(
            {"choices": [{"message":
             {"content": '{"type":"slam_try","reason":"r"}'}}]}).encode())

    monkeypatch.setenv("GITHUB_TOKEN", "tok123")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    out = classify.run_github_models("classify this as JSON",
                                     model="openai/gpt-4.1-mini")
    assert '"type":"slam_try"' in out
    assert captured["url"] == classify.GITHUB_MODELS_URL
    assert captured["method"] == "POST"
    assert captured["auth"] == "Bearer tok123"
    assert captured["body"]["model"] == "openai/gpt-4.1-mini"
    assert captured["body"]["temperature"] == 0
    assert (captured["body"]["messages"][0]["content"]
            == "classify this as JSON")


def test_run_github_models_prefers_explicit_models_token(monkeypatch):
    import urllib.request

    from bridge_trainer.engine import classify

    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["auth"] = req.headers["Authorization"]
        return _FakeResp(b'{"choices":[{"message":{"content":"{}"}}]}')

    monkeypatch.setenv("GITHUB_TOKEN", "actions-token")
    monkeypatch.setenv("GITHUB_MODELS_TOKEN", "pat-token")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    classify.run_github_models("x")
    assert seen["auth"] == "Bearer pat-token"      # PAT wins over GITHUB_TOKEN


def test_run_github_models_requires_a_token(monkeypatch):
    from bridge_trainer.engine import classify

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_MODELS_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="GITHUB_TOKEN|models:read"):
        classify.run_github_models("x")


def test_run_github_models_http_error_becomes_runtimeerror(monkeypatch):
    import io
    import urllib.error
    import urllib.request

    from bridge_trainer.engine import classify

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 429, "Too Many Requests", hdrs=None,
            fp=io.BytesIO(b"rate limit exceeded"))

    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="429"):
        classify.run_github_models("x")


def test_run_github_models_end_to_end_through_classify_records(monkeypatch):
    # The full path: classify_records -> run_github_models (default backend) ->
    # HTTP -> parse_batch_response, with only the network call stubbed.
    import urllib.request

    from bridge_trainer.engine import classify

    a, b = _two_recs()

    def fake_urlopen(req, timeout=None):
        return _FakeResp(json.dumps({"choices": [{"message": {"content":
            '[{"id":"ben1-aaaa","type":"compete_or_sell","reason":"p"},'
            '{"id":"ben1-bbbb","type":"invite_or_game","reason":"q"}]'}}]}
            ).encode())

    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    out = classify.classify_records([a, b])       # no run= -> default backend
    assert out["ben1-aaaa"]["type"] == "compete_or_sell"
    assert out["ben1-bbbb"]["type"] == "invite_or_game"
