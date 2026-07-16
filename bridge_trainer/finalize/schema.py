"""Problem finalization: the bridge-judgment layer.

A FINALIZATION DOCUMENT turns a raw spot (real deal + auction stem + hero
seat) into a training problem. It carries everything that requires bridge
knowledge, so that the empirical machinery downstream needs none:

  options      2-5 candidate calls a strong player would actually consider
  meanings     what each concealed seat's calls showed (HCP/suit bands with
               soft margins, per-suit quality bands, conditional denials)
               -> constrains the simulated hidden hands
  projections  per option, a small continuation policy: ordered when/else
               rules over the concealed hands (and the hero's known hand,
               me_*) deciding the FINAL CONTRACT reached on each layout —
               the user's call is NOT the end of the auction: doubles get
               pulled, partners raise, opponents save, all per layout
  deviations   options that bend the card: {opt: {note, kind}} where kind
               is 'card_violation' (objective breach) or 'judgment'
               (style/evaluation note) — least-lie accounting, never a ban
  category     taxonomy bucket for batch quotas
  explanation  DRAFT prose; the shipping text is authored after the
               verdict exists and installed via prose.attach_explanation

The DD simulation over the constrained layouts is the judge (owner
decision, docs/core_problem_method.md). Between the author and the judge
stands the hard shell — validators that trust nobody:

  V1  auction-state legality         (validate/auction_state.py)
  V3  equivalence collapse           (here)
  V5  ground-truth admissibility     (validate/ground_truth.py)
  V6  projection-tree realism        (validate/trees.py)
  V7  verdict sanity + dilemma gates (here)

plus automatic silence denials (validate/inference.py) and post-verdict
prose linting (finalize/prose.py).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from datetime import datetime, timezone

import numpy as np

from .. import __version__ as trainer_version
from ..dd.correction import load_default_correction
from ..dealing.rejection import RejectionDealSource
from ..domain.auction import SEATS
from ..domain.constraints import (Band, ConstraintProfile, Denial,
                                  SeatConstraints)
from ..domain.interfaces import GenerationBudget
from ..pool.store import SCHEMA_VERSION
from ..projection.tree import ConditionalTreeProjector, deal_features
from ..scoring.comparison import compare_candidates
from ..scoring.evaluate import ScoreEvaluator
from ..validate.auction_state import validate_options_against_state
from ..validate.ground_truth import check_deal_admissible
from ..validate.inference import default_silence_denials
from ..validate.trees import check_hero_stem, lint_projection_trees

EQUIVALENCE_THRESHOLD = 0.90  # V3: options reaching the same contract this
                              # often are one option wearing two hats

# V7 verdict sanity gates: a "verdict" past these is a modeling artifact.
GATE_P_GAIN = 0.97
GATE_MARGIN = 6.0
GATE_MIN_DEALS_FOR_PUSH = 200
DILEMMA_MARGIN = 1.5          # flagged-only menus must at least be close

VALID_CALL = re.compile(r"^(P|X|XX|[1-7](C|D|H|S|NT))$")

CATEGORIES = ("partscore", "game", "slam", "sacrifice", "opening-style",
              "raise-choice", "other")
DEVIATION_KINDS = ("card_violation", "judgment")


class FinalizationError(ValueError):
    pass


def _bands(spec) -> list[Band]:
    lo, hi = int(spec[0]), int(spec[1])
    bands = [Band(lo, hi, 1.0)]
    for m in (spec[2] if len(spec) > 2 else []):
        bands.append(Band(int(m[0]), int(m[1]), float(m[2])))
    return bands


def normalize_deviations(doc: dict) -> dict:
    """Deviation taxonomy (backlog D14): str -> judgment note; dicts must
    carry note + kind."""
    out = {}
    for opt, spec in (doc.get("deviations") or {}).items():
        if isinstance(spec, str):
            out[opt] = {"note": spec, "kind": "judgment"}
        else:
            if not spec.get("note") or spec.get("kind") not in DEVIATION_KINDS:
                raise FinalizationError(
                    f"deviation for {opt!r} needs a note and a kind in "
                    f"{DEVIATION_KINDS}")
            out[opt] = {"note": spec["note"], "kind": spec["kind"]}
    return out


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
    deviations = normalize_deviations(doc)
    if not set(deviations) <= set(options):
        raise FinalizationError("deviations must reference offered options")
    category = doc.get("category", "other")
    if category not in CATEGORIES:
        raise FinalizationError(f"category must be one of {CATEGORIES}")
    if not (doc.get("explanation") or "").strip():
        raise FinalizationError("explanation is required")
    opt_notes = doc.get("option_explanations")
    if opt_notes is not None:
        if set(opt_notes) != set(options):
            raise FinalizationError(
                "option_explanations must cover exactly the options")
        for opt, spec in opt_notes.items():
            if not (spec.get("shows") or "").strip() \
                    or not (spec.get("partner") or "").strip():
                raise FinalizationError(
                    f"option_explanations[{opt!r}] needs 'shows' and "
                    f"'partner' texts")


def meanings_to_profile(meanings: dict) -> ConstraintProfile:
    profile = ConstraintProfile(seats={})
    for seat, spec in meanings.items():
        suits = {s: _bands(b) for s, b in (spec.get("suits") or {}).items()}
        suit_hcp = {s: _bands(b)
                    for s, b in (spec.get("suit_hcp") or {}).items()}
        denials = [Denial(int(d[0]), int(d[1]), d[2], int(d[3]), float(d[4]))
                   for d in (spec.get("denials") or [])]
        hcp = _bands(spec["hcp"]) if "hcp" in spec else None
        profile.seats[seat] = SeatConstraints.from_bands(
            hcp=hcp, suits=suits, suit_hcp=suit_hcp, denials=denials)
    return profile


def apply_silence_denials(profile: ConstraintProfile, meanings: dict,
                          dealer: str, stem: list, hero: str) -> list[str]:
    """A3: all-pass seats inherit baseline negative inferences unless the
    author opts out explicitly. Returns notes for the quality block."""
    notes = []
    for seat, denials in default_silence_denials(dealer, stem, hero).items():
        spec = meanings.get(seat) or {}
        if spec.get("no_default_denials"):
            notes.append(f"{seat}: default silence denials waived by author")
            continue
        sc = profile.seats.setdefault(seat, SeatConstraints())
        sc.denials = list(sc.denials) + denials
        notes.append(f"{seat}: {len(denials)} silence denials applied")
    return notes


def deal_hash(hands: dict) -> str:
    canon = "|".join(f"{s}:{hands[s]}" for s in SEATS)
    return hashlib.md5(canon.encode()).hexdigest()[:12]


def hero_features(hand: str) -> dict:
    from ..dealing.features import HCP_BY_RANK, parse_hand_pbn
    cards = parse_hand_pbn(hand)
    feats = {"hcp": int(sum(HCP_BY_RANK[c % 13] for c in cards))}
    for i, s in enumerate("SHDC"):
        feats[s] = sum(1 for c in cards if c // 13 == i)
    return feats


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
    layouts for all options), and lets DD judge (INV2-INV8 stack). The
    stored explanation is the author's DRAFT rendered with flag lines;
    ship-quality prose is installed afterwards via attach_explanation.
    """
    validate_finalization(doc, hero)
    options = list(doc["options"])
    deviations = normalize_deviations(doc)
    stem_notes = doc.get("stem_explanations")
    if stem_notes is not None and len(stem_notes) != len(stem):
        raise FinalizationError(
            f"stem_explanations must have one entry per stem call "
            f"({len(stem_notes)} notes for {len(stem)} calls)")
    # V1 hard shell: mechanical auction legality of every option and every
    # continuation leaf. Never trusted to an author.
    validate_options_against_state(dealer, stem, hero, options,
                                   doc["projections"])
    # V6: tree realism — strength floors, deviation downsides, symmetric
    # opponent aggression.
    tree_errors, tree_warnings = lint_projection_trees(
        dealer, stem, hero, options, doc["projections"], deviations)
    if tree_errors:
        raise FinalizationError("projection trees rejected:\n- "
                                + "\n- ".join(tree_errors))
    stem_warnings = check_hero_stem(dealer, stem, hero,
                                    hero_features(hands[hero]))

    profile = meanings_to_profile(doc.get("meanings") or {})
    inference_notes = apply_silence_denials(
        profile, doc.get("meanings") or {}, dealer, stem, hero)

    # V5: when the deal is real, the meanings must admit it.
    if source:
        violations = check_deal_admissible(hands, hero, profile)
        if violations:
            raise FinalizationError("ground truth rejected:\n- "
                                    + "\n- ".join(violations))

    src = RejectionDealSource(my_seat=hero)
    deals, diag = src.generate(
        hands[hero], profile, n_deals, seed=seed,
        budget=GenerationBudget(max_attempts=6_000_000, max_seconds=25.0))
    if len(deals) < min(150, n_deals // 2):
        raise FinalizationError(
            f"meanings too tight: only {len(deals)} layouts generated")

    projector = ConditionalTreeProjector(doc["projections"], hero)
    features = [deal_features(wd.deal, hero) for wd in deals]
    weights = np.array([wd.weight for wd in deals])
    contracts_by_option = {
        opt: [projector.project_features(f, opt) for f in features]
        for opt in options
    }
    # B8 overfit telemetry: dead when-branches suggest the tree was
    # written around one known layout.
    branch_mass = projector.branch_masses(features, weights)
    for opt, masses in branch_mass.items():
        for i, m in enumerate(masses[:-1]):
            if m < 0.005:
                tree_warnings.append(
                    f"option {opt!r} branch #{i} captures {m:.2%} of "
                    f"layouts — dead branch, possible overfit")

    evaluator = ScoreEvaluator(hero, vul, load_default_correction())
    evaluator.prepare(deals, contracts_by_option)
    raw_s, corr_s = {}, {}
    for opt, contracts in contracts_by_option.items():
        raw_s[opt], corr_s[opt] = evaluator.evaluate(deals, contracts)
    widen = float(np.sqrt(n_deals / len(deals))) if diag.shortfall else 1.0
    raw = compare_candidates(raw_s, weights, ci_widen=widen)
    corr = compare_candidates(corr_s, weights, ci_widen=widen)

    accepted = [corr.candidates[0].action]
    toss_up = corr.toss_up
    if corr.toss_up:
        accepted += corr.toss_up_with

    # V7a: fog forces a toss-up — when raw and corrected disagree the
    # verdict may not crown a single winner (backlog C11).
    fog = (raw.toss_up != corr.toss_up or raw.verdict != corr.verdict)
    if fog:
        toss_up = True
        for action in ([raw.candidates[0].action] + list(raw.toss_up_with)):
            if action not in accepted:
                accepted.append(action)

    # V7b: penalty-branch sensitivity — DD defense inflates doubled
    # penalties; if undoubling every doubled leaf flips the winner, the
    # margin was the artifact (backlog C12).
    penalty_sensitivity = None
    if any(c.doubled for cs in contracts_by_option.values() for c in cs):
        undoubled = {
            opt: [replace(c, doubled=False) if c.doubled else c
                  for c in cs]
            for opt, cs in contracts_by_option.items()}
        u_corr_s = {opt: evaluator.evaluate(deals, cs)[1]
                    for opt, cs in undoubled.items()}
        u_corr = compare_candidates(u_corr_s, weights, ci_widen=widen)
        flips = u_corr.candidates[0].action != corr.candidates[0].action
        penalty_sensitivity = {
            "undoubled_winner": u_corr.candidates[0].action,
            "winner_flips": flips}
        if flips:
            toss_up = True
            if u_corr.candidates[0].action not in accepted:
                accepted.append(u_corr.candidates[0].action)

    # V3 hard shell: options that reach the SAME final contract on almost
    # every layout are equivalent — any DD margin between them is noise.
    contract_keys = {opt: [str(fc) for fc in contracts_by_option[opt]]
                     for opt in options}
    wsum = float(weights.sum())
    equivalent_pairs = []
    for i, a in enumerate(options):
        for b in options[i + 1:]:
            same = sum(w for ka, kb, w in
                       zip(contract_keys[a], contract_keys[b], weights)
                       if ka == kb)
            if same / wsum >= EQUIVALENCE_THRESHOLD:
                equivalent_pairs.append([a, b])
    if equivalent_pairs:
        eq_set = {opt for pair in equivalent_pairs for opt in pair}
        if eq_set & set(accepted):
            accepted = list(dict.fromkeys(accepted + sorted(eq_set)))
            toss_up = True

    # V7c: sanity gates — quarantine verdicts no bridge decision produces
    # (backlog C10).
    top = corr.candidates[0]
    margin = abs(float(top.ev_vs_best_alt))
    if not toss_up:
        if top.p_gain > GATE_P_GAIN:
            raise FinalizationError(
                f"sanity gate: winner gains on {top.p_gain:.1%} of layouts "
                f"— tree-vs-tree, not bid-vs-bid (V7)")
        if margin > GATE_MARGIN:
            raise FinalizationError(
                f"sanity gate: {margin:.1f} IMP margin is a modeling "
                f"artifact, not a bridge margin (V7)")
        if top.p_push == 0.0 and len(deals) >= GATE_MIN_DEALS_FOR_PUSH:
            raise FinalizationError(
                "sanity gate: zero pushes across the sample — the option "
                "trees produce disjoint auctions (V7)")

    # V7d: dilemma gate — a menu of one legal call is a quiz, not a
    # problem (backlog C13).
    clean = [o for o in options if o not in deviations]
    if len(clean) < 2 and margin >= DILEMMA_MARGIN and not toss_up:
        raise FinalizationError(
            f"dilemma gate: only {len(clean)} non-deviating option(s) and "
            f"a {margin:.1f} IMP margin — the decision is routine (V7)")

    def rows(comp):
        return [{"action": c.action, "ev": round(c.ev_vs_best_alt, 2),
                 "ci": round(c.ci_half_width, 2), "vs": c.best_alternative,
                 "p_gain": round(c.p_gain, 3), "p_loss": round(c.p_loss, 3),
                 "p_push": round(c.p_push, 3)} for c in comp.candidates]

    meanings_out = [
        {"seat": s, "meaning": (spec.get("note") or ""),
         "hcp": ([int(spec["hcp"][0]), int(spec["hcp"][1])]
                 if "hcp" in spec else None)}
        for s, spec in (doc.get("meanings") or {}).items()]

    record = {
        "schema": SCHEMA_VERSION,
        "id": problem_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": {"kind": "finalized", "n_deals": len(deals),
                      "seed": seed, "trainer_version": trainer_version},
        "dealer": dealer, "vul": vul, "seat": hero,
        "hand": hands[hero],
        "auction": list(stem),
        "candidates": options,
        "category": doc.get("category", "other"),
        "deviations": deviations,
        "auction_notes": stem_notes,
        "option_notes": doc.get("option_explanations"),
        "verdict": {
            "accepted": accepted,
            "toss_up": toss_up,
            "fog": fog,
            "corrected": rows(corr), "raw": rows(raw),
        },
        "difficulty": round(float(corr.candidates[0].ev_vs_best_alt), 3),
        "quality": {"ess": round(diag.effective_sample_size, 1),
                    "acceptance": round(diag.acceptance_rate, 6),
                    "shortfall": diag.shortfall,
                    "equivalent_pairs": equivalent_pairs,
                    "branch_mass": branch_mass,
                    "penalty_sensitivity": penalty_sensitivity,
                    "tree_warnings": tree_warnings,
                    "stem_warnings": stem_warnings,
                    "inference_notes": inference_notes},
        "source": source or {},
        "meanings": meanings_out,
        "deal_hash": deal_hash(hands),
        "full_deal": dict(hands),
    }
    from .prose import render_full_explanation
    record["explanation"] = render_full_explanation(
        doc["explanation"], record)
    return record
