"""Diagnostic artifact for a single opening-lead problem.

``build_lead_debug_artifact`` assembles the inspectable JSON described in the
audit task: for every physical candidate it records the physical/display/dds
card and the (folded) policy action side by side, Ben's policy probability and
the double-dummy statistics; for every sampled layout it records the four
hands, why the sampler accepted it, and the per-candidate raw DDS output with
its conversion to declarer and defender tricks.

The builder is PURE (numpy only) so it is unit-tested without Ben. The full
original deal is copied in under an ``audit_only`` key that is clearly marked
and never read by evaluation. ``engine/ben.py`` and the ``trainer lead-debug``
CLI wire the Ben sampler/policy in and hand the results here.
"""
from __future__ import annotations

import math

import numpy as np

from .lead_cards import SEATS, policy_action
from .lead_evaluate import Contract, opening_leader_for_contract


def _stats(arr) -> dict:
    a = np.asarray(arr, dtype=float)
    n = int(a.shape[0])
    if n == 0:
        return {"mean_def_tricks": None, "std": None, "stderr": None,
                "ci95": None, "n": 0}
    mean = float(a.mean())
    std = float(a.std(ddof=1)) if n > 1 else 0.0
    stderr = std / math.sqrt(n) if n else 0.0
    half = 1.96 * stderr
    return {"mean_def_tricks": round(mean, 4), "std": round(std, 4),
            "stderr": round(stderr, 4),
            "ci95": [round(mean - half, 4), round(mean + half, 4)], "n": n}


def build_lead_debug_artifact(
        *, problem_id: str, source_seed, sampler_seed, config: dict,
        contract: Contract, auction, dealer_i: int, vul,
        displayed_leader_hand: str, candidates, def_tricks: dict,
        softmax: dict, layouts, quality: float,
        verdict=None, source_deal: dict | None = None,
        sampling: dict | None = None, max_layouts: int = 200) -> dict:
    """Assemble the full diagnostic dict. ``source_deal`` (seat->hand) is
    stored under ``audit_only`` and never influences any number here."""
    leader_i = opening_leader_for_contract(contract)

    cand_rows = []
    for card in candidates:
        s = _stats(def_tricks.get(card, np.zeros(0)))
        cand_rows.append({
            "physical_card": card,
            "display_card": card,      # UI shows the exact physical card
            "dds_card": card,          # DDS evaluated the exact physical card
            "policy_action": policy_action(card),
            "ben_softmax": round(float(softmax.get(card, 0.0)), 4),
            **s,
        })
    cand_rows.sort(key=lambda r: (r["mean_def_tricks"] is None,
                                  -(r["mean_def_tricks"] or 0.0)))

    sample_rows = []
    for si, lay in enumerate(layouts[:max_layouts]):
        per_cand = {}
        for card in candidates:
            arr = def_tricks.get(card)
            if arr is None or si >= len(arr):
                continue
            defender = int(round(float(arr[si])))
            per_cand[card] = {
                "raw_dds_defender_tricks": defender,   # endplay native return
                "declarer_tricks": 13 - defender,
                "defender_tricks": defender,
            }
        sample_rows.append({
            "sample_index": lay.sample_index if lay.sample_index >= 0 else si,
            "sample_seed": lay.sample_seed,
            "hands_by_seat": {SEATS[i]: h for i, h in enumerate(lay.hands)},
            "accept": lay.accept,
            "per_candidate_dds": per_cand,
        })

    art = {
        "problem_id": problem_id,
        "source_seed": source_seed,
        "sampler_seed": sampler_seed,
        "config": config,
        "seat_mapping": {"order": "absolute NESW = 0,1,2,3",
                         "compass": {i: SEATS[i] for i in range(4)}},
        "auction": list(auction),
        "contract": str(contract),
        "declarer": SEATS[contract.declarer_i],
        "declarer_i": contract.declarer_i,
        "leader": SEATS[leader_i],
        "leader_i": leader_i,
        "dealer": SEATS[dealer_i],
        "vul": list(vul),
        "displayed_leader_hand": displayed_leader_hand,
        "candidate_cards": list(candidates),
        "candidates": cand_rows,
        "sampled_layouts": sample_rows,
        "n_samples": len(layouts),
        "quality": round(float(quality), 4),
        "sampling": dict(sampling or {}),
        "note": ("physical_card == display_card == dds_card for every "
                 "candidate; policy_action folds 7..2 for Ben policy ONLY. "
                 "DD means are averaged over Q(layout|info), a truncated, "
                 "uniformly-weighted neural bidding-consistency distribution "
                 "(see sampling.posterior_calibration_status), NOT a proven "
                 "bridge posterior."),
    }
    if verdict is not None:
        art["summary_ranking"] = {
            "accepted_best": list(verdict.best),
            "measured": verdict.measured,
            "flags": verdict.flags,
            "accepted": verdict.accepted,
            "reason": verdict.reason,
        }
    if source_deal is not None:
        art["audit_only"] = {
            "WARNING": "source full deal — NOT used by evaluation, for audit "
                       "only. The evaluator never receives this.",
            "full_deal": source_deal,
        }
    return art


