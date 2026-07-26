"""The batch maker: scan → verdict → explanations → pool, with quotas,
time budget and per-attempt logging (docs/ben_execution_plan.md §3 + v2
amendments 8, 13).

Run under the Ben venv (scripts/setup_ben.sh):
    trainer ben-forge --count 20 --pool pool_ben --seed 1
"""
from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .batch_state import BatchState
from .conventions import hero_role
from .difficulty import difficulty_classification
from .scanner import SEATS, VUL_NAMES, scan_board
from .verdict import judge, prejudge

SCREEN_SAMPLES = 128    # rejection decisions (10x more rejects than accepts)
CONFIRM_SAMPLES = 512   # published evidence: 4x the screen count, CI halved.
                        # NOT independent replication: Ben's sampler reseeds
                        # deterministically per call (hash of the hero hand),
                        # so the 512-sample confirm pool CONTAINS the screen's
                        # 128 abstract deals (~25% weight selection carryover).
                        # Changing that (e.g. perturbing the seed for confirm)
                        # is an owner-level evidence-policy decision.
PRESCREEN_SAMPLES = 32  # decisive-rejection slice of the screen pool
                        # (all candidates are evaluated on it — see
                        # forge_one — so its pairs match the full judge)

def _round_trip_ok(spot) -> bool:
    """Rec 13d: the hand we publish is the hand Ben bid for that seat."""
    return spot.hands[spot.hero_i].count(".") == 3 and \
        sum(len(p) for p in spot.hands[spot.hero_i].split(".")) == 13


def _rollout_violations(ev, verdict, spot, option_cards: dict) -> list[str]:
    """The two gates that read the ROLLOUT rather than the glosses
    (docs/4nt_projection_and_gloss_gate.md):

    R1 ``answer_insensitive_violations`` — a candidate whose rollout has
       partner answering differently on different layouts while the final
       contract never moves. The published "Leads to 6♣S 100%" then describes
       Ben's argmax continuation, not a bridge outcome.
    R3 ``forcing_contract_violations`` — a candidate the board itself calls
       forcing (or a cue-bid in their suit) that the rollout leaves in as the
       final contract, i.e. evidence drawn from a partner who passes forces.

    Both are fatal for the whole board, not for the offending option: the
    rollout that ranked every other candidate sampled the same partner (the
    argument ``forcing_pass_violations`` sets out)."""
    from .explain_check import (answer_insensitive_violations,
                                forcing_contract_violations)
    out = answer_insensitive_violations(ev, spot.stem)
    out += forcing_contract_violations(
        verdict.table, option_cards, spot.stem, spot.dealer_i, spot.hero_i,
        verdict.measured.get("n_samples") or ev.n_samples)
    return out


def build_record(spot, verdict, stem_expl, opt_expl, elapsed) -> dict:
    policy_map = dict(spot.candidates)
    rec = {
        "schema": 1,
        "kind": "bidding",
        "id": f"ben1-{spot.seed:08x}",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": {"engine": "ben BEN-21GF", "seed": spot.seed,
                      "samples": verdict.measured["n_samples"],
                      "oracle": "none", "elapsed_s": round(elapsed, 1)},
        "scoring_form": "IMPs",
        "dealer": SEATS[spot.dealer_i],
        "vul": VUL_NAMES[spot.vul],
        "seat": SEATS[spot.hero_i],
        "hand": spot.hands[spot.hero_i],
        "auction": list(spot.stem),
        "candidates": [{"call": b, "policy": round(p, 3)}
                       for b, p in spot.candidates],
        "verdict": {
            "accepted": "" if verdict.toss_up else verdict.best,
            "toss_up": verdict.toss_up,
            "toss_up_set": ([verdict.best] + verdict.toss_up_with)
            if verdict.toss_up else [],
            "flags": verdict.flags,
            "table": verdict.table,
            "dead_options": verdict.dead,
        },
        "difficulty": verdict.measured["gap_imps"],
        "quality": verdict.measured,
        "explanations": {
            "note": "call meanings follow standard 2/1 Game Force",
            "stem": stem_expl,
            "options": opt_expl,
        },
        "hero_role": hero_role(spot.stem, spot.dealer_i, spot.hero_i),
        "full_deal": {SEATS[i]: h for i, h in enumerate(spot.hands)},
        "engine_auction_complete": list(spot.full_auction),
        "policy_trail": [
            {"idx": t.idx, "seat": SEATS[t.seat_i], "chosen": t.chosen,
             "policy": [(b, round(p, 3)) for b, p in t.policy[:4]]}
            for t in spot.turns],
    }
    # graded 1-5 difficulty (docs: engine/difficulty.py); the LLM-assigned
    # problem type is attached by scripts/classify_pool.py in the same
    # generation run
    rec["classification"] = difficulty_classification(rec)
    return rec


