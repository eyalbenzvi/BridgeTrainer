"""Harvester spike: 10 problems from real 2017 world-championship auctions.

Pipeline per problem: real deal + real auction stem (from vugraph LIN, both
rooms) -> hand-authored call meanings (the future LLM-finalization step,
done by hand for this spike) -> existing rejection sampler deals hidden
hands -> each candidate maps to the FINAL CONTRACT its room actually
reached -> DD judges (existing evaluator/comparison stack, INV1-INV8).

Run: python scripts/spike_harvest.py <lin_dir> <out_pool_dir>
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from bridge_trainer import __version__ as trainer_version
from bridge_trainer.dd.correction import load_default_correction
from bridge_trainer.dealing.rejection import RejectionDealSource
from bridge_trainer.domain.auction import SEATS
from bridge_trainer.domain.constraints import Band, ConstraintProfile, SeatConstraints
from bridge_trainer.domain.interfaces import GenerationBudget
from bridge_trainer.harvest.lin import find_divergences, parse_lin
from bridge_trainer.pool.store import SCHEMA_VERSION, ProblemPool
from bridge_trainer.scoring.comparison import compare_candidates
from bridge_trainer.scoring.evaluate import ScoreEvaluator

N_DEALS = 600


def bands(core, *margins):
    out = [Band(core[0], core[1], 1.0)]
    for lo, hi, w in margins:
        out.append(Band(lo, hi, w))
    return out


# ---------------------------------------------------------------------------
# The 10 selected problems. `meanings`: seat -> (hcp bands, suit bands,
# note). This is the hand-authored stand-in for the LLM finalization call.
# Conventions at world level vary; meanings are standard-ish and DISCLOSED.
# ---------------------------------------------------------------------------
SELECTION = [
    dict(
        lin="50022", board=21, note="5-level decision over their save",
        explanation=(
            "Partner's 1H and your 4H put the auction in forcing-pass "
            "territory; E's 4S is a two-way save. With a singleton spade and "
            "prime cards (two aces-worth in the blacks, KQ of trumps) the "
            "field question is take the penalty or bid on — and the "
            "simulation confirms a genuine coin-flip: partner's range is "
            "capped by the 1H response, so the penalty and the 11-trick "
            "game both hinge on exactly where his cards sit."),
        meanings={
            "S": ("6-12 HCP, 4+ hearts (1H response, then a forcing pass)",
                  bands((6, 12), (13, 13, 0.4)), {"H": bands((4, 6))}),
            "W": ("weak jump overcall: 6-7 spades, 3-9 HCP",
                  bands((3, 9), (10, 10, 0.4)), {"S": bands((6, 7))}),
            "E": ("passed hand raising to 4S: spade fit, shapely, 4-11 HCP",
                  bands((4, 11)), {"S": bands((3, 5))}),
        },
    ),
    dict(
        lin="50020", board=20, note="raising partner's forced advance",
        explanation=(
            "Partner's 1H over your takeout double promised nothing — 0-8 "
            "with four hearts is the expectation. With a flat 14 and only "
            "four trumps the raise is a pure pressure bid: the simulation "
            "measures whether pushing to 2H (and sometimes higher) beats "
            "selling to 2D."),
        meanings={
            "E": ("3rd-seat 1D opening then 2D rebid: 10-16, 5+ diamonds",
                  bands((10, 16), (9, 9, 0.4)), {"D": bands((5, 7))}),
            "N": ("forced 1H advance of the double: 0-8 HCP, 4+ hearts",
                  bands((0, 8), (9, 9, 0.5)), {"H": bands((4, 6),
                                                          (3, 3, 0.3))}),
            "W": ("passed throughout: 0-9 HCP",
                  bands((0, 9), (10, 10, 0.4)), {}),
        },
    ),
    dict(
        lin="50023", board=32, note="balancing against their runout",
        explanation=(
            "They escaped partner's strong NT into 2S and it's about to be "
            "passed out. With 6 points and no spade wastage the classic "
            "balancing X protects partner's trap-pass hands; the risk is "
            "converting a plus defense into -X. The simulation prices "
            "exactly that trade."),
        meanings={
            "N": ("strong 1NT: 15-17 balanced",
                  bands((15, 17)), {s: bands((2, 5)) for s in "SHDC"}),
            "E": ("2D showing both majors, sub-opening values",
                  bands((5, 12), (13, 13, 0.3)),
                  {"S": bands((4, 6)), "H": bands((4, 6))}),
            "W": ("passed hand taking a 2S preference: 0-7 HCP, 2-4 spades",
                  bands((0, 7), (8, 8, 0.4)), {"S": bands((2, 4))}),
        },
    ),
    dict(
        lin="50022", board=20, note="opener's competitive rebid",
        explanation=(
            "RHO doubled and advancer jumped to 2H; with a sound 14 and "
            "KQJT96 of diamonds the choice is a free 3D or a disciplined "
            "pass. 3D is textbook shape-wise, but at Both the simulation "
            "asks whether it mostly pushes them into a making game."),
        meanings={
            "S": ("takeout double of 1D: 12+ HCP, short diamonds, both majors",
                  bands((12, 20), (11, 11, 0.4)),
                  {"D": bands((0, 2), (3, 3, 0.3)), "S": bands((3, 5)),
                   "H": bands((3, 5))}),
            "N": ("2H jump advance: 9-11 HCP, 4-5 hearts",
                  bands((9, 11), (8, 8, 0.4), (12, 12, 0.4)),
                  {"H": bands((4, 5))}),
            "W": ("passed throughout incl. over the double: 0-9",
                  bands((0, 9), (10, 10, 0.4)), {}),
        },
    ),
    dict(
        lin="50006", board=27, note="cooperating below slam",
        explanation=(
            "Partner's 4C over their weak-two interference is a serious "
            "club hand. Your AQJxxx of diamonds and spade ace are huge "
            "cards; 4D (showing where your values are) against the direct "
            "4S cue is a classic style split — the deep question is whether "
            "the extra information reaches slam more often than it wrong-"
            "sides the auction."),
        meanings={
            "S": ("weak 2S: 5-10 HCP, 6 spades",
                  bands((5, 10), (4, 4, 0.3), (11, 11, 0.3)),
                  {"S": bands((6, 6), (5, 5, 0.2))}),
            "N": ("passed over 3D: 0-8 HCP",
                  bands((0, 8), (9, 10, 0.4)), {}),
            "E": ("4C: natural strong clubs, slam interest: 13+ HCP, 6+ clubs",
                  bands((13, 20), (12, 12, 0.4)), {"C": bands((6, 8))}),
        },
    ),
    dict(
        lin="50021", board=27, note="setting up the giant hand",
        explanation=(
            "Twenty points, seven solid-ish diamonds, and both black aces "
            "after partner's 1D was overcalled 1S and doubled back to you. "
            "The single cue (2S) keeps room; the jump cue (3S) forces to "
            "game immediately. The simulation compares where each actually "
            "landed the pair — 3NT versus 5D."),
        meanings={
            "N": ("1S overcall: 8-16 HCP, 5-7 spades",
                  bands((8, 16), (7, 7, 0.5), (17, 17, 0.4)),
                  {"S": bands((5, 7))}),
            "E": ("negative double: 6+ HCP, 4+ hearts, short spades",
                  bands((6, 14)), {"H": bands((4, 6)), "S": bands((0, 3))}),
            "S": ("passed twice: 0-8 HCP",
                  bands((0, 8), (9, 10, 0.4)), {}),
        },
    ),
    dict(
        lin="50000", board=16, note="support double or pass",
        explanation=(
            "Both sides are feeling for a fit at the one level. With a "
            "flat 13 and only three-card diamond support, X (support-"
            "double style, showing exactly three) against Pass is a pure "
            "agreement-and-judgment question; the simulation prices the "
            "part-score war it starts."),
        meanings={
            "E": ("1D response: 6+ HCP, 4+ diamonds",
                  bands((6, 14), (5, 5, 0.4)), {"D": bands((4, 6))}),
            "S": ("1S overcall: 8-16 HCP, 5-7 spades",
                  bands((8, 16), (7, 7, 0.5)), {"S": bands((5, 7))}),
            "N": ("passed over 1C: 0-10 HCP",
                  bands((0, 10), (11, 11, 0.4)), {}),
        },
    ),
    dict(
        lin="50015", board=8, note="freak hand vs their preemptive jump",
        explanation=(
            "A seven-card heart suit, a spade void, and they jump to 4S "
            "over partner's 1NT response. 4NT (two places to play) risks "
            "-500 against a partial; Pass lets 4S play. World-class tables "
            "split exactly here, and the actual result was brutal — the "
            "simulation shows how often the save actually pays."),
        meanings={
            "E": ("1NT response to 1H: 5-11 HCP, at most 3 spades",
                  bands((5, 11), (12, 12, 0.3)), {"S": bands((0, 4))}),
            "S": ("4S jump: 7-8 spades, preemptive playing strength",
                  bands((5, 12), (13, 13, 0.3)), {"S": bands((7, 8),
                                                             (6, 6, 0.3))}),
            "N": ("passed over 1H: 0-11 HCP",
                  bands((0, 11), (12, 13, 0.3)), {}),
        },
    ),
    dict(
        lin="50021", board=20, note="how high to advance the double",
        explanation=(
            "Five hearts to the ace-ten and 8 points opposite a takeout "
            "double: the single-level 1H keeps the auction low but hides "
            "the hand; the jump to 2H invites with the fit. A world-class "
            "field split — and note the paradox in the real results: the "
            "underbidding table was pushed higher later."),
        meanings={
            "E": ("3rd-seat 1D opening: 10-19 HCP, 3+ diamonds",
                  bands((10, 19), (9, 9, 0.3)), {"D": bands((3, 6))}),
            "S": ("takeout double of 1D: 12+ HCP, short diamonds, both majors",
                  bands((12, 20), (11, 11, 0.4)),
                  {"D": bands((0, 2), (3, 3, 0.3)), "S": bands((3, 5)),
                   "H": bands((3, 5))}),
            "W": ("passed throughout: 0-9 HCP",
                  bands((0, 9), (10, 10, 0.4)), {}),
        },
    ),
    dict(
        lin="50009", board=29, note="advancing with a misfit",
        explanation=(
            "Partner overcalls 1H on your singleton. With 11 points and "
            "both minors guarded the choice between the flexible 1S and "
            "the descriptive 1NT is a real style question — and the rooms' "
            "auctions drifted to very different club partials."),
        meanings={
            "S": ("3rd-seat 1D opening: 10-19 HCP, 3+ diamonds",
                  bands((10, 19), (9, 9, 0.3)), {"D": bands((3, 6))}),
            "W": ("1H overcall: 8-16 HCP, 5-7 hearts",
                  bands((8, 16), (7, 7, 0.5)), {"H": bands((5, 7))}),
            "N": ("passed twice: 0-10 HCP",
                  bands((0, 10), (11, 11, 0.3)), {}),
        },
    ),
]


def build_problem(div, spec) -> dict:
    hero = div.hero
    profile = ConstraintProfile(seats={})
    meanings_out = []
    for seat, (note, hcp_bands, suit_bands) in spec["meanings"].items():
        assert seat != hero
        profile.seats[seat] = SeatConstraints.from_bands(
            hcp=hcp_bands, suits=suit_bands)
        meanings_out.append({"seat": seat, "meaning": note})

    seed = int(spec["lin"]) * 100 + spec["board"]
    source = RejectionDealSource(my_seat=hero)
    deals, diag = source.generate(
        div.hands[hero], profile, N_DEALS, seed=seed,
        budget=GenerationBudget(max_attempts=6_000_000, max_seconds=20.0))
    if len(deals) < 150:
        raise RuntimeError(
            f"{spec['lin']}/bd{spec['board']}: only {len(deals)} deals "
            f"(meanings too tight?)")

    cand_contracts = {div.calls["o"]: div.contracts["o"],
                      div.calls["c"]: div.contracts["c"]}
    contracts_by_candidate = {c: [fc] * len(deals)
                              for c, fc in cand_contracts.items()}
    evaluator = ScoreEvaluator(hero, div.vul, load_default_correction())
    evaluator.prepare(deals, contracts_by_candidate)
    weights = np.array([wd.weight for wd in deals])
    raw_s, corr_s = {}, {}
    for cand, contracts in contracts_by_candidate.items():
        raw_s[cand], corr_s[cand] = evaluator.evaluate(deals, contracts)
    widen = float(np.sqrt(N_DEALS / len(deals))) if diag.shortfall else 1.0
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
    top = corr.candidates[0]
    return {
        "schema": SCHEMA_VERSION,
        "id": f"h{spec['lin']}-{spec['board']}",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": {"kind": "harvest_spike", "lin_id": spec["lin"],
                      "n_deals": len(deals), "seed": seed,
                      "trainer_version": trainer_version},
        "dealer": div.dealer, "vul": div.vul, "seat": hero,
        "hand": div.hands[hero],
        "auction": list(div.stem),
        "candidates": list(cand_contracts),
        "verdict": {
            "accepted": accepted, "toss_up": corr.toss_up,
            "fog": (raw.toss_up != corr.toss_up or raw.verdict != corr.verdict),
            "corrected": rows(corr), "raw": rows(raw),
        },
        "difficulty": round(float(top.ev_vs_best_alt), 3),
        "quality": {"ess": round(diag.effective_sample_size, 1),
                    "acceptance": round(diag.acceptance_rate, 6),
                    "shortfall": diag.shortfall},
        "explanation": spec["explanation"],
        "source": {
            "event": div.event, "teams": div.teams, "board": div.number,
            "room_calls": dict(div.calls),
            "room_contracts": {r: str(fc) for r, fc in div.contracts.items()},
            "room_results": dict(div.results),
        },
        "meanings": meanings_out,
        "full_deal": dict(div.hands),
    }


def main(lin_dir: str, out_dir: str) -> None:
    lin_dir = Path(lin_dir)
    pool = ProblemPool(out_dir)
    for spec in SELECTION:
        text = (lin_dir / f"{spec['lin']}.lin").read_text(errors="replace")
        divs = {d.number: d for d in find_divergences(parse_lin(text))}
        div = divs[spec["board"]]
        rec = build_problem(div, spec)
        pool.add(rec)
        v = rec["verdict"]
        verdict = ("toss-up " + "/".join(v["accepted"])) if v["toss_up"] \
            else v["accepted"][0]
        print(f"{rec['id']}: ({' '.join(rec['auction'])}) ? "
              f"{rec['candidates']} -> {verdict} gap={rec['difficulty']} "
              f"ess={rec['quality']['ess']}")
    pool.rebuild_index()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
