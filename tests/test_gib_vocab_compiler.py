"""Full-vocabulary GIB clause compiler + new DSL primitives.

Ben-free. The vocabulary fixture (tests/data/gib_vocab_patterns.json) is the
complete set of 94 distinct clause patterns measured over the production
pool — the compiler must recognise every one of them (constraint, no-op, or
graceful contradiction; never `None`).
"""
import json
from pathlib import Path

import numpy as np
import pytest

from bridge_trainer.dealing.features import SeatFeatures, parse_hand_pbn
from bridge_trainer.dealing.rejection import RejectionDealSource
from bridge_trainer.domain.constraints import (
    Band, ConstraintProfile, HonorSpec, SeatConstraints)
from bridge_trainer.engine.lead_gib_constraints import (
    at_best_partial_bands, clause_core_satisfied, clause_kind,
    compile_card, compile_clause, two_stop_bands)

FIXTURE = Path(__file__).parent / "data" / "gib_vocab_patterns.json"
NEUTRAL_LEADER = ["T98", "765", "432", "5432"]      # holds no honor anywhere


# ---- DSL primitives ---------------------------------------------------------

def _features(*hands):
    rows = [parse_hand_pbn(h) for h in hands]
    return SeatFeatures(cards=np.array(rows, dtype=np.int8))


def test_holds_specific_card():
    f = _features("KQ2.752.A854.T62", "A93.752.K854.T62")
    assert list(f.holds("S", "K")) == [True, False]
    assert list(f.holds("D", "A")) == [True, False]
    assert list(f.holds("C", "T")) == [True, True]


def test_honor_spec_modes_weighting():
    from bridge_trainer.dealing.rejection import _honor_spec_weight
    f = _features("KQ2.752.A854.T62",     # holds SK and SQ
                  "A93.752.K854.T62")     # holds SA only
    all_kq = _honor_spec_weight(HonorSpec("S", "KQ", "all", 0.1), f)
    assert list(all_kq) == [1.0, 0.1]
    any_kq = _honor_spec_weight(HonorSpec("S", "KQA", "any", 0.0), f)
    assert list(any_kq) == [1.0, 1.0]
    none_a = _honor_spec_weight(HonorSpec("S", "A", "none", 0.2), f)
    assert list(none_a) == [1.0, 0.2]


def test_alt_groups_take_best_alternative_and_merge():
    solid = SeatConstraints.from_bands(
        honor_specs=[HonorSpec("S", "AKQ", "all", 0.0)])
    void = SeatConstraints.from_bands(suits={"S": [Band(0, 0)]})
    sc = SeatConstraints.from_bands(alt_groups=[[solid, void]])
    merged = sc.merge(SeatConstraints.from_bands(hcp=[Band(0, 40)]))
    assert len(merged.alt_groups) == 1
    fp = sc.fingerprint()
    assert fp["alt_groups"] and fp["honor_specs"] == []
    with pytest.raises(ValueError):
        SeatConstraints.from_bands(alt_groups=[[]])
    with pytest.raises(ValueError):
        SeatConstraints.from_bands(alt_groups=[[sc]])   # no nesting


def test_rejection_sampler_honours_honor_spec_and_alternatives():
    leader = "AQJ754.Q.T975.76"
    profile = ConstraintProfile(seats={
        "N": SeatConstraints.from_bands(
            honor_specs=[HonorSpec("S", "K", "all", 0.0)]),
        "S": SeatConstraints.from_bands(alt_groups=[[
            SeatConstraints.from_bands(
                honor_specs=[HonorSpec("H", "AK", "all", 0.0)]),
            SeatConstraints.from_bands(suits={"H": [Band(0, 1)]}),
        ]]),
    })
    deals, diag = RejectionDealSource(my_seat="E", batch_size=5000).generate(
        leader, profile, 40, seed=7)
    assert len(deals) == 40
    for wd in deals:
        seats = str(wd.deal.to_pbn()).split(":", 1)[1].split()
        hands = dict(zip("NESW", seats))
        assert "K" in hands["N"].split(".")[0]          # spec enforced
        s_hearts = hands["S"].split(".")[1]
        assert ("A" in s_hearts and "K" in s_hearts) or len(s_hearts) <= 1


# ---- clause handlers --------------------------------------------------------

def test_full_vocabulary_is_recognised():
    vocab = json.loads(FIXTURE.read_text())
    for c in vocab["clauses"]:
        effect = compile_clause(c["example"], NEUTRAL_LEADER)
        assert effect is not None, f"unrecognised clause: {c['example']!r}"


def test_honor_clause_compiles_to_all_spec():
    eff = compile_clause("!CKQ", NEUTRAL_LEADER)
    (spec,) = eff["honor_specs"]
    assert (spec.suit, spec.ranks, spec.mode) == ("C", "KQ", "all")
    assert 0 <= spec.weight < 1


def test_no_honor_clause_compiles_to_none_spec():
    eff = compile_clause("no !DAK", NEUTRAL_LEADER)
    (spec,) = eff["honor_specs"]
    assert (spec.suit, spec.ranks, spec.mode) == ("D", "AK", "none")


def test_honor_plus_clause_is_any_of_rank_or_better():
    eff = compile_clause("Q+ in !D", NEUTRAL_LEADER)
    (spec,) = eff["honor_specs"]
    assert (spec.suit, spec.ranks, spec.mode) == ("D", "AKQ", "any")


