"""Explanation-consistency gate: disqualify boards whose displayed call
meanings are wrong — either the auction is engine-weird or GIB's gloss
describes a different system than Ben actually bid.

Motivating board (ben1-01354c2d): Ben answered a 4NT ask with 5♦ — glossed
by GIB as "One or four key cards" — while holding two, and the 5NT
candidate's gloss asserted the trump queen the hero does not hold. A human
can neither follow such an auction nor trust its explanations, so the board
must not be published. Both faults are visible mechanically at generation
time; nothing here consults an LLM or a human.

Second motivating board (ben1-0135752a): after P-1NT-P, Ben offered 2NT as
a natural invitational raise (its rollouts pass it or raise to 3NT), but
GIB's 2/1 card glosses that sequence "Minor transfer -- 6+ !C" — a
convention Ben does not play. The hero held four clubs, so the gloss was
a lie about the very option being taught. Two rules catch this class:
an OPTION whose gloss promises a suit length the hero breaches beyond
slack is now fatal (not a style shade), and the band check compares
Ben's measured meaning of every offered candidate — not just stem calls —
against GIB's card, with the length-refutation threshold scaled to the
promised length (a 6+ promise is refuted by an average well above the
one that refutes a 5+ promise).

Third motivating board (ben1-19f93c012bc): after 1♥-P-1♠-3♦ GIB glosses
X as "5+ !H; 1- !S; 17-21 HCP; biddable !D" — its own strong two-suited
action double — but Ben doubles holding three spades, a singleton
diamond and 14 HCP (a support/action double GIB does not play there).
The gate used to skip X/XX wholesale, so the lying card was published
on the very option the board teaches. Doubles and redoubles are now
vetted like any suit bid — GIB's card for them states real hand
requirements — in both checks, stems and options alike. Only Pass stays
exempt: its "No suitable call" gloss merely restates constraints the
seat's earlier bids established, which those bids' own entries already
vet.

Fourth motivating board (ben1-19f93c01296): after 1♣-P-1♥-P-2♦-P-3♣-P
the hero (opener, 16 HCP) was offered Pass — and the rollout made Pass
the graded-best call, 2.8 IMPs ahead of 3NT. But GIB glosses partner's
3♣ "3+ !C; 4+ !H; 8+ HCP; forcing to 3N" and repeats the commitment on
the pass's own card, so in the system the explanations claim to teach
("standard 2/1 Game Force") that pass is not a legal choice at all. Ben
none the less rates it 46% of the policy, which is *why* the evidence
favours it: the partner hands its sampler draws after 3♣ are hands that
would not have forced. Either way the board is unpublishable — it either
grades a system violation as best or narrates a force nobody is playing —
and ``forcing_pass_violations`` catches it from the stored cards alone.

Fifth motivating board (ben1-19f947b9723): after 2NT-P-3D-P-3H-P the
hero (9 HCP, six hearts) was offered 4♥ glossed "Mild slam try" and 4NT
glossed "Quantitative invite", and the board's winner was a direct 6♥.
But the rollout behind those two options ends in 4♥ on 512 of 512
layouts and in a slam on 512 of 512 respectively: in the system that
produced the evidence, neither call is an invitation — 4♥ is a signoff
partner never accepts and 4NT is a commitment partner never declines.
So the 5.3 IMPs charged against 4♥ (the call Ben's own policy gives 51%)
measure the partner model's refusal to accept a try the same evidence
says should be accepted — the winner reaches slam and makes it — not the
bridge merit of inviting, and the board teaches "never invite, blast".
``invite_violations`` catches both halves from the stored record alone.

Independent checks — these four, plus the three rollout rules of
docs/4nt_projection_and_gloss_gate.md (``meaningless_gloss_violations``,
``forcing_contract_violations``, ``answer_insensitive_violations``), which
are documented at their own definitions:

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
    Ben's OWN meaning of a stem call or offered candidate — suit-length/HCP
    statistics over the layouts Ben's sampler accepts after that call — is
    compared against GIB's parsed card. Fires when the bid systemically
    promises 5+ cards in a suit the gloss does not mention (Leaping
    Michaels glossed as a natural club overcall), when the gloss promises
    a 5+ suit the bid's band refutes (Minor transfer glossed onto a natural
    invitational 2NT), or when the HCP bands are disjoint. Pass and
    low-n bands are skipped. On the same sampling pass it also runs R7,
    ``band_vs_shaded_hand``: the one-card length shade ``SLACK_LEN``
    forgives, on a call whose band says the shortfall is the system rather
    than a shade (ben1-19f975caec3: 2♠ glossed "Weak two bid, 6+♠" offered
    to five spades, and Ben's weak twos measure 5.09 with P(6+)=0.09).

``forcing_pass_violations`` (cheap, no engine, no hand)
    Pass is offered while the partnership is still under a live force.
    GIB carries the commitment on the pass's OWN card ("forcing to 3N",
    "forcing") for exactly as long as it lives — an opponent's bid over
    the forcing call discharges it and the clause disappears — so the
    flag ``parse_meaning`` already sets is the whole test. Purely an
    auction fact: no cards, no sampling, same answer for every hand.

``game_force_stop_violations`` (cheap, no engine, no hand — reads the rollout
    that was already paid for)
    An option whose rollout parks the hero's side in a partscore although the
    two hands' own glosses have stated game values in an uncontested auction
    (ben1-19f9c2b962c: 1NT "15-17" opposite 3♣ "13+ total points" = 28 stated
    points, and the offered 4♣ shown as "Leads to 4♣N 57%"). Same fault as R3
    one level up: there the passed-out call carried GIB's "forcing" clause,
    here the force is in the arithmetic of the two cards.

``invite_violations`` (cheap, no engine, no hand — reads the rollout that
    was already paid for)
    An option GIB glosses as an invitation ("Invitational to 3NT game",
    "Game try suit", "Quantitative invite", "Mild slam try") whose
    rollout gives partner no decision to make: the invited level is
    reached on essentially every sampled layout, or on none of them while
    the board's own winner gets there and beats the invitation. Both
    halves compare the displayed MEANING against the EVIDENCE the board
    publishes, which is why they need neither the engine nor the cards.
"""
from __future__ import annotations

import re

from .conventions import CLASS_RANK, contract_class, contract_side, seat_of

SEATS = "NESW"
SLACK_HCP = 2          # GIB band may be shaded by a couple of points
SLACK_LEN = 1          # ... and a promised length by one card
SLACK_PTS = 2          # ... and a total-points band by a couple of points
SHADE_FATAL = 5        # An OPTION's point band the hero misses by less than
                       # this is the stretch/underbid dilemma the trainer
                       # trades in, and stays soft. At this gap and beyond it
                       # is not a shade a player weighs but a different hand:
                       # ben1-19f94d0042d offered "Invitational to 3NT game,
                       # 24-24" to nine HCP.
SELLOUT_HCP = 15       # A seat that never bids at all, holds this much and let
                       # the auction die at the one level. Measured on the
                       # published pool: at 15 exactly one board fires
                       # (lead1i-19fa5b321a7, 15 HCP with six clubs and a
                       # singleton, passing 1NT); at 14 thirteen do and most
                       # are flat 14-counts correctly passing an opponent's
                       # 1NT, which is why the bar is not there.
COLD_SET_SHARE = 0.02  # No offered lead beats the contract on more than this
                       # share of layouts (or every lead beats it on 1 - this)
OVERBID_NT_HCP = 21    # 3NT+ reached in an uncontested undoubled auction on at
OVERBID_SUIT_HCP = 19  # most this many combined HCP; likewise a 4-level game.
                       # Contested and doubled auctions are exempt — a cheap
                       # game over an opponent's bidding is a sacrifice.
BAND_N_MIN = 30        # below this many samples an HCP PERCENTILE proves
                       # nothing (p10/p90 of a handful of layouts is noise)
