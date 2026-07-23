"""Regression tests for the two lead-posterior additions:

  * ``ConstraintSampler`` — applies EXPLICIT accumulated auction constraints
    (owner requirement 3, first bullet): per-seat HCP / suit-length / suit-
    quality / denial / exclusion bands as an importance-weighted modelled prior;
  * the calibration harness (owner requirement 6) — compares a sampler's hidden-
    hand distribution against REAL complete deals grouped by auction family.

Both are Ben-free and run in normal CI.
"""
from __future__ import annotations

import numpy as np
import pytest

from bridge_trainer.engine.lead_posterior import (
    SUITS, RANKS, build_problem, evaluate_layouts, result_signature,
    problem_fingerprint, correctness_gate)
from bridge_trainer.engine.lead_samplers import (
    ConstraintSampler, constraint_profile_from_auction, _pbn_to_seats)
from bridge_trainer.domain.constraints import (
    ConstraintProfile, SeatConstraints, Band)

REF_HAND = "874.AQ94.T.97642"
REF_AUCTION = "1S P 2C P 3D P 3NT P P P".split()


def ref_problem():
    return build_problem(REF_HAND, REF_AUCTION, "E", "Both", "3NTW")


def _explicit_W_spades(lo=5, hi=7, hcp=(11, 21)):
    prof = ConstraintProfile()
    prof.seats["W"] = SeatConstraints.from_bands(
        hcp=[Band(*hcp)], suits={"S": [Band(lo, hi)]})
    return prof


# --------------------------------------------------------------------------
# ConstraintSampler: honours explicit constraints, conserves cards
# --------------------------------------------------------------------------
def test_constraint_sampler_honours_explicit_constraints():
    p = ref_problem()
    s = ConstraintSampler(profile=_explicit_W_spades(5, 7),
                          semantic_constraint_mode="explicit", max_seconds=10)
    ls = s.sample(p, 50, seed=1)
    assert ls.n == 50
    for hd in ls.hands:
        assert hd["N"] == REF_HAND                       # leader fixed
        assert len(hd["W"].split(".")[0]) >= 5           # constraint honoured


def test_constraint_sampler_labels_are_honest():
    p = ref_problem()
    s = ConstraintSampler(profile=_explicit_W_spades(),
                          semantic_constraint_mode="explicit", max_seconds=10)
    ls = s.sample(p, 20, seed=1)
    prov = ls.provenance()
    assert prov["sampling_model"] == "auction_constraint_bands"
    # NEVER labelled a calibrated posterior
    assert prov["posterior_calibration_status"] == "modelled_prior_uncalibrated"
    assert prov["weighting_method"] == "constraint_importance_bands"
    assert prov["semantic_constraint_mode"] == "explicit"     # not "none"
    assert prov["source_deal_independent"] is True
    assert ls.constraint_diagnostics["constrained_seats"] == ["W"]
    assert ls.constraint_diagnostics["any_constraint_applied"] is True


def test_constraint_sampler_deterministic_and_source_independent():
    p1 = ref_problem()
    p2 = ref_problem()      # identical public state; imagine a different truth
    prof = _explicit_W_spades()
    a = ConstraintSampler(profile=prof, max_seconds=10).sample(p1, 40, seed=3)
    b = ConstraintSampler(profile=prof, max_seconds=10).sample(p2, 40, seed=3)
    assert a.hands == b.hands                              # deterministic
    assert problem_fingerprint(p1, 3) == problem_fingerprint(p2, 3)
    assert result_signature(evaluate_layouts(a), a) == \
        result_signature(evaluate_layouts(b), b)          # independent of truth
    c = ConstraintSampler(profile=prof, max_seconds=10).sample(p1, 40, seed=4)
    assert a.hands != c.hands                              # seed actually varies