def test_solid_and_exact_card_lengths():
    eff = compile_clause("solid 6-card !S", NEUTRAL_LEADER)
    assert eff["suits"]["S"][0].lo == 6
    (spec,) = eff["honor_specs"]
    assert spec.ranks == "AKQ" and spec.mode == "all"
    eff = compile_clause("3-card !D", NEUTRAL_LEADER)
    assert (eff["suits"]["D"][0].lo, eff["suits"]["D"][0].hi) == (3, 3)


def test_honors_or_void_compiles_to_alternatives():
    eff = compile_clause("!SAKQ,no !S", NEUTRAL_LEADER)
    (group,) = eff["alt_groups"]
    assert len(group) >= 2        # solid honors / void (+ optional floor)
    assert any(alt.honor_specs for alt in group)
    assert any(alt.suit_weights["S"][0] >= 0.999
               and alt.suit_weights["S"][1] == 0 for alt in group)


def test_leader_held_honor_contradicts_gracefully():
    leader = ["AKQ32", "765", "432", "543"]    # leader owns all top spades
    eff = compile_clause("!SAKQ", leader)
    assert eff["contradicted"] == "!SAKQ"
    assert not eff.get("honor_specs")
    # partial contradiction: only the promisable ranks survive
    eff = compile_clause("!HAK", ["T98", "A65", "432", "5432"])
    (spec,) = eff["honor_specs"]
    assert spec.ranks == "K"


def test_negative_and_double_stops():
    bands = at_best_partial_bands("AQJ754")    # missing K: no full stop
    assert bands[0].lo == 0 and bands[0].hi == 2 and bands[0].weight == 1.0
    assert bands[1].lo == 3                    # holds-it-after-all, reduced
    assert bands[1].weight < 1
    bands = two_stop_bands("Q7")               # missing A,K,J: two cheapest
    assert bands[0].lo == 4                    # K(3) + J(1)


def test_auction_facts_are_noops_not_unrecognised():
    for clause in ("forcing", "forcing to 3N",
                   "opponents cannot play undoubled below 2N", "4- losers"):
        assert compile_clause(clause, NEUTRAL_LEADER) == {}


def test_compile_card_merges_clause_with_parsed_fields():
    card = {"gib_raw": "6+ !S; 12-17 HCP; solid 6-card !S",
            "hcp": (12, 17), "pts": None,
            "minlen": {"S": 6}, "maxlen": {}}
    sc, diag = compile_card(card, "T98.765.432.5432")
    assert diag["unrecognized"] == [] and diag["contradicted"] == []
    # conjunction: minlen 6 x exact-6..7 band => weight 0 at 5, >0 at 6
    assert sc.suit_weights["S"][5] == 0.0 and sc.suit_weights["S"][6] > 0
    assert sc.honor_specs and sc.honor_specs[0].ranks == "AKQ"


def test_unknown_clause_reported_not_dropped():
    card = {"gib_raw": "totally new gib phrase; 10+ HCP",
            "hcp": (10, 37), "pts": None, "minlen": {}, "maxlen": {}}
    sc, diag = compile_card(card, "T98.765.432.5432")
    assert diag["unrecognized"] == ["totally new gib phrase"]
    assert sc.hcp_weights[10] == 1.0          # the known part still applies


# ---- calibration plumbing ---------------------------------------------------

def test_clause_kind_buckets():
    assert clause_kind("stop in !D") == "stop"
    assert clause_kind("likely stop in !H") == "partial_stop"
    assert clause_kind("at best partial stop in !C") == "at_best_partial"
    assert clause_kind("!CKQ") == "honor_all"
    assert clause_kind("no !HAK") == "honor_none"
    assert clause_kind("Q+ in !D") == "honor_any"
    assert clause_kind("solid 6-card !C") == "solid"
    assert clause_kind("!SAKQ,no !S") == "alt_group"
    assert clause_kind("5+ !H") is None
    assert clause_kind("forcing") is None


def test_clause_core_satisfied_measures_the_promise():
    leader = "AQJ754.Q.T975.76"
    holds = clause_core_satisfied("partial stop in !S", leader,
                                  "K82.A85.KQ6.KT42")
    lacks = clause_core_satisfied("partial stop in !S", leader,
                                  "982.A85.KQ6.KT42")
    assert holds is True and lacks is False
    assert clause_core_satisfied("forcing", leader, "K82.A85.KQ6.KT42") is None
    # honors-or-void: satisfied by the void alternative
    assert clause_core_satisfied("!SAKQ,no !S", "T98.765.432.5432",
                                 ".AK85.KQ632.KT42") is True


def test_fit_weights_is_a_likelihood_ratio_with_clamps():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "calibrate_gib_vocab",
        Path(__file__).parent.parent / "scripts" / "calibrate_gib_vocab.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fitted = mod.fit_weights({
        "stop": {"n": 100, "hold": 80, "base_n": 300, "base_hold": 150},
        "rare": {"n": 5, "hold": 5, "base_n": 15, "base_hold": 5},
    }, min_n=30)
    assert fitted["stop"]["weight"] == pytest.approx(0.25)   # (0.2/0.8)*(1)
    assert fitted["rare"]["weight"] is None                  # keeps default


def test_calibration_file_is_checked_in_and_loaded():
    from bridge_trainer.engine.lead_gib_constraints import (
        CALIBRATION_PATH, miss_weight)
    assert CALIBRATION_PATH.exists()
    data = json.loads(CALIBRATION_PATH.read_text())
    assert data["stop"]["n"] > 100
    if data["stop"]["weight"] is not None:
        assert miss_weight("stop") == pytest.approx(data["stop"]["weight"])
    assert miss_weight("stop", 0.0) == 0.0                   # strict reading
