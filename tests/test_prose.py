"""Post-verdict explanation linting (backlog group E)."""
import pytest

from bridge_trainer.finalize.prose import (ProseError, attach_explanation,
                                           lint_explanation,
                                           render_full_explanation)


def _record(**over):
    rec = {
        "hand": "KQJ76.Q83.7.QJ94",   # 11 HCP, 5-3-1-4
        "candidates": ["3C", "P", "2S"],
        "deviations": {"2S": {"note": "five spades, not six",
                              "kind": "card_violation"}},
        "verdict": {
            "accepted": ["3C", "2S"], "toss_up": True, "fog": False,
            "corrected": [
                {"action": "3C", "ev": 0.19, "ci": 0.3, "vs": "2S",
                 "p_gain": 0.3, "p_loss": 0.28, "p_push": 0.42}],
        },
        "difficulty": 0.19,
        "meanings": [{"seat": "W", "meaning": "balancing X",
                      "hcp": [9, 15]}],
        "source": {"room_calls": {"o": "P", "c": "3C"},
                   "room_contracts": {"o": "2DE", "c": "3CN"}},
        "quality": {},
    }
    rec.update(over)
    return rec


GOOD = ("A toss-up: 3C and 2S cannot be separated by the simulation. "
        "3C competes on the eight-card fit; 2S retreats to the "
        "five-carder, off the card but the suit is chunky. "
        "P risks defending 2C doubled with an eleven-count.")


def test_good_text_passes():
    errors, _ = lint_explanation(GOOD, _record())
    assert errors == []


def test_future_tense_rejected():
    errors, _ = lint_explanation(
        GOOD + " The simulation will show which pays.", _record())
    assert any("future tense" in e for e in errors)


def test_all_options_must_be_addressed():
    errors, _ = lint_explanation(
        "A toss-up: 3C and 2S cannot be separated, off the card or not.",
        _record())
    assert any("'P'" in e for e in errors)


def test_toss_up_language_required():
    errors, _ = lint_explanation(
        "3C is clearly best. 2S and P both lose, off the card.", _record())
    assert any("toss-up" in e for e in errors)


def test_blowout_may_not_be_called_close():
    rec = _record(difficulty=7.4,
                  verdict={"accepted": ["P"], "toss_up": False,
                           "fog": False,
                           "corrected": [{"action": "P", "ev": 7.4,
                                          "ci": 0.5, "vs": "3C",
                                          "p_gain": 0.9, "p_loss": 0.05,
                                          "p_push": 0.05}]})
    errors, _ = lint_explanation(
        "A classic close decision between P, 3C and 2S; the card favors "
        "P.", rec)
    assert any("close" in e for e in errors)


def test_shape_and_count_claims_checked():
    # 5-2-2-4 is not the hero shape; a five-count matches neither the
    # hero hand (11) nor W's 9-15 band
    errors, _ = lint_explanation(
        GOOD + " With this 5-2-2-4 five-count, act.", _record())
    assert any("shape claim" in e for e in errors)
    assert any("five-count" in e for e in errors)
    # 11-count (hero) and 12-count (inside W's band) are both fine
    errors2, _ = lint_explanation(
        GOOD + " An eleven-count facing a possible 12-count.", _record())
    assert errors2 == []


def test_accepted_deviation_needs_reconciliation():
    text = ("A toss-up: 3C and 2S cannot be separated. "
            "P risks defending doubled.")
    errors, _ = lint_explanation(text, _record())
    assert any("reconcile" in e for e in errors)


def test_render_appends_flags_and_table():
    out = render_full_explanation("Body.", _record())
    assert "⚠ 2S — five spades, not six" in out
    assert "At the table" in out and "2DE" in out


def test_attach_explanation():
    rec = _record()
    attach_explanation(rec, GOOD)
    assert rec["explanation"].startswith(GOOD)
    assert "At the table" in rec["explanation"]
    with pytest.raises(ProseError):
        attach_explanation(_record(), "Too short and names nothing.")