@dataclass
class BoardOutcome:
    """Everything the batch loop needs to know about one board."""
    seed: int
    status: str                    # accepted | rejected | error
    reason: str = ""
    rec: dict | None = None
    timings: dict = field(default_factory=dict)
    detail: str = ""               # preformatted log tail (no [i/count])
    audit: dict | None = None      # prescreen audit outcome, if any


def forge_one(engine, seed: int, audit_prescreen: bool = False) -> BoardOutcome:
    """The whole per-board pipeline: scan → prescreen (decisive-rejection
    cascade on a 32-row slice, top-2 candidates) → 128-sample screen →
    menu completion (rollout-implied candidates the softmax missed) →
    512-sample confirm → explanations. Fully self-contained so the
    sequential loop and parallel workers share one implementation.

    audit_prescreen: run the full screen even when the prescreen
    rejects, recording both outcomes — the only way to MEASURE the
    prescreen's false-kill rate (a pre-rejected board is otherwise never
    escalated, so `pre_*` counters alone can't see it)."""
    import numpy as np

    from .explain import option_explanations

    t = {}
    t_board = time.perf_counter()
    try:
        spot = scan_board(engine, seed)
    except Exception as e:
        return BoardOutcome(seed, "error", "scan_error",
                            detail=f"scan error ({type(e).__name__}: {e})")
    t["scan_s"] = time.perf_counter() - t_board
    if spot is None:
        return BoardOutcome(seed, "rejected", "no_dilemma", timings=t,
                            detail=f"no dilemma [{t['scan_s']:.1f}s]")
    if not _round_trip_ok(spot):
        return BoardOutcome(seed, "rejected", "round_trip", timings=t)

    # ---- explanation-consistency gate, cheap half (engine/explain_check):
    # GIB's gloss for every stem call and offered option vs the ACTUAL
    # cards. A stem that misdescribes the hand that bid it, or an option
    # asserting specific cards the hero lacks (keycard counts, "!CQ") or
    # promising a suit the hero is 2+ cards short of,
    # kills the board before any rollout money is spent. Soft band
    # stretches (hero shades the gloss's HCP) are kept as annotations —
    # they ARE the training content. GIB fetches are cached, so the stem
    # explanations computed here are reused for the published record.
    from .explain import stem_explanations
    from .explain_check import (forcing_pass_violations, hand_violations,
                                meaningless_gloss_violations)
    from .gib_explain import card_for_auction

    stem_expl = stem_explanations(spot)
    option_cards = {b: card_for_auction(spot.stem + [b])
                    for b, _ in spot.candidates}
    fatal, soft_gloss = hand_violations(
        stem_expl, option_cards, spot.hands, spot.dealer_i, spot.hero_i)
    if fatal:
        return BoardOutcome(
            seed, "rejected", "expl_vs_hand", timings=t,
            detail="expl_vs_hand " + "; ".join(fatal[:3]) +
                   (f" (+{len(fatal) - 3} more)" if len(fatal) > 3 else ""))

    # ... and R2: an offered candidate that cannot be natural (4NT/5NT, a
    # cue-bid) whose gloss explains nothing — either empty, or a restatement
    # of what the hero's own earlier calls already showed (ben1-19f975cad49's
    # 4NT, glossed with North's 1♠ card). Cheap, auction-only, so it runs
    # before any rollout money is spent.
    gloss_bad = meaningless_gloss_violations(
        stem_expl, option_cards, spot.stem, spot.dealer_i, spot.hero_i)
    if gloss_bad:
        return BoardOutcome(seed, "rejected", "expl_meaningless", timings=t,
                            detail="expl_meaningless " + "; ".join(gloss_bad))

    # ... and the auction-only half: Pass offered while the hero's side is
    # still under a live force (ben1-19f93c01296). Rejected as a board, not
    # patched by dropping the option — the rollout behind the other calls
    # samples the same partner (see forcing_pass_violations).
    forcing_bad = forcing_pass_violations(stem_expl, option_cards,
                                          spot.dealer_i, spot.hero_i)
    if forcing_bad:
        return BoardOutcome(seed, "rejected", "forcing_pass", timings=t,
                            detail="forcing_pass " + "; ".join(forcing_bad))

    hero_bot = engine.bot(spot.hands[spot.hero_i], spot.hero_i,
                          spot.dealer_i, spot.vul)
    cand_bids = [b for b, _ in spot.candidates]
    policy_top = spot.candidates[0][0]
    dd_memo: dict = {}   # board-scoped: shared across prescreen + screen

    # ---- sample ONCE at screen size; prescreen judges a slice of it ----
    t_v = time.perf_counter()
    try:
        padded, hands_np, hands_pbn, quality = engine.sample_for_auction(
            hero_bot, spot.dealer_i, spot.stem, n_samples=SCREEN_SAMPLES)
    except Exception as e:
        return BoardOutcome(seed, "error", "evaluate_error", timings=t,
                            detail=f"evaluate error ({type(e).__name__}: {e})")

    pre_reason, n = None, hands_np.shape[0]
    if n >= 2 * PRESCREEN_SAMPLES:
        # strided slice, NOT the head: after selection Ben re-sorts
        # samples by bidding-trust score, so the head is a biased
        # (most-auction-consistent) subset
        idx = np.arange(0, n, n // PRESCREEN_SAMPLES)[:PRESCREEN_SAMPLES]
        sub_np = hands_np[idx]
        sub_pbn = [hands_pbn[i] for i in idx]
        try:
            # evaluate the FULL candidate list (not just the top-2): the
            # prescreen's best/second/ref then match the 128-sample judge's,
            # so its decisive-rejection bounds stay valid now that a lower
            # option threshold admits more low-policy candidates. The
            # shared dd_memo means the screen reuses these DD solves.
            ev_pre = engine.rollout_eval(
                hero_bot, padded, cand_bids,
                sub_np, sub_pbn, quality, dd_memo=dd_memo)
            pre_reason = prejudge(ev_pre, policy_top=policy_top,
                                  hero_i=spot.hero_i,
                                  policy_map=dict(spot.candidates))
        except Exception as e:
            return BoardOutcome(seed, "error", "evaluate_error", timings=t,
                                detail=f"prescreen error "
                                       f"({type(e).__name__}: {e})")
    t["prescreen_s"] = time.perf_counter() - t_v

    if pre_reason and not audit_prescreen:
        t["verdict_s"] = time.perf_counter() - t_v
        return BoardOutcome(
            seed, "rejected", "pre_" + pre_reason, timings=t,
            detail=f"pre_{pre_reason} "
                   f"[{t['scan_s']:.1f}+{t['prescreen_s']:.1f}s]")

    # ---- full screen: all candidates on all sampled rows (unchanged) ---
    try:
        ev = engine.rollout_eval(hero_bot, padded, cand_bids,
                                 hands_np, hands_pbn, quality,
                                 dd_memo=dd_memo)
    except Exception as e:
        return BoardOutcome(seed, "error", "evaluate_error", timings=t,
                            detail=f"evaluate error ({type(e).__name__}: {e})")

    # ---- menu completion (ben1-19f95ad149d): a final contract the menu's
    # own rollout reaches on >= COMPLETE_SHARE of some candidate's layouts,
    # declared by the hero's side and directly biddable, is a real
    # alternative the softmax under-rated below P_OPTION — 3NT at 2.35%
    # while 3♣'s rollout ended in 3NT-by-hero on 92% of layouts. Roll the
    # missing calls out on the SAME sample rows (pairing preserved, dd_memo
    # already warm) and judge the completed menu; policies come from the
    # decision turn's full softmax, so the judge's implausible_winner rule
    # still rejects a winner Ben would never actually bid. The prescreen
    # above ran on the un-completed menu: it only ever rejects, so at worst
    # a board the completed menu would have accepted is lost (recall-only,
    # the tradeoff the prescreen already makes).
    from .explain_check import menu_completion_calls
    extra = menu_completion_calls(
        {b: Counter(ev.contracts[b]) for b in ev.bids}, ev.n_samples,
        spot.stem, spot.dealer_i, spot.hero_i, cand_bids)
    if extra:
        from .ben import merge_evaluations
        extra_cards = {b: card_for_auction(spot.stem + [b]) for b in extra}
        # the same three cheap gloss gates the original options passed:
        # an added option whose card lies about the hand or explains
        # nothing makes the board unpublishable, not the option droppable
        # (without it the menu is incomplete again)
        fatal2, soft2 = hand_violations(
            stem_expl, extra_cards, spot.hands, spot.dealer_i, spot.hero_i)
        if fatal2:
            return BoardOutcome(
                seed, "rejected", "expl_vs_hand", timings=t,
                detail="expl_vs_hand (menu completion) " +
                       "; ".join(fatal2[:3]))
        gloss_bad2 = meaningless_gloss_violations(
            stem_expl, extra_cards, spot.stem, spot.dealer_i, spot.hero_i)
        if gloss_bad2:
            return BoardOutcome(
                seed, "rejected", "expl_meaningless", timings=t,
                detail="expl_meaningless (menu completion) " +
                       "; ".join(gloss_bad2))
        try:
            ev = merge_evaluations(ev, engine.rollout_eval(
                hero_bot, padded, extra, hands_np, hands_pbn, quality,
                dd_memo=dd_memo))
        except Exception as e:
            return BoardOutcome(seed, "error", "evaluate_error", timings=t,
                                detail=f"completion rollout error "
                                       f"({type(e).__name__}: {e})")
        turn_policy = {}
        for turn in spot.turns:
            if turn.idx == len(spot.stem):
                turn_policy = dict(turn.policy)
        spot.candidates = sorted(
            list(spot.candidates) +
            [(b, turn_policy.get(b, 0.0)) for b in extra],
            key=lambda bp: -bp[1])
        cand_bids = [b for b, _ in spot.candidates]
        option_cards.update(extra_cards)
        soft_gloss += soft2

    t["verdict_s"] = time.perf_counter() - t_v
    v = judge(ev, policy_top=policy_top,
              hero_i=spot.hero_i, policy_map=dict(spot.candidates))

    # ---- rollout-evidence gates (R1/R3, docs/4nt_projection_and_gloss_gate
    # .md). Pure python over evidence already in hand, so they run here on the
    # screen — killing the board before the confirm and band passes — and
    # again on the confirm evidence below, which is what gets published.
    rollout_bad = _rollout_violations(ev, v, spot, option_cards)
    if rollout_bad:
        return BoardOutcome(seed, "rejected", "rollout_evidence", timings=t,
                            detail="rollout_evidence " +
                                   "; ".join(rollout_bad[:2]))

    audit = None
    if pre_reason:                  # audit mode: compare the two verdicts
        audit = {"pre_reason": pre_reason,
                 "screen_reason": v.reason,
                 "false_kill": bool(v.accepted)}
    if not v.accepted:
        return BoardOutcome(
            seed, "rejected", v.reason, timings=t, audit=audit,
            detail=f"{v.reason} gap={v.measured.get('gap_imps')}"
                   f" ci={v.measured.get('ci')}"
                   f" [{t['scan_s']:.1f}+{t['verdict_s']:.1f}s]")

    # ---- explanation-consistency gate, expensive half: Ben's MEASURED
    # meaning of each stem call AND each offered candidate (sampled
    # layouts) vs GIB's gloss. Catches conventions GIB narrates as
    # something else entirely (Leaping Michaels glossed as a natural club
    # overcall; a natural invitational 2NT glossed as a minor transfer).
    # Runs only here — on boards the statistical judge already accepted —
    # so its sampling cost lands on ~1 board in 12.
    from .explain_check import band_violations
    try:
        band_bad = band_violations(engine, spot, stem_expl, option_cards)
    except Exception as e:
        return BoardOutcome(seed, "error", "expl_band_error", timings=t,
                            detail=f"band check error "
                                   f"({type(e).__name__}: {e})")
    if band_bad:
        return BoardOutcome(
            seed, "rejected", "expl_vs_band", timings=t, audit=audit,
            detail="expl_vs_band " + "; ".join(band_bad[:3]) +
                   (f" (+{len(band_bad) - 3} more)"
                    if len(band_bad) > 3 else ""))

    # ---- confirm at 4x samples: the published evidence (see the note
    # at CONFIRM_SAMPLES: a superset re-evaluation, not fresh samples;
    # its PBNs differ from the screen's, so dd_memo gets ~no hits here
    # and is passed only for uniformity) ----
    t_c = time.perf_counter()
    try:
        ev = engine.evaluate(hero_bot, spot.dealer_i, spot.stem, cand_bids,
                             n_samples=CONFIRM_SAMPLES, dd_memo=dd_memo)
    except Exception as e:
        return BoardOutcome(seed, "error", "confirm_error", timings=t,
                            audit=audit,
                            detail=f"confirm error ({type(e).__name__}: {e})")
    t["confirm_s"] = time.perf_counter() - t_c
    v = judge(ev, policy_top=policy_top,
              hero_i=spot.hero_i, policy_map=dict(spot.candidates))
    if not v.accepted:
        return BoardOutcome(
            seed, "rejected", "confirm_" + v.reason, timings=t, audit=audit,
            detail=f"confirm_{v.reason} gap={v.measured.get('gap_imps')} "
                   f"[{t['confirm_s']:.1f}s]")

    # the same two rules on the evidence that will actually be published: the
    # confirm pool is 4x bigger, so a candidate whose answer-insensitivity or
    # passed-out force only shows up at 512 layouts still dies here
    rollout_bad = _rollout_violations(ev, v, spot, option_cards)
    if rollout_bad:
        return BoardOutcome(
            seed, "rejected", "confirm_rollout_evidence", timings=t,
            audit=audit,
            detail="confirm_rollout_evidence " + "; ".join(rollout_bad[:2]))

    # ---- invitation gate: an option GIB glosses as an invitation whose
    # rollout gives partner no decision — the invited level reached on
    # every layout, or on none while the winner gets there and the
    # invitation is charged for missing it (ben1-19f947b9723). Free (it
    # counts the confirm rollout's own contracts) and run on the PUBLISHED
    # evidence, so what the gate judges is exactly what the board shows.
    # Distinct from R1 above: that rule asks whether the rollout DISCARDED
    # partner's answer, this one whether the displayed MEANING of the call
    # survives what partner did with it (a partner with one action passes
    # R1 and can still be refusing an invitation the board narrates).
    from .explain_check import invite_violations
    invite_bad = invite_violations(
        option_cards, v.table, v.best, spot.hero_i,
        v.measured["n_samples"],
        dists={b: Counter(ev.contracts[b]) for b in ev.bids})
    if invite_bad:
        return BoardOutcome(
            seed, "rejected", "invite_vs_rollout", timings=t, audit=audit,
            detail="invite_vs_rollout " + "; ".join(invite_bad))

    t_e = time.perf_counter()
    opt_expl = option_explanations(spot, v, dict(spot.candidates), ev=ev)
    t["explain_s"] = time.perf_counter() - t_e

    elapsed = time.perf_counter() - t_board
    rec = build_record(spot, v, stem_expl, opt_expl, elapsed)
    if soft_gloss:
        # kept, not fatal: options whose GIB band the hero's hand shades
        # (see explain_check.hand_violations) — available to the UI as
        # "this call overstates/understates your hand" annotations.
        rec["explanations"]["option_gloss_flags"] = soft_gloss
    verdict_txt = ("toss-up " + "/".join(rec["verdict"]["toss_up_set"])
                   ) if v.toss_up else v.best
    detail = (f"ACCEPTED {rec['id']} "
              f"hero {rec['seat']} after {' '.join(spot.stem) or '(opening)'} "
              f"cands={cand_bids} verdict={verdict_txt} "
              f"gap={v.measured['gap_imps']} "
              f"[scan {t['scan_s']:.1f}s screen {t['verdict_s']:.1f}s "
              f"confirm {t['confirm_s']:.1f}s expl {t['explain_s']:.1f}s]")
    return BoardOutcome(seed, "accepted", "accepted", rec=rec, timings=t,
                        audit=audit, detail=detail)


class _BatchState(BatchState):
    """Bidding-batch aggregation (shared core in engine/batch_state.py).
    Logs every board, tracks vul/role/contested quotas, and audits the
    prescreen. Kept as _BatchState — parallel.py imports it by that name."""

    boards_key = "boards_scanned"

    def _init_quotas(self) -> None:
        self.quotas = {"vuls": Counter(), "roles": Counter(), "contested": 0}
        self.audits = {"pre_rejects_audited": 0, "false_kills": 0}

    def _absorb_extra(self, out: BoardOutcome) -> None:
        if out.audit:
            self.audits["pre_rejects_audited"] += 1
            self.audits["false_kills"] += out.audit["false_kill"]

    def _on_reject(self, out: BoardOutcome, tag: str) -> None:
        if out.detail:
            self.log(f"  {tag}seed {out.seed}: {out.detail}")

    def _on_accept(self, out: BoardOutcome, rec, tag: str) -> None:
        self.quotas["vuls"][rec["vul"]] += 1
        self.quotas["roles"][rec["hero_role"]] += 1
        stem, dealer = rec["auction"], SEATS.index(rec["dealer"])
        hero = SEATS.index(rec["seat"])
        self.quotas["contested"] += 1 if any(
            tok != "P" for i, tok in enumerate(stem)
            if (dealer + i) % 4 not in (hero, (hero + 2) % 4)) else 0
        self.log(f"  {tag}seed {out.seed}: "
                 + out.detail.replace(
                     "ACCEPTED " + rec["id"],
                     f"ACCEPTED {rec['id']} [{len(self.made)}/{self.count}]",
                     1))

    def _mix(self) -> dict:
        return {"vuls": dict(self.quotas["vuls"]),
                "roles": dict(self.quotas["roles"]),
                "contested": self.quotas["contested"]}

    def _summary_extra(self, summary: dict) -> None:
        if self.audits["pre_rejects_audited"]:
            summary["prescreen_audit"] = dict(self.audits)


def forge_batch(pool_dir: str, count: int, base_seed: int,
                max_seconds: float = 3600.0, log=print,
                workers: int = 1, audit_prescreen: bool = False) -> dict:
    # Resolve the pool BEFORE engine init: BenEngine chdir's into the ben
    # source tree, so a relative pool path would land there.
    import os
    pool_dir = os.path.abspath(pool_dir)

    if workers == 0:
        # auto: each worker holds a ~1.2 GB engine — stay conservative
        # (the 7 GB CI runner OOMs at 4) unless told explicitly
        workers = max(1, min(3, os.cpu_count() or 1))
    if workers > 1:
        from .parallel import forge_batch_parallel
        return forge_batch_parallel(pool_dir, count, base_seed, max_seconds,
                                    log, workers, audit_prescreen)

    from .ben import get_engine

    t_load = time.perf_counter()
    engine = get_engine()
    log(f"engine loaded in {time.perf_counter() - t_load:.1f}s")

    state = _BatchState(pool_dir, count, log)
    t0 = time.perf_counter()
    k = 0
    while len(state.made) < count and time.perf_counter() - t0 < max_seconds:
        state.absorb(forge_one(engine, base_seed + k, audit_prescreen))
        k += 1

    wall = time.perf_counter() - t0
    summary = state.summary(wall)
    log(f"\nDone: {len(state.made)}/{count} in {wall / 60:.1f} min "
        f"({summary['per_accepted_s']}s per accepted deal); "
        f"scanned {k} boards; rejections: {summary['rejections']}")
    return summary
