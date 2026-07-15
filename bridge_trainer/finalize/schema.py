"""Problem finalization: the bridge-judgment layer.

A FINALIZATION DOCUMENT turns a raw spot (real deal + auction stem + hero
seat) into a training problem. It carries everything that requires bridge
knowledge, so that the empirical machinery downstream needs none:

  options      2-5 candidate calls a strong player would actually consider
  meanings     what each concealed seat's calls showed (HCP/suit bands with
               soft margins) -> constrains the simulated hidden hands
  projections  per option, a small continuation policy: ordered when/else
               rules over the concealed hands (and the hero's known hand,
               me_*) deciding the FINAL CONTRACT reached on each layout —
               the user's call is NOT the end of the auction: doubles get
               pulled, partners raise, opponents save, all per layout
  explanation  why, in bridge language (shown after answering)

Finalization documents are authored by an expert — today by hand, next by
an LLM API call in the producer. The DD simulation over the constrained
layouts is the judge (owner decision, docs/core_problem_method.md).

Document shape (JSON-compatible):
{
  "dilemma": true,
  "options": ["P", "X", "3D"],
  "meanings": {
     "E": {"note": "...", "hcp": [11, 19, [[10, 10, 0.4]]],
            "suits": {"D": [3, 6, []]}},
     ...one entry per concealed seat with constraints...
  },
  "projections": {
     "P":  [{"else": {"contract": "2HN"}}],
     "X":  [{"when": "partner_hearts >= 3 and partner_hcp <= 7",
             "contract": "2SWx"}, {"else": {"contract": "3CN"}}],
     ...one per option...
  },
  "explanation": "..."
}
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import numpy as np

from .. import __version__ as trainer_version
from ..dd.correction import load_default_correction
from ..dealing.rejection import RejectionDealSource
from ..domain.auction import SEATS
from ..domain.constraints import Band, ConstraintProfile, SeatConstraints
from ..domain.contracts import FinalContract
from ..domain.interfaces import GenerationBudget
from ..pool.store import SCHEMA_VERSION
from ..projection.tree import ConditionalTreeProjector, deal_features
from ..scoring.comparison import compare_candidates
from ..scoring.evaluate import ScoreEvaluator

VALID_CALL = re.compile(r"^(P|X|XX|[1-7](C|D|H|S|NT))$")


class FinalizationError(ValueError):
    pass


def _bands(spec) -> list[Band]:
    lo, hi = int(spec[0]), int(spec[1])
    bands = [Band(lo, hi, 1.0)]
    for m in (spec[2] if len(spec) > 2 else []):
        bands.append(Band(int(m[0]), int(m[1]), float(m[2])))
    return bands


def validate_finalization(doc: dict, hero: str) -> None:
    if not isinstance(doc, dict):
        raise FinalizationError("finalization must be a mapping")
    if not doc.get("dilemma"):
        raise FinalizationError("not a dilemma (finalizer rejected the spot)")
    options = doc.get("options") or []
    if not (2 <= len(options) <= 5):
        raise FinalizationError(f"need 2-5 options, got {len(options)}")
    for o in options:
        if not VALID_CALL.match(o):
            raise FinalizationError(f"invalid option call {o!r}")
    if len(set(options)) != len(options):
        raise FinalizationError("duplicate options")
    meanings = doc.get("meanings") or {}
    for seat in meanings:
        if seat not in SEATS or seat == hero:
            raise FinalizationError(f"meanings for invalid seat {seat!r}")
    projections = doc.get("projections") or {}
    if set(projections) != set(options):
        raise FinalizationError("projections must cover exactly the options")
    # Tree + contract validation via the real projector/parser.
    ConditionalTreeProjector(projections, hero)
    if not (doc.get("explanation") or "").strip():
        raise FinalizationError("explanation is required")


def meanings_to_profile(meanings: dict) -> ConstraintProfile:
    profile = ConstraintProfile(seats={})
    for seat, spec in meanings.items():
        suits = {s: _bands(b) for s, b in (spec.get("suits") or {}).items()}
        hcp = _bands(spec["hcp"]) if "hcp" in spec else None
        profile.seats[seat] = SeatConstraints.from_bands(hcp=hcp, suits=suits)
    return profile


def build_record(
    *,
    problem_id: str,
    dealer: str,
    vul: str,
    hero: str,
    hands: dict,
    stem: list,
    doc: dict,
    source: dict | None = None,
    n_deals: int = 600,
    seed: int = 1,
) -> dict:
    """Finalization document + raw spot -> judged pool record.

    Simulates layouts under the meanings, projects every option to its
    final contract PER LAYOUT via the continuation trees (INV1: identical
    layouts for all options), and lets DD judge (INV2-INV8 stack).
    """
    validate_finalization(doc, hero)
    options = list(doc["options"])
    profile = meanings_to_profile(doc.get("meanings") or {})

    src = RejectionDealSource(my_seat=hero)
    deals, diag = src.generate(
        hands[hero], profile, n_deals, seed=seed,
        budget=GenerationBudget(max_attempts=6_000_000, max_seconds=25.0))
    if len(deals) < min(150, n_deals // 2):
        raise FinalizationError(
            f"meanings too tight: only {len(deals)} layouts generated")

    projector = ConditionalTreeProjector(doc["projections"], hero)
    features = [deal_features(wd.deal, hero) for wd in deals]
    contracts_by_option = {
        opt: [projector.project_features(f, opt) for f in features]
        for opt in options
    }

    evaluator = ScoreEvaluator(hero, vul, load_default_correction())
    evaluator.prepare(deals, contracts_by_option)
    weights = np.array([wd.weight for wd in deals])
    raw_s, corr_s = {}, {}
    for opt, contracts in contracts_by_option.items():
        raw_s[opt], corr_s[opt] = evaluator.evaluate(deals, contracts)
    widen = float(np.sqrt(n_deals / len(deals))) if diag.shortfall else 1.0
    raw = compare_candidates(raw_s, weights, ci_widen=widen)
    corr = compare_candidates(corr_s, weights, ci_widen=widen)

    def rows(comp):
        return [{"action": c.action, "ev": round(c.ev_vs_best_alt, 2),
                 "ci": round(c.ci_half_width, 2), "vs": c.best_alternative,
                 "p_gain": round(c.p_gain, 3), "p_loss": round(c.p_loss, 3),
                 "p_push": round(c.p_push, 3)} for c in comp.candidates]

    accepted = [corr.candidates[0].action]
    if corr.toss_up:
        accepted += corr.toss_up_with

    meanings_out = [{"seat": s, "meaning": (spec.get("note") or "")}
                    for s, spec in (doc.get("meanings") or {}).items()]
    return {
        "schema": SCHEMA_VERSION,
        "id": problem_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": {"kind": "finalized", "n_deals": len(deals),
                      "seed": seed, "trainer_version": trainer_version},
        "dealer": dealer, "vul": vul, "seat": hero,
        "hand": hands[hero],
        "auction": list(stem),
        "candidates": options,
        "verdict": {
            "accepted": accepted, "toss_up": corr.toss_up,
            "fog": (raw.toss_up != corr.toss_up or raw.verdict != corr.verdict),
            "corrected": rows(corr), "raw": rows(raw),
        },
        "difficulty": round(float(corr.candidates[0].ev_vs_best_alt), 3),
        "quality": {"ess": round(diag.effective_sample_size, 1),
                    "acceptance": round(diag.acceptance_rate, 6),
                    "shortfall": diag.shortfall},
        "explanation": doc["explanation"],
        "source": source or {},
        "meanings": meanings_out,
        "full_deal": dict(hands),
    }
