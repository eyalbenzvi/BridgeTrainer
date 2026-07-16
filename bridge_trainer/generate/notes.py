"""Bot-derived explanations for generated problems.

The authored batches carry hand-written prose notes; random problems get
mechanical but honest ones straight from the generator's own data:

- auction_notes: one line per stem call, rendered from the bot rule that
  chose it plus the call's constraint signature (the exact bounds the
  concealed-hand simulation enforces — so the text can never overclaim).
- option_notes: per candidate, "shows" from the rule/signature the call
  fires under, and "partner" from the weighted distribution of final
  contracts the simulation actually reached after that call.

Format matches scripts/attach_notes.py and the app (webapp p.html):
auction_notes is a list aligned with the auction; option_notes is
{token: {"shows": ..., "partner": ...}}.
"""
from __future__ import annotations

from collections import defaultdict

from ..bot.bidder import BotCall, Signature
from ..domain.auction import partner_of
from ..domain.contracts import FinalContract

SUIT_NAMES = {"S": "spades", "H": "hearts", "D": "diamonds", "C": "clubs"}

# Meaning of each bot rule, phrased for the solver. Dynamic families
# (open_1x, weak_two_x, preempt_3x) are matched by prefix.
RULE_PHRASES = {
    "no_action": "nothing suitable to say",
    "cap_6level": "the bot never bids past the six level",
    # openings
    "open_pass": "no opening bid",
    "open_1nt": "balanced 1NT opening",
    "open_2nt": "strong balanced opening",
    "open_big": "maximum one-level opening (no 2C in this system; "
                "very strong hands start low)",
    "open_1": "natural opening, longest suit first",
    "weak_two_": "weak two: a good six-card suit in a limited hand",
    "preempt_3": "preempt: a long suit and a weak hand",
    # responses to partner's opening
    "resp_1nt_major_game": "game in the major over 1NT "
                           "(no Stayman/transfers in this system)",
    "resp_1nt_raise_game": "raising 1NT to game",
    "resp_1nt_invite": "invitational raise of 1NT",
    "resp_1nt_pass": "no game interest opposite 1NT",
    "resp_2nt_raise": "raising partner's 2NT to game",
    "resp_2nt_pass": "nothing to add opposite 2NT",
    "resp_pass": "too weak to respond",
    "resp_preemptive_game": "preemptive raise to game: big fit, "
                            "shape more than points",
    "resp_game_raise": "raise to game on fit and values",
    "resp_limit_raise": "limit raise: fit with invitational values",
    "resp_simple_raise": "single raise: fit, minimum response",
    "resp_new_suit_1": "new suit at the one level, forcing; "
                       "bidding up the line",
    "resp_two_over_one": "two-over-one: a real suit and real values",
    "neg_double": "negative double: length in the unbid major(s)",
    "resp_minor_raise": "raise of partner's minor",
    "resp_minor_limit": "limit raise of partner's minor",
    "resp_3nt": "natural raise to 3NT",
    "resp_1nt": "catch-all 1NT response",
    "resp_pass_competition": "declining to act over the interference",
    # opener's rebids
    "rebid_negx_major": "answering the negative double with a major",
    "rebid_negx_major_j": "jump answer to the negative double: extras",
    "rebid_pass_game_reached": "game already reached — nothing more to say",
    "rebid_accept_game": "accepting the invitation",
    "rebid_minor_game": "game in the minor",
    "rebid_minor_3nt": "choosing 3NT over five of the minor",
    "rebid_pass_partscore": "minimum opener, staying low",
    "rebid_raise_game": "raising partner's suit to game",
    "rebid_raise": "raising partner's suit",
    "rebid_six_card": "rebidding a six-card suit",
    "rebid_2nt_1819": "balanced 18-19 rebid",
    "rebid_1nt_1214": "balanced minimum rebid",
    "rebid_3nt": "enough for game in notrump",
    "rebid_nt_strong": "strong notrump rebid",
    "rebid_suit_strong": "strong jump rebid of the suit",
    "rebid_pass": "nothing extra to show",
    # responder's rebids
    "resp_rebid_game_major": "enough combined values: game in the "
                             "major-suit fit",
    "resp_rebid_3nt": "enough combined values for 3NT with stoppers",
    "resp_rebid_invite": "inviting game in notrump",
    "resp_rebid_stop": "signing off: the combined values are limited",
    # direct seat over their opening
    "takeout_double": "takeout double: opening values, short in their "
                      "suit, support for the unbid suits",
    "power_double": "power double: too strong for a simple overcall",
    "overcall_1nt": "1NT overcall: strong balanced with their suit stopped",
    "overcall_1level": "one-level overcall on a decent five-card suit",
    "overcall_2level": "two-level overcall: good suit, sound values",
    "weak_jump_overcall": "weak jump overcall: long suit, weak hand",
    "pass_over_1nt": "no action over their 1NT",
    "direct_pass": "no overcall or double available",
    # advancing partner's overcall / double
    "advance_nt_pass": "nothing to say opposite the 1NT overcall",
    "advance_game_raise": "raising partner's overcall to game",
    "advance_law_raise": "preemptive raise on trumps "
                         "(Law of Total Tricks)",
    "advance_simple_raise": "simple raise of the overcall",
    "advance_pass": "no fit or values to advance the overcall",
    "advance_x_penalty_pass": "penalty pass of the takeout double: "
                              "a trump stack",
    "advance_x_game": "jumping to game in answer to the takeout double",
    "advance_x_jump": "invitational jump in answer to the double",
    "advance_x_min": "minimum answer to the takeout double "
                     "(may be worthless)",
    "advance_x_stuck": "stuck: answering the takeout double is forced",
    # later competitive rounds
    "penalty_double_unopposed": "penalty double of their freely-bid "
                                "contract: trump tricks and values",
    "penalty_double_comp": "penalty double in competition: trumps plus "
                           "combined values",
    "compete_law": "competing on the known fit (Law of Total Tricks)",
    "compete_game": "bidding game on the combined values",
    "sacrifice": "sacrifice: favorable vulnerability, huge fit, "
                 "little defence",
    "safety_valve": "auction cut off by the bot's safety valve",
    "forced": "the candidate under test",
}


