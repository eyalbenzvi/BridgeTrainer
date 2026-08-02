"""Auction-inference constraints from GIB cards (engine/lead_gib_constraints).

Ben-free. The fixture is the real explained auction of lead1-19fa5daef4b
(1C P 2C P 2D P 3NT, 3NT by N, East leads AQJ754.Q.T975.76) — the board on
which the production sampler's key-honor placement contradicted the calls'
own stated meanings (docs/lead_auction_inference_gap.md).
"""
import numpy as np
import pytest

from bridge_trainer.domain.constraints import MAX_SUIT_HCP
from bridge_trainer.engine.lead_gib_constraints import (
    profile_from_explained_auction, seat_constraints_from_card, stop_bands,
    stop_threshold, stops_in_card)

LEADER_HAND = "AQJ754.Q.T975.76"   # East

ENTRIES = [
    {"idx": 0, "seat": "S", "call": "1C", "card": {
        "gib_raw": "Minor suit opening -- 3+ !C; 11-21 HCP; 12-22 total points",
        "hcp": (11, 21), "pts": (12, 22), "minlen": {"C": 3},
        "maxlen": {"C": 13}}},
    {"idx": 1, "seat": "W", "call": "P", "card": {
        "gib_raw": "No suitable call -- 16- total points",
        "hcp": None, "pts": (0, 16), "minlen": {}, "maxlen": {}}},
    {"idx": 2, "seat": "N", "call": "2C", "card": {
        "gib_raw": "Inverted minor suit raise -- 4+ !C; 3- !H; 3- !S; "
                   "10+ HCP; forcing to 2N",
        "hcp": (10, 37), "pts": None,
        "minlen": {"S": 0, "C": 4, "H": 0},
        "maxlen": {"S": 3, "C": 13, "H": 3}}},
    {"idx": 3, "seat": "E", "call": "P", "card": {
        "gib_raw": "No suitable call -- 16- total points",
        "hcp": None, "pts": (0, 16), "minlen": {}, "maxlen": {}}},
    {"idx": 4, "seat": "S", "call": "2D", "card": {
        "gib_raw": "3+ !C; 11-21 HCP; 12-22 total points; stop in !D; "
                   "forcing to 2N",
        "hcp": (11, 21), "pts": (12, 22), "minlen": {"C": 3},
        "maxlen": {"C": 13}}},
    {"idx": 5, "seat": "W", "call": "P", "card": {
        "gib_raw": "No suitable call -- 16- total points",
        "hcp": None, "pts": (0, 16), "minlen": {}, "maxlen": {}}},
    {"idx": 6, "seat": "N", "call": "3NT", "card": {
        "gib_raw": "4+ !C; 3- !H; 3- !S; 14-18 HCP; partial stop in !H; "
                   "partial stop in !S",
        "hcp": (14, 18), "pts": None,
        "minlen": {"S": 0, "C": 4, "H": 0},
        "maxlen": {"S": 3, "C": 13, "H": 3}}},
]


# ---- stop parsing / thresholds ------------------------------------------

def test_stops_in_card_reads_full_and_partial():
    assert stops_in_card(ENTRIES[4]["card"]) == [("D", False)]
    assert stops_in_card(ENTRIES[6]["card"]) == [("H", True), ("S", True)]
    assert stops_in_card({"gib_raw": "6+ !H; 10- HCP"}) == []


def test_stop_threshold_relative_to_leader_holding():
    # The threshold is a FLOOR: the cheapest missing honor that can headline
    # a stop given enough length (A always, Kx, Qxx, Jxxx).
    assert stop_threshold("AQJ754") == 3    # missing K -> the stop is the K
    assert stop_threshold("Q") == 1         # A,K,J all out -> at least the J
    assert stop_threshold("AKJ5") == 2      # missing Q only -> Qxx headline
    assert stop_threshold("AKQ5") == 1      # missing J -> Jxxx 4th-round stop
    assert stop_threshold("AKQJ") == 0      # nothing testable by HCP


def test_stop_bands_partial_keeps_more_miss_mass_than_full():
    full = stop_bands("AQJ754", partial=False)
    part = stop_bands("AQJ754", partial=True)
    assert full[0].lo == part[0].lo == 3
    assert full[0].hi == part[0].hi == MAX_SUIT_HCP
    assert full[1].weight < part[1].weight     # full stop is a firmer promise
    assert stop_bands("AKQJ", partial=False) is None


# ---- per-card constraints -------------------------------------------------

