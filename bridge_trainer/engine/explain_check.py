"""Explanation-consistency gate: disqualify boards whose displayed call
meanings are wrong — either the auction is engine-weird or GIB's gloss
describes a different system than Ben actually bid.

Motivating board (ben1-01354c2d): Ben answered a 4NT ask with 5♦ — glossed
by GIB as "One or four key cards" — while holding two, and the 5NT
candidate's gloss asserted the trump queen the hero does not hold. A human
can neither follow such an auction nor trust its explanations, so the board
must not be published. Both faults are visible mechanically at generation
time; nothing here consults an LLM or a human.

Two independent checks:

``hand_violations`` (cheap, no engine)
    GIB's parsed card for every stem call and every offered candidate is
    compared against the ACTUAL 13 cards of the bidder (the forge knows the
    full deal). Fires on: HCP band breached beyond SLACK_HCP; a promised
    suit length breached beyond SLACK_LEN; an explicit holding assertion
    ("!CQ", "!SK") the hand fails; a keycard/ace-count response ("One or
    four key cards") that does not match the hand's actual count (checked
    exactly — a wrong keycard answer is never a style deviation); a
    trump-queen statement ("Queen and king", "No queen") the hand
    contradicts. Slack exists because GIB describes the systemic meaning
    and sound bridge shades by a point or a card.

``band_violations`` (engine sampling; run only on boards that already
    passed the statistical judge, so its cost lands on ~1 board in 12)
    Ben's OWN meaning of a stem call — suit-length/HCP statistics over the
    layouts Ben's sampler accepts after that call — is compared against
    GIB's parsed card. Fires when the bid systemically promises 5+ cards in
    a suit the gloss does not mention (Leaping Michaels glossed as a
    natural club overcall), when the gloss promises a 5+ suit the bid's
    band refutes, or when the HCP bands are disjoint. Pass/X/XX and low-n
    bands are skipped.
"""
from __future__ import annotations

import re

from .conventions import seat_of

SEATS = "NESW"
SLACK_HCP = 2          # GIB band may be shaded by a couple of points
SLACK_LEN = 1          # ... and a promised length by one card
BAND_N_MIN = 30        # below this many samples a band proves nothing
BAND_P5_SURE = 0.90    # measured "the bid promises 5+ here"
BAND_LEN_REFUTED = 3.0 # gloss says 5+, band average below this refutes it
BAND_HCP_GAP = 2       # gloss and band HCP ranges must at least touch ±this

_HCP_W = {"A": 4, "K": 3, "Q": 2, "J": 1}
_NUM_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
              "five": 5}
# explicit holding assertion in a GIB raw string: "!CQ" = club queen.
# The rank letter must follow the suit letter immediately, which cannot
# collide with suit-range fragments ("5+ !C", "1- !D") where the suit
# letter ends the token.
_HOLDING_RE = re.compile(r"!([CDHS])([AKQJ])\b")
_BLACKWOOD_SUIT_RE = re.compile(r"Blackwood \(([CDHS])\)", re.I)
_TRUMP_HINT_RE = re.compile(r"\b([CDHS]) trump\b", re.I)
_QUEEN_YES_RE = re.compile(r"(?i)^queen\b|\bqueen and\b")


def hand_hcp(hand_pbn: str) -> int:
    return sum(_HCP_W.get(c, 0) for c in hand_pbn)


def suit_lengths(hand_pbn: str) -> dict:
    return {s: len(h) for s, h in zip("SHDC", hand_pbn.split("."))}


def holds(hand_pbn: str, suit: str, rank: str) -> bool:
    return rank in hand_pbn.split(".")["SHDC".index(suit)]


def keycards(hand_pbn: str, trump: str | None) -> int:
    """Aces + trump king; plain ace count when no trump is known."""
    n = sum(1 for h in hand_pbn.split(".") if "A" in h)
    if trump and holds(hand_pbn, trump, "K"):
        n += 1
    return n


def _stated_counts(text: str) -> list[int]:
    """'One or four key cards' -> [1, 4]; digits accepted too."""
    low = text.lower()
    counts = [_NUM_WORDS[w] for w in re.findall(
        r"\b(zero|one|two|three|four|five)\b", low)]
    counts += [int(d) for d in re.findall(r"\b([0-5])\b", low)]
    return counts


def _trump_from_context(entries: list[dict], upto: int) -> str | None:
    """Trump suit for an ask/answer at entries[upto]: the nearest earlier
    'Blackwood (X)' gloss, else a '<X> trump' hint in the entry itself."""
    raw = (entries[upto].get("card") or {}).get("gib_raw") or ""
    m = _TRUMP_HINT_RE.search(raw)
    if m:
        return m.group(1).upper()
    for e in reversed(entries[:upto]):
        raw = (e.get("card") or {}).get("gib_raw") or ""
        m = _BLACKWOOD_SUIT_RE.search(raw)
        if m:
            return m.group(1).upper()
    return None


