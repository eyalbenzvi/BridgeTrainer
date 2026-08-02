"""Card-world grading: the published lead verdict, computed on the auction's
stated meaning instead of Ben's neural-consistency samples.

Why (lead1-19fa5daef4b, docs/lead_auction_inference_gap.md): the app teaches
with the GIB gloss cards, so the grading distribution must be the world
those cards describe. This module grades every physical lead on layouts
drawn from the record's own compiled card constraints (engine/
lead_gib_constraints — full measured vocabulary, calibrated miss weights)
and returns a stock ``LeadEvaluation``, so the entire downstream machinery —
``judge_lead_mode``, ``compute_lead_metrics``, ``build_lead_record``,
``card_notes`` — runs untouched and the published record keeps exact parity.

Ben keeps every role it is good at (dealing, bidding, candidate softmax,
difficulty texture); only the GRADING distribution changes. Importance
weights are folded in by weight-proportional resampling of the shared
layouts, so the per-sample arrays every downstream consumer expects stay
plain (paired across cards, split-half-able) while the averages match the
weighted means.

Coherence loop closed here:
  * ``gloss_violations`` — the served deal must SATISFY every probabilistic
    promise its own glosses make (stops, honor holdings, solid suits),
    exactly as the grading core assumes them (``clause_core_satisfied``).
  * ``stability`` — the accepted answer set must overlap between the
    calibrated reading and the strict reading (miss weights 0); a board
    whose answer flips with the interpretation has no single answer.
"""
from __future__ import annotations

import numpy as np

from .lead_gib_constraints import (
    _clauses, clause_core_satisfied, clause_kind,
    profile_from_explained_auction)
from .lead_posterior import LeadProblem, build_problem, evaluate_layouts
from .lead_verdict import LeadEvaluation

GRADE_SAMPLES = 400          # calibrated-reading layouts (the verdict)
STRICT_SAMPLES = 250         # strict-reading layouts (the stability check)
GRADE_SECONDS = 90.0


def gloss_violations(entries: list[dict], hands_by_seat: dict,
                     leader_hand: str, leader: str) -> list[str]:
    """Probabilistic gloss promises the ACTUAL hands fail to honour.

    For every call by a concealed seat, every calibratable clause of its GIB
    card ("partial stop in !S", "!CKQ", "solid 6-card !H", ...) is checked
    against that seat's real hand with the SAME core-satisfaction test the
    grading distribution assumes (clause_core_satisfied). A violation means
    the served deal contradicts the lesson shown to the student — the board
    must not ship. Hard facts (lengths, HCP) stay with the existing
    explain_check gate; this covers the promises it never validated."""
    out = []
    for e in entries:
        seat, call = e.get("seat"), e.get("call")
        if seat == leader or seat not in hands_by_seat:
            continue
        raw = ((e.get("card") or {}).get("gib_raw")) or ""
        for clause in _clauses(raw):
            if clause_kind(clause) is None:
                continue
            sat = clause_core_satisfied(clause, leader_hand,
                                        hands_by_seat[seat])
            if sat is False:
                out.append(f"{seat}:{call}: {clause!r} unfulfilled")
    return out