def test_inverted_raise_card_length_bands():
    sc = seat_constraints_from_card(ENTRIES[2]["card"], LEADER_HAND)
    assert sc.suit_weights["S"][3] == 1.0 and sc.suit_weights["S"][4] == 0.0
    assert sc.suit_weights["H"][3] == 1.0 and sc.suit_weights["H"][4] == 0.0
    assert sc.suit_weights["C"][3] == 0.0 and sc.suit_weights["C"][4] == 1.0
    assert sc.hcp_weights[10] == 1.0 and sc.hcp_weights[8] == 0.0
    assert 0 < sc.hcp_weights[9] < 1                       # stretch margin


def test_3nt_card_encodes_major_stops_and_range():
    sc = seat_constraints_from_card(ENTRIES[6]["card"], LEADER_HAND)
    # spade partial stop: the K (3 hcp) is core, K-less at reduced weight
    assert sc.suit_hcp_weights["S"][3] == 1.0
    assert 0 < sc.suit_hcp_weights["S"][0] < 1
    assert sc.suit_hcp_weights["H"][3] == 1.0
    assert sc.hcp_weights[14] == sc.hcp_weights[18] == 1.0
    assert 0 < sc.hcp_weights[13] < 1 and 0 < sc.hcp_weights[19] < 1
    assert sc.hcp_weights[21] == 0.0


def test_pass_card_binds_hcp_only_through_pts_upper_bound():
    sc = seat_constraints_from_card(ENTRIES[1]["card"], LEADER_HAND)
    assert sc.hcp_weights[16] == 1.0 and sc.hcp_weights[17] == 0.0
    assert all(sc.suit_weights[s].min() == 1.0 for s in "SHDC")


# ---- whole-auction profile ------------------------------------------------

def test_profile_merges_declarer_calls_and_skips_leader():
    p = profile_from_explained_auction(ENTRIES, "E", LEADER_HAND)
    assert "E" not in p.seats
    n = p.seats["N"]
    # 2C (10+) x 3NT (14-18) intersect to 14-18 with soft 13/19 shoulders
    assert n.hcp_weights[14] == n.hcp_weights[18] == 1.0
    assert 0 < n.hcp_weights[13] < 1
    assert n.hcp_weights[12] == 0.0
    assert n.suit_weights["S"][4] == 0.0 and n.suit_weights["C"][3] == 0.0
    assert n.suit_hcp_weights["S"][3] == 1.0        # partial S stop kept
    s = p.seats["S"]
    assert s.suit_hcp_weights["D"][3] == 1.0        # 2D's diamond stop
    assert s.suit_weights["C"][2] == 0.0            # 3+ clubs
    assert p.unrecognized_calls == []


def test_silent_partner_gets_overcall_denials_in_unbid_suits():
    p = profile_from_explained_auction(ENTRIES, "E", LEADER_HAND)
    w = p.seats["W"]
    suits = {d.suit for d in w.denials}
    assert suits == {"S", "H", "D"}                 # everything but clubs
    assert all(0 < d.weight < 1 for d in w.denials)
    # opener's side never gets silence denials
    assert not any(d for d in p.seats["S"].denials)


def test_silence_denials_can_be_disabled():
    p = profile_from_explained_auction(ENTRIES, "E", LEADER_HAND,
                                       silence_denials=False)
    assert not p.seats.get("W") or not p.seats["W"].denials


def test_unparsed_non_pass_call_reported_not_dropped():
    entries = ENTRIES + [{"idx": 7, "seat": "S", "call": "4C",
                          "card": {"gib_raw": "", "hcp": None, "pts": None,
                                   "minlen": {}, "maxlen": {}}}]
    p = profile_from_explained_auction(entries, "E", LEADER_HAND)
    assert p.unrecognized_calls == ["S:4C"]
    assert "N" in p.seats                            # the rest still applied


# ---- end-to-end through the sampler ---------------------------------------