BAND_LEN_N_MIN = 12    # ... but a suit-length mean/share still does, and the
                       # gap matters: Ben's sampler answers "I cannot place
                       # this call in any system" by falling back to its rescue
                       # floor (min_sample_hands_auction = 15 layouts, filter
                       # off — sample.py), so a blanket n < 30 skip disabled
                       # the whole check on exactly the calls that needed it.
                       # ben1-19f975cad49 offered four such candidates (n = 15,
                       # sampler quality 0.48-0.56 against its own 0.70
                       # threshold) and its 4♦ gloss — "5+ !C" against a
                       # measured avg 3.6, P5+ 0.07 — went unchecked. The
                       # returned layouts are the BEST-fitting ones, so a
                       # length refutation measured on them is conservative;
                       # 12 keeps the rescue floor in and genuine noise out.
                       # See docs/4nt_projection_and_gloss_gate.md §4.
BAND_P5_SURE = 0.90    # measured "the bid promises 5+ here"
BAND_LEN_SLACK = 2.0   # gloss says N+, band average below N-2 refutes it
BAND_P5_REFUTED = 0.5  # gloss says 5+/6+, most sampled hands lack even 5
BAND_PLEN_DENIED = 0.15  # R7, the mirror of BAND_P5_SURE at the length a gloss
                       # actually promises: measured "the call does NOT promise
                       # N here". Set at the pool's own gap — measured
                       # 2026-07-26 (docs/system_fit_gate.md) over the 472
                       # published bidding boards, 71 stem/option rows state a
                       # minimum of 5+ cards that the bidder's hand is short
                       # of, and they split: 24 rows at P(N+) <= 0.13 (Ben's
                       # weak twos are five-card suits, its three-level
                       # preempts six-card ones — the gloss is describing
                       # another call) and 47 at P(N+) >= 0.20 rising to 1.00
                       # (a jump overcall Ben means as six, held with five: the
                       # shade SLACK_LEN exists for). Any floor in (0.14, 0.20]
                       # picks the same 24 rows.
BAND_HCP_GAP = 2       # gloss and band HCP ranges must at least touch ±this.
                       # Confirmed empirically 2026-07-25 (docs/
                       # forcing_pass_gate.md): over 249 stem/option rows on
                       # 80 published boards this fires on 0 — GIB states
                       # floors ~1.8 HCP above Ben's measured mean (p95 +1.0,
                       # max +2.0), so ±2 is the smallest tolerance that is
                       # clean, and no tighter HCP rule catches a false
                       # FORCING claim without killing ~25% of the pool.
                       # That class is caught by forcing_pass_violations.

# Invitation gate (ben1-19f947b9723). Thresholds are deliberately at the
# extremes: acceptance rate is a genuine bridge quantity (the hero's hand
# is fixed, partner's is sampled), so a try partner accepts 3% of the time
# is a thin invitation, not a mislabelled one. Measured 2026-07-25 over the
# 477 published bidding boards (docs/invitation_gate.md): 57 offered
# options carry an invitational gloss, their acceptance rates spread
# smoothly from 0.00 to 1.00, and only 5 rows on 4 boards sit at the
# extremes below.
INVITE_NEVER = 0.02      # partner essentially never accepts
INVITE_ALWAYS = 0.98     # ... or essentially never declines
INVITE_N_MIN = 100       # same evidence floor as verdict.N_MIN
INVITE_COVER_MIN = 0.95  # the distribution must account for the samples
INVITE_OURS_MIN = 0.90   # ... and our side must be the one deciding
INVITE_WINNER_REACH = 0.5   # the winner does reach the invited level
INVITE_MARGIN_IMPS = 1.0    # ... and the refused invitation is charged for it

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


def max_total_points(hand_pbn: str) -> int:
    """The most "total points" any counting system can credit this hand.

    GIB states total points, not HCP, on a large share of its cards, and the
    renderer prints that band whenever no HCP band exists — so the band needs
    a bound to be checked against. This is deliberately the LOOSEST bound: HCP
    plus shortness (void 3, singleton 2, doubleton 1) plus length (a point per
    card over four in each suit), i.e. both distributional methods added
    together. No system counts more than that, so a band whose floor is above
    this number is not a shade — it describes a different hand."""
    lens = suit_lengths(hand_pbn)
    shortness = sum({0: 3, 1: 2, 2: 1}.get(v, 0) for v in lens.values())
    length = sum(max(0, v - 4) for v in lens.values())
    return hand_hcp(hand_pbn) + shortness + length


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


