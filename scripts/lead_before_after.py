"""Before(legacy 32-code folding)/after(fixed physical-card) opening-lead audit
for suspect boards. Reconstructs each board with Ben (bid-out), then for a
threshold sweep runs the production `current` sampler, DD-solves the shared
layouts, and compares the legacy-folded ranking to the physical ranking plus
ace-vs-best-non-ace tail/strata diagnostics. Saves reproducible JSON per board.

Run:  BEN_HOME=/home/user/ben /home/user/benv/bin/python \
        scripts/lead_before_after.py 02faf4ff 03473cc7 --out /abs/output
Real code/results only; no assumption that the ace is wrong.
"""
from __future__ import annotations

import argparse
import json
import sys

import numpy as np

from bridge_trainer.engine.ben import get_engine
from bridge_trainer.engine.scanner import bid_out, VUL_NAMES
from bridge_trainer.engine.conventions import (
    SEATS, final_contract, opening_leader, contract_str)
from bridge_trainer.engine.lead_posterior import (
    build_problem, evaluate_layouts, legacy_folded_eval, compare_pipelines,
    delta_report, is_tail_dominated, strata_report, quality_flag,
    card_level_audit, result_signature, problem_fingerprint)
from bridge_trainer.engine.lead_samplers import BenCurrentSampler

THRESHOLDS = [0.70, 0.75, 0.80, 0.85, 0.90]


def _json_default(o):
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def audit_board(engine, hexid: str, samples: int, seed: int, n_boot: int):
    s = int(hexid, 16)
    hands, dealer_i, vul, auction = bid_out(engine, s)
    fc = final_contract(auction, dealer_i)
    if fc is None:
        return {"id": f"lead1-{hexid}", "status": "passed_out"}
    leader_i = opening_leader(fc["declarer_i"])
    hand = hands[leader_i]
    contract = contract_str(fc)
    problem = build_problem(hand, auction, SEATS[dealer_i], VUL_NAMES[vul],
                            contract)
    # the ace(s) the leader holds
    aces = [su + "A" for su in "SHDC" if "A" in hand.split(".")["SHDC".index(su)]]

    out = {
        "id": f"lead1-{hexid}",
        "public_state": {
            "hand": hand, "auction": auction, "dealer": SEATS[dealer_i],
            "vul": VUL_NAMES[vul], "contract": contract,
            "declarer": problem.declarer, "leader": problem.leader,
            "fingerprint": problem_fingerprint(problem, seed),
        },
        "aces_held": aces,
        "thresholds": {},
    }

    reports_for_flag = {}
    sweep_winner_fixed, sweep_winner_legacy, sweep_gap = {}, {}, {}
    for thr in THRESHOLDS:
        sampler = BenCurrentSampler(engine=engine, threshold=thr)
        ls = sampler.sample(problem, samples, seed)
        fixed = evaluate_layouts(ls)
        legacy = legacy_folded_eval(fixed, seed=seed)

        cmp = compare_pipelines(problem, ls, fixed, legacy, n_boot=n_boot,
                                seed=seed)
        # determinism: resample + regrade, compare signatures
        ls2 = sampler.sample(problem, samples, seed)
        det = result_signature(evaluate_layouts(ls2), ls2) == \
            result_signature(fixed, ls)

        # ace vs best non-ace (fixed pipeline)
        m = fixed.weighted_mean()
        ace = aces[0] if aces else None
        best_non_ace = None
        ace_delta = None
        if ace:
            non = [c for c in fixed.cards if c != ace]
            best_non_ace = max(non, key=lambda c: m[c])
            ace_delta = delta_report(fixed.def_tricks[ace],
                                     fixed.def_tricks[best_non_ace],
                                     weight=ls.weight, n_boot=n_boot, seed=seed)

        best, runner = cmp["fixed"]["winner"], cmp["fixed"]["runner_up"]
        strata = strata_report(problem, ls, fixed, best, runner)
        loso_changes = _loso_summary(strata)
        card_audit = card_level_audit(ls, fixed,
                                      focus=([ace, best_non_ace] if ace else None))

        br = delta_report(fixed.def_tricks[best], fixed.def_tricks[runner],
                          weight=ls.weight, n_boot=n_boot, seed=seed)
        reports_for_flag[f"current@{thr:.2f}"] = {
            "winner": best, "delta_report": br}

        sweep_winner_fixed[thr] = best
        sweep_winner_legacy[thr] = cmp["legacy"]["winner"]
        sweep_gap[thr] = cmp["fixed"]["gap"]

        out["thresholds"][f"{thr:.2f}"] = {
            "provenance": ls.provenance(),
            "deterministic_repeat": det,
            "legacy_vs_fixed": cmp,
            "ace_vs_best_non_ace": {
                "ace": ace, "best_non_ace": best_non_ace,
                "ace_mean": round(m[ace], 4) if ace else None,
                "best_non_ace_mean": round(m[best_non_ace], 4) if best_non_ace else None,
                "delta": ace_delta,
                "tail_dominated": is_tail_dominated(ace_delta) if ace_delta else None,
            },
            "best_vs_runner_delta": br,
            "tail_dominated": is_tail_dominated(br),
            "strata_score_bins": strata["stratifiers"]["score_bin"]["rows"],
            "strata_missing_key_honor_top": sorted(
                strata["stratifiers"]["missing_key_honor"]["rows"],
                key=lambda r: -abs(r["delta_contribution"]))[:6],
            "leave_one_stratum_out_winner_changes": loso_changes,
            "card_level_audit": card_audit,
        }

    out["sweep"] = {
        "winner_fixed_by_threshold": {f"{t:.2f}": sweep_winner_fixed[t]
                                      for t in THRESHOLDS},
        "winner_legacy_by_threshold": {f"{t:.2f}": sweep_winner_legacy[t]
                                       for t in THRESHOLDS},
        "gap_fixed_by_threshold": {f"{t:.2f}": round(sweep_gap[t], 4)
                                   for t in THRESHOLDS},
        "winner_stable_across_thresholds":
            len(set(sweep_winner_fixed.values())) == 1,
    }
    out["quality_flag"] = quality_flag(reports_for_flag)
    # cross-check vs Ben's OWN production lead_evaluate (true legacy path)
    out["ben_native_lead_evaluate"] = _ben_native(engine, problem, hands,
                                                  leader_i, dealer_i, vul,
                                                  auction, fc, contract)
    return out


