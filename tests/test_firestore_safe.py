"""The Firestore sanitizer wraps directly-nested arrays (which Firestore
rejects) without touching maps, scalars, or already-flat arrays."""
from bridge_trainer.pool.firestore_store import _firestore_safe


def test_wraps_array_of_pairs():
    # top_contracts shape: list of [contract, count] pairs.
    out = _firestore_safe({"top_contracts": [["4SW", 231], ["3SW", 104]]})
    assert out == {"top_contracts": [{"items": ["4SW", 231]},
                                     {"items": ["3SW", 104]}]}


def test_flat_arrays_and_scalars_unchanged():
    doc = {"auction": ["P", "1D", "P"], "difficulty": 1.6, "seat": "W",
           "candidates": [{"call": "3NT", "policy": 0.46}]}
    assert _firestore_safe(doc) == doc


def test_recurses_into_deeper_nesting():
    out = _firestore_safe({"a": {"b": [[1, 2], [3]]}})
    assert out == {"a": {"b": [{"items": [1, 2]}, {"items": [3]}]}}


def test_nested_array_of_arrays():
    out = _firestore_safe([[[1]]])
    assert out == [{"items": [{"items": [1]}]}]