def band_gap(card: dict, hand_pbn: str) -> int:
    """How far outside the card's POINT bands (HCP and total points) the hand
    falls, in points, beyond the slack each band already allows. 0 when the
    hand is inside them. Feeds ``SHADE_FATAL``: the same miss is a style shade
    at 3 points and a different hand at 8, and only the size tells them
    apart."""
    gap = 0
    hcp = card.get("hcp")
    if hcp:
        have, lo, hi = hand_hcp(hand_pbn), int(hcp[0]), int(hcp[1])
        gap = max(gap, lo - have, have - hi)
    pts = card.get("pts")
    if pts:
        lo, hi = int(pts[0]), int(pts[1])
        gap = max(gap, lo - max_total_points(hand_pbn),
                  hand_hcp(hand_pbn) - hi)
    return max(0, gap)


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
    # R8, the total-points band. The renderer shows it in place of an HCP band
    # (explain.terse_meaning), so it is a claim a trainee reads and nothing
    # used to check it. Bounded both ways: the floor against the loosest total
    # any system can count, the ceiling against plain HCP (no distribution can
    # take points away). Published example: lead1-b8b469b31 showed "6-11 pts"
    # over T654.932.T95.983 — 0 HCP and a flat hand.
    pts = card.get("pts")
    if pts:
        lo, hi = int(pts[0]), int(pts[1])
        ceiling = max_total_points(hand_pbn)
        floor = hand_hcp(hand_pbn)
        if lo > ceiling + SLACK_PTS:
            out.append(f"pts band {lo}-{hi} above the hand's {ceiling} max")
        elif hi < floor - SLACK_PTS:
            out.append(f"pts band {lo}-{hi} below the hand's {floor} HCP")
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
        a lie),
      * hard assertions on an OPTION: keycard/ace counts, explicit
        holdings (!CQ), trump-queen statements. Offering "5♠ = queen and
        king" to a hand holding neither is nonsense, not a style choice,
      * an OPTION whose gloss promises a suit length the hero breaches
        beyond slack. A reported breach is already 2+ cards short of the
        promise — that is never a stretch a player weighs; it means the
        gloss describes a convention Ben is not playing (ben1-0135752a:
        a natural invitational 2NT glossed "Minor transfer -- 6+ !C"
        offered to a hand with four clubs).

    soft — kept, for annotation only: an option whose point band the hero
    shades by less than ``SHADE_FATAL`` ("shows 14-17", hero has 13) or
    whose length CAP the hero exceeds (3NT over a long suit). That is not
    a defect — the stretch/underbid dilemma is exactly what this trainer
    trades in. A band the hero misses by ``SHADE_FATAL`` or more is fatal:
    at that distance the gloss is not describing a stretched version of
    the hand it is offered to (ben1-19f94d0042d offered "Invitational to
    3NT game, 24-24" to nine HCP).

    X/XX go through the same vetting as suit bids — GIB's card for a
    double states real hand requirements, and a breached one is the same
    lie (ben1-19f93c012bc: X glossed "5+!H, 4+!D, 17-21" offered to a
    hand with a singleton diamond and 14 HCP).

    Pass is vetted too, since 2026-07-28. The old exemption rested on the
    claim that a pass's gloss "only restates constraints the seat's earlier
    bids established, which those bids' own entries already vet" — and that
    is false. GIB's pass card carries claims the seat's own bids never made,
    and the renderer prints them like any other: lead1-19f9f6c19be showed
    North's final pass as "5♠, 25+" over AK8, lead1-19fa45cd957 showed
    West's as "6+♥" over a singleton, lead1i-19fa5191916 showed North's as
    "4+♠" over a doubleton."""
    fatal, soft = [], []
    for j, e in enumerate(stem_entries):
        bidder = hands[seat_of(dealer_i, e["idx"])]
        for v in card_vs_hand(e.get("card") or {}, bidder):
            fatal.append(f"stem {e['call']} ({e.get('seat', '?')}): {v}")
        v = _ask_answer_violation(e, stem_entries, j, bidder)
        if v:
            fatal.append(f"stem {e['call']} ({e.get('seat', '?')}): {v}")
    hero = hands[hero_i]
    entries = list(stem_entries)
    for bid, card in option_cards.items():
        if bid == "P":
            # An option's Pass card restates what the hero's OWN earlier calls
            # established, and those entries are vetted above — unlike a stem
            # pass, which speaks for a seat whose cards nothing else describes.
            continue
        gap = band_gap(card or {}, hero)
        for v in card_vs_hand(card or {}, hero):
            (fatal if "asserts" in v or "< promised" in v
             or (gap >= SHADE_FATAL and ("hcp " in v or "pts band" in v))
             else soft).append(f"option {bid}: {v}")
        e = {"call": bid, "card": card}
        v = _ask_answer_violation(e, entries + [e], len(entries), hero)
        if v:
            fatal.append(f"option {bid}: {v}")
    return fatal, soft


def auction_violations(auction_entries: list[dict], hands: list[str],
                       dealer_i: int) -> list[str]:
    """Displayed calls whose gloss contradicts the hand that made them, for a
    problem that shows a COMPLETE auction and no candidate set of its own —
    i.e. an opening-lead board.

    Same rule and same slack as a bidding board's STEM (``hand_violations``),
    and fatal for the same reason, only more so: the auction IS the evidence a
    leader reasons from. Measured over the published lead pool 2026-07-25,
    18% of boards showed at least one such call — Ben bidding a splinter or a
    two-suited cue that GIB narrates as a natural suit bid, e.g. 4♣ with a
    club VOID glossed "twice rebiddable !C" and the claim then repeated on the
    4NT and 6♠ that followed. The lead forge never ran this check, which is
    why the rate was the same on boards forged that morning.

    Pass is vetted here too, as in ``hand_violations``, and this is where it
    matters most: a lead board's auction is over, so most of what it shows a
    trainee IS passes, and the final pass carries the fullest card GIB ever
    emits. Three of the five boards the change caught were lead boards printing
    a suit-length promise the passer contradicts."""
    out = []
    for j, e in enumerate(auction_entries):
        idx = e.get("idx", j)
        bidder = hands[seat_of(dealer_i, idx)]
        for v in card_vs_hand(e.get("card") or {}, bidder):
            out.append(f"call {idx} {e['call']} ({e.get('seat', '?')}): {v}")
        v = _ask_answer_violation(e, auction_entries, j, bidder)
        if v:
            out.append(f"call {idx} {e['call']} ({e.get('seat', '?')}): {v}")
    return out


def sellout_violations(auction: list[str], hands: list[str],
                       dealer_i: int) -> list[str]:
    """A seat that never bids at all, holds ``SELLOUT_HCP`` or more, and let the
    auction die at the ONE level (R9).

    Not a gloss check and not a style call: a hand this strong that never opens
    its mouth while the auction stays at the cheapest level is a bid no
    partnership misses, and a board built on it teaches an auction that could
    not happen. lead1i-19fa5b321a7 ran P-P-1NT-P-P-P and then asked the hero —
    15 HCP, six clubs, a singleton — for the opening lead against 1NT.

    Only the seat's OWN silence counts, so a hand that passed once and came in
    later (a trap pass behind an opener, then an overcall) never fires. The
    one-level condition is what keeps ordinary discipline out: passing a
    preempt or a game bid with a good hand is normal bridge."""
    from .conventions import final_contract as _fc
    fc = _fc(auction, dealer_i)
    if fc is None or fc["level"] != 1:
        return []
    out = []
    for si in range(4):
        idxs = [j for j in range(len(auction)) if seat_of(dealer_i, j) == si]
        if not idxs or any(auction[j] != "P" for j in idxs):
            continue
        have = hand_hcp(hands[si])
        if have >= SELLOUT_HCP:
            out.append(f"{SEATS[si]} never bid, holds {have} HCP "
                       f"({hands[si]}), and the auction died at the one level")
    return out


def overbid_contract_violations(auction: list[str], hands: list[str],
                                dealer_i: int) -> list[str]:
    """A game reached in an UNCONTESTED, undoubled auction on too few combined
    HCP (R10) — the declaring side's own free-standing overbid, not a save.

    lead1-b8b5bf70a bid 3NT on 21 combined, the responder having jumped to 3♣
    and then 3NT while void in the major partner opened. A trainee asked to
    defend that is being asked to believe an auction no partnership produces.

    Both exemptions matter. A doubled contract is a sacrifice by definition,
    and so in practice is a cheap game the opponents bid over: 4♥ on 17 with a
    nine-card fit over an opposing 1♣ is a real action, and flagging it would
    reject good boards."""
    from .conventions import final_contract as _fc
    fc = _fc(auction, dealer_i)
    if fc is None or fc["doubled"]:
        return []
    level, denom, decl = fc["level"], fc["denom"], fc["declarer_i"]
    if not ((denom == "NT" and level >= 3) or level >= 4):
        return []
    side = {decl, (decl + 2) % 4}
    if any(auction[j] not in ("P", "X", "XX")
           and seat_of(dealer_i, j) not in side
           for j in range(len(auction))):
        return []                       # contested: a cheap game is a save
    combined = sum(hand_hcp(hands[i]) for i in sorted(side))
    cap = OVERBID_NT_HCP if denom == "NT" else OVERBID_SUIT_HCP
    if combined <= cap:
        return [f"{level}{denom} by {SEATS[decl]} reached in an uncontested "
                f"auction on {combined} combined HCP"]
    return []


def cold_contract_violations(candidates: list[dict],
                             contract: str) -> list[str]:
    """No offered lead changes the result: every one of them beats the contract
    on at most ``COLD_SET_SHARE`` of layouts, or every one beats it on all but
    that share (R11).

    A lead board is a question about which card to play. When the contract is
    cold — or dead — whatever hits the table, the board has an answer but no
    question, and its published "best lead" is measuring the tail of the trick
    distribution rather than a defensive decision. Kept as a rejection rather
    than a warning because the boards this fires on are also the ones with the
    thinnest margins between the best card and the worst."""
    sps = [c["set_prob"] for c in candidates if c.get("set_prob") is not None]
    if not sps:
        return []
    if max(sps) <= COLD_SET_SHARE:
        return [f"no offered lead beats {contract} on more than "
                f"{max(sps):.0%} of layouts"]
    if min(sps) >= 1.0 - COLD_SET_SHARE:
        return [f"every offered lead beats {contract} on at least "
                f"{min(sps):.0%} of layouts"]
    return []


def ev_argmax_violations(table: list[dict], accepted: str) -> list[str]:
    """The graded answer must be the one the published evidence favours (R12).

    ``verdict.judge`` picks ``accepted`` as the EV argmax and then states every
    OTHER row's margin against it, so every other ``ev_imp_vs_top`` must be
    <= 0 by construction. ben1-19f9609a4b3 published 3♥ as correct while its own
    table gave X +0.10 IMPs against 3♥ and the best result on 61% of layouts
    against 3♥'s 31% — a trainee choosing the call the page recommends by the
    numbers was marked wrong. X carried the lowest policy of the three, which
    is the signature of a menu-completion option evaluated after the winner was
    chosen and never re-argmaxed; this catches that ordering bug wherever it
    happens rather than trusting the pipeline not to reintroduce it."""
    out = []
    for row in table:
        if row.get("bid") == accepted:
            continue
        ev = row.get("ev_imp_vs_top")
        if ev is not None and ev > 0:
            out.append(f"option {row['bid']} measures {ev:+.2f} IMPs against "
                       f"the accepted {accepted} (best on "
                       f"{row.get('best_share')} of layouts)")
    return out


def mode_accept_violations(rec: dict) -> list[str]:
    """A lead board's top-level ``accepted`` must match the accepted set of the
    mode that actually grades it (R13).

    lead1i-19fa11e39af carries accepted ["CT","C5","C4","C3"] with
    by_mode.IMP.accepted ["C5","C4","C3"] and target_mode IMP, so ♣T is right
    or wrong depending on which field the client happens to read."""
    mode = (rec.get("training") or {}).get("target_mode")
    verdict = rec.get("verdict") or {}
    by_mode = (verdict.get("by_mode") or {}).get(mode or "") or {}
    acc, want = verdict.get("accepted"), by_mode.get("accepted")
    if not mode or want is None or acc is None:
        return []
    if sorted(acc if isinstance(acc, list) else [acc]) != sorted(want):
        return [f"accepted {acc} != by_mode.{mode}.accepted {want}, and "
                f"{mode} is the board's target mode"]
    return []


def lead_record_violations(rec: dict) -> list[str]:
    """``auction_violations`` for an already-built lead record (the audit's
    entry point, mirroring ``record_violations`` for bidding boards), plus the
    four lead-only record gates: the sell-out auction, the uncontested overbid,
    the cold contract and the target-mode grading mismatch."""
    hands = [rec["full_deal"][s] for s in SEATS]
    entries = (rec.get("explanations") or {}).get("auction") or []
    dealer_i = SEATS.index(rec["dealer"])
    auction = list(rec.get("auction") or [])
    out = auction_violations(entries, hands, dealer_i)
    out += sellout_violations(auction, hands, dealer_i)
    out += overbid_contract_violations(auction, hands, dealer_i)
    out += cold_contract_violations(rec.get("candidates") or [],
                                    rec.get("contract") or "the contract")
    out += mode_accept_violations(rec)
    return out


# GIB's own forcing phrase, for the violation message: the ";"-clause that
# carries it ("forcing to 3N", "forcing", "game force").
_FORCING_CLAUSE_RE = re.compile(r"[^;]*\bforc\w*[^;]*")


def _forcing_clause(card: dict) -> str:
    m = _FORCING_CLAUSE_RE.search(card.get("gib_raw") or "")
    return m.group(0).strip() if m else "forcing"


def forcing_pass_violations(stem_entries: list[dict], option_cards: dict,
                            dealer_i: int, hero_i: int) -> list[str]:
    """Fatal: Pass is among the offered candidates while the hero's side is
    still under a live force (ben1-19f93c01296).

    A board that offers it is broken whichever engine is right. If GIB is,
    the trainee is offered — and may be graded best for — a call the
    system forbids. If Ben is (it passed the auction 46% of the time),
    then the gloss the board displays narrates a force nobody at the table
    is playing, and every sampled partner hand behind the evidence was
    drawn under that disagreement. Neither is publishable, so the board
    dies here rather than being half-repaired by dropping the option: the
    rollout that ranked the REMAINING calls sampled the same partner.

    The force is read off GIB's cards, which is why this needs no hand and
    no sampling:

    * the pass's own card asserts it ("No suitable call -- ...; forcing to
      3N"). GIB keeps the clause exactly while the commitment lives — over
      1♥-P-2♣-P-2♥-P-3♥-P-P it is there (passing a 2/1 game force), over
      1♦-P-1♥-P-2♦-2♠-P-P it is gone (the overcall discharged it) — so
      competitive auctions, where a pass is a real choice, never fire.
    * failing that (a GIB fetch failed at generation time and left the
      pass card empty), partner's last call asserts it and nothing but
      passes has happened since.

    Returns a one-item list (the board is already dead) or []."""
    if "P" not in option_cards:
        return []
    card = option_cards.get("P") or {}
    if card.get("forcing"):
        return [f"option P: the pass's own gloss says "
                f"{_forcing_clause(card)!r} — the hero's side may not pass"]
    last = next((e for e in reversed(stem_entries)
                 if e.get("call") != "P"), None)
    if last is not None and (last.get("card") or {}).get("forcing") \
            and seat_of(dealer_i, last["idx"]) == (hero_i + 2) % 4:
        return [f"option P: partner's {last['call']} is "
                f"{_forcing_clause(last['card'])!r} and only passes have "
                f"followed — the hero's side may not pass"]
    return []


# ---------------------------------------------------------------------------
# The ben1-19f975cad49 rules (docs/4nt_projection_and_gloss_gate.md).
#
# One board, three faults, three predicates. R2/R3 are record-only (they read
# the stored cards and the verdict table, so `scripts/audit_pool.py` vets the
# published pool with them); R1 needs the rollout auctions and therefore runs
# in the forge, with a cheap record-only pre-filter for the audit.
# ---------------------------------------------------------------------------

CONTRACT_RE = re.compile(r"^(\d)([NSHDC])([NESW])$")
FORCING_CONTRACT_SHARE = 0.05   # R3: the observed shares jump from 8.5% to
                                # 1.2%, so any floor in (2%, 8%] picks the
                                # same rows — this is not a fitted knob.
ASK_REPLY_SHARE = 0.05          # R1: a reply this common counts as an answer
ASK_SETTLED_SHARE = 0.99        # R1: ... and the contract this stable counts
                                # as "the answer changed nothing"
NT_ASK_LEVELS = (4, 5)          # 4NT/5NT cannot be a natural contract bid
GAME_PTS = 26                   # R6: the classic "26 points and the
                                # partnership belongs in game" line, in the
                                # same total-points currency GIB's cards state.
                                # Not a fitted knob, and the pool brackets it:
                                # over the 472 published bidding boards the
                                # uncontested partscore stops sit at 24 (the
                                # legitimate 1NT-2♥-2♠-2NT invitations, where
                                # opener's 3♠ IS a place to play) and then jump
                                # to 26 and 28 — the two boards this kills.


def contract_call(contract: str) -> str | None:
    """'6CS' -> '6C', '3NN' -> '3NT'; None when it isn't a contract token
    (``PASS``, a doubled contract like ``5DXW``)."""
    m = CONTRACT_RE.match(str(contract or ""))
    if not m:
        return None
    level, strain, _decl = m.groups()
    return level + ("NT" if strain == "N" else strain)


def contract_pairs(top_contracts) -> list[tuple]:
    """``verdict.table[i]["top_contracts"]`` as plain (contract, count) pairs.

    Accepts both shapes the same field takes in this codebase: the forge's
    ``Counter.most_common`` list of tuples, and the Firestore round-trip where
    ``_firestore_safe`` has wrapped each inner list in ``{"items": [...]}``."""
    out = []
    for e in top_contracts or []:
        if isinstance(e, dict):
            e = e.get("items") or []
        if isinstance(e, (list, tuple)) and len(e) >= 2:
            out.append((e[0], e[1]))
    return out


COMPLETE_SHARE = 0.25   # menu completion: a final contract reached on this
                        # share of an offered candidate's rollout layouts IS
                        # where the auction is heading, so its direct bid is
                        # a real alternative the menu must contain


def menu_completion_calls(rollout_contracts: dict, n: int, stem: list[str],
                          dealer_i: int, hero_i: int, offered) -> list[str]:
    """Direct calls the candidate menu is missing, read off the menu's OWN
    rollout evidence (ben1-19f95ad149d).

    The menu is Ben's raw softmax over the P_OPTION floor, so a call the
    network underrates is simply absent — no downstream gate ever asks
    whether an UNOFFERED call would beat the winner. But the rollout behind
    the offered candidates knows: on ben1-19f95ad149d the winner 3♣'s own
    rollout ended in 3NT by the hero on 92% of layouts while the direct 3NT
    (softmax 2.35%) was never evaluated; adding it shows 3♣/3NT are
    equivalent and the board has no single winner. Mechanically: any final
    contract carrying >= COMPLETE_SHARE of some offered candidate's rollout,
    declared by the hero's side, whose direct bid is legal at the decision
    point and not already offered, is a missing candidate. Pure and
    engine-free, so the forge (Counter distributions) and the pool purge
    (published ``top_contracts`` rows, wrapped or not) share it.

    Doubled contracts and PASS never nominate a call (``contract_call``
    returns None): a pass-out is not biddable and a doubled contract's
    direct bid means something else entirely."""
    from ..validate.auction_state import AuctionStateError, replay
    try:
        state = replay(SEATS[dealer_i], list(stem or []))
    except AuctionStateError:
        return []
    have = set(offered or [])
    out = []
    for dist in (rollout_contracts or {}).values():
        pairs = dist.items() if isinstance(dist, dict) else \
            contract_pairs(dist)
        for contract, count in pairs:
            if not n or count / n < COMPLETE_SHARE:
                continue
            m = CONTRACT_RE.match(str(contract or ""))
            if not m:
                continue
            call = contract_call(contract)
            if call is None or call in have or call in out:
                continue
            if SEATS.index(m.group(3)) % 2 != hero_i % 2:
                continue                    # their contract, not our call
            if not state.is_legal(call):
                continue                    # can't be bid directly anymore
            out.append(call)
    return sorted(out)


def conventional_call(call: str, auction: list[str], dealer_i: int,
                      hero_i: int) -> str | None:
    """Why *call* cannot be read off its own denomination — '4NT/5NT ask' or
    'cue-bid' — or None when the call may be natural.

    A natural call needs no stated meaning: the strain says what it is and
    only the level is in question. A 4NT/5NT ask and a bid in a suit only the
    opponents have shown are the two cases where the denomination carries no
    meaning at all, so the gloss is the whole explanation."""
    if not call or call in ("P", "X", "XX"):
        return None
    level, den = int(call[0]), call[1:]
    if den == "NT":
        return "4NT/5NT ask" if level in NT_ASK_LEVELS else None
    ours, theirs = set(), set()
    for i, tok in enumerate(auction or []):
        if tok in ("P", "X", "XX"):
            continue
        side = ours if seat_of(dealer_i, i) % 2 == hero_i % 2 else theirs
        side.add(tok[1:])
    return "cue-bid" if den in theirs and den not in ours else None


def hero_prior_card(stem_entries: list[dict], dealer_i: int,
                    hero_i: int) -> dict:
    """What the hero's OWN earlier calls have already established: cumulative
    suit minima/maxima, the widest HCP and total-point bands stated, and
    whether a force is already live. Same accumulation ``band_violations``
    does for ``known_minlen``, over one seat and every band."""
    prior = {"minlen": {}, "maxlen": {}, "hcp": None, "pts": None,
             "forcing": False, "calls": []}
    for e in stem_entries or []:
        if e.get("call") == "P" or seat_of(dealer_i, e["idx"]) != hero_i:
            continue
        card = e.get("card") or {}
        prior["calls"].append(e.get("call"))
        for st, v in stated_minlen(card).items():
            prior["minlen"][st] = max(prior["minlen"].get(st, 0), v)
        for st, mx in (card.get("maxlen") or {}).items():
            prior["maxlen"][st] = min(prior["maxlen"].get(st, 13), mx)
        for key in ("hcp", "pts"):
            b = card.get(key)
            if b:
                lo, hi = int(b[0]), int(b[1])
                cur = prior[key]
                prior[key] = (lo, hi) if cur is None else (min(cur[0], lo),
                                                           max(cur[1], hi))
        prior["forcing"] = prior["forcing"] or bool(card.get("forcing"))
    return prior


def gloss_adds_nothing(card: dict, prior: dict) -> bool:
    """True when *card* states no constraint *prior* had not established, and
    names no convention — i.e. it is not an explanation of anything.

    This is deliberately not "GIB gave no convention name": GIB describes most
    cue-bids by constraints alone ("4+ !S; 12+ HCP; forcing to 3N") and those
    glosses are informative. What is not informative is a card that repeats
    the seat's own earlier one, which is what GIB returns when it has no rule
    for the call (ben1-19f975cad49: 4NT glossed with North's 1♠ card,
    ``4+ !S; 6+ total points``)."""
    if (card.get("text") or "").strip():
        return False                      # named a convention
    if _HOLDING_RE.search(card.get("gib_raw") or ""):
        return False                      # asserts specific cards
    if card.get("forcing") and not prior.get("forcing"):
        return False                      # states a force that is new
    for st, v in stated_minlen(card).items():
        if v > (prior.get("minlen") or {}).get(st, 0):
            return False                  # a length the seat had not shown
    for st, mx in (card.get("maxlen") or {}).items():
        if mx < 13 and mx < (prior.get("maxlen") or {}).get(st, 13):
            return False                  # a cap the seat had not shown
    for key in ("hcp", "pts"):
        b = card.get(key)
        p = prior.get(key)
        if b and (p is None or int(b[0]) > p[0] or int(b[1]) < p[1]):
            return False                  # a narrower strength band
    return True


def meaningless_gloss_violations(stem_entries: list[dict], option_cards: dict,
                                 auction: list[str], dealer_i: int,
                                 hero_i: int) -> list[str]:
    """R2, fatal: an offered candidate that cannot be natural is displayed
    with a gloss that explains nothing (ben1-19f975cad49).

    The trainee is asked to choose 4NT — or a cue-bid — and the line that is
    supposed to say what it means either is empty (GIB returned nothing) or
    restates the constraints the hero's own earlier calls already established.
    Whatever the rollout then says about the call, the board teaches a
    decision it never explains, and the hero is graded on it.

    Fatal rather than option-dropping, for the reason ``forcing_pass_
    violations`` gives: the rollout that ranked the other calls sampled the
    same partner behind the same undefined auction."""
    out = []
    prior = hero_prior_card(stem_entries, dealer_i, hero_i)
    for call, card in (option_cards or {}).items():
        why = conventional_call(call, auction, dealer_i, hero_i)
        if not why:
            continue
        card = card or {}
        raw = (card.get("gib_raw") or "").strip()
        if not raw:
            out.append(f"option {call}: a {why} with no meaning stated at all")
        elif gloss_adds_nothing(card, prior):
            shown = "/".join(prior["calls"]) or "the auction so far"
            out.append(f"option {call}: a {why} glossed {raw!r} — exactly "
                       f"what {shown} already showed, so the option the board "
                       f"teaches is never explained")
    return out


def forcing_contract_violations(table: list[dict], option_cards: dict,
                                auction: list[str], dealer_i: int, hero_i: int,
                                n_samples: int,
                                floor: float = FORCING_CONTRACT_SHARE
                                ) -> list[str]:
    """R3, fatal: the rollout leaves a FORCING candidate in as the final
    contract (ben1-19f975cad49's 4♦, ``forcing to 5C``, played by North on
    36 of 423 layouts).

    ``forcing_pass_violations`` covers the adjacent case — Pass offered to the
    hero under a live force — and never looks inside the rollout. This does:
    if the projection the board publishes has partner passing a call the board
    itself calls forcing, then that option's evidence (and the EV gap measured
    against it) comes from a partner nobody plays with, and the trainee is
    shown "leads to 4♦N 9%" as if playing the opponents' suit were a real
    outcome of the choice."""
    out = []
    if not n_samples:
        return out
    for row in table or []:
        call = row.get("bid")
        if not call or call in ("P", "X", "XX"):
            continue
        card = (option_cards or {}).get(call) or {}
        cue = conventional_call(call, auction, dealer_i, hero_i) == "cue-bid"
        if not (card.get("forcing") or cue):
            continue
        for contract, cnt in contract_pairs(row.get("top_contracts")):
            if contract_call(contract) != call:
                continue
            decl = CONTRACT_RE.match(str(contract)).group(3)
            if SEATS.index(decl) % 2 != hero_i % 2:
                continue        # they bought it — the force was discharged
            share = cnt / n_samples
            if share >= floor:
                what = (_forcing_clause(card) if card.get("forcing")
                        else "a cue-bid in their suit")
                out.append(
                    f"option {call} is {what!r} yet the rollout leaves it as "
                    f"the contract ({contract}) on {cnt}/{n_samples} "
                    f"({share:.0%}) layouts")
    return out


def stated_min_pts(card: dict) -> int:
    """The minimum values a gloss states for its bidder: the low end of
    GIB's "total points" clause or of its HCP band, whichever is higher.
    0 when the card states neither (Stayman, a transfer — an artificial call
    whose card carries no values at all)."""
    lo = 0
    for key in ("pts", "hcp"):
        band = (card or {}).get(key)
        if band:
            lo = max(lo, int(band[0]))
    return lo


def side_stated_min_pts(stem_entries: list[dict], dealer_i: int,
                        hero_i: int) -> tuple[int, int]:
    """(hero, partner) minimum values the hero's SIDE has stated so far —
    per seat, the highest minimum any of that seat's own glosses states.

    Cumulative by max, not by sum: a seat's later call re-describes the same
    hand, so 1♥ then 3♥ ("13+ total points") has shown 13, not 13 plus
    whatever the opening promised."""
    best = {0: 0, 2: 0}                 # offset from the hero: self, partner
    for e in stem_entries or []:
        off = (seat_of(dealer_i, e["idx"]) - hero_i) % 4
        if off in best:
            best[off] = max(best[off], stated_min_pts(e.get("card") or {}))
    return best[0], best[2]


def uncontested(auction: list[str], dealer_i: int, hero_i: int) -> bool:
    """No opponent of the hero has made a call other than Pass."""
    for idx, call in enumerate(auction or []):
        if call != "P" and (seat_of(dealer_i, idx) - hero_i) % 2:
            return False
    return True


def game_force_stop_violations(table: list[dict], stem_entries: list[dict],
                               auction: list[str], dealer_i: int, hero_i: int,
                               n_samples: int,
                               floor: float = FORCING_CONTRACT_SHARE,
                               game_pts: int = GAME_PTS) -> list[str]:
    """R6, fatal: the rollout parks the hero's side in a PARTSCORE although
    the partnership's own displayed glosses state game values
    (ben1-19f9c2b962c).

    That board's hero opened 1NT ("15-17 HCP") and heard Stayman and then 3♣
    ("5+ !C; 13+ total points") — 28 stated points between the two hands, so
    in the system the explanations claim to teach ("standard 2/1 Game Force")
    the auction cannot stop below game. The offered 4♣ is none the less shown
    as "Leads to 4♣N 57%": on 290 of 512 layouts partner passed it out at the
    four level. The 1.9 IMPs the board then charges against 4♣ measure that
    partner — one who passes with the values his own gloss promised — not the
    bridge merit of the call, and the trainee is taught that 4♣ is a place to
    play.

    ``forcing_contract_violations`` (R3) is the adjacent rule and misses this
    class: it needs GIB to have written "forcing" on the candidate's own card,
    and GIB's card for 4♣ here is a bare "3-5 !C; 15-17 HCP" — the force lives
    in the two hands' stated values, not in one clause. So the test is the
    arithmetic GIB itself supplies:

    * the auction is UNCONTESTED (once an opponent bids, a partscore is a real
      resting place and a force can have been discharged — the same reasoning
      ``forcing_pass_violations`` applies to its clause);
    * hero's stated minimum + partner's stated minimum >= *game_pts*;
    * the candidate's own call is left in as the final contract, declared by
      the hero's side, on >= *floor* of the layouts, and that contract is a
      partscore.

    Fatal for the board, not for the option: the rollout that ranked every
    other candidate sampled the same partner."""
    out = []
    if not n_samples or not uncontested(auction, dealer_i, hero_i):
        return out
    hero_pts, partner_pts = side_stated_min_pts(stem_entries, dealer_i, hero_i)
    if hero_pts + partner_pts < game_pts:
        return out
    for row in table or []:
        call = row.get("bid")
        if not call or call in ("P", "X", "XX"):
            continue
        for contract, cnt in contract_pairs(row.get("top_contracts")):
            if contract_call(contract) != call:
                continue
            if contract_class(str(contract)) != "partscore":
                continue
            decl = CONTRACT_RE.match(str(contract))
            if not decl or SEATS.index(decl.group(3)) % 2 != hero_i % 2:
                continue
            share = cnt / n_samples
            if share >= floor:
                out.append(
                    f"option {call}: the hero's side has stated "
                    f"{hero_pts}+{partner_pts}={hero_pts + partner_pts} points "
                    f"in an uncontested auction, yet the rollout stops in the "
                    f"partscore {contract} on {cnt}/{n_samples} "
                    f"({share:.0%}) layouts")
    return out


def point_mass_suspects(table: list[dict], n_samples: int) -> list[str]:
    """R1's cheap pre-filter, for auditing records whose rollout auctions are
    gone: a candidate whose projection is ONE contract on every layout, and
    that contract is not the candidate itself.

    Not a verdict. Measured over the published pool, 5 of the 11 rows this
    flags are boards where partner had a single action on all 128 layouts, so
    the point mass is a fact about the auction. Only
    ``answer_insensitive_violations`` can tell the two apart, so this reports
    suspects to re-roll."""
    out = []
    if not n_samples:
        return out
    for row in table or []:
        call = row.get("bid")
        if not call or call in ("P", "X", "XX"):
            continue
        pairs = contract_pairs(row.get("top_contracts"))
        if not pairs:
            continue
        contract, cnt = pairs[0]
        if contract_call(contract) in (None, call):
            continue            # sign-off: the call IS the contract
        if cnt >= n_samples:
            out.append(f"option {call}: {contract} on {cnt}/{n_samples} "
                       f"layouts — the auction ran past the candidate, so no "
                       f"sampled hand changed the outcome (re-roll to confirm)")
    return out


def answer_insensitive_violations(ev, stem: list[str],
                                  reply_share: float = ASK_REPLY_SHARE,
                                  settled_share: float = ASK_SETTLED_SHARE
                                  ) -> list[str]:
    """R1, fatal: a candidate that asks a question and then ignores the answer
    (ben1-19f975cad49).

    Over the rollouts of one candidate, look at partner's first call after it
    and at the final contract:

    * partner's reply takes two or more distinct non-pass values (each on at
      least *reply_share* of layouts) — so the call functioned as an ask or a
      force, and the sampled layouts genuinely differed in what came back;
    * the final contract is nevertheless the same on *settled_share* of them.

    Then the projection the board publishes ("Leads to 6♣S 100%") is a
    property of the search, not of bridge: Ben's ``bidding_rollout`` takes the
    argmax for every sample, the hero's hand is identical in all of them, so
    the hero's own continuation is a constant — 4NT answered 5♥/5♣/5♦/5♠ and
    6♣ bid over every one of them.

    Both halves are load-bearing. Without the first, this would also kill the
    legitimate case where partner has one action on every layout (a splinter
    partner signs off over): measured on the published pool, 5 of the 11
    point-mass rows are exactly that, and 22 boards drawn at random produce no
    hit in 56 option rows.

    *ev* is an ``engine.ben.Evaluation`` (its ``auctions``/``contracts`` maps
    are what ``rollout_eval`` already builds); *stem* is the spot's stem, so
    ``len(stem) + 2`` indexes partner's reply (hero, LHO, partner, RHO)."""
    from collections import Counter

    out = []
    k = len(stem or [])
    for call in getattr(ev, "bids", []) or []:
        if call in ("P", "X", "XX"):
            continue
        auctions = [a.split() if isinstance(a, str) else list(a)
                    for a in (ev.auctions or {}).get(call, [])]
        contracts = (ev.contracts or {}).get(call, [])
        n = len(auctions)
        if not n or not contracts:
            continue
        replies = Counter(a[k + 2] if len(a) > k + 2 else "-" for a in auctions)
        answered = {r: c for r, c in replies.items()
                    if r not in ("P", "-") and c / n >= reply_share}
        if len(answered) < 2:
            continue                      # no question was asked
        contract, cnt = Counter(contracts).most_common(1)[0]
        if cnt / n < settled_share:
            continue                      # the answer moved the contract
        shown = ", ".join(f"{r} x{c}" for r, c in
                          sorted(answered.items(), key=lambda kv: -kv[1]))
        out.append(f"option {call}: partner answered {shown} yet the contract "
                   f"is {contract} on {cnt}/{n} ({cnt / n:.0%}) layouts — the "
                   f"rollout discards the information the call asks for")
    return out


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