def _loso_summary(strata):
    changes = {}
    for name, blk in strata["stratifiers"].items():
        flips = [lo for lo in blk["leave_one_out"] if lo["best_changed"]]
        changes[name] = {"any_winner_flip": bool(flips),
                         "flips": flips[:3]}
    return changes


def _ben_native(engine, problem, hands, leader_i, dealer_i, vul, auction, fc,
                contract):
    """Ben's own production opening-lead grade (32-code folded, its own DDS and
    averaging) for cross-validation of the fixed winner."""
    try:
        le = engine.lead_evaluate(
            hands[leader_i], leader_i, dealer_i, vul, auction,
            fc["denom"], contract, bool(fc["doubled"]), n_samples=300)
        avg = {c: float(np.mean(le.def_tricks[c])) for c in le.cards}
        order = sorted(le.cards, key=lambda c: -avg[c])
        return {"n_samples": le.n_samples,
                "winner": order[0], "runner_up": order[1],
                "top": [{"card": c, "avg_def_tricks": round(avg[c], 4),
                         "ben_softmax": round(le.softmax.get(c, 0.0), 4)}
                        for c in order[:6]]}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="+")
    ap.add_argument("--samples", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--out", default=".")
    args = ap.parse_args(argv)
    engine = get_engine()
    rows = []
    for hexid in args.ids:
        res = audit_board(engine, hexid, args.samples, args.seed, args.n_boot)
        path = f"{args.out}/lead1-{hexid}.before_after.json"
        with open(path, "w") as f:
            json.dump(res, f, indent=2, default=_json_default)
        print(f"wrote {path}")
        rows.append(res)
    # summary table
    print("\n" + "=" * 118)
    print("%-16s %-8s %-8s %-8s %-14s %-10s %-9s %-9s %-16s %s" % (
        "Board", "Before", "After", "Changed", "gap b/a@.70", "AceMapBug",
        "SrcLeak", "TailDom", "Thr/Samp-sens", "Quality"))
    print("=" * 118)
    for r in rows:
        if r.get("status") == "passed_out":
            print(r["id"], "passed out"); continue
        t70 = r["thresholds"]["0.70"]
        cmp = t70["legacy_vs_fixed"]
        before, after = cmp["legacy"]["winner"], cmp["fixed"]["winner"]
        changed = cmp["winner_changed"]
        gap_b, gap_a = cmp["gap_legacy"], cmp["gap_fixed"]
        ca = t70["card_level_audit"]
        # ace-mapping bug in the fixed engine iff candidates are not 13-distinct
        # or an ace-suit low card shares an aggregation slot (never, by design)
        idxs = {row["candidate"]: row["aggregation_index"]
                for row in ca["candidate_to_index"]}
        ace_bug = (not ca["all_distinct"]) or ca["n_candidates"] != 13 \
            or len(set(idxs.values())) != len(idxs)
        srcleak = not t70["provenance"]["source_deal_independent"]
        taildom = t70["ace_vs_best_non_ace"]["tail_dominated"]
        thr_sens = not r["sweep"]["winner_stable_across_thresholds"]
        print("%-16s %-8s %-8s %-8s %-14s %-10s %-9s %-9s %-16s %s" % (
            r["id"], before, after, str(changed),
            f"{gap_b:+.2f}/{gap_a:+.2f}", str(ace_bug), str(srcleak),
            str(taildom), str(thr_sens), r["quality_flag"]))
    return 0




if __name__ == "__main__":
    sys.exit(main())
