"""Invitation gate (engine/explain_check.invite_violations).

Fixtures reproduce the motivating board ben1-19f947b9723: after
2NT-P-3D-P-3H-P the hero (9 HCP, six hearts) is offered 4H glossed "Mild
slam try" — whose rollout ends in 4H on all 512 layouts — and 4NT glossed
"Quantitative invite" — whose rollout reaches slam on all 512 — while the
board's winner is a direct 6H. Both halves must die; a thin-but-real
invitation must not.
"""
from bridge_trainer.engine.explain_check import (invite_violations,
                                                 invited_class)
from bridge_trainer.engine.gib_explain import parse_meaning

N = 512
HERO_I = 2                      # hero S; partner N declares the slam


def _card(gib_raw):
    return parse_meaning(gib_raw)


def _row(bid, ev_imp_vs_top, contracts):
    return {"bid": bid, "ev_imp_vs_top": ev_imp_vs_top,
            "top_contracts": list(contracts)}


_MILD_TRY = ("Mild slam try. No shortness -- 2+ !C; 2+ !D; 6+ !H; 2+ !S; "
             "9-10 total points")
_QUANT = "Quantitative invite -- 5 !H; 12 HCP"


def _table_19f947b9723():
    return [
        _row("6H", 0.85, [("6HN", N)]),
        _row("4NT", -0.85, [("6HN", 268), ("6NN", 244)]),
        _row("3NT", -2.71, [("3NN", 244), ("6HN", 228), ("5HN", 40)]),
        _row("4H", -5.29, [("4HN", N)]),
    ]


def test_invited_class_reads_the_gloss():
    assert invited_class(_card(_MILD_TRY)) == "slam"
    assert invited_class(_card(_QUANT)) == "slam"
    assert invited_class(
        _card("Quantitative invite to 6NT -- 21 HCP")) == "slam"
    assert invited_class(
        _card("Invitational to 3NT game -- 11 HCP")) == "game"
    assert invited_class(_card("Game try suit -- 3+ !C; 4+ !S")) == "game"
    # not invitations at all
    assert invited_class(_card("Jacoby transfer -- 5+ !H")) is None
    assert invited_class(_card("Blackwood (H) -- 2+ !H")) is None
    assert invited_class({}) is None


def test_the_motivating_board_dies_on_both_halves():
    bad = invite_violations(
        {"6H": _card("6+ !H; 12+ total points"), "4NT": _card(_QUANT),
         "3NT": _card("5 !H; 5-10 HCP"), "4H": _card(_MILD_TRY)},
        _table_19f947b9723(), "6H", HERO_I, N)
    assert len(bad) == 2
    never = next(v for v in bad if v.startswith("option 4H"))
    always = next(v for v in bad if v.startswith("option 4NT"))
    assert "never accepts the try" in never and "5.3 IMPs" in never
    assert "never declines" in always and "100% of layouts" in always


def test_a_thin_but_real_invitation_is_kept():
    # partner accepts 8% of the time: ordinary bridge (they need a max),
    # not a mislabelled call
    table = [_row("4S", 1.2, [("4SN", N)]),
             _row("2NT", -1.2, [("2NN", 470), ("3NN", 42)])]
    assert invite_violations(
        {"2NT": _card("Invitational to 3NT game -- 11 HCP"),
         "4S": _card("4+ !S; 9+ total points")},
        table, "4S", 0, N) == []


def test_a_refused_invitation_is_kept_when_the_winner_stays_low():
    # 2NT is never accepted, but the board's winner is a partscore too:
    # nothing in the evidence says the game was there, so the invitation's
    # score is not measuring a refusal
    table = [_row("P", 0.6, [("2HN", N)]),
             _row("2NT", -1.4, [("2NN", N)])]
    assert invite_violations(
        {"2NT": _card("Invitational to 3NT game -- 11 HCP"),
         "P": _card("No suitable call -- 11- HCP")},
        table, "P", 0, N) == []


def test_a_refused_invitation_under_the_imp_margin_is_kept():
    table = [_row("4S", 0.4, [("4SN", N)]),
             _row("2NT", -0.4, [("2NN", N)])]
    assert invite_violations(
        {"2NT": _card("Invitational to 3NT game -- 11 HCP")},
        table, "4S", 0, N) == []