def band_share_at(feats: dict, st: str, length: int) -> float | None:
    """Share of the sampled hands holding at least *length* cards in *st*.

    Reads the full ladder ``seat_features`` measures (``len_ge``); returns None
    when the feature dict does not carry the threshold asked for, so a caller
    that cannot measure its claim says nothing rather than guessing."""
    tbl = (feats.get("len_ge") or {}).get(st)
    if tbl is not None and 0 <= length < len(tbl):
        return float(tbl[length])
    for key, k in (("len5plus", 5), ("len4plus", 4)):
        if length == k and feats.get(key) is not None:
            return float(feats[key].get(st, 0.0))
    return None


def band_vs_shaded_hand(card: dict, feats: dict, call: str,
                        hand_pbn: str) -> list[str]:
    """R7, fatal: the one-card length shade ``hand_violations`` forgives, on a
    call whose OWN measured meaning says the shortfall is the system rather
    than a shade (ben1-19f975caec3).

    That board offered — and graded best — a third-seat 2♠ to ♠JT875 ♥KJ53
    ♦Q9 ♣KT, glossed with GIB's card for a weak two: "Weak two bid, 6+♠,
    0-10". Five spades against a promised six is exactly the shade
    ``SLACK_LEN`` exists to forgive, so the cheap hand check passed it, and
    the trainee was taught to open a weak two the displayed system does not
    contain. Ben's own sampler settles which of the two it is: over the
    layouts it accepts after that 2♠ the caller holds 5.09 spades on average
    and six on 9% of them — BEN-21GF's weak twos ARE five-card suits, so the
    gloss is not describing a stretched version of the call, it is describing
    a different call.

    The test, per suit the gloss states a minimum of five or more cards in
    (below five a minimum is a shape statement GIB attaches to raises and
    notrump bids, where one card either way is ordinary bridge):

    * the bidder is short of the promise (any shortfall — a 2+ card breach is
      already fatal in ``hand_violations``, so in practice this is the
      one-card shade), and
    * fewer than ``BAND_PLEN_DENIED`` of the layouts Ben accepts for the call
      hold the promised length.

    Then the shade is the system and the gloss misdescribes it. Fatal for the
    board rather than repaired in place: the length is the very content of the
    call the trainee is asked to judge, and rewriting the gloss to match Ben
    would publish a system claim ("weak two, 5+♠") that GIB's card and the
    board's own "meanings follow standard 2/1 Game Force" label both deny."""
    out = []
    if not card or feats.get("n", 0) < BAND_LEN_N_MIN:
        return out
    lens = suit_lengths(hand_pbn)
    for st, mn in sorted(stated_minlen(card).items()):
        held = lens.get(st)
        if mn < 5 or held is None or held >= mn:
            continue
        share = band_share_at(feats, st, mn)
        if share is None or share >= BAND_PLEN_DENIED:
            continue
        out.append(f"gloss promises {mn}+{st} and the hand holds {held}: the "
                   f"call's own band is avg {feats['len_avg'][st]:.1f}{st} "
                   f"with P({mn}+)={share:.2f} — the shortfall is the system, "
                   f"not a shade")
    return out