def rule_phrase(rule: str) -> str:
    if rule in RULE_PHRASES:
        return RULE_PHRASES[rule]
    for prefix in ("open_1", "weak_two_", "preempt_3"):
        if rule.startswith(prefix):
            return RULE_PHRASES[prefix]
    return ""


def signature_text(sig: Signature) -> str:
    """Render the signature's sound bounds as prose."""
    parts = []
    lo, hi = sig.hcp
    if (lo, hi) != (0, 40):
        if hi == 40:
            parts.append(f"{lo}+ HCP")
        elif lo == 0:
            parts.append(f"at most {hi} HCP")
        else:
            parts.append(f"about {lo}-{hi} HCP")
    for s, n in sorted(sig.suit_min.items()):
        parts.append(f"{n}+ {SUIT_NAMES[s]}")
    for s, n in sorted(sig.suit_max.items()):
        parts.append(f"at most {n} {SUIT_NAMES[s]}")
    for s in sorted(sig.quality):
        parts.append(f"decent {SUIT_NAMES[s]} quality")
    return ", ".join(parts)


def call_note(call: BotCall) -> str:
    phrase = rule_phrase(call.rule)
    sig = signature_text(call.signature)
    if phrase and sig:
        return f"{phrase} — {sig}"
    return phrase or sig or "nothing specific shown"


def auction_notes(stem_calls: list[BotCall]) -> list[str]:
    """One line per stem call, aligned with the recorded auction."""
    return [call_note(c) for c in stem_calls]


def continuation_summary(contracts: list[FinalContract], weights,
                         hero: str) -> str:
    """Weighted distribution of where the auction actually ended across
    the simulated layouts after this candidate."""
    mass: dict[str, float] = defaultdict(float)
    partner = partner_of(hero)
    for c, w in zip(contracts, weights):
        if c.passed_out:
            key = "passed out"
        else:
            who = {hero: "you", partner: "partner"}.get(c.declarer,
                                                        f"{c.declarer}")
            key = (f"{c.level}{c.denom}{'x' if c.doubled else ''} "
                   f"by {who}")
        mass[key] += float(w)
    total = sum(mass.values()) or 1.0
    ranked = sorted(mass.items(), key=lambda kv: -kv[1])
    shown = [(k, v / total) for k, v in ranked[:3] if v / total >= 0.05]
    if not shown:  # degenerate: everything is tiny — show the top one
        shown = [(ranked[0][0], ranked[0][1] / total)]
    parts = ", ".join(f"{k} ({p:.0%})" for k, p in shown)
    rest = 1.0 - sum(p for _, p in shown)
    tail = f", other {rest:.0%}" if rest >= 0.05 else ""
    return f"simulated auctions end in {parts}{tail}"


def option_notes(
    candidates: list[str],
    fired_by_token: dict[str, BotCall],
    contracts_by_candidate: dict[str, list[FinalContract]],
    weights,
    hero: str,
) -> dict[str, dict[str, str]]:
    out = {}
    for cand in candidates:
        call = fired_by_token.get(cand)
        if call is not None:
            shows = call_note(call)
        elif cand == "P":
            shows = "declining to act: willing to defend"
        else:
            shows = "a call outside the bot's book"
        out[cand] = {
            "shows": shows,
            "partner": continuation_summary(
                contracts_by_candidate[cand], weights, hero),
        }
    return out