def test_sampler_from_record_places_key_honor_with_declarer():
    from bridge_trainer.engine.lead_posterior import build_problem
    from bridge_trainer.engine.lead_gib_constraints import sampler_from_record

    rec = {"id": "lead1-19fa5daef4b", "kind": "lead",
           "hand": LEADER_HAND, "leader": "E", "dealer": "S", "vul": "Both",
           "auction": [e["call"] for e in ENTRIES] + ["P", "P", "P"],
           "contract": "3NTN",
           "explanations": {"auction": ENTRIES}}
    problem = build_problem(rec["hand"], rec["auction"], rec["dealer"],
                            rec["vul"], rec["contract"])
    sampler = sampler_from_record(rec, max_seconds=60.0)
    ls = sampler.sample(problem, 120, seed=1)
    assert ls.n >= 60
    assert ls.semantic_constraint_mode == "gib_cards"
    w = np.asarray(ls.weight, float)
    w = w / w.sum()

    def holds_sk(hd, seat):
        return "K" in hd[seat].split(".")[0]

    p_sk_n = sum(wi for hd, wi in zip(ls.hands, w) if holds_sk(hd, "N"))
    # explicit-card sampling puts the missing spade K with the seat that
    # announced the spade stop far more often than not (~0.8 measured)
    assert p_sk_n > 0.6
    # and every accepted deal honours the inverted raise's hard lengths
    for hd in ls.hands:
        s, h, d, c = (len(x) for x in hd["N"].split("."))
        assert s <= 3 and h <= 3 and c >= 4

    # determinism in the seed
    ls2 = sampler_from_record(rec, max_seconds=60.0).sample(problem, 120, seed=1)
    assert [hd["N"] for hd in ls2.hands] == [hd["N"] for hd in ls.hands]


# ---- the inference gate (one definition for forge + pool audit) -----------

def _reading(winner, delta=None, ci=None):
    r = {"winner": winner, "means": {}, "diagnostics": {}}
    if delta is not None:
        r["published_delta"] = {"delta": delta, "ci95": list(ci), "ess": 200}
    return r


def test_verdict_stable_when_published_wins_both_readings():
    from bridge_trainer.engine.lead_gib_constraints import inference_verdict
    readings = {"soft": _reading("SA", 0.0, (0.0, 0.0)),
                "strict": _reading("SA", 0.0, (0.0, 0.0))}
    assert inference_verdict("SA", readings)[0] == "stable"


def test_verdict_refuted_on_ci_clean_loss_in_any_reading():
    from bridge_trainer.engine.lead_gib_constraints import inference_verdict
    readings = {"soft": _reading("SA", 0.0, (0.0, 0.0)),
                "strict": _reading("D5", -0.25, (-0.40, -0.07))}
    status, detail = inference_verdict("SA", readings)
    assert status == "inference_refuted"
    assert "strict" in detail and "D5" in detail


def test_verdict_refuted_on_margin_even_when_ci_touches_zero():
    from bridge_trainer.engine.lead_gib_constraints import (
        REFUTE_MARGIN, inference_verdict)
    readings = {"soft": _reading("SA", 0.0, (0.0, 0.0)),
                "strict": _reading("D5", -(REFUTE_MARGIN + 0.05),
                                   (-0.5, 0.02))}
    assert inference_verdict("SA", readings)[0] == "inference_refuted"


def test_verdict_honor_sensitive_when_readings_disagree_within_noise():
    from bridge_trainer.engine.lead_gib_constraints import inference_verdict
    readings = {"soft": _reading("SA", 0.0, (0.0, 0.0)),
                "strict": _reading("D5", -0.05, (-0.2, 0.1))}
    assert inference_verdict("SA", readings)[0] == "honor_sensitive"


def test_verdict_abstains_without_constraints_or_answer():
    from bridge_trainer.engine.lead_gib_constraints import inference_verdict
    assert inference_verdict("SA", {"soft": {"diagnostics": {}},
                                    "strict": {"diagnostics": {}}})[0] \
        == "abstain"
    assert inference_verdict(None, {"soft": _reading("SA")})[0] == "abstain"


def test_forge_helper_blocks_refuted_and_passes_stable(monkeypatch):
    from bridge_trainer.engine import lead_maker, lead_gib_constraints

    rec = {"contract": "3NTN", "verdict": {"accepted": ["SA"]}}

    def fake_gate_refuted(record, **kw):
        return ("inference_refuted", "strict: SA loses 0.25 to D5", {})

    monkeypatch.setattr(lead_gib_constraints, "inference_gate",
                        fake_gate_refuted)
    t = {}
    out = lead_maker._inference_gate_reject(rec, t)
    assert out is not None and out[0] == "inference_refuted"
    assert "inference_gate_s" in t

    monkeypatch.setattr(lead_gib_constraints, "inference_gate",
                        lambda record, **kw: ("stable", "ok", {}))
    assert lead_maker._inference_gate_reject(rec, {}) is None
    monkeypatch.setattr(lead_gib_constraints, "inference_gate",
                        lambda record, **kw: ("abstain", "none", {}))
    assert lead_maker._inference_gate_reject(rec, {}) is None