def band_vs_card(card: dict, feats: dict, call: str,
                 known_minlen: dict | None = None) -> list[str]:
    """One stem call: Ben's measured meaning band vs GIB's parsed card.

    known_minlen — suit minima already STATED for this seat by earlier
    glosses (cumulative). A response needn't restate shape its earlier
    bids established, so the omitted-suit rule only fires on suits absent
    from the whole story so far.

    Two sample floors, not one (R0, docs/4nt_projection_and_gloss_gate.md §4):
    the suit-length rules need ``BAND_LEN_N_MIN`` layouts, the HCP-percentile
    rule needs ``BAND_N_MIN``. A single n < 30 skip silenced the length rules
    on every call Ben could not place — which it signals by returning exactly
    its 15-layout rescue floor."""
    out = []
    n = feats.get("n", 0)
    if not card or n < BAND_LEN_N_MIN:
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
        # the gloss promises a suit the bid's own meaning refutes — by a
        # band average far below the promise (scaled: a 6+ gloss dies at
        # a higher average than a 5+ one) or because MOST sampled hands
        # lack even five (ben1-0135752a: "Minor transfer -- 6+ !C" on a
        # natural invitational 2NT whose band was avg 4.0 clubs, P5+ 0.34)
        mn = minlen.get(st, 0)
        if mn >= 5 and (feats["len_avg"][st] < mn - BAND_LEN_SLACK
                        or feats["len5plus"][st] < BAND_P5_REFUTED):
            out.append(f"gloss promises {mn}+{st} but bid shows "
                       f"avg {feats['len_avg'][st]:.1f} "
                       f"(P5+={feats['len5plus'][st]:.2f})")
    hcp = card.get("hcp")
    if hcp and n >= BAND_N_MIN:
        lo, hi = int(hcp[0]), int(hcp[1])
        if feats["hcp_p90"] < lo - BAND_HCP_GAP or \
                feats["hcp_p10"] > hi + BAND_HCP_GAP:
            out.append(f"gloss hcp {lo}-{hi} vs measured "
                       f"{feats['hcp_p10']:.0f}-{feats['hcp_p90']:.0f}")
    return out


