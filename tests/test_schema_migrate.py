"""ARCH-9: canonicalize_record applies only the safe, documented normalizations
and is idempotent. (The migration itself is run separately, with approval.)"""
from __future__ import annotations

from bridge_trainer.pool.migrate import canonicalize_record, detect_schema


def test_detect_schema_honors_field_then_infers():
    assert detect_schema({"schema": 2, "kind": "lead"}) == 2
    assert detect_schema({"schema": 1, "kind": "bidding"}) == 1
    # a mode-aware lead (IMP metrics) with no schema field infers 2
    assert detect_schema(
        {"kind": "lead", "training": {"modes": {"MP": True, "IMP": True}}}) == 2
    # tricks-only lead / bidding infer 1
    assert detect_schema(
        {"kind": "lead", "training": {"modes": {"MP": True}}}) == 1
    assert detect_schema({"kind": "bidding"}) == 1


def test_stamps_schema_and_classification():
    rec = {"id": "x", "kind": "bidding"}       # no schema, no classification
    out, changed = canonicalize_record(rec)
    assert changed
    assert out["schema"] == 1
    assert out["classification"] == {}
    assert rec == {"id": "x", "kind": "bidding"}   # input not mutated


def test_aliases_legacy_action_rows():
    rec = {"id": "y", "kind": "bidding", "schema": 1, "classification": {},
           "verdict": {"corrected": [{"action": "4H", "ev": -1.2}],
                       "raw": [{"action": "P", "ev": -5.0}]}}
    out, changed = canonicalize_record(rec)
    assert changed
    assert out["verdict"]["corrected"][0]["bid"] == "4H"
    assert out["verdict"]["corrected"][0]["action"] == "4H"   # original kept
    assert out["verdict"]["raw"][0]["bid"] == "P"


def test_idempotent_on_canonical_record():
    rec = {"id": "z", "kind": "lead", "schema": 2,
           "classification": {"type": "lead_3nt"},
           "training": {"modes": {"MP": True, "IMP": True}},
           "verdict": {"corrected": [{"bid": "SK", "ev": 0.0}]}}
    out, changed = canonicalize_record(rec)
    assert not changed
    assert out == rec
    # running twice is stable
    out2, changed2 = canonicalize_record(out)
    assert not changed2 and out2 == rec
