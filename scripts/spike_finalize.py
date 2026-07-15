"""Finalized-problem demo batch: real championship deals, multi-option
dilemmas, per-layout continuations.

Each entry pairs a real spot (deal + auction stem from vugraph) with a
hand-authored FINALIZATION DOCUMENT (see bridge_trainer/finalize/schema.py)
— 2-5 options a strong player would weigh, meanings for the concealed
hands, and a continuation policy per option so the hero's call is NOT the
end of the auction (doubles, raises, saves happen per layout). DD judges.

Run: python scripts/spike_finalize.py <lin_dir> <out_pool_dir>
"""
from __future__ import annotations

import sys
from pathlib import Path

from bridge_trainer.finalize.schema import build_record
from bridge_trainer.harvest.lin import find_divergences, parse_lin
from bridge_trainer.pool.store import ProblemPool


def H(lo, hi, *margins):  # meaning band helper
    return [lo, hi, [list(m) for m in margins]]


BATCH = [
    # ------------------------------------------------------------------ P1
    dict(lin="50022", board=21, doc=dict(
        dilemma=True,
        options=["X", "P", "5H", "5C"],
        meanings={
            "S": {"note": "1H response then a forcing pass: 6-12, 4+ hearts",
                  "hcp": H(6, 12, (13, 13, 0.4)), "suits": {"H": H(4, 6)}},
            "W": {"note": "weak jump overcall: 3-9, 6-7 spades",
                  "hcp": H(3, 9, (10, 10, 0.4)), "suits": {"S": H(6, 7)}},
            "E": {"note": "passed-hand save raise: 4-11, 3-5 spades",
                  "hcp": H(4, 11), "suits": {"S": H(3, 5)}},
        },
        projections={
            "X": [
                {"when": "partner_hearts >= 7", "contract": "5HS"},
                {"else": {"contract": "4SWx"}},
            ],
            # Forcing pass: PARTNER decides — double with balanced defence,
            # pull with extreme shape. Your call is not the auction's end.
            "P": [
                {"when": "partner_hearts >= 6 and partner_spades <= 1",
                 "contract": "5HS"},
                {"else": {"contract": "4SWx"}},
            ],
            "5H": [
                {"when": "opps_combined_spades >= 11", "contract": "6SWx"},
                {"when": "opps_combined_hcp >= 16", "contract": "5HSx"},
                {"else": {"contract": "5HS"}},
            ],
            "5C": [
                {"when": "partner_clubs >= 5", "contract": "5CN"},
                {"else": {"contract": "5HS"}},
            ],
        },
        explanation=(
            "A forcing-pass position: X takes the sure plus, Pass hands "
            "partner the decision (he doubles with defence, pulls with "
            "shape), and the five-level bids commit — 5C offering a choice "
            "of strains. The simulation prices all four against each "
            "other; at this vulnerability the margin is razor-thin."),
    )),
    # ------------------------------------------------------------------ P2
    dict(lin="50020", board=20, doc=dict(
        dilemma=True,
        options=["P", "2H", "3H", "X"],
        meanings={
            "E": {"note": "3rd-seat 1D then 2D rebid: 10-16, 5+ diamonds",
                  "hcp": H(10, 16, (9, 9, 0.4)), "suits": {"D": H(5, 7)}},
            "N": {"note": "forced 1H over the double: 0-8, 4+ hearts",
                  "hcp": H(0, 8, (9, 9, 0.5)),
                  "suits": {"H": H(4, 6, (3, 3, 0.3))}},
            "W": {"note": "passed throughout: 0-9",
                  "hcp": H(0, 9, (10, 10, 0.4)), "suits": {}},
        },
        projections={
            "P": [
                {"when": "partner_hearts >= 5 and partner_hcp >= 5",
                 "contract": "2HN"},
                {"else": {"contract": "2DE"}},
            ],
            "2H": [
                {"when": "rho_diamonds >= 6", "contract": "3DE"},
                {"when": "partner_hcp >= 7", "contract": "3HN"},
                {"else": {"contract": "2HN"}},
            ],
            "3H": [
                {"when": "partner_hcp >= 6 and partner_hearts >= 4",
                 "contract": "4HN"},
                {"when": "rho_diamonds >= 6 and rho_hcp >= 14",
                 "contract": "4DE"},
                {"else": {"contract": "3HN"}},
            ],
            "X": [
                {"when": "partner_hearts >= 4", "contract": "3HN"},
                {"when": "partner_spades >= 4", "contract": "2SN"},
                {"else": {"contract": "3CN"}},
            ],
        },
        explanation=(
            "Partner's forced 1H promised nothing, and opener's 2D rebid "
            "gives you a second turn with a flat 14. The menu runs from "
            "selling out, through the pressure raise, to the invitational "
            "jump and a second (values) double. Each keeps the auction "
            "alive differently — opener competes to 3D on shape, partner "
            "accepts invitations on his actual cards."),
    )),
    # ------------------------------------------------------------------ P3
    dict(lin="50023", board=32, doc=dict(
        dilemma=True,
        options=["P", "X"],
        meanings={
            "N": {"note": "strong 1NT: 15-17 balanced",
                  "hcp": H(15, 17),
                  "suits": {s: H(2, 5) for s in "SHDC"}},
            "E": {"note": "2D = both majors, sub-opening values",
                  "hcp": H(5, 12, (13, 13, 0.3)),
                  "suits": {"S": H(4, 6), "H": H(4, 6)}},
            "W": {"note": "passed hand taking a 2S preference: 0-7",
                  "hcp": H(0, 7, (8, 8, 0.4)), "suits": {"S": H(2, 4)}},
        },
        projections={
            "P": [{"else": {"contract": "2SW"}}],
            "X": [
                {"when": "partner_spades >= 4 and partner_spades_hcp >= 5",
                 "contract": "2SWx"},
                {"when": "partner_hearts >= 4", "contract": "3HN"},
                {"when": "partner_diamonds >= 4", "contract": "3DN"},
                {"else": {"contract": "3CN"}},
            ],
        },
        explanation=(
            "They ran from partner's strong NT and 2S is about to buy it. "
            "The balancing double protects partner's trap hands — he "
            "converts for penalties with a spade stack, otherwise picks a "
            "suit at the three level. A genuine two-way problem: the "
            "simulation weighs the penalties you collect against the "
            "three-level minuses."),
    )),
    # ------------------------------------------------------------------ P4
    dict(lin="50022", board=20, doc=dict(
        dilemma=True,
        options=["P", "3D", "X"],
        meanings={
            "S": {"note": "takeout X of 1D: 12+, short diamonds, both majors",
                  "hcp": H(12, 20, (11, 11, 0.4)),
                  "suits": {"D": H(0, 2, (3, 3, 0.3)), "S": H(3, 5),
                            "H": H(3, 5)}},
            "N": {"note": "2H jump advance: 9-11, 4-5 hearts",
                  "hcp": H(9, 11, (8, 8, 0.4), (12, 12, 0.4)),
                  "suits": {"H": H(4, 5)}},
            "W": {"note": "passed throughout incl. over the double: 0-9",
                  "hcp": H(0, 9, (10, 10, 0.4)), "suits": {}},
        },
        projections={
            "P": [
                {"when": "partner_diamonds >= 5 and partner_hcp >= 6",
                 "contract": "3DW"},
                {"else": {"contract": "2HN"}},
            ],
            "3D": [
                {"when": "opps_combined_hcp >= 22 and lho_hearts >= 4",
                 "contract": "4HN"},
                {"when": "lho_hcp >= 9", "contract": "3HN"},
                {"else": {"contract": "3DE"}},
            ],
            "X": [
                {"when": "partner_spades >= 5", "contract": "2SW"},
                {"else": {"contract": "3DW"}},
            ],
        },
        explanation=(
            "Opener's classic rebid problem after X and a jump to 2H: the "
            "suit is chunky (KQJT96) but the hand is minimum and they are "
            "vulnerable too. 3D is automatic for many players — the "
            "simulation asks how often it buys the contract versus pushing "
            "them into a heart game that makes."),
    )),
    # ------------------------------------------------------------------ P5
    dict(lin="50021", board=27, doc=dict(
        dilemma=True,
        options=["2S", "3S", "4D", "5D"],
        meanings={
            "N": {"note": "1S overcall: 8-16, 5-7 spades",
                  "hcp": H(8, 16, (7, 7, 0.5), (17, 17, 0.4)),
                  "suits": {"S": H(5, 7)}},
            "E": {"note": "negative double: 6+, 4+ hearts, short spades",
                  "hcp": H(6, 14), "suits": {"H": H(4, 6), "S": H(0, 3)}},
            "S": {"note": "passed twice: 0-8",
                  "hcp": H(0, 8, (9, 10, 0.4)), "suits": {}},
        },
        projections={
            "2S": [
                {"when": "partner_spades_hcp >= 3 and partner_hcp >= 8",
                 "contract": "3NTE"},
                {"when": "partner_hcp >= 10", "contract": "6DW"},
                {"else": {"contract": "5DW"}},
            ],
            "3S": [
                {"when": "partner_spades_hcp >= 3", "contract": "3NTE"},
                {"when": "partner_hcp >= 9", "contract": "6DW"},
                {"else": {"contract": "5DW"}},
            ],
            "4D": [
                {"when": "partner_hcp >= 9", "contract": "5DW"},
                {"else": {"contract": "4DW"}},
            ],
            "5D": [
                {"when": "partner_hcp >= 11", "contract": "6DW"},
                {"else": {"contract": "5DW"}},
            ],
        },
        explanation=(
            "Twenty points and a seven-card suit after partner's negative "
            "double: the cue-bids keep 3NT and slam in the picture (partner "
            "declares 3NT with a spade card), while the direct diamond "
            "bids trade information for safety. The simulation measures "
            "what the extra room is actually worth."),
    )),
    # ------------------------------------------------------------------ P6
    dict(lin="50000", board=16, doc=dict(
        dilemma=True,
        options=["X", "P", "1NT"],
        meanings={
            "E": {"note": "1D response: 6+, 4+ diamonds",
                  "hcp": H(6, 14, (5, 5, 0.4)), "suits": {"D": H(4, 6)}},
            "S": {"note": "1S overcall: 8-16, 5-7 spades",
                  "hcp": H(8, 16, (7, 7, 0.5)), "suits": {"S": H(5, 7)}},
            "N": {"note": "passed over 1C: 0-10",
                  "hcp": H(0, 10, (11, 11, 0.4)), "suits": {}},
        },
        projections={
            "X": [
                {"when": "lho_spades >= 3 and opps_combined_hcp >= 17",
                 "contract": "2SS"},
                {"when": "partner_hcp >= 10", "contract": "3DE"},
                {"else": {"contract": "2DE"}},
            ],
            "P": [
                {"when": "lho_spades >= 3 and lho_hcp >= 5",
                 "contract": "2SS"},
                {"when": "partner_hcp >= 10", "contract": "2DE"},
                {"else": {"contract": "1SS"}},
            ],
            "1NT": [
                {"when": "rho_hcp >= 12 and rho_spades_hcp >= 7",
                 "contract": "1NTWx"},
                {"else": {"contract": "1NTW"}},
            ],
        },
        explanation=(
            "A flat 13 with three small in their suit: the support-style "
            "double keeps both red suits in play, Pass is disciplined, and "
            "1NT — tempting at the table — has only J9x behind the spade "
            "bidder and sometimes gets doubled. Note how the part-score "
            "war plays out differently after each choice."),
    )),
    # ------------------------------------------------------------------ P7
    dict(lin="50021", board=20, doc=dict(
        dilemma=True,
        options=["1H", "2H", "3H"],
        meanings={
            "E": {"note": "3rd-seat 1D opening: 10-19, 3+ diamonds",
                  "hcp": H(10, 19, (9, 9, 0.3)), "suits": {"D": H(3, 6)}},
            "S": {"note": "takeout X of 1D: 12+, short diamonds, both majors",
                  "hcp": H(12, 20, (11, 11, 0.4)),
                  "suits": {"D": H(0, 2, (3, 3, 0.3)), "S": H(3, 5),
                            "H": H(3, 5)}},
            "W": {"note": "passed throughout: 0-9",
                  "hcp": H(0, 9, (10, 10, 0.4)), "suits": {}},
        },
        projections={
            "1H": [
                {"when": "rho_hcp >= 13 and rho_diamonds >= 5",
                 "contract": "2DE"},
                {"when": "partner_hcp >= 17", "contract": "4HN"},
                {"when": "partner_hcp >= 15", "contract": "3HN"},
                {"else": {"contract": "1HN"}},
            ],
            "2H": [
                {"when": "partner_hcp >= 15", "contract": "4HN"},
                {"when": "rho_hcp >= 14 and rho_diamonds >= 5",
                 "contract": "3DE"},
                {"else": {"contract": "2HN"}},
            ],
            "3H": [
                {"when": "partner_hcp >= 14", "contract": "4HN"},
                {"else": {"contract": "3HN"}},
            ],
        },
        explanation=(
            "Ace-ten-fifth of hearts and 8 points opposite a takeout "
            "double: the timid 1H invites opener back in cheaply, 2H "
            "shows the values, and the LAW-style 3H bounce takes their "
            "room away at the cost of occasionally being too high. "
            "Note the trap in underbidding — the auction doesn't end, "
            "and you may defend 2D instead of declaring hearts."),
    )),
    # ------------------------------------------------------------------ P8
    dict(lin="50003", board=18, doc=dict(
        dilemma=True,
        options=["1NT", "2C", "2D", "P"],
        meanings={
            "S": {"note": "1C opening: 11-19, 3+ clubs",
                  "hcp": H(11, 19, (10, 10, 0.3), (20, 21, 0.3)),
                  "suits": {"C": H(3, 7)}},
            "W": {"note": "1S overcall: 8-16, 5-7 spades",
                  "hcp": H(8, 16, (7, 7, 0.5)), "suits": {"S": H(5, 7)}},
            "E": {"note": "passed as dealer: 0-11",
                  "hcp": H(0, 11, (12, 12, 0.3)), "suits": {}},
        },
        projections={
            "1NT": [
                {"when": "rho_spades >= 3 and rho_hcp >= 7", "contract": "2SW"},
                {"when": "partner_hcp >= 16", "contract": "3NTN"},
                {"else": {"contract": "1NTN"}},
            ],
            "2C": [
                {"when": "rho_spades >= 3 and rho_hcp >= 6", "contract": "2SW"},
                {"when": "partner_hcp >= 17", "contract": "3NTS"},
                {"else": {"contract": "2CS"}},
            ],
            "2D": [
                {"when": "partner_hcp >= 15 and partner_diamonds >= 3",
                 "contract": "3NTS"},
                {"when": "rho_spades >= 3 and rho_hcp >= 6", "contract": "2SW"},
                {"when": "partner_clubs >= 6", "contract": "3CS"},
                {"else": {"contract": "2DN"}},
            ],
            "P": [
                {"when": "rho_spades >= 3 and rho_hcp >= 6", "contract": "2SW"},
                {"when": "partner_hcp >= 16", "contract": "2CS"},
                {"else": {"contract": "1SW"}},
            ],
        },
        explanation=(
            "An everyday decision, not a fireworks hand: 8 points, both "
            "pointed kings, five weak diamonds, after partner's 1C is "
            "overcalled 1S. 1NT describes the strength with a stopper, "
            "2C and 2D each misdescribe something, and Pass risks selling "
            "cheap. The differences are small — which is exactly why the "
            "field gets it wrong."),
    )),
]


def main(lin_dir: str, out_dir: str) -> None:
    lin_dir = Path(lin_dir)
    pool = ProblemPool(out_dir)
    for spec in BATCH:
        text = (lin_dir / f"{spec['lin']}.lin").read_text(errors="replace")
        divs = {d.number: d for d in find_divergences(parse_lin(text))}
        div = divs[spec["board"]]
        rec = build_record(
            problem_id=f"f{spec['lin']}-{spec['board']}",
            dealer=div.dealer, vul=div.vul, hero=div.hero, hands=div.hands,
            stem=div.stem, doc=spec["doc"],
            source={"event": div.event, "teams": div.teams,
                    "board": div.number,
                    "room_calls": dict(div.calls),
                    "room_contracts": {r: str(fc)
                                       for r, fc in div.contracts.items()},
                    "room_results": dict(div.results)},
            seed=int(spec["lin"]) * 100 + spec["board"],
        )
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