def card_world_evaluation(problem: LeadProblem, entries: list[dict],
                          softmax: dict, *, n_samples: int = GRADE_SAMPLES,
                          seed: int = 1, miss_scale: float = 1.0,
                          doubled: bool | None = None,
                          ) -> tuple[LeadEvaluation | None, dict]:
    """Grade all 13 physical leads on the card-constraint distribution.

    Returns (LeadEvaluation, diagnostics). The evaluation is None when the
    auction constrained nothing recognisable (diagnostics say why) — the
    caller then falls back to the Ben-sample verdict rather than fake a
    grade. Importance weights become a weight-proportional resample so the
    per-sample arrays stay plain and paired."""
    from .lead_samplers import ConstraintSampler, _seed_int

    profile = profile_from_explained_auction(
        entries, problem.leader, problem.hand, stop_miss_scale=miss_scale)
    mode = "gib_cards" if miss_scale else "gib_cards_strict"
    sampler = ConstraintSampler(profile=profile,
                                semantic_constraint_mode=mode,
                                unrecognized_calls=profile.unrecognized_calls,
                                max_seconds=GRADE_SECONDS)
    ls = sampler.sample(problem, n_samples, seed)
    diag = dict(getattr(ls, "constraint_diagnostics", {}) or {})
    diag["reading"] = mode
    diag["contradicted_clauses"] = list(
        getattr(profile, "contradicted_clauses", []))
    if not diag.get("any_constraint_applied"):
        diag["fallback"] = "no_constraints_recognised"
        return None, diag
    if ls.n == 0:
        diag["fallback"] = "empty_accepted_set"
        return None, diag

    ev = evaluate_layouts(ls)
    w = np.asarray(ls.weight, dtype=float)
    w = w / w.sum()
    # weight-proportional resample: one shared index vector so the per-card
    # arrays stay PAIRED (split-half stability and per-sample IMPs depend on
    # that), deterministic in the public state + seed.
    rng = np.random.default_rng(_seed_int(problem, seed) ^ 0x5EED)
    idx = rng.choice(ls.n, size=ls.n, replace=True, p=w)
    def_tricks = {c: np.asarray(ev.def_tricks[c], dtype=float)[idx]
                  for c in ev.def_tricks}
    ess = float(w.sum() ** 2 / (w ** 2).sum())
    diag["accepted"] = int(ls.n)
    diag["ess"] = round(ess, 1)
    le = LeadEvaluation(
        cards=problem.legal_leads(),
        def_tricks=def_tricks,
        softmax=dict(softmax or {}),
        n_samples=int(ls.n),
        quality=ess / ls.n if ls.n else 0.0,
        contract=problem.contract,
        doubled=bool(doubled if doubled is not None else problem.doubled))
    return le, diag


def stability_check(problem: LeadProblem, entries: list[dict],
                    accepted: list[str], softmax: dict, *,
                    seed: int = 1, target_mode: str = "MP",
                    vul: str | None = None) -> tuple[bool, dict]:
    """Does the accepted answer set survive the STRICT reading (announced
    promises taken literally)? True when the strict winner set overlaps the
    calibrated accepted set — ties allowed, flips rejected. Abstains-true
    when the strict reading yields no gradable layouts."""
    from .lead_verdict import judge_lead_mode

    le, diag = card_world_evaluation(problem, entries, softmax,
                                     n_samples=STRICT_SAMPLES, seed=seed,
                                     miss_scale=0.0)
    if le is None:
        return True, {"strict": "abstain", **diag}
    v = judge_lead_mode(le, target_mode, vul=vul, force=True)
    ok = bool(set(v.best) & set(accepted))
    return ok, {"strict_best": list(v.best),
                "strict_n": le.n_samples,
                "strict_ess": diag.get("ess"),
                "overlap": ok}


