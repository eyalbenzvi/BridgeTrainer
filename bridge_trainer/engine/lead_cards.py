"""Strict separation of the card concepts the opening-lead evaluator must
never conflate, plus the ONE seat-conversion layer between the application's
absolute seats and Ben's hero-relative sample rows.

Vocabulary (see docs/lead_evaluator_audit.md §3):

    physical_card   exact legal card, e.g. "S7"          -> what DDS evaluates
    display_card    exact card shown in the UI           == physical_card
    dds_card        exact physical card sent to DDS      == physical_card
    policy_action   Ben's abstract 32-card lead action   -> "S-low" for 7..2

The physical/display/dds cards are ALWAYS identical strings; only the policy
action may collapse the low spots of a suit. Nothing in this module ever maps
a policy action back to a physical card — the fold is one-way and is used
solely to look up or record Ben's neural policy mass.

Suit and rank orderings are encoded exactly ONCE here; every other module
imports these helpers rather than re-deriving an ordering, so a stray
inversion of 2..A cannot creep in.
"""
from __future__ import annotations

SUITS = "SHDC"
# Descending strength order: index 0 == Ace (strongest), 12 == deuce.
RANKS = "AKQJT98765432"

# The rank index at and below which a card is a "low spot" for policy folding.
# "7" .. "2" all share Ben's single low slot; "8" and up keep their identity.
_LOW_RANK_INDEX = RANKS.index("7")   # == 7

FULL_DECK = frozenset(s + r for s in SUITS for r in RANKS)

SEATS = "NESW"   # absolute seat order used everywhere in the application


def suit_of(card: str) -> str:
    return card[0]


def rank_of(card: str) -> str:
    return card[1]


def rank_index(card: str) -> int:
    """Strength rank: 0 (Ace) .. 12 (deuce). Higher card => lower index."""
    return RANKS.index(card[1])


def is_low_spot(card: str) -> bool:
    """True for 7..2 — the spot cards Ben folds into one policy action."""
    return rank_index(card) >= _LOW_RANK_INDEX


def physical_cards(hand_pbn: str) -> list[str]:
    """The 13 exact physical cards of a PBN hand.

    'K93.752.A854.T62' -> ['SK','S9','S3','H7','H5','H2','DA','D8','D5','D4',
                            'CT','C6','C2'] in S,H,D,C then descending rank.
    Raises ValueError on a malformed hand so callers fail loudly rather than
    silently score a 12-card or duplicated hand.
    """
    parts = hand_pbn.split(".")
    if len(parts) != 4:
        raise ValueError(f"hand must have 4 suit groups: {hand_pbn!r}")
    out: list[str] = []
    for suit, holding in zip(SUITS, parts):
        for r in holding:
            if r not in RANKS:
                raise ValueError(f"bad rank {r!r} in hand {hand_pbn!r}")
            out.append(suit + r)
    if len(out) != 13:
        raise ValueError(f"hand must have 13 cards: {hand_pbn!r}")
    if len(set(out)) != 13:
        raise ValueError(f"duplicate card in hand: {hand_pbn!r}")
    return out


def canonical_hand(hand_pbn: str) -> str:
    """A hand's canonical PBN with each suit sorted high-to-low, so two spellings
    of the same 13 cards compare equal (used by the leader-identity invariant)."""
    parts = hand_pbn.split(".")
    if len(parts) != 4:
        raise ValueError(f"hand must have 4 suit groups: {hand_pbn!r}")
    fixed = ["".join(sorted(p, key=RANKS.index)) for p in parts]
    return ".".join(fixed)


# -- policy action (fold) — never touches the physical/DDS card --------------
POLICY_LOW = "low"


def policy_action(card: str) -> str:
    """Ben's abstract opening-lead action for a physical card.

    Honors and the 8/9 keep their exact rank ("HK", "S9"); the low spots 7..2
    fold to "<suit>-low" ("S-low"). This is ONLY for querying/recording Ben's
    policy probability — it is never used to choose or name the card DDS
    evaluates.
    """
    if is_low_spot(card):
        return card[0] + "-" + POLICY_LOW
    return card


def lead_code32(card: str) -> int:
    """Ben's 32-card lead code: suit*8 + rank, spots 7..2 folded to slot 7.
    Suit order S,H,D,C. Kept identical to engine.ben.lead_code32 and
    engine.lead_classify.lead_code32 (the canonical copy lives here)."""
    return SUITS.index(card[0]) * 8 + min(RANKS.index(card[1]), _LOW_RANK_INDEX)


# -- endplay Card -> our token ----------------------------------------------
_SUIT_FROM_ENDPLAY = {"spades": "S", "hearts": "H",
                      "diamonds": "D", "clubs": "C"}


def token_from_endplay_card(card) -> str:
    """endplay `Card` -> our 'SK' token. endplay ranks are named 'RK','R2',
    'RT', ... so the physical rank is the second character."""
    return _SUIT_FROM_ENDPLAY[card.suit.name] + card.rank.name[1]


# -- the single seat-conversion layer ---------------------------------------
def hero_first_to_absolute(rows_per_seat, hero_seat_i: int) -> tuple:
    """Convert a Ben sample row (hero-relative) to absolute-seat hands.

    Ben serialises a sampled layout hero-first: the hand at position ``p`` in
    the row belongs to absolute seat ``(hero_seat_i + p) % 4``. This is the
    SAME rotation the working bidding DD uses in engine.ben._tricks_dd_memo
    (``leader = (leader + 4 - bot.seat) % 4``); keeping the inverse in one
    place stops ad-hoc rotations from scattering through the code.

    Returns hands indexed by absolute seat N,E,S,W (0,1,2,3).
    """
    rows = list(rows_per_seat)
    if len(rows) != 4:
        raise ValueError(f"expected 4 hands, got {len(rows)}")
    if not 0 <= hero_seat_i < 4:
        raise ValueError(f"hero seat out of range: {hero_seat_i}")
    absolute: list[str | None] = [None, None, None, None]
    for p, hand in enumerate(rows):
        absolute[(hero_seat_i + p) % 4] = hand
    return tuple(absolute)