def card_vs_hand(card: dict, hand_pbn: str) -> list[str]:
    """Violations of one parsed GIB card against the actual hand."""
    out = []
    if not card:
        return out
    hcp = card.get("hcp")
    if hcp:
        have = hand_hcp(hand_pbn)
        lo, hi = int(hcp[0]), int(hcp[1])
        if have < lo - SLACK_HCP or have > hi + SLACK_HCP:
            out.append(f"hcp {have} outside {lo}-{hi}")
    lens = suit_lengths(hand_pbn)
    for st, mn in (card.get("minlen") or {}).items():
        if st in lens and lens[st] < mn - SLACK_LEN:
            out.append(f"{st} len {lens[st]} < promised {mn}")
    for st, mx in (card.get("maxlen") or {}).items():
        if st in lens and mx < 13 and lens[st] > mx + SLACK_LEN:
            out.append(f"{st} len {lens[st]} > promised max {mx}")
    for st, rank in _HOLDING_RE.findall(card.get("gib_raw") or ""):
        if not holds(hand_pbn, st.upper(), rank):
            out.append(f"gloss asserts {st}{rank}, not held")
    return out


def _ask_answer_violation(entry: dict, entries: list[dict], j: int,
                          hand_pbn: str) -> str | None:
    """Keycard/ace-count and trump-queen statements, checked exactly."""
    card = entry.get("card") or {}
    text = (card.get("text") or "").strip()
    low = text.lower()
    if "key card" in low or "keycard" in low:
        counts = _stated_counts(text)
        if counts:
            trump = _trump_from_context(entries, j)
            have = keycards(hand_pbn, trump)
            if have not in counts:
                return (f"gloss says {text!r} but hand has {have} "
                        f"keycard(s) ({trump or '?'} trump)")
    elif re.search(r"\baces?\b", low) and "?" not in low:
        counts = _stated_counts(text)
        if counts:
            have = keycards(hand_pbn, None)
            if have not in counts:
                return f"gloss says {text!r} but hand has {have} ace(s)"
    if "?" not in low:      # "? queen" is an ask, not a statement
        trump = _trump_from_context(entries, j)
        if trump:
            has_q = holds(hand_pbn, trump, "Q")
            if "no queen" in low and has_q:
                return f"gloss denies the {trump} queen, hand holds it"
            if _QUEEN_YES_RE.search(text) and "no queen" not in low \
                    and not has_q:
                return f"gloss asserts the {trump} queen, hand lacks it"
    return None


def hand_violations(stem_entries: list[dict], option_cards: dict,
                    hands: list[str], dealer_i: int,
                    hero_i: int) -> tuple[list[str], list[str]]:
    """Gloss-vs-actual-cards check for a board. Returns (fatal, soft).

    fatal — the board must not be published:
      * any violation on a STEM call (the stem is forced context; if it
        misdescribes the hand that actually bid it, the trainee analyzes
        a lie), and
      * hard assertions on an OPTION: keycard/ace counts, explicit
        holdings (!CQ), trump-queen statements. Offering "5♠ = queen and
        king" to a hand holding neither is nonsense, not a style choice.

    soft — kept, for annotation only: an option whose HCP/length band the
    hero shades ("shows 14-17", hero has 11). That is not a defect — the
    stretch/underbid dilemma is exactly what this trainer trades in."""
    fatal, soft = [], []
    for j, e in enumerate(stem_entries):
        if e.get("call") in ("P", "X", "XX"):
            continue
        bidder = hands[seat_of(dealer_i, e["idx"])]
        for v in card_vs_hand(e.get("card") or {}, bidder):
            fatal.append(f"stem {e['call']} ({e.get('seat', '?')}): {v}")
        v = _ask_answer_violation(e, stem_entries, j, bidder)
        if v:
            fatal.append(f"stem {e['call']} ({e.get('seat', '?')}): {v}")
    hero = hands[hero_i]
    entries = list(stem_entries)
    for bid, card in option_cards.items():
        if bid in ("P", "X", "XX"):
            continue
        for v in card_vs_hand(card or {}, hero):
            (fatal if "asserts" in v else soft).append(f"option {bid}: {v}")
        e = {"call": bid, "card": card}
        v = _ask_answer_violation(e, entries + [e], len(entries), hero)
        if v:
            fatal.append(f"option {bid}: {v}")
    return fatal, soft


# GIB states suit length in prose too; parse_meaning ignores these, so the
# band check reads them itself lest it accuse a gloss of omitting a suit it
# stated in words. ("biddable" ~4+, "rebiddable" ~5+, "twice rebiddable" ~6+)
_REBID_RE = re.compile(r"(twice rebiddable|rebiddable|biddable)\s*!([CDHS])",
                       re.I)
_REBID_LEN = {"biddable": 4, "rebiddable": 5, "twice rebiddable": 6}