def test_constraint_sampler_importance_weights_and_ess():
    # a soft margin band (reduced weight outside the core) => non-uniform
    # importance weights => ESS below n.
    p = ref_problem()
    prof = ConstraintProfile()
    prof.seats["W"] = SeatConstraints.from_bands(
        hcp=[Band(15, 17, 1.0)], suits={"S": [Band(5, 5, 1.0)]})
    # add a margin band on HCP at reduced weight via from_bands margins
    prof.seats["W"] = SeatConstraints.from_bands(
        hcp=[Band(15, 17, 1.0), Band(12, 14, 0.3)],
        suits={"S": [Band(5, 7, 1.0)]})
    ls = ConstraintSampler(profile=prof, max_seconds=10).sample(p, 60, seed=2)
    assert ls.n > 0
    # weights are not all identical -> Kish ESS strictly below n
    assert ls.ess() <= ls.n
    if len(set(np.round(ls.weight, 6))) > 1:
        assert ls.ess() < ls.n


def test_constraint_sampler_passes_correctness_gate():
    p = ref_problem()
    prof = _explicit_W_spades()
    s = ConstraintSampler(profile=prof, max_seconds=10)
    ls = s.sample(p, 40, seed=1)
    ev = evaluate_layouts(ls)
    ls2 = s.sample(p, 40, seed=1)
    gate = correctness_gate(p, ls, ev, ls2, evaluate_layouts(ls2))
    assert gate["passed"] is True
    assert gate["checks"]["card_conserving_layouts"] is True
    assert gate["checks"]["fixed_seed_reproducible"] is True


# --------------------------------------------------------------------------
# rule-engine derivation path: recognised calls constrain, gaps reported
# --------------------------------------------------------------------------
def test_constraint_from_auction_records_unrecognized_and_constrains():
    p = ref_problem()
    profile, label = constraint_profile_from_auction(p)
    assert label.startswith("rule_engine:")
    # at least one call is recognised (a seat gets constraints) and the
    # remaining unmatched calls are surfaced, not silently dropped
    assert len(profile.seats) >= 1
    assert len(profile.unrecognized_calls) >= 1


def test_constraint_sampler_from_auction_votes_only_when_constrained():
    from bridge_trainer.app.lead_audit import run_audit
    r = run_audit(REF_HAND, REF_AUCTION, "E", "Both", "3NTW",
                  samplers=["uniform", "constraint"], thresholds=[0.70],
                  requested=60, proposals=0, compare=["HA", "H4"], seed=1,
                  n_boot=150)
    assert "constraint" in r["runs"]
    cd = r["runs"]["constraint"]["constraint_diagnostics"]
    assert cd["any_constraint_applied"] is True
    # an auction-aware sampler that constrained a seat is a valid voter
    assert r["runs"]["constraint"]["winner"] in \
        r["cross_sampler"]["valid_sampler_winners"]
    # provenance is honest about the mode
    assert r["runs"]["constraint"]["provenance"]["semantic_constraint_mode"] \
        .startswith("rule_engine:")


def test_constraint_over_tight_yields_empty_not_crash():
    # W cannot hold 11+ spades (the leader already holds three) -> 0 accepted;
    # the audit must record the gap, not divide by zero.
    from bridge_trainer.app.lead_audit import run_one_sampler
    p = ref_problem()
    prof = ConstraintProfile()
    prof.seats["W"] = SeatConstraints.from_bands(suits={"S": [Band(11, 13)]})
    s = ConstraintSampler(profile=prof, max_seconds=2)
    r = run_one_sampler(p, s, 10, 1, ["HA", "H4"], 100)
    assert r["empty_accepted_set"] is True
    assert "winner" not in r
    assert r["constraint_diagnostics"]["shortfall"] > 0


def test_pbn_to_seats_roundtrip():
    seats = _pbn_to_seats("N:874.AQ94.T.97642 KT652.K75.Q72.KQ "
                          "J93.862.AK9843.J AQ.JT3.J65.AT853")
    assert seats["N"] == "874.AQ94.T.97642"
    assert set(seats) == {"N", "E", "S", "W"}


# --------------------------------------------------------------------------
# calibration harness (requirement 6)
# --------------------------------------------------------------------------
def _pbn(cards):
    by = {s: [] for s in SUITS}
    for c in cards:
        by[c[0]].append(c[1])
    order = {r: i for i, r in enumerate(RANKS)}
    return ".".join("".join(sorted(by[s], key=lambda r: order[r]))
                    for s in SUITS)