def test_opponents_taking_the_decision_away_is_not_a_violation():
    # the hero's 2NT was overcalled: the level was never partner's to
    # accept, so the branch says nothing about the invitation
    table = [_row("4S", 1.5, [("4SN", N)]),
             _row("2NT", -1.5, [("3SE", 300), ("2NN", 112), ("4SE", 100)])]
    assert invite_violations(
        {"2NT": _card("Invitational to 3NT game -- 11 HCP")},
        table, "4S", 0, N) == []


def test_a_diffuse_stored_distribution_is_not_judged():
    # the stored row keeps only the top three contracts; when they do not
    # account for the samples the check abstains rather than guess
    table = [_row("4S", 1.5, [("4SN", N)]),
             _row("2NT", -1.5, [("2NN", 100), ("3CN", 90), ("2HN", 80)])]
    assert invite_violations(
        {"2NT": _card("Invitational to 3NT game -- 11 HCP")},
        table, "4S", 0, N) == []
    # ... and the forge's full distribution answers it, same board
    assert invite_violations(
        {"2NT": _card("Invitational to 3NT game -- 11 HCP")},
        table, "4S", 0, N,
        dists={"2NT": {"2NN": 300, "3CN": 122, "2HN": 90},
               "4S": {"4SN": N}})


def test_thin_evidence_is_never_judged():
    assert invite_violations(
        {"4H": _card(_MILD_TRY)},
        [_row("6H", 0.85, [("6HN", 64)]), _row("4H", -5.29, [("4HN", 64)])],
        "6H", HERO_I, 64) == []


def test_the_winning_call_is_checked_too():
    # an always-accepted invitation is a violation even when it wins: the
    # numbers shown for it were measured as a commitment
    table = [_row("4NT", 1.1, [("6HN", 268), ("6NN", 244)]),
             _row("4H", -1.1, [("4HN", N)])]
    bad = invite_violations({"4NT": _card(_QUANT)}, table, "4NT", HERO_I, N)
    assert len(bad) == 1 and "never declines" in bad[0]


# ben1-19fb00aa07e: after 2NT-P-3H-P-3S-P the hero (4 HCP, six spades) has
# 4S graded best — game opposite 20-21 — while GIB glosses that very answer
# "Mild slam try. No shortness, 9-10 total points" and the rollout ends in
# 4S on all 512 layouts. The old never-accepted half judged only LOSING
# options, so the board's own answer was narrated as a try nobody plays.
_MILD_TRY_S = ("Mild slam try. No shortness -- 2+ !C; 2+ !D; 2+ !H; 6+ !S; "
               "9-10 total points")


def test_a_never_accepted_try_that_wins_is_a_violation():
    table = [_row("4S", 1.95, [("4SS", N)]),
             _row("3NT", -1.95, [("4SS", 288), ("3NS", 224)]),
             _row("P", -7.64, [("3SS", N)])]
    bad = invite_violations(
        {"4S": _card(_MILD_TRY_S), "3NT": _card("5 !S; 5-10 HCP"),
         "P": _card("No suitable call -- 5+ !S; 3- total points")},
        table, "4S", 0, N)
    assert len(bad) == 1
    assert bad[0].startswith("option 4S")
    assert "board's own answer" in bad[0]
    assert "signoff narrated as a try" in bad[0]


def test_a_winning_try_partner_sometimes_accepts_is_kept():
    # acceptance 11% — the thinnest rate the published pool shows on a real
    # accepted try (the extreme sits at 0.00-0.01, then an empty decade)
    table = [_row("4S", 1.2, [("4SS", 456), ("6SS", 56)]),
             _row("3NT", -1.2, [("3NS", N)])]
    assert invite_violations(
        {"4S": _card(_MILD_TRY_S), "3NT": _card("5 !S; 5-10 HCP")},
        table, "4S", 0, N) == []