def grade_record_card_world(rec: dict, *, seed: int = 1,
                            n_samples: int = GRADE_SAMPLES) -> dict:
    """Re-grade a STORED lead record on its own card world. Returns a report
    with either replacement record fields (answer possibly CHANGED) or a
    deletion/fallback reason. Shared by the migration script; the forge
    builds fresh records through card_world_evaluation directly.

    Decision ladder (one definition for the whole backward migration):
      gloss_unfulfilled  the actual deal contradicts its own glosses -> delete
      no_constraints     nothing recognisable -> keep as-is (Ben verdict)
      empty_set          constraints unsatisfiable -> delete (incoherent)
      honor_sensitive    calibrated vs strict winners disjoint -> delete
      regraded           new verdict fields returned (answer may change)
    """
    from ..scoring.lead_metrics import compute_lead_metrics, mode_rankings
    from .lead_explain import card_notes
    from .lead_verdict import judge_lead_mode

    entries = ((rec.get("explanations") or {}).get("auction")) or []
    problem = build_problem(rec["hand"], list(rec["auction"]), rec["dealer"],
                            rec.get("vul", "None"), rec["contract"])
    target_mode = ((rec.get("training") or {}).get("target_mode")
                   or (rec.get("generator") or {}).get("target_mode") or "MP")
    softmax = {r["card"]: r.get("ben_softmax", 0.0)
               for r in ((rec.get("verdict") or {}).get("table") or [])
               if r.get("card")}
    report = {"id": rec["id"], "target_mode": target_mode,
              "published": list((rec.get("verdict") or {}).get("accepted")
                               or [])}

    fd = rec.get("full_deal") or {}
    bad = gloss_violations(entries, fd, rec["hand"], rec["leader"]) \
        if fd else []
    if bad:
        report.update(status="gloss_unfulfilled", detail="; ".join(bad[:4]))
        return report

    le, diag = card_world_evaluation(problem, entries, softmax,
                                     n_samples=n_samples, seed=seed)
    report["diagnostics"] = diag
    if le is None:
        report["status"] = ("no_constraints"
                            if diag.get("fallback")
                            == "no_constraints_recognised" else "empty_set")
        return report

    v = judge_lead_mode(le, target_mode, vul=rec.get("vul"), force=True)
    stable, stab = stability_check(problem, entries, list(v.best), softmax,
                                   seed=seed, target_mode=target_mode,
                                   vul=rec.get("vul"))
    report["stability"] = stab
    if not stable:
        report.update(status="honor_sensitive",
                      detail=f"calibrated {v.best} vs strict "
                             f"{stab.get('strict_best')}")
        return report

    metrics = compute_lead_metrics(le.def_tricks, rec["contract"],
                                   rec.get("vul", "None"))
    rankings = mode_rankings(metrics)

    def card_row(base):
        c = base["card"]
        m = metrics[c]
        return {**base, "exp_score": round(m["exp_score"], 1),
                "exp_imps": round(m["exp_imps"], 2),
                "set_prob": round(m["set_prob"], 3),
                "rank_mp": rankings["MP"]["rank"][c],
                "rank_imp": rankings["IMP"]["rank"][c],
                "recommended_mp": c in rankings["MP"]["accepted"],
                "recommended_imp": c in rankings["IMP"]["accepted"]}

    by_mode = {mode: {k: rankings[mode][k] for k in
                      ("ranking_metric", "recommended", "accepted")}
               for mode in rankings}
    verdict_fields = {
        "accepted": list(v.best),
        "by_mode": by_mode,
        "gap": v.measured.get("gap"),
        "n_samples": le.n_samples,
        "table": [card_row(r) for r in v.table],
        "flags": v.flags,
    }
    report.update(
        status="regraded",
        answer_changed=set(v.best) != set(report["published"]),
        new_accepted=list(v.best),
        would_reject_now=(judge_lead_mode(le, target_mode,
                                          vul=rec.get("vul")).reason
                          if not judge_lead_mode(le, target_mode,
                                                 vul=rec.get("vul")).accepted
                          else None),
        update={
            "verdict": verdict_fields,
            "candidates": [card_row({"card": r["card"],
                                     "avg_def_tricks": r["avg_def_tricks"],
                                     "ben_softmax": r["ben_softmax"]})
                           for r in v.table],
            "difficulty": v.difficulty,
            "classification": {**(rec.get("classification") or {}),
                               "difficulty_level": v.difficulty},
            "quality": v.measured,
            "explanations": {**(rec.get("explanations") or {}),
                             "cards": card_notes(v)},
            "generator": {**(rec.get("generator") or {}),
                          "grading": {"distribution": "gib_cards_calibrated",
                                      "n": le.n_samples,
                                      "ess": diag.get("ess"),
                                      "strict_agreed": True,
                                      "seed": seed}},
        })
    return report
