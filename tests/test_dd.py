"""Tiny DD fixture, the correction layer (INV5), and the cache key (INV4)."""
import numpy as np
import pytest
from endplay.types import Deal

from bridge_trainer.dd.cache import DealSetCache, deal_set_cache_key
from bridge_trainer.dd.correction import CorrectionTable, load_default_correction
from bridge_trainer.dd.solver import DDSolver
from bridge_trainer.domain.constraints import (Band, ConstraintProfile,
                                               SeatConstraints)
from bridge_trainer.domain.contracts import FinalContract
from bridge_trainer.domain.deals import GenerationDiagnostics, WeightedDeal
from bridge_trainer.scoring.evaluate import ScoreEvaluator

# Cold deal: N takes all 13 tricks in spades/hearts/NT; E/W take none.
FIXTURE = Deal("N:AKQJ.AKQJ.AKQ.AK 5432.5432.543.32 T987.T987.T98.Q4 6.6.J762.JT98765")


def test_dd_fixture_known_tricks():
    tricks = DDSolver().solve([WeightedDeal(FIXTURE)], {"S", "H"})
    assert tricks[("S", "N")][0] == 13
    assert tricks[("H", "N")][0] == 13
    assert tricks[("S", "E")][0] == 0
    assert tricks[("H", "W")][0] == 0


def test_solver_chunks_beyond_40_deals():
    deals = [WeightedDeal(FIXTURE)] * 85
    tricks = DDSolver().solve(deals, {"S"})
    assert len(tricks[("S", "N")]) == 85
    assert (tricks[("S", "N")] == 13).all()


def identity_correction():
    return CorrectionTable({"schema_version": 1,
                            "suit": {0: 1.0}, "nt": {0: 1.0}})


def test_identity_correction_equals_raw():
    ev = ScoreEvaluator("S", "EW", identity_correction())
    deals = [WeightedDeal(FIXTURE)]
    contracts = [FinalContract.parse("4SN")]
    ev.prepare(deals, {"4S": contracts})
    raw, corrected = ev.evaluate(deals, contracts)
    np.testing.assert_array_equal(raw, corrected)
    # 4S+3 by N, NS not vul: 420 + 3*30 = 510, from my (S) perspective +510.
    assert raw[0] == 510


def test_correction_applied_symmetrically_inv5():
    """Every non-passed-out contract gets the same smearing — the corrected
    score differs from raw for our contract AND theirs."""
    # Symmetric deltas: N's 13 tricks can only move down, W's 0 tricks can
    # only move up, so both contracts' corrected scores must shift.
    table = CorrectionTable({"schema_version": 1,
                             "suit": {-1: 0.25, 0: 0.5, 1: 0.25}, "nt": {0: 1.0}})
    ev = ScoreEvaluator("S", "EW", table)
    deals = [WeightedDeal(FIXTURE)]
    ours = [FinalContract.parse("4SN")]
    theirs = [FinalContract.parse("3HW")]
    ev.prepare(deals, {"ours": ours, "theirs": theirs})
    raw_o, corr_o = ev.evaluate(deals, ours)
    raw_t, corr_t = ev.evaluate(deals, theirs)
    assert corr_o[0] != raw_o[0]   # our contract smeared
    assert corr_t[0] != raw_t[0]   # their contract smeared too
    # 3HW takes 0 tricks raw: down 9 vul = -900 to them = +900 to us.
    assert raw_t[0] == 900


def test_correction_table_validation():
    with pytest.raises(ValueError):
        CorrectionTable({"schema_version": 1,
                         "suit": {0: 0.9}, "nt": {0: 1.0}})  # doesn't sum to 1
    with pytest.raises(ValueError):
        CorrectionTable({"schema_version": 99, "suit": {0: 1.0}, "nt": {0: 1.0}})
    assert load_default_correction().distribution("NT")


def make_key(**overrides):
    base = dict(
        my_hand="K93.752.A854.T62",
        constraints=ConstraintProfile(seats={
            "W": SeatConstraints.from_bands(hcp=[Band(11, 21)])}),
        system_fingerprints={"us": "abc", "them": "def"},
        dealer="W", vul="EW", seed=42, n=800,
    )
    base.update(overrides)
    return deal_set_cache_key(**base)


def test_cache_key_sensitivity_inv4():
    base = make_key()
    assert make_key() == base  # deterministic
    assert make_key(vul="None") != base      # vulnerability mandatory in key
    assert make_key(dealer="N") != base      # dealer mandatory in key
    assert make_key(seed=43) != base
    assert make_key(my_hand="K93.752.A854.T63") != base
    assert make_key(system_fingerprints={"us": "abc", "them": "xyz"}) != base
    assert make_key(constraints=ConstraintProfile(seats={
        "W": SeatConstraints.from_bands(hcp=[Band(12, 21)])})) != base


def test_dd_tricks_cache_roundtrip(tmp_path):
    cache = DealSetCache(tmp_path)
    tricks = DDSolver().solve([WeightedDeal(FIXTURE)], {"S", "H"})
    assert cache.load_tricks("k1", {"S", "H"}) is None
    cache.store_tricks("k1", {"S", "H"}, tricks)
    loaded = cache.load_tricks("k1", {"S", "H"})
    assert set(loaded) == set(tricks)
    for k in tricks:
        np.testing.assert_array_equal(loaded[k], tricks[k])
    # Different denomination set is a different cache entry.
    assert cache.load_tricks("k1", {"S"}) is None


def test_deal_set_cache_roundtrip(tmp_path):
    cache = DealSetCache(tmp_path)
    deals = [WeightedDeal(FIXTURE, weight=0.4)]
    diag = GenerationDiagnostics(attempts=10, acceptance_rate=0.1,
                                 effective_sample_size=1.0,
                                 unrecognized_calls=["E:4C after '1H 1S'"],
                                 elapsed_s=0.5, shortfall=0)
    cache.store("k1", deals, diag)
    loaded = cache.load("k1")
    assert loaded is not None
    deals2, diag2 = loaded
    assert str(deals2[0].deal) == str(FIXTURE)
    assert deals2[0].weight == 0.4
    assert diag2.to_dict() == diag.to_dict()
    assert cache.load("nope") is None
