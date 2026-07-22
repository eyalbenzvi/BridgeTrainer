"""The lead-debug artifact builder (pure; no Ben)."""
from __future__ import annotations

import numpy as np

from bridge_trainer.engine.lead_cards import physical_cards
from bridge_trainer.engine.lead_debug import build_lead_debug_artifact, seed_from_id
from bridge_trainer.engine.lead_evaluate import Contract, Layout

HAND = "T87.JT86.QJ7.Q83"


def _artifact(source_deal=None):
    cands = physical_cards(HAND)
    contract = Contract(3, "NT", declarer_i=1)
    layouts = [Layout(hands=("K93.752.A854.T62", "AQJ4.KQ4.K3.AK54", HAND,
                             "652.A93.T962.J97"),
                      sample_index=i, sample_seed=10 + i,
                      accept={"posterior": "ben_auction_replay"})
               for i in range(3)]
    dt = {c: np.array([2.0, 2.0, 3.0]) for c in cands}
    dt["HJ"] = np.array([3.0, 3.0, 3.0])
    sm = {c: 0.05 for c in cands}
    sm["HJ"] = 0.4
    return build_lead_debug_artifact(
        problem_id="lead1-0000002a", source_seed=42, sampler_seed=42,
        config={"n_samples": 3}, contract=contract,
        auction=["1NT", "P", "3NT", "P", "P", "P"], dealer_i=1,
        vul=[False, False], displayed_leader_hand=HAND, candidates=cands,
        def_tricks=dt, softmax=sm, layouts=layouts, quality=0.9,
        source_deal=source_deal)


def test_seed_from_id():
    assert seed_from_id("lead1-0000002a") == 42
    assert seed_from_id("lead1-00000001") == 1


def test_artifact_has_physical_and_policy_fields():
    art = _artifact()
    for row in art["candidates"]:
        # physical == display == dds for every candidate
        assert row["physical_card"] == row["display_card"] == row["dds_card"]
        assert "policy_action" in row
        assert "ben_softmax" in row
        assert "mean_def_tricks" in row and "ci95" in row and "stderr" in row
    # ranked best-first
    means = [r["mean_def_tricks"] for r in art["candidates"]]
    assert means == sorted(means, reverse=True)
    assert art["candidates"][0]["physical_card"] == "HJ"


def test_artifact_per_sample_dds_conversion():
    art = _artifact()
    s0 = art["sampled_layouts"][0]
    assert set(s0["hands_by_seat"]) == {"N", "E", "S", "W"}
    assert s0["accept"]["posterior"] == "ben_auction_replay"
    cell = s0["per_candidate_dds"]["HJ"]
    assert cell["defender_tricks"] == 3
    assert cell["declarer_tricks"] == 13 - 3


def test_artifact_source_deal_is_audit_only():
    art_no = _artifact(source_deal=None)
    assert "audit_only" not in art_no
    art_yes = _artifact(source_deal={"N": "x", "E": "y", "S": HAND, "W": "z"})
    assert "audit_only" in art_yes
    assert "WARNING" in art_yes["audit_only"]
    # the source deal appears ONLY inside audit_only, never at top level
    assert "full_deal" not in art_yes
    assert art_yes["audit_only"]["full_deal"]["S"] == HAND