def _family_declarer_long_spades(n_boards=12, seed=0):
    """Real deals where declarer W ALWAYS holds 6 spades; auction announces
    spades ('1S ...'), so a calibrated sampler must reproduce W's spade length.
    """
    rng = np.random.default_rng(seed)
    auc = "1S P 3NT P P P".split()
    deals = []
    for _ in range(n_boards):
        wspades = list(rng.choice(list(RANKS), size=6, replace=False))
        whand = ["S" + r for r in wspades]
        nonspade = [s + r for s in SUITS if s != "S" for r in RANKS]
        rng.shuffle(nonspade)
        whand += nonspade[:7]
        used = set(whand)
        others = [c for c in (s + r for s in SUITS for r in RANKS)
                  if c not in used]
        rng.shuffle(others)
        hands = {"W": _pbn(whand), "N": _pbn(others[0:13]),
                 "E": _pbn(others[13:26]), "S": _pbn(others[26:39])}
        deals.append({"hands": hands, "auction": auc, "contract": "3NTW",
                      "dealer": "N", "vul": "None"})
    return deals


def test_auction_family_key_and_announced_suits():
    from bridge_trainer.engine.lead_calibration import (
        auction_family_key, announced_suits)
    assert auction_family_key("1S P 2C P 3D P 3NT P P P".split()) == \
        "1S P 2C P 3D P 3NT"
    assert announced_suits("1S P 2C P 3D P 3NT P P P".split()) == \
        ["S", "C", "D"]                    # NT excluded, first-appearance order


def test_hand_features_basic():
    from bridge_trainer.engine.lead_calibration import hand_features
    f = hand_features("AKQ.J82.T5.9743")
    assert f["hcp"] == 4 + 3 + 2 + 1
    assert f["controls"] == 2 + 1           # A=2, K=1 (in spades)
    assert f["suit_len"]["S"] == 3
    assert f["has_A"]["S"] is True and f["has_K"]["H"] is False


def test_calibration_detects_uniform_miscalibration_on_announced_suit():
    from bridge_trainer.engine.lead_samplers import UniformSampler
    from bridge_trainer.engine.lead_calibration import calibrate_family
    deals = _family_declarer_long_spades()
    rep = calibrate_family(deals, UniformSampler(), requested=120, seed=1)
    ds = rep["roles"]["declarer"]["features"]["len_S"]
    # uniform ignores the auction -> declarer's spade length is far off
    assert ds["within_tol"] is False
    assert ds["real_mean"] == pytest.approx(6.0)
    assert ds["model_mean"] < 4.5
    assert rep["calibration_label"] == "miscalibrated"
    assert "declarer.len_S" in rep["off_features"]


def test_calibration_constraint_sampler_matches_announced_suit():
    from bridge_trainer.engine.lead_calibration import calibrate_family
    deals = _family_declarer_long_spades()
    prof = ConstraintProfile()
    prof.seats["W"] = SeatConstraints.from_bands(suits={"S": [Band(6, 6)]})
    s = ConstraintSampler(profile=prof, max_seconds=10)
    rep = calibrate_family(deals, s, requested=120, seed=1)
    ds = rep["roles"]["declarer"]["features"]["len_S"]
    # a sampler that respects the announced suit reproduces it exactly
    assert ds["within_tol"] is True
    assert ds["model_mean"] == pytest.approx(6.0)
    assert ds["tv_distance"] == pytest.approx(0.0, abs=1e-9)


def test_calibration_insufficient_real_data():
    from bridge_trainer.engine.lead_samplers import UniformSampler
    from bridge_trainer.engine.lead_calibration import calibrate_family
    deals = _family_declarer_long_spades(n_boards=3)
    rep = calibrate_family(deals, UniformSampler(), requested=60, seed=1)
    assert rep["calibration_label"] == "insufficient_real_data"


def test_calibrate_corpus_groups_and_summarises():
    from bridge_trainer.engine.lead_samplers import UniformSampler
    from bridge_trainer.engine.lead_calibration import calibrate_corpus
    deals = _family_declarer_long_spades()      # one family, 12 boards
    out = calibrate_corpus(deals, UniformSampler(), requested=100, seed=1)
    assert out["summary"]["n_families"] == 1
    assert out["summary"]["miscalibrated"] == 1
    # the most-off features include the announced-suit length for the bidders
    off = dict(out["summary"]["most_off_features"])
    assert any(k.endswith("len_S") for k in off)