def band_violations(engine, spot, stem_entries: list[dict],
                    option_cards: dict | None = None) -> list[str]:
    """Gloss-vs-Ben's-measured-meaning violations for every non-pass stem
    call and (when *option_cards* is given) every offered candidate.
    Costs one sampling pass per checked call; callers run it late, on
    boards that already passed the statistical judge.

    Options matter as much as the stem: a candidate whose gloss narrates
    a convention Ben is not bidding (ben1-0135752a's natural 2NT glossed
    as a minor transfer) teaches the trainee a system nobody at the table
    is playing, even when the hero's actual cards happen to fit the gloss
    (a 5-club hand slips the hand check's slack).

    Two rules per call, on the one sampling pass: ``band_vs_card`` (gloss vs
    the band) and ``band_vs_shaded_hand`` (gloss vs the band AND the bidder's
    actual cards — the SLACK_LEN arbitration, R7)."""
    from .ben import seat_features

    out = []
    bots = {}
    known: dict[int, dict] = {}     # per seat: suit minima stated so far
    for j, e in enumerate(stem_entries):
        call = e.get("call")
        if call == "P":
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
                              known_minlen=known.get(bidder_i)) + \
                band_vs_shaded_hand(card, feats, call, spot.hands[bidder_i]):
            out.append(f"stem {call} ({e.get('seat', '?')}): {v}")
        acc = known.setdefault(bidder_i, {})
        for st, v in stated_minlen(card).items():
            acc[st] = max(acc.get(st, 0), v)
        if feats.get("n", 0) >= BAND_LEN_N_MIN:
            # once the band itself establishes a suit it is "known" — an
            # omission fires at the first call that hides it, not again on
            # every later call by the same seat
            for st in "SHDC":
                if feats["len5plus"][st] >= BAND_P5_SURE:
                    acc[st] = max(acc.get(st, 0), 5)
    for bid, card in (option_cards or {}).items():
        if bid == "P" or not card:
            continue
        observer_i = (spot.hero_i + 2) % 4      # partner sees the candidate
        if observer_i not in bots:
            bots[observer_i] = engine.bot(spot.hands[observer_i], observer_i,
                                          spot.dealer_i, spot.vul)
        hands_np, n = engine.sample_prefix(
            bots[observer_i], spot.dealer_i, spot.stem + [bid])
        feats = seat_features(hands_np, spot.hero_i,
                              engine.models.n_cards_bidding)
        for v in band_vs_card(card, feats, bid,
                              known_minlen=known.get(spot.hero_i)) + \
                band_vs_shaded_hand(card, feats, bid,
                                    spot.hands[spot.hero_i]):
            out.append(f"option {bid}: {v}")
    return out


