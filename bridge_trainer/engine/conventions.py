"""Mechanical call classification for a 2/1 GF card (bridge review recs
1, 2, 4, 11): convention names for artificial calls, contextual double
types, systemic categories, jump attributes, and the asking-call list
whose responses are ineligible as problems.

Everything here is derived from the auction alone — no engine, no
guessing. Seats are absolute indices 0..3 = N,E,S,W; auction tokens run
from the dealer.
"""
from __future__ import annotations

from dataclasses import dataclass

DENOMS = ("C", "D", "H", "S", "NT")


def seat_of(dealer_i: int, idx: int) -> int:
    return (dealer_i + idx) % 4


def _is_bid(tok: str) -> bool:
    return tok not in ("P", "X", "XX")


def _level(tok: str) -> int:
    return int(tok[0])


def _denom(tok: str) -> str:
    return tok[1:]


@dataclass
class CallInfo:
    category: str            # opening/response/overcall/raise/cue/new-suit/...
    convention: str | None   # named convention when recognized
    artificial: bool
    double_type: str | None  # takeout/negative/penalty/lead-directing/balancing
    jump: int                # levels above minimal legal
    asking: bool             # responses to this call are ineligible turns


def _last_bid_by(auction: list[str], dealer_i: int, seats: set[int],
                 before: int) -> tuple[int, str] | None:
    for j in range(before - 1, -1, -1):
        if seat_of(dealer_i, j) in seats and _is_bid(auction[j]):
            return j, auction[j]
    return None


def _suits_shown_naturally(auction: list[str], dealer_i: int,
                           seats: set[int], before: int) -> set[str]:
    shown = set()
    for j in range(before):
        tok = auction[j]
        if seat_of(dealer_i, j) in seats and _is_bid(tok) and _denom(tok) != "NT":
            info = classify(auction[:j] + [tok], dealer_i, j) if j < before else None
            # avoid recursion blowups: treat non-artificial suit bids as natural
            if info is None or not info.artificial:
                shown.add(_denom(tok))
    return shown


def _min_legal_level(auction: list[str], idx: int, denom: str) -> int:
    last = None
    for j in range(idx - 1, -1, -1):
        if _is_bid(auction[j]):
            last = auction[j]
            break
    if last is None:
        return 1
    ll, ld = _level(last), _denom(last)
    return ll if DENOMS.index(denom) > DENOMS.index(ld) else ll + 1


