"""Hand-class sampler for "next deal" variants."""
import numpy as np
import pytest

from bridge_trainer.dealing.features import HCP_BY_RANK, parse_hand_pbn
from bridge_trainer.dealing.myhand import sample_my_hand

CLASS = {"hcp": [5, 10], "suits": {"S": [3, 3], "H": [2, 3]}}


def _stats(hand):
    cards = parse_hand_pbn(hand)
    hcp = int(sum(HCP_BY_RANK[c % 13] for c in cards))
    lens = {s: sum(1 for c in cards if c // 13 == i)
            for i, s in enumerate("SHDC")}
    return hcp, lens


def test_sampled_hands_satisfy_class():
    rng = np.random.default_rng(1)
    for _ in range(20):
        hcp, lens = _stats(sample_my_hand(CLASS, rng))
        assert 5 <= hcp <= 10
        assert lens["S"] == 3
        assert 2 <= lens["H"] <= 3


def test_sampler_is_deterministic():
    a = sample_my_hand(CLASS, np.random.default_rng([7, 777]))
    b = sample_my_hand(CLASS, np.random.default_rng([7, 777]))
    c = sample_my_hand(CLASS, np.random.default_rng([8, 777]))
    assert a == b
    assert a != c


def test_unsatisfiable_class_raises():
    with pytest.raises(RuntimeError):
        sample_my_hand({"hcp": [0, 0], "suits": {"S": [13, 13]}},
                       np.random.default_rng(0), batch=64, max_batches=2)