# GIB's invitational vocabulary, and the half of it that invites to SLAM
# rather than to game ("Quantitative invite to 6NT", "Mild slam try").
_INVITE_RE = re.compile(
    r"(?i)\b(invitational|invites?|invited|game try|quantitative|slam try)\b")
_SLAM_INVITE_RE = re.compile(r"(?i)\bslam\b|\bquantitative\b|\b6\s*N")


def invited_class(card: dict) -> str | None:
    """The level bracket a gloss invites partner to — "slam", "game", or
    None when the gloss is not an invitation at all."""
    raw = f"{card.get('gib_raw') or ''} {card.get('text') or ''}"
    if not _INVITE_RE.search(raw):
        return None
    return "slam" if _SLAM_INVITE_RE.search(raw) else "game"


def _reach_share(pairs: list[tuple[str, int]], hero_i: int, want: str,
                 n_samples: int) -> float | None:
    """Share of the rollout's layouts that end at or above level bracket
    *want*, counted over the layouts the hero's side declares.

    None = "this distribution cannot answer the question", for either
    reason: the pairs account for less than INVITE_COVER_MIN of the
    samples (a stored row keeps only the top three contracts, so a diffuse
    branch is deliberately not judged), or the opponents declare too often
    (INVITE_OURS_MIN) — then partner's decision was overtaken by their
    bidding rather than declined."""
    dist = [(str(k), int(c)) for k, c in pairs]
    total = sum(c for _, c in dist)
    if not dist or n_samples <= 0 or total < INVITE_COVER_MIN * n_samples:
        return None
    ours = [(k, c) for k, c in dist if contract_side(k, hero_i) == 0]
    n_ours = sum(c for _, c in ours)
    if n_ours < INVITE_OURS_MIN * total:
        return None
    rank = CLASS_RANK[want]
    return sum(c for k, c in ours
               if CLASS_RANK[contract_class(k)] >= rank) / n_ours


