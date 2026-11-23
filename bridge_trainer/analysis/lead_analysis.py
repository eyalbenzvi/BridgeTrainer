"""Opening-lead analysis of a user-entered deal (leads twin of the bidding
analysis behind analyze.html).

The user enters the leader's 13 cards and the COMPLETE auction (ending in
three passes). The Ben engine — the same grader the lead-problem forge
uses (engine.lead_evaluate) — samples layouts of the three hidden hands
consistent with the auction, double-dummy solves every distinct lead on
the SAME layouts (INV1), and this module turns the per-sample defensive
tricks into a ranked, statistically honest lead table:

  * expected defensive tricks, set probability, expected duplicate score
    and expected IMPs (scoring/lead_metrics — datum = mean over leads);
  * the paired difference of every lead against the best one, with a 95%
    CI, in the unit of the chosen scoring (tricks for MP, IMPs for IMP);
  * the distribution of defensive tricks for the leading options.

Cards that are equivalent on every sampled layout (Ben folds spot cards
7..2 into one "low" lead per suit; touching honours often tie too) are
grouped into one row.

Requires the external Ben checkout (BEN_HOME; scripts/setup_ben.sh). Tests
inject a fake engine exposing ``lead_evaluate``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from ..scoring.lead_metrics import (compute_lead_metrics, per_sample_imps)
from ..validate.auction_state import AuctionStateError, replay

SEATS = "NESW"
SUITS = "SHDC"
RANKS = "AKQJT98765432"
DEFAULT_SAMPLES = 512
MAX_SAMPLES = 1000
MIN_SAMPLES = 100
TOSS_UP = {"MP": 0.10, "IMP": 0.25}   # |diff| below this is a wash anyway
QUALITY_WARN = 0.8
QUALITY_BAD = 0.5


@dataclass
class LeadAnalysisRequest:
    dealer: str
    vul: str
    my_seat: str
    my_hand: str
    auction: list
    scoring: str = "IMP"
    actual_lead: str | None = None
    seed: int = 1
    n_samples: int = DEFAULT_SAMPLES


# ---------------------------------------------------------------------------
# validation
def _hand_cards(pbn: str) -> list[str]:
    parts = pbn.split(".")
    if len(parts) != 4:
        raise ValueError("hand must be PBN 'S.H.D.C'")
    cards = []
    for suit, holding in zip(SUITS, parts):
        for r in holding:
            if r not in RANKS:
                raise ValueError(f"bad rank {r!r}")
            cards.append(suit + r)
    if len(cards) != 13 or len(set(cards)) != 13:
        raise ValueError("the hand must hold exactly 13 distinct cards")
    return cards


def final_contract(dealer: str, auction: list) -> dict:
    """Replay the complete auction; return {level, denom, declarer,
    doubled ('', 'x', 'xx'), leader, contract ('4HE', '3NTWx')}."""
    state = replay(dealer, list(auction))      # AuctionStateError if illegal
    if not state.finished:
        raise AuctionStateError(
            "the auction is not over — enter it to the end (three passes "
            "after the last bid)")
    fc = state.standing_contract()
    if fc is None:
        raise AuctionStateError("the board was passed out — no lead")
    dbl = "x" * state.doubled
    declarer = fc.declarer
    leader = SEATS[(SEATS.index(declarer) + 1) % 4]
    return {"level": state.level, "denom": state.denom,
            "declarer": declarer, "doubled": dbl, "leader": leader,
            "contract": f"{state.level}{state.denom}{declarer}{dbl}"}


def validate(req: LeadAnalysisRequest) -> dict:
    _hand_cards(req.my_hand)
    if req.vul not in ("None", "NS", "EW", "Both"):
        raise ValueError(f"bad vulnerability {req.vul!r}")
    if req.scoring not in ("IMP", "MP"):
        raise ValueError(f"bad scoring mode {req.scoring!r}")
    if req.dealer not in SEATS or req.my_seat not in SEATS:
        raise ValueError("bad seat")
    fc = final_contract(req.dealer, req.auction)
    if fc["leader"] != req.my_seat:
        raise AuctionStateError(
            f"the opening leader is {fc['leader']}, not {req.my_seat}")
    if req.actual_lead and req.actual_lead not in _hand_cards(req.my_hand):
        raise ValueError("the actual lead is not in the hand")
    return fc


# ---------------------------------------------------------------------------
# the engine run
def _vul_tuple(vul: str) -> tuple:
    return (vul in ("NS", "Both"), vul in ("EW", "Both"))


def _default_engine():
    from .ben_pipeline import ben_available
    if not ben_available():
        raise RuntimeError(
            "Ben engine not installed (BEN_HOME) — run scripts/setup_ben.sh;"
            " the lead analysis requires Ben")
    from ..engine.ben import get_engine
    return get_engine()


def _group_cards(cards: list, def_tricks: dict) -> list[list[str]]:
    """Same-suit cards with identical per-sample results -> one option."""
    groups: list[list[str]] = []
    for c in cards:
        for g in groups:
            if g[0][0] == c[0] and np.array_equal(def_tricks[g[0]],
                                                  def_tricks[c]):
                g.append(c)
                break
        else:
            groups.append([c])
    return groups


def _paired(diff: np.ndarray) -> tuple[float, float]:
    n = diff.shape[0]
    mean = float(diff.mean())
    half = float(1.96 * diff.std(ddof=1) / np.sqrt(n)) if n > 1 else 0.0
    return mean, half


def run_lead_analysis(req: LeadAnalysisRequest, engine=None) -> dict:
    """Validate, grade every lead, return the report facts (JSON-safe)."""
    fc = validate(req)
    t0 = time.time()
    engine = engine or _default_engine()
    n_req = max(MIN_SAMPLES, min(int(req.n_samples), MAX_SAMPLES))
    try:                                   # Ben seeds per hand; best effort
        np.random.seed(int(req.seed))
    except (TypeError, ValueError):
        pass
    le = engine.lead_evaluate(
        req.my_hand, SEATS.index(req.my_seat), SEATS.index(req.dealer),
        _vul_tuple(req.vul), list(req.auction), fc["denom"],
        fc["contract"], bool(fc["doubled"]), n_samples=n_req)
    if not le.cards or le.n_samples == 0:
        raise RuntimeError(
            "the engine found no layouts consistent with this auction")
    return build_lead_facts(req, fc, le, time.time() - t0)


def build_lead_facts(req: LeadAnalysisRequest, fc: dict, le,
                     elapsed: float = 0.0) -> dict:
    mode = req.scoring
    cards = list(le.cards)
    dt = {c: np.asarray(le.def_tricks[c], dtype=float) for c in cards}
    n = int(next(iter(dt.values())).shape[0])
    metrics = compute_lead_metrics(dt, fc["contract"], req.vul)
    imps = per_sample_imps(dt, fc["contract"], req.vul)
    unit = dt if mode == "MP" else imps        # the judging unit per sample
    to_set = 8 - fc["level"]

    groups = _group_cards(cards, dt)
    key = "exp_def_tricks" if mode == "MP" else "exp_imps"

    def order(g):
        m = metrics[g[0]]
        return (-m[key], -m["exp_score"], SUITS.index(g[0][0]),
                RANKS.index(g[0][1]))

    groups.sort(key=order)
    best = groups[0][0]
    rows = []
    for g in groups:
        c = g[0]
        m = metrics[c]
        diff_mean, diff_ci = _paired(np.asarray(unit[c]) -
                                     np.asarray(unit[best]))
        hist = np.bincount(np.rint(dt[c]).astype(int), minlength=14)[:14]
        if c == best:
            verdict = "best"
        elif abs(diff_mean) <= max(diff_ci, TOSS_UP[mode]):
            verdict = "close"
        else:
            verdict = "worse"
        rows.append({
            "cards": g, "suit": c[0],
            "exp_def_tricks": round(m["exp_def_tricks"], 3),
            "set_prob": round(m["set_prob"], 4),
            "exp_score": round(m["exp_score"], 1),
            "exp_imps": round(m["exp_imps"], 3),
            "diff": round(diff_mean, 3), "diff_ci": round(diff_ci, 3),
            "verdict": verdict,
            "ben_p": round(float(max(le.softmax.get(x, 0.0) for x in g)), 4),
            "hist": [round(float(v) / n, 4) for v in hist],
            "is_actual": bool(req.actual_lead and req.actual_lead in g),
        })

    # the strongest alternative in a DIFFERENT suit — the real decision
    alt = next((r for r in rows[1:] if r["suit"] != rows[0]["suit"]), None)
    ben_top = max(cards, key=lambda c: le.softmax.get(c, 0.0))
    notes = []
    q = float(getattr(le, "quality", 1.0) or 0.0)
    if q < QUALITY_BAD:
        notes.append("התאמת המכרז לשיטת המנוע נמוכה מאוד — ייתכן שחלק "
                     "מההכרזות מתפרשות אחרת אצל המנוע (הסכמים מיוחדים). "
                     "התייחס לתוצאות בזהירות.")
    elif q < QUALITY_WARN:
        notes.append("התאמת המכרז לשיטת המנוע חלקית — חלק מהחלוקות "
                     "שנדגמו תואמות את המכרז רק בקירוב.")
    if n < 200:
        notes.append(f"נמצאו רק {n} חלוקות תואמות — רווחי הסמך רחבים.")
    return {
        "kind": "lead",
        "meta": {"dealer": req.dealer, "vul": req.vul,
                 "my_seat": req.my_seat, "scoring": mode,
                 "seed": req.seed, "n_samples": n,
                 "quality": round(q, 3), "elapsed_s": round(elapsed, 1),
                 "engine": "Ben BEN-21GF"},
        "hand": {"pbn": req.my_hand},
        "auction": list(req.auction),
        "contract": fc, "to_set": to_set,
        "recommended": best,
        "recommended_cards": rows[0]["cards"],
        "alt_suit": alt,
        "ben_top": ben_top,
        "actual_lead": req.actual_lead,
        "rows": rows,
        "notes": notes,
    }
