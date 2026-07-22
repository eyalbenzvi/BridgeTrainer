"""The bid-explanation guard: detect the BBO-blocked generation signature
(a non-empty auction whose calls got no meaning notes) so such problems are
kept out of the pool and out of Firestore."""
from bridge_trainer.engine.explain import bid_notes_missing


def _rec(kind, auction, notes):
    key = "stem" if kind == "bidding" else "auction"
    return {"kind": kind, "auction": auction,
            "explanations": {key: notes}}


def test_bidding_all_blank_is_missing():
    rec = _rec("bidding", ["P", "1D", "2S", "X", "P"],
               [{"call": c, "text": ""} for c in ["P", "1D", "2S", "X", "P"]])
    assert bid_notes_missing(rec) is True


def test_lead_all_blank_is_missing():
    rec = _rec("lead", ["P", "1C", "P", "1H", "P", "P", "P"],
               [{"call": c, "text": ""} for c in
                ["P", "1C", "P", "1H", "P", "P", "P"]])
    assert bid_notes_missing(rec) is True


def test_populated_notes_ok():
    rec = _rec("bidding", ["1S", "P", "2S"],
               [{"call": "1S", "text": "1♠ (W): Major suit opening"},
                {"call": "P", "text": "Pass (N): No suitable call, 0-11"},
                {"call": "2S", "text": "2♠ (E): Simple raise, 3+♠"}])
    assert bid_notes_missing(rec) is False


def test_partial_notes_ok():
    # a silent pass legitimately gets no text; one real note is enough.
    rec = _rec("bidding", ["1S", "P"],
               [{"call": "1S", "text": "1♠ (W): Major suit opening"},
                {"call": "P", "text": ""}])
    assert bid_notes_missing(rec) is False


def test_empty_auction_is_not_missing():
    # the hero opens: nothing to explain, not a bug.
    assert bid_notes_missing(_rec("bidding", [], [])) is False


def test_all_pass_blank_is_missing():
    # even passes are annotated when BBO is up, so all-blank means it was down.
    rec = _rec("bidding", ["P", "P"],
               [{"call": "P", "text": ""}, {"call": "P", "text": ""}])
    assert bid_notes_missing(rec) is True
