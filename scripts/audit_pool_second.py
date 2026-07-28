"""Second-opinion pool audit: the checks ``explain_check`` does NOT run.

``scripts/audit_pool.py`` vets one thing very well — GIB's parsed ``card``
against the cards a seat actually holds — and the published pool passes it
clean. This script covers what that leaves open, in four families:

  HAND    the DISPLAYED description string (what a trainee reads on the page)
          vs the 13 actual cards. Two gaps matter: ``card_vs_hand`` reads
          ``hcp``/``minlen``/``maxlen`` and never ``pts``, while
          ``explain.terse_meaning`` renders the ``pts`` band whenever GIB gave
          no HCP band — so every "16-18 pts" on the page ships unvetted; and
          Pass is exempt from the gate although its gloss carries suit-length
          and point claims the page shows like any other.

  OPTIONS legality of every offered call at the decision point (sufficiency,
          X only over an opponent's undoubled bid, XX only over their X),
          duplicates, menu size, and verdict-table/candidate agreement.

  SCORE   the published numbers against themselves: probability triples,
          CI signs, contract counts vs sample count, rank vs the metric each
          rank claims to order, accepted-vs-best agreement in the board's own
          target mode, equal-evidence leads graded equally, and lead
          ``exp_score`` inside the range the contract can actually produce.

  BRIDGE  auction legality and turn order, contract/declarer/leader derived
          from the auction vs the stored fields, deal integrity (52 cards,
          13 each, 40 HCP), actions no partnership takes for the cards held,
          and lead boards with no decision left to teach.

Usage:
    python3 scripts/audit_pool_second.py <pool_dir> [--out F]
    python3 scripts/audit_pool_second.py --firestore [--key K] [--out F]

Exit code 1 when any BAD finding remains, so CI can gate on it.
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bridge_trainer.scoring.tables import contract_score

SEATS = "NESW"
RANKS = "AKQJT98765432"
HCPV = {"A": 4, "K": 3, "Q": 2, "J": 1}
DENOMS = ["C", "D", "H", "S", "N"]        # ascending; "N" == NT
SUITS = "SHDC"                            # order used in the "S.H.D.C" hand string


# ---------------------------------------------------------------- hand parsing
def parse_hand(h):
    """'AJT52.J875.K85.9' -> {'S': 'AJT52', 'H': ..., 'D': ..., 'C': ...}"""
    parts = h.split(".")
    if len(parts) != 4:
        return None
    return dict(zip(SUITS, parts))


def hcp(h):
    return sum(HCPV.get(c, 0) for suit in parse_hand(h).values() for c in suit)


def lengths(h):
    return {s: len(v) for s, v in parse_hand(h).items()}


def cards(h):
    p = parse_hand(h)
    return [s + c for s in SUITS for c in p[s]]


# --------------------------------------------------------------- call handling
CALL_RE = re.compile(r"^([1-7])(C|D|H|S|N|NT)$")


def bid_rank(call):
    m = CALL_RE.match(call)
    if not m:
        return None
    lvl, d = int(m.group(1)), m.group(2)[0]
    return lvl * 5 + DENOMS.index(d)


def legal_calls_state(auction):
    """Replay *auction* (list of calls, dealer on turn first) and return
    (error_or_None, state) where state = (last_bid_rank, last_bid_idx,
    doubled_level, n_trailing_passes)."""
    last_rank, last_idx, dbl = None, None, 0
    trailing = 0
    for i, call in enumerate(auction):
        c = call.upper()
        if c in ("P", "PASS"):
            trailing += 1
            continue
        if c in ("X", "D", "DBL"):
            # legal only over an opponent's undoubled bid
            if last_idx is None or dbl != 0:
                return f"illegal X at index {i} in the auction", None
            if (i - last_idx) % 2 == 0:          # same side made the last bid
                return f"X at index {i} doubles partner's own bid", None
            dbl, trailing = 1, 0
            continue
        if c in ("XX", "R", "RDBL"):
            if dbl != 1 or last_idx is None:
                return f"illegal XX at index {i} in the auction", None
            # XX comes from the side that BID (and was doubled): same parity
            if (i - last_idx) % 2 == 1:
                return f"XX at index {i} redoubles our own double", None
            dbl, trailing = 2, 0
            continue
        r = bid_rank(c)
        if r is None:
            return f"unparseable call {call!r} at index {i}", None
        if last_rank is not None and r <= last_rank:
            return (f"insufficient bid {call} at index {i} over "
                    f"{auction[last_idx]}"), None
        last_rank, last_idx, dbl, trailing = r, i, 0, 0
    return None, (last_rank, last_idx, dbl, trailing)


def legal_next(call, auction):
    """Is *call* a legal call for the seat on turn after *auction*?"""
    err, st = legal_calls_state(auction)
    if err:
        return False
    last_rank, last_idx, dbl, _ = st
    c = call.upper()
    if c in ("P", "PASS"):
        return True
    if c in ("X", "D", "DBL"):
        n = len(auction)
        return (last_idx is not None and dbl == 0
                and (n - last_idx) % 2 == 1)
    if c in ("XX", "R", "RDBL"):
        n = len(auction)
        return dbl == 1 and last_idx is not None and (n - last_idx) % 2 == 0
    r = bid_rank(c)
    return r is not None and (last_rank is None or r > last_rank)


def final_contract(auction, dealer_i):
    """(level, denom, doubled, declarer_seat) from a complete auction, or None."""
    last_rank, last_idx, dbl = None, None, 0
    denom = None
    for i, call in enumerate(auction):
        c = call.upper()
        if c in ("X", "D", "DBL"):
            dbl = 1
        elif c in ("XX", "R", "RDBL"):
            dbl = 2
        elif c not in ("P", "PASS"):
            r = bid_rank(c)
            if r is None:
                return None
            last_rank, last_idx, dbl = r, i, 0
            denom = CALL_RE.match(c).group(2)[0]
    if last_idx is None:
        return None
    level = last_rank // 5
    # declarer: first seat of the winning side to name that denomination
    win_side = (dealer_i + last_idx) % 2
    for i, call in enumerate(auction):
        m = CALL_RE.match(call.upper())
        if m and m.group(2)[0] == denom and (dealer_i + i) % 2 == win_side:
            return level, denom, dbl, SEATS[(dealer_i + i) % 4]
    return None


# the canonical shape the web client parses is {level}{denom}{declarer}{x|xx}
# (webapp.py: /^(\d(?:NT|[CDHS]))[NESW](x{0,2})$/); accept X before the seat too
CONTRACT_RE = re.compile(r"^([1-7])(NT|N|C|D|H|S)(XX|X|xx|x)?([NESW])"
                         r"(xx|x|XX|X)?$")


def parse_contract(s):
    m = CONTRACT_RE.match(s.strip())
    if not m:
        return None
    dbl = (m.group(3) or m.group(5) or "").lower()
    return (int(m.group(1)), m.group(2)[0], {"": 0, "x": 1, "xx": 2}[dbl],
            m.group(4))


def is_vul(vul, seat):
    v = (vul or "None").replace("Both", "All")
    if v in ("None", "-", "Love"):
        return False
    if v == "All":
        return True
    return seat in ("NS" if v == "NS" else "EW") and v in ("NS", "EW") and (
        seat in v)


# ------------------------------------------------------------------- the audit
def audit(rec):
    out = []          # (severity, code, message)
    def bad(code, msg):
        out.append(("BAD", code, msg))
    def warn(code, msg):
        out.append(("WARN", code, msg))

    pid = rec.get("id")
    kind = rec.get("kind") or "bidding"
    deal = rec.get("full_deal") or {}
    dealer = rec.get("dealer")
    seat = rec.get("seat")
    auction = list(rec.get("auction") or [])

    # ---- A. deal integrity
    if sorted(deal) != list("ENSW"):
        bad("A1", f"full_deal seats {sorted(deal)} != N/E/S/W")
        return out
    allc = []
    for s in SEATS:
        h = deal[s]
        p = parse_hand(h)
        if p is None:
            bad("A2", f"{s} hand {h!r} does not have four suits")
            return out
        n = sum(len(v) for v in p.values())
        if n != 13:
            bad("A2", f"{s} holds {n} cards, not 13 ({h})")
        for suit, v in p.items():
            for c in v:
                if c not in RANKS:
                    bad("A3", f"{s} has bad rank {c!r} in {suit}")
            if len(set(v)) != len(v):
                bad("A3", f"{s} has a repeated card in {suit}: {v}")
        allc += cards(h)
    dup = [c for c, k in Counter(allc).items() if k > 1]
    if dup:
        bad("A4", f"card(s) dealt twice: {' '.join(sorted(dup))}")
    if len(allc) == 52 and not dup:
        tot = sum(hcp(deal[s]) for s in SEATS)
        if tot != 40:
            bad("A5", f"deal holds {tot} HCP, not 40")
    if dealer not in SEATS:
        bad("A6", f"dealer {dealer!r} invalid")
        return out
    di = SEATS.index(dealer)
    if (rec.get("vul") or "").replace("Both", "All") not in (
            "None", "NS", "EW", "All"):
        bad("A7", f"vul {rec.get('vul')!r} invalid")

    # ---- B. the hero's hand as displayed vs the deal
    hero_of = seat if kind == "bidding" else (rec.get("leader") or seat)
    if rec.get("hand") != deal.get(hero_of):
        bad("B1", f"displayed hand {rec.get('hand')} != {hero_of}'s cards "
                  f"{deal.get(hero_of)}")

    # ---- C. auction legality + turn order
    err, st = legal_calls_state(auction)
    if err:
        bad("C1", err)
    if kind == "bidding":
        if seat not in SEATS:
            bad("C2", f"seat {seat!r} invalid")
        elif SEATS[(di + len(auction)) % 4] != seat:
            bad("C2", f"hero seat {seat} is not on turn after {len(auction)} "
                      f"calls from dealer {dealer} "
                      f"(on turn: {SEATS[(di + len(auction)) % 4]})")
        if not err and st[3] >= 3 and len(auction) >= 4:
            bad("C3", "the stem auction is already over (3+ trailing passes) "
                      "yet the hero is asked to call")
    else:
        if not err:
            if st[3] < 3:
                bad("C4", f"lead problem whose auction is not complete "
                          f"({st[3]} trailing pass(es))")
            fc = final_contract(auction, di)
            declared = parse_contract(rec.get("contract") or "")
            if fc is None:
                bad("C5", "auction was passed out but the record has a "
                          "contract")
            elif declared is None:
                bad("C5", f"contract {rec.get('contract')!r} unparseable")
            else:
                if fc[:3] != declared[:3]:
                    bad("C5", f"auction ends in {fc[0]}{fc[1]}"
                              f"{'X'*fc[2]} but record says "
                              f"{rec.get('contract')}")
                if fc[3] != declared[3]:
                    bad("C6", f"declarer from the auction is {fc[3]}, record "
                              f"says {declared[3]}")
                if rec.get("declarer") != declared[3]:
                    bad("C6", f"declarer field {rec.get('declarer')} != "
                              f"contract {rec.get('contract')}")
                lho = SEATS[(SEATS.index(declared[3]) + 1) % 4]
                if rec.get("leader") != lho:
                    bad("C7", f"leader {rec.get('leader')} is not LHO of "
                              f"declarer {declared[3]} (should be {lho})")
                if seat != rec.get("leader"):
                    bad("C7", f"seat {seat} != leader {rec.get('leader')}")

    # ---- D. gloss (hand description) vs the actual cards, per bidding seat
    ex = rec.get("explanations") or {}
    stem = ex.get("stem") if kind == "bidding" else ex.get("auction")
    stem = stem or []
    if len(stem) != len(auction):
        warn("D0", f"{len(stem)} explained call(s) for an auction of "
                   f"{len(auction)}")
    for e in stem:
        idx = e.get("idx")
        call = (e.get("call") or "").upper()
        s = e.get("seat")
        if s not in SEATS or idx is None:
            continue
        if idx < len(auction) and auction[idx].upper() != call:
            bad("D1", f"explained call #{idx} is {call} but the auction has "
                      f"{auction[idx]}")
        if SEATS[(di + idx) % 4] != s:
            bad("D1", f"explained call #{idx} attributed to {s}, on turn is "
                      f"{SEATS[(di + idx) % 4]}")
        card = e.get("card") or {}
        h = deal.get(s)
        if not h:
            continue
        # HCP band (slack 2, matching the shipped gate) — pass exempt
        band = card.get("hcp")
        if band and call not in ("P", "PASS"):
            lo, hi = band[0], band[1]
            a = hcp(h)
            if a < lo - 2 or a > hi + 2:
                bad("D2", f"{call} by {s} glossed {lo}-{hi} HCP, hand has "
                          f"{a} ({h})")
        L = lengths(h)
        for suit, need in (card.get("minlen") or {}).items():
            if suit in L and need and L[suit] < need - 1:
                bad("D3", f"{call} by {s} glossed {need}+{suit}, hand has "
                          f"{L[suit]} ({h})")
        for suit, cap in (card.get("maxlen") or {}).items():
            if suit in L and cap < 13 and L[suit] > cap + 1:
                bad("D3", f"{call} by {s} glossed {cap}-{suit}, hand has "
                          f"{L[suit]} ({h})")

    # ---- D'. the DISPLAYED description string vs the actual cards.
    # explain.terse_meaning renders only the claims a user reads: the top two
    # suits with minlen >= 4 (or 3 on the bid denomination), then an HCP band
    # ("11-14" / "25+") or, when GIB gave none, a total-points band
    # ("16-18 pts"). This checks exactly those, for EVERY call including Pass
    # (the shipped gate exempts Pass, which is where the visible lies live).
    for e in stem:
        idx, s = e.get("idx"), e.get("seat")
        txt = e.get("text") or ""
        # bidding boards prefix the meaning with "<call> (<seat>): " — strip it
        # so the bid token itself is not read as a suit-length claim
        txt = txt.split("): ", 1)[1] if "): " in txt else txt
        if s not in SEATS or idx is None:
            continue
        h = deal.get(s)
        if not h:
            continue
        L, a = lengths(h), hcp(h)
        for lo, hi, gl in re.findall(r"(\d+)(?:-(\d+))?\+?([♠♥"
                                     r"♦♣])", txt):
            suit = {"♠": "S", "♥": "H", "♦": "D",
                    "♣": "C"}[gl]
            lo = int(lo)
            if L[suit] < lo - 1:
                bad("D4", f"[{idx}] {s} {e.get('call')} is displayed as "
                          f"{txt!r} — the hand holds {L[suit]} {suit} ({h})")
            elif hi and L[suit] > int(hi) + 1:
                bad("D4", f"[{idx}] {s} {e.get('call')} is displayed as "
                          f"{txt!r} — the hand holds {L[suit]} {suit} ({h})")
        m = re.search(r"(?:^|,\s)(\d+)(?:-(\d+)|\+)(?!\s*pts)"
                      r"[♠♥♦♣]?\s*$", txt)
        if m and not re.search(r"[♠♥♦♣]\s*$", txt):
            lo = int(m.group(1))
            hi = int(m.group(2)) if m.group(2) else 40
            if a < lo - 2 or a > hi + 2:
                bad("D5", f"[{idx}] {s} {e.get('call')} is displayed as "
                          f"{txt!r} — the hand has {a} HCP ({h})")
        mp = re.search(r"(\d+)(?:-(\d+)|\+)\s*pts\s*$", txt)
        if mp:
            lo = int(mp.group(1))
            hi = int(mp.group(2)) if mp.group(2) else 40
            shortness = sum({0: 3, 1: 2, 2: 1}.get(v, 0) for v in L.values())
            length = sum(max(0, v - 4) for v in L.values())
            ptmax = a + shortness + length
            if lo > ptmax + 2 or hi < a - 2:
                bad("D6", f"[{idx}] {s} {e.get('call')} is displayed as "
                          f"{txt!r} — hand is {a} HCP, at most ~{ptmax} total "
                          f"({h})")
        # a call in the auction the user is shown with no explanation at all
        raw = ((e.get("card") or {}).get("gib_raw") or "").strip()
        if (e.get("call") or "").upper() not in ("P", "PASS") and not raw:
            bad("D7", f"[{idx}] {s} {e.get('call')} carries no explanation at "
                      f"all (blank gloss)")
        band = (e.get("card") or {}).get("hcp")
        if band and band[0] == band[1] and (
                e.get("call") or "").upper() not in ("P", "PASS"):
            warn("D8", f"[{idx}] {s} {e.get('call')} is glossed with the "
                       f"degenerate band {band[0]}-{band[1]} HCP "
                       f"(hand has {hcp(deal[s])})")

    # ---- E. bidding options
    cands = rec.get("candidates") or []
    table = ((rec.get("verdict") or {}).get("table")) or []
    if kind == "bidding":
        calls = [c.get("call") for c in cands]
        if len(calls) < 2:
            bad("E1", f"only {len(calls)} option(s) offered")
        d = [c for c, k in Counter(calls).items() if k > 1]
        if d:
            bad("E2", f"duplicate option(s): {d}")
        for c in calls:
            if c and not legal_next(c, auction):
                bad("E3", f"option {c} is not a legal call after "
                          f"{'-'.join(auction)}")
        tcalls = [r.get("bid") for r in table]
        if set(tcalls) != set(calls):
            bad("E4", f"verdict table {sorted(filter(None,tcalls))} != "
                      f"options {sorted(filter(None,calls))}")
        acc = (rec.get("verdict") or {}).get("accepted")
        if acc and acc not in calls:
            bad("E5", f"accepted call {acc} is not among the offered options")
        pol = sum(c.get("policy") or 0 for c in cands)
        if pol > 1.02:
            bad("E6", f"option policy weights sum to {pol:.3f} > 1")
        # the option the hero is graded against must be the table's best
        if table and all("ev_imp_vs_top" in r for r in table):
            best = max(table, key=lambda r: r["ev_imp_vs_top"])
            if acc and best.get("bid") != acc and abs(
                    best["ev_imp_vs_top"] -
                    next(r["ev_imp_vs_top"] for r in table
                         if r.get("bid") == acc)) > 1e-9:
                bad("E7", f"accepted {acc} is not the best row "
                          f"({best.get('bid')} scores higher)")
        # a candidate offered with no rollout evidence at all
        for r in table:
            tc = r.get("top_contracts") or []
            if not tc:
                warn("E8", f"option {r.get('bid')} has no contract "
                           f"distribution")
        # a row that BEATS the accepted call by the record's own numbers:
        # verdict.py picks `accepted` as the EV argmax, so every other row's
        # ev_imp_vs_top (measured against the winner) must be <= 0
        for r in table:
            if r.get("bid") != acc and (r.get("ev_imp_vs_top") or 0) > 0:
                bad("E9", f"option {r.get('bid')} measures "
                          f"{r['ev_imp_vs_top']:+.2f} IMPs vs the accepted "
                          f"{acc} (best on {r.get('best_share')} of layouts "
                          f"against {acc}'s "
                          f"{next((x.get('best_share') for x in table if x.get('bid') == acc), '?')}) "
                          f"— the answer graded correct is not the one the "
                          f"evidence favours")
        # the hero's own displayed option text vs the hero's actual hand
        hh = deal.get(seat) or ""
        if hh:
            L, a = lengths(hh), hcp(hh)
            for o in (ex.get("options") or []):
                txt = o.get("text") or ""
                head = txt.split(". Leads to")[0].split(". Engine")[0]
                head = head.split(" — ", 1)[1] if " — " in head else ""
                for lo, hi, gl in re.findall(r"(\d+)(?:-(\d+))?\+?"
                                             r"([♠♥♦♣])", head):
                    suit = {"♠": "S", "♥": "H", "♦": "D", "♣": "C"}[gl]
                    if L[suit] < int(lo) - 1:
                        bad("E10", f"option text {head!r} claims "
                                   f"{lo}{gl} but you hold {L[suit]} ({hh})")
                m = re.search(r"(\d+)-(\d+)\s*$", head)
                if m and not (int(m.group(1)) - 2 <= a <= int(m.group(2)) + 2):
                    bad("E11", f"option text {head!r} states "
                               f"{m.group(1)}-{m.group(2)} HCP but you hold "
                               f"{a} ({hh})")

    # ---- F. lead options
    if kind == "lead":
        hero = rec.get("leader") or seat
        hand = set(cards(deal.get(hero, "...")))
        cc = [c.get("card") for c in cands]
        if len(cc) < 2:
            bad("F1", f"only {len(cc)} lead(s) offered")
        d = [c for c, k in Counter(cc).items() if k > 1]
        if d:
            bad("F2", f"duplicate lead option(s): {d}")
        outside = [c for c in cc if c and c not in hand]
        if outside:
            bad("F3", f"lead option(s) not in the leader's hand: "
                      f"{' '.join(outside)}")
        missing = sorted(hand - set(cc))
        if missing:
            warn("F4", f"{len(missing)} card(s) of the hand are not offered: "
                       f"{' '.join(missing)}")
        exc = [c.get("card") for c in (ex.get("cards") or [])]
        if set(exc) != set(cc):
            bad("F5", "explained cards differ from the offered leads")
        # ranks must follow the metric they claim to rank by
        for key, metric, sign in (("rank_mp", "avg_def_tricks", -1),
                                  ("rank_imp", "exp_imps", -1)):
            rows = [c for c in cands if c.get(key) and metric in c]
            rows.sort(key=lambda c: c[key])
            vals = [c[metric] for c in rows]
            if any(b - a > 1e-6 for a, b in zip(vals, vals[1:])):
                bad("F6", f"{key} does not order by {metric}: {vals}")
        for c in cands:
            t = c.get("avg_def_tricks")
            if t is not None and not 0 <= t <= 13:
                bad("F7", f"{c.get('card')}: avg_def_tricks {t} out of range")
            sp = c.get("set_prob")
            if sp is not None and not 0 <= sp <= 1:
                bad("F7", f"{c.get('card')}: set_prob {sp} out of range")
        acc = (rec.get("verdict") or {}).get("accepted") or []
        if isinstance(acc, str):
            acc = [acc]
        strays = [a for a in acc if a not in cc]
        if strays:
            bad("F8", f"accepted lead(s) {strays} not among the options")
        # the accepted lead must be the top-ranked one IN THE BOARD'S OWN
        # target mode (lead1i boards are graded on IMPs, lead1 on tricks)
        mode = (rec.get("training") or {}).get("target_mode") or "MP"
        rk = "rank_imp" if mode == "IMP" else "rank_mp"
        if acc and cands:
            best = min((c for c in cands if c.get(rk)),
                       key=lambda c: c[rk], default=None)
            if best and best.get("card") not in acc:
                bad("F9", f"accepted {acc} but {rk} 1 is "
                          f"{best.get('card')} (target mode {mode})")
        bym = ((rec.get("verdict") or {}).get("by_mode") or {}).get(mode) or {}
        if bym.get("accepted") and sorted(bym["accepted"]) != sorted(acc):
            bad("F12", f"verdict.accepted {acc} != by_mode.{mode}.accepted "
                       f"{bym['accepted']}")
        # two leads with identical evidence must be graded identically
        metric = "exp_imps" if mode == "IMP" else "avg_def_tricks"
        if acc:
            accv = [c[metric] for c in cands
                    if c.get("card") in acc and metric in c]
            if accv:
                for c in cands:
                    if (c.get("card") not in acc and metric in c
                            and any(abs(c[metric] - v) < 1e-9 for v in accv)):
                        bad("F13", f"{c.get('card')} scores exactly the same "
                                   f"{metric} ({c[metric]}) as the accepted "
                                   f"lead(s) {acc} but is graded wrong")
        # score plausibility: exp_score must sit inside the range the
        # contract can actually produce
        pc = parse_contract(rec.get("contract") or "")
        if pc:
            lvl, den, dbl, decl = pc
            v = is_vul(rec.get("vul"), decl)
            lo = -max(contract_score(lvl, "NT" if den == "N" else den, dbl, v,
                                     t) for t in range(0, 14))
            hi = -min(contract_score(lvl, "NT" if den == "N" else den, dbl, v,
                                     t) for t in range(0, 14))
            for c in cands:
                sc = c.get("exp_score")
                if sc is None:
                    continue
                if not lo - 1 <= sc <= hi + 1:
                    bad("F10", f"{c.get('card')}: exp_score {sc} outside the "
                               f"[{lo}, {hi}] range {rec.get('contract')} can "
                               f"produce (vul={rec.get('vul')})")
            need = 14 - (lvl + 6)      # defensive tricks needed to defeat it
            for c in cands:
                t, sp = c.get("avg_def_tricks"), c.get("set_prob")
                if t is None or sp is None:
                    continue
                if sp == 0 and t >= need:
                    bad("F11", f"{c.get('card')}: set_prob 0 but average "
                               f"{t} defensive tricks >= the {need} needed")
                if sp == 1 and t < need:
                    bad("F11", f"{c.get('card')}: set_prob 1 but average "
                               f"{t} defensive tricks < the {need} needed")

    # ---- G. score / probability arithmetic (bidding)
    for r in table:
        ps = [r.get(k) for k in ("p_gain", "p_loss", "p_push")]
        if all(p is not None for p in ps):
            tot = sum(ps)
            if abs(tot - 1.0) > 0.02:
                bad("G1", f"option {r.get('bid')}: p_gain+p_loss+p_push = "
                          f"{tot:.3f}")
            for k in ("p_gain", "p_loss", "p_push"):
                if not 0 <= r[k] <= 1:
                    bad("G1", f"option {r.get('bid')}: {k} = {r[k]}")
        bs = r.get("best_share")
        if bs is not None and not 0 <= bs <= 1:
            bad("G2", f"option {r.get('bid')}: best_share {bs}")
        ci = r.get("ci")
        if ci is not None and ci < 0:
            bad("G2", f"option {r.get('bid')}: negative CI {ci}")
        n = (rec.get("quality") or {}).get("n_samples")
        tc = r.get("top_contracts") or []
        if n and tc:
            tot = sum(c[1] for c in tc if isinstance(c, list) and len(c) > 1)
            if tot > n:
                bad("G3", f"option {r.get('bid')}: contract counts total "
                          f"{tot} > {n} samples")
    if kind == "bidding" and table:
        tops = [r for r in table if abs(r.get("ev_imp_vs_top", 0)) < 1e-9]
        # the reference row's own margin is stated vs the runner-up, so a
        # positive top and negatives elsewhere is the convention; more than one
        # non-negative row means two calls both claim to beat the field
        pos = [r.get("bid") for r in table if (r.get("ev_imp_vs_top") or 0) > 0]
        if len(pos) > 1:
            bad("G4", f"{len(pos)} options claim a positive margin vs the "
                      f"top: {pos}")

    # ---- H. bridge sanity of the auction itself, from the actual cards
    #   (no gloss involved: these are actions no partnership would take)
    full = list(rec.get("engine_auction_complete") or auction)
    if full[:len(auction)] != auction and rec.get("engine_auction_complete"):
        bad("H0", "engine_auction_complete does not start with the displayed "
                  "auction")
    seen_bid = False
    for i, call in enumerate(auction):
        s = SEATS[(di + i) % 4]
        h = deal.get(s)
        if not h:
            continue
        a = hcp(h)
        c = call.upper()
        if c in ("P", "PASS"):
            # A seat that passes a hand no partnership passes, while the
            # auction is still at the ONE level and its own side has said
            # nothing: not a style shade, a bid nobody would miss.
            if not seen_bid and a >= 13:
                bad("H1", f"{s} passed with {a} HCP as the first bid of the "
                          f"auction ({h})")
            elif seen_bid:
                err2, st2 = legal_calls_state(auction[:i])
                mine = any(auction[j].upper() not in ("P", "PASS", "X", "XX")
                           for j in range(i) if (j - i) % 2 == 0)
                if (not err2 and st2[0] and st2[0] // 5 == 1 and not mine
                        and a >= 16):
                    bad("H1", f"{s} passed with {a} HCP over a one-level "
                              f"auction, its side silent ({h})")
        else:
            if not seen_bid:
                seen_bid = True
                L = lengths(h)
                if a <= 5 and max(L.values()) <= 5:
                    bad("H2", f"{s} opened {call} with {a} HCP and no long "
                              f"suit ({h})")
    # Final contract vs the two hands that bid it. Only UNCONTESTED auctions:
    # a low-HCP game the other side bid over is a sacrifice, not a bad bid.
    if kind == "lead":
        pcx = parse_contract(rec.get("contract") or "")
        if pcx:
            lvl, den, dbl, decl = pcx
            side = (decl, SEATS[(SEATS.index(decl) + 2) % 4])
            comb = sum(hcp(deal[s]) for s in side)
            opp_bid = any(
                auction[i].upper() not in ("P", "PASS", "X", "XX")
                and SEATS[(di + i) % 4] not in side
                for i in range(len(auction)))
            if not dbl and not opp_bid:
                if lvl >= 3 and den == "N" and comb <= 21:
                    bad("H3", f"{rec.get('contract')} bid in an uncontested "
                              f"auction on {comb} combined HCP")
                elif lvl >= 4 and comb <= 19:
                    bad("H3", f"{rec.get('contract')} bid in an uncontested "
                              f"auction on {comb} combined HCP")

    # ---- I. is there a decision to teach at all? (lead boards)
    if kind == "lead" and cands:
        sps = [c.get("set_prob") for c in cands if c.get("set_prob")
               is not None]
        tks = [c.get("avg_def_tricks") for c in cands
               if c.get("avg_def_tricks") is not None]
        if sps and max(sps) <= 0.02:
            bad("I1", f"no lead defeats {rec.get('contract')} on more than "
                      f"{max(sps):.0%} of layouts — the contract is cold "
                      f"whatever you lead")
        if sps and min(sps) >= 0.98:
            bad("I1", f"every lead defeats {rec.get('contract')} on "
                      f">= {min(sps):.0%} of layouts")
        pcy = parse_contract(rec.get("contract") or "")
        need = 14 - (pcy[0] + 6) if pcy else 4
        if tks and max(tks) < need - 2.5:
            bad("I2", f"the best lead averages {max(tks):.2f} defensive "
                      f"tricks against {rec.get('contract')}, which needs "
                      f"{need} to beat — the defence has nothing to find")
    return out


def _local_records(pool_dir):
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(Path(pool_dir).glob("problems/*.json"))]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pool", nargs="?", help="local pool dir (omit with "
                                            "--firestore)")
    ap.add_argument("--firestore", action="store_true",
                    help="audit the live Firestore pool")
    ap.add_argument("--key", default=None,
                    help="service-account JSON (or set "
                         "GOOGLE_APPLICATION_CREDENTIALS)")
    ap.add_argument("--out", default=None,
                    help="write the full findings to this JSON file")
    ap.add_argument("--code", default="",
                    help="comma-separated codes to report (default: all)")
    args = ap.parse_args(argv)
    if bool(args.pool) == bool(args.firestore):
        ap.error("give a pool dir OR --firestore")

    if args.firestore:
        from bridge_trainer.pool.firestore_store import FirestorePool
        recs = FirestorePool(args.key).stream_records()
    else:
        recs = _local_records(args.pool)
    want = {c.strip() for c in args.code.split(",") if c.strip()}

    findings, codes = {}, Counter()
    for r in recs:
        try:
            f = audit(r)
        except Exception as e:                       # never lose the report
            f = [("BAD", "ERR", f"{type(e).__name__}: {e}")]
        if want:
            f = [x for x in f if x[1] in want]
        if f:
            findings[r["id"]] = f
            for sev, code, _ in f:
                codes[(sev, code)] += 1
    print(f"{len(findings)} of {len(recs)} records have at least one finding\n")
    for (sev, code), k in sorted(codes.items(), key=lambda x: -x[1]):
        boards = len({p for p, fs in findings.items()
                      if any(c == code for _s, c, _m in fs)})
        print(f"  {sev:5} {code:4} {k:5} finding(s)  {boards:5} board(s)")

    byd = defaultdict(list)
    for r in recs:
        byd[(json.dumps(r.get("full_deal"), sort_keys=True),
             tuple(r.get("auction") or []), r.get("kind"))].append(r["id"])
    dups = [v for v in byd.values() if len(v) > 1]
    print(f"\nsame deal + same auction published more than once: {len(dups)}")
    for v in dups[:15]:
        print("   ", " ".join(sorted(v)))

    if args.out:
        Path(args.out).write_text(json.dumps(
            {"findings": findings, "duplicates": [sorted(v) for v in dups]},
            indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"\nfindings written to {args.out}")
    return 1 if any(s == "BAD" for fs in findings.values()
                    for s, _c, _m in fs) else 0


if __name__ == "__main__":
    sys.exit(main())