def test_record_violations_flags_the_stored_winner_try_board():
    from bridge_trainer.engine.explain_check import record_violations
    rec = {
        "kind": "bidding", "dealer": "S", "seat": "N",
        "full_deal": {"N": "T87653.AT7.T2.84", "E": "J92.Q63.7.KJ9752",
                      "S": "AKQ.K9.QJ854.AQ3", "W": "4.J8542.AK963.T6"},
        "quality": {"n_samples": N},
        "verdict": {"accepted": "4S", "table": [
            _row("4S", 1.95, [("4SS", N)]),
            _row("3NT", -1.95, [("4SS", 288), ("3NS", 224)]),
            _row("P", -7.64, [("3SS", N)])]},
        "explanations": {
            "stem": [{"idx": 0, "seat": "S", "call": "2NT",
                      "card": _card("Two NT opener. Could have 5M. -- 2-5 !C; "
                                    "2-5 !D; 2-5 !H; 2-5 !S; 20-21 HCP")},
                     {"idx": 2, "seat": "N", "call": "3H",
                      "card": _card("Jacoby transfer -- 5+ !S")},
                     {"idx": 4, "seat": "S", "call": "3S",
                      "card": _card("Transfer completed to S -- 2-5 !C; "
                                    "2-5 !D; 2-5 !H; 2-5 !S; 20-21 HCP")}],
            "options": [{"bid": "4S", "card": _card(_MILD_TRY_S)},
                        {"bid": "3NT", "card": _card("5 !S; 5-10 HCP")},
                        {"bid": "P", "card": _card("No suitable call -- "
                                                   "5+ !S; 3- total points")}],
        },
    }
    fatal, _soft = record_violations(rec)
    hits = [v for v in fatal if "signoff narrated as a try" in v]
    assert hits and hits[0].startswith("option 4S")


def test_record_violations_flags_the_stored_board():
    from bridge_trainer.engine.explain_check import record_violations
    rec = {
        "kind": "bidding", "dealer": "N", "seat": "S",
        "full_deal": {"N": "AQT.A643.AKJ.QT5", "E": "642.QT.93.AJ7642",
                      "S": "75.KJ9752.QT.K98", "W": "KJ983.8.876542.3"},
        "quality": {"n_samples": N},
        "verdict": {"accepted": "6H", "table": _table_19f947b9723()},
        "explanations": {
            "stem": [{"idx": 0, "seat": "N", "call": "2NT",
                      "card": _card("Two NT opener -- 2-5 !C; 2-5 !D; "
                                    "2-5 !H; 2-5 !S; 20-21 HCP")}],
            "options": [{"bid": "6H", "card": _card("6+ !H; 12+ total points")},
                        {"bid": "4NT", "card": _card(_QUANT)},
                        {"bid": "3NT", "card": _card("5 !H; 5-10 HCP")},
                        {"bid": "4H", "card": _card(_MILD_TRY)}],
        },
    }
    fatal, _soft = record_violations(rec)
    assert [v for v in fatal if "never accepts the try" in v]
    assert [v for v in fatal if "never declines" in v]


def test_stored_wrapped_pairs_are_read():
    # Firestore forbids nested arrays, so top_contracts arrives wrapped
    table = [{"bid": "6H", "ev_imp_vs_top": 0.85,
              "top_contracts": [{"items": ["6HN", N]}]},
             {"bid": "4H", "ev_imp_vs_top": -5.29,
              "top_contracts": [{"items": ["4HN", N]}]}]
    bad = invite_violations({"4H": _card(_MILD_TRY)}, table, "6H", HERO_I, N)
    assert len(bad) == 1 and "never accepts the try" in bad[0]


def test_offenders_and_cli_wiring(monkeypatch):
    from bridge_trainer.app import cli
    from bridge_trainer.pool.firestore_store import invite_offenders

    rec = {"id": "ben1-19f947b9723", "kind": "bidding", "seat": "S",
           "quality": {"n_samples": N},
           "verdict": {"accepted": "6H", "table": _table_19f947b9723()},
           "explanations": {"options": [{"bid": "4H", "card": _card(_MILD_TRY)},
                                        {"bid": "6H", "card": _card("6+ !H")}]}}
    clean = {"id": "ben1-clean", "kind": "bidding", "seat": "S",
             "quality": {"n_samples": N},
             "verdict": {"accepted": "6H", "table": _table_19f947b9723()},
             "explanations": {"options": [{"bid": "6H", "card": _card("6+ !H")}]}}
    lead = {"id": "lead1-x", "kind": "lead"}
    assert list(invite_offenders([rec, clean, lead])) == ["ben1-19f947b9723"]

    seen = {}
    monkeypatch.setattr(cli, "cmd_pool_purge_mislabeled_invites",
                        lambda a: seen.update(hit=True, dry=a.dry_run) or 0)
    assert cli.main(["pool", "purge-mislabeled-invites", "--dry-run"]) == 0
    assert seen == {"hit": True, "dry": True}
