"""The split lead-problem generator: MP and IMP each select boards with
their own gates.

Ben-free: the mode-specific verdict gates (judge_lead_imp / prejudge_lead_imp
and their MP counterparts) run on synthetic per-sample DD arrays, and the
record builder is exercised directly — the same code paths `trainer
lead-forge --mode {MP,IMP}` drives.
"""
from __future__ import annotations

import numpy as np
import pytest

from bridge_trainer.engine.lead_maker import ID_PREFIX, build_lead_record
from bridge_trainer.engine.lead_verdict import (
    GAP_MIN_IMP, IMP_SCALE, MP_SCALE, LeadEvaluation, judge_lead,
    judge_lead_imp, judge_lead_mode, prejudge_lead, prejudge_lead_imp)
from bridge_trainer.pool.store import index_entry
from bridge_trainer.scoring.lead_metrics import (per_sample_imps,
                                                 target_mode_of)


def _hand13():
    return ["SA", "SK", "S3", "HQ", "HJ", "H7", "H2",
            "DA", "D6", "CT", "C8", "C5", "C3"]


def _eval(tricks_by_card, contract, n=512, softmax=None):
    """LeadEvaluation whose per-card trick arrays tile `tricks_by_card`
    (card -> list of per-sample defensive trick counts)."""
    cards = _hand13()
    def_tricks = {}
    for c in cards:
        pattern = tricks_by_card.get(c, [4])
        def_tricks[c] = np.tile(np.asarray(pattern, dtype=float),
                                n // len(pattern) + 1)[:n]
    # low, spread policy so the C1 "obvious" gate never masks the gap gates
    softmax = softmax or {c: 0.03 for c in cards}
    return LeadEvaluation(cards=cards, def_tricks=def_tricks, softmax=softmax,
                          n_samples=n, quality=0.9, contract=contract,
                          doubled=False)


# A board where the TRICK choice barely matters but the SCORE swing is
# decisive: against 3NT by East (both vul, 5 tricks to set), DA cashes 5
# tricks half the time (down 1) and 3 most other times (avg 4.1); every
# other card always takes 4 (3NT just makes). A 0.1-trick gap -> MP calls it
# suit-indifferent; a huge expected-IMP edge -> IMP accepts it.
IMP_ONLY = _eval({"DA": [5, 3, 5, 3, 5, 3, 5, 3, 5, 4]}, "3NTE")

# The mirror image: against 3D by East (non-vul minor part score), DA always
# takes 4 defensive tricks (3D makes exactly, -110) and everything else takes
# 3 (an overtrick, -130). A full-trick gap -> MP accepts; the 20-point score
# difference is worth 0 IMPs on every layout -> IMP calls it indifferent.
MP_ONLY = _eval({"DA": [4]} | {c: [3] for c in _hand13() if c != "DA"}, "3DE")
VUL = "Both"


# --------------------------------------------------------------------------
# the two gates disagree in exactly the intended direction
# --------------------------------------------------------------------------

def test_imp_gate_accepts_score_swing_board():
    assert not judge_lead(IMP_ONLY).accepted            # MP: tricks all equal
    assert judge_lead(IMP_ONLY).reason == "suit_indifferent"
    v = judge_lead_imp(IMP_ONLY, VUL)
    assert v.accepted, v.reason
    assert v.best == ["DA"]
    assert v.measured["mode"] == "IMP"
    assert v.measured["gap"] >= GAP_MIN_IMP
    assert "best_avg_imps" in v.measured


def test_mp_gate_accepts_trick_board_that_imp_rejects():
    v = judge_lead(MP_ONLY)
    assert v.accepted, v.reason
    assert v.best == ["DA"]
    assert v.measured["mode"] == "MP"
    assert "best_avg_tricks" in v.measured
    vi = judge_lead_imp(MP_ONLY, VUL)
    assert not vi.accepted
    assert vi.reason == "suit_indifferent"


def test_imp_gate_never_ranks_by_tricks():
    # sanity on the underlying evidence: DA's IMP edge on IMP_ONLY comes
    # from set probability, not trick count — the trick gap is far below
    # the MP gate while the IMP gap is enormous
    imps = per_sample_imps(IMP_ONLY.def_tricks, "3NTE", VUL)
    imp_gap = float(np.mean(imps["DA"])) - float(np.mean(imps["HQ"]))
    trick_gap = float(np.mean(IMP_ONLY.def_tricks["DA"])) - \
        float(np.mean(IMP_ONLY.def_tricks["HQ"]))
    assert imp_gap > GAP_MIN_IMP
    assert trick_gap == pytest.approx(0.1, abs=0.02)


def test_mode_dispatch():
    assert judge_lead_mode(MP_ONLY, "MP").accepted
    assert not judge_lead_mode(MP_ONLY, "IMP", vul=VUL).accepted
    with pytest.raises(ValueError):
        judge_lead_mode(MP_ONLY, "IMP")        # IMP needs the vulnerability
    with pytest.raises(KeyError):
        judge_lead_mode(MP_ONLY, "TOTAL_POINTS", vul=VUL)


def test_verdict_table_stays_trick_denominated_in_both_modes():
    # avg_def_tricks / vs_best keep their meaning regardless of judge mode
    for v in (judge_lead_imp(IMP_ONLY, VUL), judge_lead(MP_ONLY)):
        top = v.table[0]
        assert "avg_def_tricks" in top and "vs_best" in top
        assert top["vs_best"] == 0


# --------------------------------------------------------------------------
# prescreen cascade rules out per-mode
# --------------------------------------------------------------------------

def test_prejudge_splits_by_mode():
    # IMP_ONLY: tricks confidently indifferent, IMPs decisively not
    assert prejudge_lead(IMP_ONLY) == "suit_indifferent"
    assert prejudge_lead_imp(IMP_ONLY, VUL) is None
    # MP_ONLY: tricks decisive, IMPs confidently indifferent
    assert prejudge_lead(MP_ONLY) is None
    assert prejudge_lead_imp(MP_ONLY, VUL) == "suit_indifferent"


def test_scales_are_distinct():
    assert MP_SCALE.mode == "MP" and IMP_SCALE.mode == "IMP"
    assert IMP_SCALE.gap_min == GAP_MIN_IMP != MP_SCALE.gap_min


# --------------------------------------------------------------------------
# records: forged-for stamp, id prefixes, index flag
# --------------------------------------------------------------------------

def _record(target_mode):
    le = IMP_ONLY
    v = judge_lead_mode(le, target_mode, vul=VUL, force=True)
    fc = {"level": 3, "denom": "NT", "declarer_i": 1, "doubled": ""}
    hands = ["A32.K54.7654.432"] * 4
    return build_lead_record(
        seed=7, hands=hands, dealer_i=0, vul=(True, True), fc=fc,
        leader_i=2, hand=hands[2],
        full_auction=["1NT", "P", "3NT", "P", "P", "P"],
        le=le, verdict=v, auc_meanings=[], card_notes={}, elapsed=0.1,
        target_mode=target_mode)


def test_records_stamped_with_target_mode_and_distinct_ids():
    mp, imp = _record("MP"), _record("IMP")
    assert mp["id"] == f"{ID_PREFIX['MP']}-00000007"
    assert imp["id"] == f"{ID_PREFIX['IMP']}-00000007"
    assert mp["id"] != imp["id"]               # same seed, no collision
    assert mp["training"]["target_mode"] == "MP"
    assert imp["training"]["target_mode"] == "IMP"
    assert imp["generator"]["target_mode"] == "IMP"
    assert target_mode_of(mp) == "MP" and target_mode_of(imp) == "IMP"
    # both records still carry BOTH modes' metrics and recommendations
    for rec in (mp, imp):
        assert set(rec["verdict"]["by_mode"]) == {"MP", "IMP"}
        assert set(rec["training"]["modes"]) == {"MP", "IMP"}


def test_index_entries_carry_target_mode():
    assert index_entry(_record("MP"))["target_mode"] == "MP"
    assert index_entry(_record("IMP"))["target_mode"] == "IMP"
    legacy = {"schema": 1, "kind": "lead", "id": "lead1-old",
              "created_at": "2025-01-01T00:00:00+00:00", "contract": "4HE",
              "classification": {}, "verdict": {}}
    assert index_entry(legacy)["target_mode"] == "MP"   # pre-split default


def test_cli_and_script_expose_the_split():
    import pathlib
    cli = pathlib.Path("bridge_trainer/app/cli.py").read_text()
    assert '"--mode"' in cli and '"MP", "IMP"' in cli
    sh = pathlib.Path("scripts/generate_and_push_leads.sh").read_text()
    assert '--mode "$MODE"' in sh


def test_web_sections_serve_their_own_generator_pool():
    from bridge_trainer.app.webapp import _index_html, _lead_html
    for page in (_index_html(), _lead_html()):
        assert "targetModeOf" in page
    assert "target_mode" in _index_html()
