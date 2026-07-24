"""PERF-D-6: client_view(record) slims a problem doc to what the web client
reads before upload — drops policy_trail / engine_auction_complete and trims
quality to {n_samples, stakes} — while the full record stays in the local pool.
"""
from __future__ import annotations

import copy

from bridge_trainer.pool.firestore_store import client_view

_REC = {
    "id": "ben1-deadbeef",
    "schema": 1,
    "kind": "bidding",
    "created_at": "2026-01-01T00:00:00",
    "generator": {"engine": "ben BEN-21GF", "seed": 1, "samples": 512},
    "verdict": {"accepted": "4H", "table": [{"bid": "4H", "ev": 1.0}]},
    "candidates": [{"call": "4H", "policy": 0.6}],
    "classification": {"type": "invite", "difficulty_level": 2},
    "difficulty": 2.0,
    "quality": {"n_samples": 512, "stakes": 2.5, "gap_imps": 1.2,
                "ess": 480.0, "shortfall": 0},
    "full_deal": {"N": "...", "E": "...", "S": "...", "W": "..."},
    "engine_auction_complete": ["P", "1H", "P", "4H"],
    "policy_trail": [{"idx": 0, "seat": "N", "policy": [("1H", 0.5)]}],
}


def test_drops_dead_fields_and_trims_quality():
    out = client_view(_REC)
    assert "policy_trail" not in out
    assert "engine_auction_complete" not in out
    assert out["quality"] == {"n_samples": 512, "stakes": 2.5}


def test_keeps_client_read_fields():
    out = client_view(_REC)
    for k in ("id", "schema", "kind", "verdict", "candidates",
              "classification", "difficulty", "created_at", "generator",
              "full_deal"):
        assert k in out, f"client_view dropped {k}"
    # generator is read by the client (n_deals/samples/engine) — must survive
    assert out["generator"]["samples"] == 512


def test_does_not_mutate_input():
    before = copy.deepcopy(_REC)
    client_view(_REC)
    assert _REC == before


def test_idempotent():
    once = client_view(_REC)
    twice = client_view(once)
    assert once == twice


def test_quality_absent_or_partial_is_safe():
    assert "quality" not in client_view({"id": "x"})
    out = client_view({"id": "x", "quality": {"n_samples": 10}})
    assert out["quality"] == {"n_samples": 10}


def test_lead_record_engine_auction_complete_dropped():
    lead = {"id": "lead1-abc", "kind": "lead",
            "auction": ["1NT", "P", "3NT", "P", "P", "P"],
            "engine_auction_complete": ["1NT", "P", "3NT", "P", "P", "P"],
            "quality": {"n_samples": 300}}
    out = client_view(lead)
    assert "engine_auction_complete" not in out
    assert out["auction"] == ["1NT", "P", "3NT", "P", "P", "P"]   # kept