def invite_violations(option_cards: dict, table: list[dict], accepted: str,
                      hero_i: int, n_samples: int,
                      dists: dict | None = None) -> list[str]:
    """Fatal: an option the board narrates as an invitation that the
    rollout behind it never treats as one (ben1-19f947b9723).

    Two halves, both read off evidence the board already paid for — the
    per-candidate contract distributions:

    never accepted
        the invited level is reached on <= INVITE_NEVER of the layouts,
        while the board's own accepted call reaches it on at least
        INVITE_WINNER_REACH of its own and beats the invitation by
        INVITE_MARGIN_IMPS or more. The board then says two contradictory
        things about one partner over one set of layouts: that the level is
        right, and that the systemic invitation to it never gets there. The
        IMPs charged against the invitation measure the refusal, so the
        lesson a trainee draws ("inviting costs 5 IMPs, blast instead") is
        an artifact of the partner model.

    never declined
        the invited level is reached on >= INVITE_ALWAYS of the layouts.
        Partner has no decision at all: the call is a commitment in the
        system that produced the evidence, however the gloss labels it, and
        every number shown for it was measured under that reading.

    A thin invitation is NOT a violation. With the hero's hand fixed and
    partner's sampled, a low acceptance rate is ordinary bridge (partner
    needs a maximum); only the extremes say the call is not invitational.

    Rejects the board rather than the option, for the reason
    ``forcing_pass_violations`` gives: the same partner model produced the
    rollout behind every other candidate, so dropping the misdescribed
    option would leave the rest of the evidence resting on it."""
    if n_samples < INVITE_N_MIN:
        return []
    rows = {r.get("bid"): r for r in table or []}

    def dist(bid):
        """*dists* (the forge's full Counter per candidate) when given,
        else the row's stored top-three — which _reach_share refuses to
        judge unless it accounts for the samples."""
        d = (dists or {}).get(bid)
        if d is not None:
            return list(d.items()) if hasattr(d, "items") \
                else contract_pairs(d)
        return contract_pairs((rows.get(bid) or {}).get("top_contracts"))

    out = []
    for bid, card in (option_cards or {}).items():
        if bid == "P" or not card:
            continue        # a pass invites nothing
        want = invited_class(card)
        if want is None or bid not in rows:
            continue
        share = _reach_share(dist(bid), hero_i, want, n_samples)
        if share is None:
            continue
        gloss = (card.get("text") or card.get("gib_raw") or "").strip()
        if share >= INVITE_ALWAYS:
            out.append(f"option {bid}: gloss {gloss!r} invites to a {want}, "
                       f"but the rollout reaches one on {share:.0%} of "
                       f"layouts — partner never declines, so the call is a "
                       f"commitment, not an invitation")
            continue
        if share > INVITE_NEVER or not accepted or accepted == bid:
            continue
        margin = -float(rows[bid].get("ev_imp_vs_top") or 0.0)
        won = _reach_share(dist(accepted), hero_i, want, n_samples)
        if won is not None and won >= INVITE_WINNER_REACH \
                and margin >= INVITE_MARGIN_IMPS:
            out.append(f"option {bid}: gloss {gloss!r} invites to a {want} "
                       f"and is charged {margin:.1f} IMPs for missing it, "
                       f"but the rollout reaches one on {share:.0%} of its "
                       f"layouts against {won:.0%} for the winning "
                       f"{accepted} — partner never accepts the try")
    return out


def record_violations(rec: dict) -> tuple[list[str], list[str]]:
    """The cheap (no-engine) audit for an already-built problem record: the
    stored stem/option cards vs the stored full deal, the pass-under-a-force
    check, the two record-only ben1-19f975cad49 rules (an unexplained
    conventional call, a forcing call the rollout leaves in as the contract),
    the invitation check and the game-force-stop check against the record's
    own rollout. Lets the same
    gate vet historical pools and freshly forged batches alike. Returns
    (fatal, soft) as ``hand_violations`` does.

    R1 (``answer_insensitive_violations``) is deliberately NOT here: it needs
    the rollout auctions, which no record stores. ``point_mass_suspects`` is
    its record-only pre-filter and is reported separately by the audit, as a
    list to re-roll rather than a verdict."""
    hands = [rec["full_deal"][s] for s in SEATS]
    dealer_i = SEATS.index(rec["dealer"])
    hero_i = SEATS.index(rec["seat"])
    auction = list(rec.get("auction") or [])
    stem_entries = (rec.get("explanations") or {}).get("stem") or []
    option_cards = {o["bid"]: o.get("card")
                    for o in (rec.get("explanations") or {}).get(
                        "options") or []}
    verdict = rec.get("verdict") or {}
    n_samples = (rec.get("quality") or {}).get("n_samples") or 0
    fatal, soft = hand_violations(stem_entries, option_cards, hands,
                                  dealer_i, hero_i)
    fatal += forcing_pass_violations(stem_entries, option_cards,
                                     dealer_i, hero_i)
    fatal += meaningless_gloss_violations(stem_entries, option_cards, auction,
                                          dealer_i, hero_i)
    fatal += forcing_contract_violations(verdict.get("table") or [],
                                         option_cards, auction, dealer_i,
                                         hero_i, n_samples)
    fatal += invite_violations(option_cards, verdict.get("table") or [],
                               verdict.get("accepted") or "", hero_i,
                               int(n_samples or 0))
    fatal += game_force_stop_violations(verdict.get("table") or [],
                                        stem_entries, auction, dealer_i,
                                        hero_i, int(n_samples or 0))
    fatal += ev_argmax_violations(verdict.get("table") or [],
                                  verdict.get("accepted") or "")
    fatal += sellout_violations(auction, hands, dealer_i)
    return fatal, soft