def stated_minlen(card: dict) -> dict:
    """Suit minima a gloss states, parsed OR prose."""
    out = dict(card.get("minlen") or {})
    for phrase, st in _REBID_RE.findall(card.get("gib_raw") or ""):
        st = st.upper()
        out[st] = max(out.get(st, 0), _REBID_LEN[phrase.lower()])
    return out


def band_vs_card(card: dict, feats: dict, call: str,
                 known_minlen: dict | None = None) -> list[str]:
    """One stem call: Ben's measured meaning band vs GIB's parsed card.

    known_minlen — suit minima already STATED for this seat by earlier
    glosses (cumulative). A response needn't restate shape its earlier
    bids established, so the omitted-suit rule only fires on suits absent
    from the whole story so far."""
    out = []
    if not card or feats.get("n", 0) < BAND_N_MIN:
        return out
    denom = call[1:] if len(call) > 1 else ""
    minlen = stated_minlen(card)
    known = dict(known_minlen or {})
    for st, v in minlen.items():
        known[st] = max(known.get(st, 0), v)
    for st in "SHDC":
        # the bid systemically promises 5+ in a suit OTHER than the one it
        # names, and neither this gloss nor any earlier one for this seat
        # mentions it -> the explanation describes a different convention
        # (Leaping Michaels glossed as a natural club overcall)
        if st != denom and feats["len5plus"][st] >= BAND_P5_SURE \
                and known.get(st, 0) < 4:
            out.append(f"bid promises 5+{st} "
                       f"(P={feats['len5plus'][st]:.2f}) but gloss omits it")
        # the gloss promises a suit the bid's own meaning refutes
        if minlen.get(st, 0) >= 5 and feats["len_avg"][st] < BAND_LEN_REFUTED:
            out.append(f"gloss promises {minlen[st]}+{st} but bid shows "
                       f"avg {feats['len_avg'][st]:.1f}")
    hcp = card.get("hcp")
    if hcp:
        lo, hi = int(hcp[0]), int(hcp[1])
        if feats["hcp_p90"] < lo - BAND_HCP_GAP or \
                feats["hcp_p10"] > hi + BAND_HCP_GAP:
            out.append(f"gloss hcp {lo}-{hi} vs measured "
                       f"{feats['hcp_p10']:.0f}-{feats['hcp_p90']:.0f}")
    return out


def band_violations(engine, spot, stem_entries: list[dict]) -> list[str]:
    """Gloss-vs-Ben's-measured-meaning violations for every non-pass stem
    call. Costs one sampling pass per checked call; callers run it late,
    on boards that already passed the statistical judge."""
    from .ben import seat_features

    out = []
    bots = {}
    known: dict[int, dict] = {}     # per seat: suit minima stated so far
    for j, e in enumerate(stem_entries):
        call = e.get("call")
        if call in ("P", "X", "XX"):
            continue
        bidder_i = seat_of(spot.dealer_i, e["idx"])
        observer_i = (bidder_i + 2) % 4         # partner sees the call
        if observer_i not in bots:
            bots[observer_i] = engine.bot(spot.hands[observer_i], observer_i,
                                          spot.dealer_i, spot.vul)
        hands_np, n = engine.sample_prefix(
            bots[observer_i], spot.dealer_i, spot.stem[:e["idx"] + 1])
        feats = seat_features(hands_np, bidder_i,
                              engine.models.n_cards_bidding)
        card = e.get("card") or {}
        for v in band_vs_card(card, feats, call,
                              known_minlen=known.get(bidder_i)):
            out.append(f"stem {call} ({e.get('seat', '?')}): {v}")
        acc = known.setdefault(bidder_i, {})
        for st, v in stated_minlen(card).items():
            acc[st] = max(acc.get(st, 0), v)
        if feats.get("n", 0) >= BAND_N_MIN:
            # once the band itself establishes a suit it is "known" — an
            # omission fires at the first call that hides it, not again on
            # every later call by the same seat
            for st in "SHDC":
                if feats["len5plus"][st] >= BAND_P5_SURE:
                    acc[st] = max(acc.get(st, 0), 5)
    return out


def record_violations(rec: dict) -> tuple[list[str], list[str]]:
    """The cheap (no-engine) audit for an already-built problem record:
    the stored stem/option cards vs the stored full deal. Lets the same
    gate vet historical pools and freshly forged batches alike. Returns
    (fatal, soft) as ``hand_violations`` does."""
    hands = [rec["full_deal"][s] for s in SEATS]
    dealer_i = SEATS.index(rec["dealer"])
    hero_i = SEATS.index(rec["seat"])
    stem_entries = (rec.get("explanations") or {}).get("stem") or []
    option_cards = {o["bid"]: o.get("card")
                    for o in (rec.get("explanations") or {}).get(
                        "options") or []}
    return hand_violations(stem_entries, option_cards, hands, dealer_i,
                           hero_i)