def classify(auction: list[str], dealer_i: int, idx: int) -> CallInfo:
    """Classify auction[idx]. The auction list must contain the call."""
    tok = auction[idx]
    me = seat_of(dealer_i, idx)
    partner = (me + 2) % 4
    opps = {(me + 1) % 4, (me + 3) % 4}
    prior = auction[:idx]
    nonpass_before = [t for t in prior if t != "P"]
    my_side_bids = [t for j, t in enumerate(prior)
                    if seat_of(dealer_i, j) in (me, partner) and _is_bid(t)]
    partner_last = _last_bid_by(prior, dealer_i, {partner}, idx)
    opp_suits = _suits_shown_naturally(prior, dealer_i, opps, idx)

    # ---- passes -----------------------------------------------------------
    if tok == "P":
        return CallInfo("pass", None, False, None, 0, False)

    # ---- doubles ----------------------------------------------------------
    if tok in ("X", "XX"):
        if tok == "XX":
            return CallInfo("redouble", None, False, None, 0, False)
        dt = "takeout"
        last = None
        for j in range(idx - 1, -1, -1):
            if _is_bid(prior[j]) or prior[j] == "X":
                last = (j, prior[j]); break
        if last is not None and _is_bid(last[1]):
            j, lt = last
            linfo = classify(prior, dealer_i, j) if j < idx else None
            if linfo is not None and linfo.artificial:
                dt = "lead-directing"
            elif _denom(lt) == "NT":
                dt = "penalty-oriented"
            elif my_side_bids and partner_last is not None and \
                    len(my_side_bids) >= 1 and _level(lt) <= 3:
                dt = "negative"
            elif idx >= 2 and prior[idx - 1] == "P" and prior[idx - 2] == "P":
                dt = "balancing takeout"
        return CallInfo("double", None, False, dt, 0, False)

    level, denom = _level(tok), _denom(tok)
    jump = level - _min_legal_level(auction, idx, denom)

    # ---- named conventions (2/1 GF card) -----------------------------------
    if not nonpass_before and tok == "2C":
        return CallInfo("opening", "strong artificial 2C (22+/9 tricks)",
                        True, None, jump, True)
    if partner_last is not None:
        _, plast = partner_last
        if plast == "1NT" and len(my_side_bids) == 1:
            if tok == "2C":
                return CallInfo("response", "Stayman (asks for a 4-card major)",
                                True, None, jump, True)
            if tok == "2D":
                return CallInfo("response", "Jacoby transfer to hearts",
                                True, None, jump, True)
            if tok == "2H":
                return CallInfo("response", "Jacoby transfer to spades",
                                True, None, jump, True)
        if plast == "2C" and len(my_side_bids) == 1 and tok == "2D":
            return CallInfo("response", "2D waiting (artificial)",
                            True, None, jump, True)
        if plast in ("2D", "2H", "2S") and tok == "2NT" \
                and len(my_side_bids) == 1 \
                and nonpass_before and nonpass_before[0] == plast:
            # 2NT over partner's weak-two opening = Ogust/feature inquiry
            return CallInfo("response", "2NT inquiry over the weak two "
                            "(Ogust/feature ask)", True, None, jump, True)
        if plast in ("1H", "1S") and tok == "2NT" and not opp_suits:
            return CallInfo("response", "Jacoby 2NT (game-forcing raise)",
                            True, None, jump, True)
        if plast in ("1H", "1S") and jump >= 2 and denom != "NT" \
                and denom != _denom(plast):
            return CallInfo("response", "splinter (shortness, raise)",
                            True, None, jump, False)
        if plast == "4NT" and tok in ("5C", "5D", "5H", "5S"):
            return CallInfo("response", "keycard step response",
                            True, None, jump, False)
    if tok == "4NT" and any(_denom(t) != "NT" for t in my_side_bids):
        return CallInfo("ask", "Roman Keycard Blackwood (4NT ask)",
                        True, None, jump, True)

    # ---- cue bid ------------------------------------------------------------
    if denom in opp_suits:
        return CallInfo("cue-bid",
                        "cue bid of their suit (strong raise/asking)",
                        True, None, jump, False)

    # ---- structural categories ---------------------------------------------
    if not nonpass_before:
        return CallInfo("opening", None, False, None, jump, False)
    my_suits = {_denom(t) for t in my_side_bids if _denom(t) != "NT"}
    partner_suits = {_denom(plast) for _, plast in [partner_last]} \
        if partner_last and _denom(partner_last[1]) != "NT" else set()
    if denom != "NT" and denom in partner_suits:
        cat = "raise"
    elif denom == "NT":
        cat = "notrump"
    elif my_side_bids:
        # 4th-suit-forcing detection: responder bids the only unbid suit
        all_shown = my_suits | opp_suits
        unbid = [d for d in ("C", "D", "H", "S") if d not in all_shown]
        if len(unbid) == 1 and denom == unbid[0] and len(my_side_bids) >= 2:
            return CallInfo("new-suit", "fourth suit (forcing one round)",
                            True, None, jump, False)
        cat = "new-suit"
    else:
        cat = "overcall" if any(
            seat_of(dealer_i, j) in opps and _is_bid(t)
            for j, t in enumerate(prior)) else "new-suit"
    if jump > 0 and cat in ("raise", "overcall", "new-suit"):
        cat = f"jump {cat}"
    return CallInfo(cat, None, False, None, jump, False)


def previous_call_is_asking(auction: list[str], dealer_i: int) -> bool:
    """Is the NEXT turn a response to partner's asking call? (rec 4)"""
    idx = len(auction)
    partner_j = idx - 2
    if partner_j < 0:
        return False
    tok = auction[partner_j]
    if not _is_bid(tok):
        return False
    return classify(auction, dealer_i, partner_j).asking


def hero_role(auction: list[str], dealer_i: int, hero_i: int) -> str:
    """opener / responder / overcaller / advancer / other at the decision."""
    first_bid_j = next((j for j, t in enumerate(auction) if _is_bid(t)), None)
    if first_bid_j is None:
        return "opener-to-be"
    opener = seat_of(dealer_i, first_bid_j)
    if hero_i == opener:
        return "opener"
    if hero_i == (opener + 2) % 4:
        return "responder"
    over_j = next((j for j in range(first_bid_j + 1, len(auction))
                   if _is_bid(auction[j]) or auction[j] == "X"), None)
    if over_j is not None:
        overcaller = seat_of(dealer_i, over_j)
        if hero_i == overcaller:
            return "overcaller"
        if hero_i == (overcaller + 2) % 4:
            return "advancer"
    return "other"
