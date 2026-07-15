"""Harvest real deals + expert auctions from BBO vugraph LIN files.

A vugraph LIN file holds one teams-match segment: the same boards played in
two rooms (qx|oN| open, qx|cN| closed). Deals and auctions are facts of the
event — free to use. Where the two expert tables DIVERGED in the auction is
a human-certified decision point: the board, the auction up to that call,
and the two calls actually chosen become a training problem. Each room's
real continuation supplies the final contract its call led to, so the DD
simulation can judge the two choices over layouts consistent with the
auction (meanings are attached at problem-finalization time).

LIN essentials (empirically verified):
  vg|title,segment,...,team1,carry,team2,carry|
  rs|<results interleaved o,c per board>|
  qx|o1| ... board segment: md|<dealer digit><4 hands S,W,N,E>|, sv|vul|,
  mb|call| (p/d/r or bids like 1H, 3N; '!' suffix = alert), an|..| notes.
  Dealer digit: 1=S 2=W 3=N 4=E. Vul: o=None n=NS e=EW b=Both.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..domain.auction import SEATS, next_seat, side_of
from ..domain.contracts import FinalContract

_DEALER = {"1": "S", "2": "W", "3": "N", "4": "E"}
_VUL = {"o": "None", "n": "NS", "e": "EW", "b": "Both"}
_HAND_ORDER = ("S", "W", "N", "E")
_RANKS = "AKQJT98765432"


@dataclass
class BoardRecord:
    board: str            # e.g. "o1" -> number "1", room "o"
    room: str
    number: int
    dealer: str
    vul: str
    hands: dict           # seat -> "S.H.D.C" pbn suits
    auction: list         # normalized tokens: P/X/XX/1H/3NT...
    event: str = ""
    teams: str = ""
    result: str = ""      # e.g. "3HN-2" from the rs| line


@dataclass
class Divergence:
    number: int
    dealer: str
    vul: str
    hands: dict
    stem: list            # common auction prefix
    hero: str             # seat to act at the divergence
    calls: dict           # room -> the call actually chosen ("o"/"c")
    contracts: dict       # room -> FinalContract its full auction reached
    results: dict         # room -> recorded table result string
    event: str = ""
    teams: str = ""


def _norm_call(tok: str) -> str | None:
    t = tok.strip().rstrip("!").upper()
    if not t:
        return None
    if t == "P":
        return "P"
    if t == "D":
        return "X"
    if t == "R":
        return "XX"
    if len(t) >= 2 and t[0] in "1234567":
        denom = t[1:]
        if denom == "N":
            denom = "NT"
        if denom in ("C", "D", "H", "S", "NT"):
            return t[0] + denom
    return None


def _hand_to_pbn(lin_hand: str) -> str:
    """'SAT2H9765DT987CQJ' -> 'AT2.9765.T987.QJ'"""
    parts = {"S": "", "H": "", "D": "", "C": ""}
    cur = None
    for ch in lin_hand.upper():
        if ch in parts:
            cur = ch
        elif cur:
            parts[cur] += ch
    return ".".join(parts[s] for s in "SHDC")


def _derive_fourth(hands: dict) -> None:
    """LIN may omit the 4th hand; derive it from the other three."""
    missing = [s for s, h in hands.items() if h.replace(".", "") == ""]
    if len(missing) != 1:
        return
    m = missing[0]
    suits = []
    for i in range(4):
        seen = set()
        for s, h in hands.items():
            if s != m:
                seen.update(h.split(".")[i])
        suits.append("".join(r for r in _RANKS if r not in seen))
    hands[m] = ".".join(suits)


def parse_lin(text: str) -> list[BoardRecord]:
    tokens = re.findall(r"([a-zA-Z]{2})\|([^|]*)\|", text)
    event = teams = ""
    results: list[str] = []
    boards: list[BoardRecord] = []
    cur: BoardRecord | None = None
    for tag, val in tokens:
        tag = tag.lower()
        if tag == "vg":
            parts = val.split(",")
            event = ",".join(parts[:2])
            if len(parts) >= 7:
                teams = f"{parts[5]} v {parts[7]}" if len(parts) >= 8 \
                    else parts[5]
        elif tag == "rs":
            results = val.split(",")
        elif tag == "qx":
            m = re.match(r"([oc])(\d+)", val.strip().lower())
            if m:
                cur = BoardRecord(board=val.strip(), room=m.group(1),
                                  number=int(m.group(2)), dealer="", vul="",
                                  hands={}, auction=[], event=event,
                                  teams=teams)
                boards.append(cur)
            else:
                cur = None
        elif cur is None:
            continue
        elif tag == "md":
            v = val.strip()
            if not v:
                continue
            cur.dealer = _DEALER.get(v[0], "")
            hand_strs = v[1:].split(",")
            hands = {}
            for seat, hs in zip(_HAND_ORDER, hand_strs + [""] * 4):
                hands[seat] = _hand_to_pbn(hs)
            _derive_fourth(hands)
            cur.hands = hands
        elif tag == "sv":
            cur.vul = _VUL.get(val.strip().lower(), "")
        elif tag == "mb":
            call = _norm_call(val)
            if call:
                cur.auction.append(call)
    # Attach recorded results: rs| interleaves open,closed per board number.
    for b in boards:
        idx = (b.number - 1) * 2 + (0 if b.room == "o" else 1)
        if 0 <= idx < len(results):
            b.result = results[idx]
    return boards


def _valid(b: BoardRecord) -> bool:
    if not (b.dealer and b.vul and len(b.hands) == 4 and b.auction):
        return False
    if any(len(h.replace(".", "")) != 13 for h in b.hands.values()):
        return False
    return _auction_complete(b.auction)


def _auction_complete(auction: list) -> bool:
    if len(auction) == 4 and all(t == "P" for t in auction):
        return True
    return len(auction) >= 4 and auction[-3:] == ["P", "P", "P"] \
        and any(t != "P" for t in auction)


def auction_to_contract(dealer: str, tokens: list) -> FinalContract:
    """Final contract of a complete real auction (declarer = first namer)."""
    level, denom, doubled = 0, "", False
    last_bid_seat = ""
    first_namer: dict[tuple, str] = {}
    seat = dealer
    for tok in tokens:
        if tok == "X":
            doubled = True
        elif tok == "XX":
            doubled = True  # scored as doubled only in v1 tables; rare
        elif tok != "P":
            level, denom = int(tok[0]), tok[1:]
            doubled = False
            last_bid_seat = seat
            first_namer.setdefault((side_of(seat), denom), seat)
        seat = next_seat(seat)
    if level == 0:
        return FinalContract(level=0, denom="", declarer=None, terminal=False)
    declarer = first_namer[(side_of(last_bid_seat), denom)]
    return FinalContract(level=level, denom=denom, declarer=declarer,
                         doubled=doubled, terminal=False)


def find_divergences(boards: list[BoardRecord]) -> list[Divergence]:
    """Pair open/closed records of each board; return real decision points."""
    by_number: dict[int, dict[str, BoardRecord]] = {}
    for b in boards:
        if _valid(b):
            by_number.setdefault(b.number, {})[b.room] = b
    out = []
    for number, rooms in sorted(by_number.items()):
        if set(rooms) != {"o", "c"}:
            continue
        o, c = rooms["o"], rooms["c"]
        if o.hands != c.hands or o.dealer != c.dealer or o.vul != c.vul:
            continue  # different deal records: not a true pair
        if o.auction == c.auction:
            continue
        i = 0
        while i < min(len(o.auction), len(c.auction)) \
                and o.auction[i] == c.auction[i]:
            i += 1
        if i >= min(len(o.auction), len(c.auction)):
            continue  # one auction is a prefix of the other (rare/odd)
        hero = o.dealer
        for _ in range(i % 4):
            hero = next_seat(hero)
        fc_o = auction_to_contract(o.dealer, o.auction)
        fc_c = auction_to_contract(c.dealer, c.auction)
        out.append(Divergence(
            number=number, dealer=o.dealer, vul=o.vul, hands=dict(o.hands),
            stem=o.auction[:i], hero=hero,
            calls={"o": o.auction[i], "c": c.auction[i]},
            contracts={"o": fc_o, "c": fc_c},
            results={"o": o.result, "c": c.result},
            event=o.event, teams=o.teams,
        ))
    return out