def seed_from_id(problem_id: str) -> int:
    """'lead1-0000002a' -> 42 (the source seed encoded in the id)."""
    tail = problem_id.rsplit("-", 1)[-1]
    return int(tail, 16)


def run_lead_debug(engine, *, seed: int | None = None,
                   problem_id: str | None = None, n_samples: int = 512,
                   include_source: bool = True) -> dict:
    """Bid a board out with Ben, then produce the full diagnostic artifact for
    its opening lead. Needs the Ben engine (sampler + policy); the DDS scoring
    itself is endplay per physical card. Only public state reaches the scorer;
    the source deal is attached under ``audit_only`` only.
    """
    from .ben import cards_of, pad
    from .conventions import final_contract, opening_leader, SEATS
    from .lead_evaluate import Contract, LeadEvaluation, score_layouts
    from .lead_cards import physical_cards
    from .lead_verdict import judge_lead
    from .scanner import bid_out, VUL_NAMES

    if seed is None and problem_id is not None:
        seed = seed_from_id(problem_id)
    if seed is None:
        raise ValueError("run_lead_debug needs a seed or a problem id")
    pid = problem_id or f"lead1-{seed:08x}"

    hands, dealer_i, vul, auction = bid_out(engine, seed)
    fc = final_contract(auction, dealer_i)
    if fc is None:
        raise ValueError(f"seed {seed} was passed out; no opening lead")
    leader_i = opening_leader(fc["declarer_i"])
    hand = hands[leader_i]
    contract = Contract.from_fc(fc)

    bot = engine.lead_bot(hand, leader_i, dealer_i, vul)
    padded = pad(dealer_i, auction)
    softmax = engine.lead_softmax(bot, padded, cards_of(hand))
    layouts, quality = engine.sample_lead_layouts(
        bot, padded, leader_i, n_samples, sampler_seed=seed)

    candidates = physical_cards(hand)
    def_tricks = score_layouts(layouts, contract, candidates, check=True,
                               problem_id=pid, displayed_leader_hand=hand)
    le = LeadEvaluation(cards=candidates, def_tricks=def_tricks,
                        softmax=softmax, n_samples=len(layouts),
                        quality=quality, contract=str(contract),
                        doubled=bool(contract.doubled))
    verdict = judge_lead(le, force=bool(contract.doubled))

    return build_lead_debug_artifact(
        problem_id=pid, source_seed=seed, sampler_seed=seed,
        config={"n_samples": n_samples, "engine": engine.model_id},
        contract=contract, auction=auction, dealer_i=dealer_i,
        vul=list(vul), displayed_leader_hand=hand, candidates=candidates,
        def_tricks=def_tricks, softmax=softmax, layouts=layouts,
        quality=quality, verdict=verdict, sampling=le.sampling,
        source_deal=({SEATS[i]: h for i, h in enumerate(hands)}
                     if include_source else None))
