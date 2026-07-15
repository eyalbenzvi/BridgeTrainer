"""SimpleBidder: determinism, termination, signature soundness."""
import numpy as np
import pytest

from bridge_trainer.bot.bidder import HandView, SimpleBidder
from bridge_trainer.bot.walker import AuctionWalker
from bridge_trainer.dealing.features import hand_to_pbn
from bridge_trainer.domain.auction import SEATS


def random_hands(seed):
    rng = np.random.default_rng(seed)
    deck = rng.permutation(52).astype(np.int8)
    return {s: HandView.from_pbn(hand_to_pbn(deck[i * 13:(i + 1) * 13]))
            for i, s in enumerate(SEATS)}


def test_handview_features():
    h = HandView.from_pbn("AKQJ2.2.A5432.32")
    assert h.hcp == 14
    assert h.length == {"S": 5, "H": 1, "D": 5, "C": 2}
    assert h.shcp["S"] == 10 and h.shcp["D"] == 4
    assert not h.balanced
    assert h.longest() == "S"
    b = HandView.from_pbn("KQ32.A54.QJ4.K32")
    assert b.balanced


@pytest.mark.parametrize("seed", range(60))
def test_all_auctions_terminate(seed):
    w = AuctionWalker(SEATS[seed % 4], ("None", "NS", "EW", "Both")[seed % 4],
                      hands=random_hands(seed))
    fc = w.run_to_end()
    assert w.finished
    assert len(w.calls) <= 40
    if fc.level:
        assert 1 <= fc.level <= 7
        assert fc.declarer in SEATS


def test_bidder_is_deterministic():
    for seed in (3, 11, 27):
        a = AuctionWalker("N", "EW", hands=random_hands(seed))
        b = AuctionWalker("N", "EW", hands=random_hands(seed))
        a.run_to_end()
        b.run_to_end()
        assert a.tokens() == b.tokens()


@pytest.mark.parametrize("seed", range(40))
def test_signatures_are_sound(seed):
    """Every call's signature must be satisfied by the hand that made it."""
    hands = random_hands(seed)
    w = AuctionWalker(SEATS[seed % 4], "None", hands=hands)
    w.run_to_end()
    for seat, call in w.calls:
        sig, h = call.signature, hands[seat]
        if not sig.informative:
            continue
        assert sig.hcp[0] <= h.hcp <= sig.hcp[1], \
            f"{seat} {call.token} ({call.rule}): hcp {h.hcp} not in {sig.hcp}"
        for s, n in sig.suit_min.items():
            assert h.length[s] >= n, \
                f"{seat} {call.token} ({call.rule}): {s} len {h.length[s]} < {n}"
        for s, n in sig.suit_max.items():
            assert h.length[s] <= n, \
                f"{seat} {call.token} ({call.rule}): {s} len {h.length[s]} > {n}"
        for s, n in sig.quality.items():
            assert h.shcp[s] >= n, \
                f"{seat} {call.token} ({call.rule}): {s} hcp {h.shcp[s]} < {n}"


def test_declarer_is_first_namer():
    # N opens 1S, S raises: declarer must be N even though S bid spades last.
    hands = {
        "N": HandView.from_pbn("AKQ54.A2.K432.32"),
        "E": HandView.from_pbn("32.KJ54.QJ54.J54"),
        "S": HandView.from_pbn("JT98.Q87.A87.K87"),
        "W": HandView.from_pbn("76.T96.T96.AQT96"),
    }
    w = AuctionWalker("N", "None", hands=hands)
    fc = w.run_to_end()
    assert fc.denom == "S"
    assert fc.declarer == "N"
