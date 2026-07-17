import json
from pathlib import Path

from bridge_trainer.engine.difficulty import (
    CUTS, difficulty_classification, _contested, _level)

POOL = Path(__file__).parent.parent / "data" / "problems"


def rec(*, accepted="3S", policy=None, gap=1.5, p_top=0.6, p_second=0.2,
        trap=False, flip=0.0, doubled=0.0, winner_by="EV gap >= 0.5 IMPs",
        auction=("1H", "P", "1S", "P", "2C", "P"), dealer="E", seat="W",
        half_stats=None):
    policy = policy or {"2S": 0.66, "3S": 0.49}
    # top2 is EV-ordered: the accepted call leads unless win-rate overruled
    top2 = [accepted] + [b for b in policy if b != accepted]
    if "win-rate over" in winner_by:
        top2 = top2[1:] + top2[:1]
    q = {"gap_imps": gap, "p_top_wins": p_top, "p_second_wins": p_second,
         "trap": trap, "flip": flip, "doubled_share": doubled,
         "winner_by": winner_by, "top2": top2[:2]}
    if half_stats is not None:
        q["half_stats"] = half_stats
    return {
        "quality": q,
        "verdict": {"accepted": accepted},
        "candidates": [{"call": b, "policy": p} for b, p in policy.items()],
        "auction": list(auction), "dealer": dealer, "seat": seat,
    }


def test_levels_are_monotone_in_score():
    assert _level(0) == 1
    assert _level(CUTS[0]) == 2
    assert _level(CUTS[-1]) == 5
    assert _level(100) == 5


def test_confirm_your_instinct_problem_is_easy():
    # high policy on the winner, big gap, decisive win rate, quiet auction
    r = rec(accepted="3S", policy={"3S": 0.68, "2S": 0.15, "4S": 0.17},
            gap=1.4, p_top=0.62, p_second=0.18)
    out = difficulty_classification(r)
    assert out["difficulty_level"] <= 2


def test_trap_with_close_winrates_is_hard():
    r = rec(accepted="3S", policy={"2S": 0.66, "3S": 0.49},
            gap=0.82, p_top=0.395, p_second=0.354, trap=True)
    out = difficulty_classification(r)
    assert out["difficulty_level"] >= 4


def test_trap_raises_score_vs_same_problem_untrapped():
    base = rec(trap=False)
    trapped = rec(trap=True)
    assert (difficulty_classification(trapped)["difficulty_score"]
            > difficulty_classification(base)["difficulty_score"])


def test_dissonant_ev_winner_counts_as_misleading():
    # winner wins fewer layouts than it loses ("wrong most nights")
    quiet = rec(gap=0.6, p_top=0.39, p_second=0.61)
    agree = rec(gap=0.6, p_top=0.61, p_second=0.39)
    assert (difficulty_classification(quiet)["difficulty_score"]
            > difficulty_classification(agree)["difficulty_score"])


def test_winrate_override_counts_as_misleading():
    over = rec(gap=0.16, p_top=0.387, p_second=0.492,
               winner_by="win-rate over a sub-0.5-IMP EV edge")
    plain = rec(gap=0.16, p_top=0.492, p_second=0.387,
                winner_by="win rate +10%")
    assert (difficulty_classification(over)["difficulty_score"]
            > difficulty_classification(plain)["difficulty_score"])


def test_structure_indicators_add_up():
    quiet = rec()  # opponents only pass
    busy = rec(accepted="X", policy={"X": 0.5, "4S": 0.4},
               auction=("1H", "2C", "2H", "3C", "3H", "P"),
               flip=0.5, doubled=0.3)
    assert (difficulty_classification(busy)["difficulty_score"]
            - difficulty_classification(quiet)["difficulty_score"]) >= 12


def test_contested_detection_is_relative_to_hero():
    # E deals and opens; hero W: partner E's bids are NOT contested
    assert not _contested(["1H", "P", "1S", "P"], "E", "W")
    # hero N: the same 1H by E IS an opponent's bid
    assert _contested(["1H", "P", "1S", "P"], "E", "N")


def test_boundary_guard_takes_median_of_halves():
    # score lands just above a cut; both halves say the higher level
    steady = rec(gap=0.9, p_top=0.5, p_second=0.3)
    base = difficulty_classification(steady)
    nearest_cut = min(CUTS, key=lambda c: abs(c - base["difficulty_score"]))
    assert abs(base["difficulty_score"] - nearest_cut) < 3, \
        "fixture must sit near a cut for this test"
    harder_half = {"gap_imps": 0.2, "p_top_wins": 0.41,
                   "p_second_wins": 0.39}
    guarded = difficulty_classification(
        rec(gap=0.9, p_top=0.5, p_second=0.3,
            half_stats=[harder_half, harder_half]))
    assert guarded["difficulty_level"] == base["difficulty_level"] + 1


def test_runs_on_every_published_record():
    for path in POOL.glob("*.json"):
        rec = json.loads(path.read_text())
        # difficulty_classification is bidding-specific; opening-lead records
        # carry their own 1-5 difficulty (engine/lead_verdict.py).
        if rec.get("kind") == "lead":
            continue
        out = difficulty_classification(rec)
        assert 0 <= out["difficulty_score"] <= 100
        assert 1 <= out["difficulty_level"] <= 5
