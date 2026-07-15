"""Regression tests for the user-flagged deals (expert_review_v2 §4).

Each test drives the real bidder/walker over the exact reported deal and
asserts the corrected behavior: absurd Double candidates are gone, fake
dilemmas don't qualify as problems, and the r01352772 stem bug (1NT response
over an overcall with a stiff in their suit) is fixed by a negative double.
"""
import pytest

from bridge_trainer.bot.bidder import HandView, SimpleBidder
from bridge_trainer.bot.walker import AuctionWalker
from bridge_trainer.generate.random_problem import evaluate_turn


def make_walker(dealer, vul, hands_pbn):
    hands = {s: HandView.from_pbn(h) for s, h in hands_pbn.items()}
    return AuctionWalker(dealer, vul, hands=hands), hands


def walk_until(walker, n_calls):
    while len(walker.calls) < n_calls:
        walker.step()


def turn_eval(walker, hands):
    seat = walker.next_to_call
    view = walker.view_for(seat)
    return seat, evaluate_turn(SimpleBidder(), hands[seat], view,
                               len(walker.calls))


R74 = {"N": "KQJ6.T5.J4.JT973", "E": "T5.KJ7432.Q72.K5",
       "S": "A9843.Q6.AKT8.A8", "W": "72.A98.9653.Q642"}
R73 = {"N": "K984.Q872.J.AK54", "E": "AT5.A53.852.QJT2",
       "S": "Q63.K9.QT973.763", "W": "J72.JT64.AK64.98"}
R70 = {"N": "AK42.AQ987.A632.", "E": "J7.KT65.K7.QJ972",
       "S": "Q8653.J2.QJ8.T85", "W": "T9.43.T954.AK643"}
R75 = {"N": "KQT76.A973.JT.T7", "E": "J832.K84.Q5.K954",
       "S": "A54.QJ2.984.AQJ3", "W": "9.T65.AK7632.862"}
R72 = {"N": "K872.K6.9432.Q96", "E": "J4.9843.A.AK8542",
       "S": "AQ9653.J52.K76.T", "W": "T.AQT7.QJT85.J73"}


def test_r01352774_no_double_of_their_4s():
    """User: 'no dilemma; and the alternative would be 5H, not Dbl'."""
    walker, hands = make_walker("S", "EW", R74)
    walk_until(walker, 7)  # 1S P 3S P 4S P P -> East's decision
    assert walker.tokens() == ["1S", "P", "3S", "P", "4S", "P", "P"]
    seat, (chosen, cands, qualifies, score) = turn_eval(walker, hands)
    assert seat == "E"
    assert chosen.token == "P"
    assert "X" not in cands          # KJxxxx of hearts is not a penalty X
    assert "5H" not in cands         # no fit, 6-card suit, unfavorable
    assert cands == ["P"]
    assert not qualifies             # no dilemma -> deal rejected


def test_r01352773_no_double_of_their_1nt():
    """User: 'no option but pass. Double is not an option.'

    (v2's opening discipline changes this stem organically — an 11-count
    4-3-3-3 now passes — so the reported auction is replayed verbatim to
    test the candidate logic at the flagged spot.)"""
    walker, hands = make_walker("E", "EW", R73)
    for tok in ["1C", "P", "1H", "P", "1NT", "P", "P"]:
        walker.force(tok)
    seat, (chosen, cands, qualifies, score) = turn_eval(walker, hands)
    assert seat == "N"
    assert chosen.token == "P"
    assert "X" not in cands
    assert cands == ["P"]
    assert not qualifies


def test_r01352770_no_double_of_their_unopposed_game():
    walker, hands = make_walker("E", "EW", R70)
    walk_until(walker, 8)  # P P P 1H P 1S P 4S -> East's decision
    assert walker.tokens() == ["P", "P", "P", "1H", "P", "1S", "P", "4S"]
    seat, (chosen, cands, qualifies, score) = turn_eval(walker, hands)
    assert seat == "E"
    assert chosen.token == "P"
    assert "X" not in cands
    assert cands == ["P"]
    assert not qualifies


def test_r01352775_no_double_of_their_1nt():
    walker, hands = make_walker("S", "Both", R75)
    walk_until(walker, 7)
    assert walker.tokens() == ["1C", "P", "1S", "P", "1NT", "P", "P"]
    seat, (chosen, cands, qualifies, score) = turn_eval(walker, hands)
    assert seat == "E"
    assert "X" not in cands
    assert cands == ["P"]
    assert not qualifies


def test_r01352772_negative_double_replaces_stopperless_1nt():
    """User: 'my first bid is 100% incorrect'. W held T.AQT7.QJT85.J73 and
    responded 1NT over 1C-(1S) with no spade stopper. Correct: negative X."""
    walker, hands = make_walker("E", "NS", R72)
    walk_until(walker, 2)  # E 1C, S 1S
    assert walker.tokens() == ["1C", "1S"]
    seat, call = walker.step()
    assert seat == "W"
    assert call.token == "X"
    assert call.rule == "neg_double"
    # Signature: 6-11 range with 4+ hearts, at most 3 spades.
    assert call.signature.hcp == (6, 11)
    assert call.signature.suit_min == {"H": 4}
    assert call.signature.suit_max == {"S": 3}
    # The auction continues sanely and terminates.
    fc = walker.run_to_end()
    assert walker.finished
    assert "1NT" not in walker.tokens()


def test_no_bare_hcp_double_candidates_anywhere():
    """Sweep random boards: every X candidate must come from a strict
    double rule of the bidder, never appear against an unopposed NT."""
    import numpy as np
    from bridge_trainer.dealing.features import hand_to_pbn
    from bridge_trainer.domain.auction import SEATS
    bidder = SimpleBidder()
    checked = 0
    for seed in range(25):
        rng = np.random.default_rng([seed, 99])
        deck = rng.permutation(52).astype(np.int8)
        hands = {s: HandView.from_pbn(hand_to_pbn(deck[i*13:(i+1)*13]))
                 for i, s in enumerate(SEATS)}
        w = AuctionWalker(SEATS[seed % 4], ("None", "NS", "EW", "Both")[seed % 4],
                          hands=hands)
        while not w.finished and len(w.calls) < 24:
            seat = w.next_to_call
            view = w.view_for(seat)
            chosen, cands, _, _ = evaluate_turn(bidder, hands[seat], view,
                                                len(w.calls))
            if "X" in cands and chosen.token != "X":
                # Must be one of the bidder's own strict X rules (doubles
                # get no slack), and never against an unopposed NT.
                fired = [c for c in bidder.enumerate_calls(hands[seat], view)
                         if c.token == "X"]
                assert fired, f"X candidate without a firing rule: {cands}"
                assert view.denom != "NT" or fired[0].rule == "neg_double"
                checked += 1
            w.record(seat, chosen)
    assert True  # sweep completed without violations
