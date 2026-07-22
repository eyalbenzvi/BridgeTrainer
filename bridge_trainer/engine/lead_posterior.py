"""Opening-lead posterior sampling audit — the auditable core.

The objective is fixed and NOT negotiable here:

    best lead = argmax over legal PHYSICAL cards of
                E[ DD defensive tricks | leader hand, public auction, contract ]

This module makes that estimate *auditable*. It is deliberately split so the
statistical machinery is pure (numpy + endplay's double-dummy solver, no Ben
import) and therefore unit-tested in normal CI — exactly the coverage the
production neural sampler inside Ben never had.

Nothing in the public state carries the hidden *source* deal. `LeadProblem`
holds only what the leader can see (their own hand, the auction, the
contract). The samplers take a `LeadProblem` and a seed; they never receive
the other three source hands. Source-deal independence is therefore a
structural property, and `assert_source_deal_independent` proves it by
construction on top of that.

Honest labels are mandatory (see the module constants): the production
sampler is a *thresholded uniform average over a neural-consistency filter*,
not a calibrated posterior. We name it that.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

SUITS = "SHDC"
RANKS = "AKQJT98765432"
SEATS = "NESW"
STRAINS = "CDHSN"   # endplay Denom ordering is c,d,h,s,nt


# ---------------------------------------------------------------------------
# honest provenance labels (owner requirement 3)
# ---------------------------------------------------------------------------
# The production pipeline: propose a full deal consistent with the leader's
# hand -> score it by how well Ben's neural bidder reproduces the observed
# calls (an UNCALIBRATED heuristic in [0,1], not a likelihood) -> accept the
# deal iff score >= bidding_threshold_sampling -> average double-dummy tricks
# UNIFORMLY over the accepted deals. That is estimating a thresholded neural
# consistency distribution Q, not the intended posterior P(deal|public info).
SAMPLING_MODEL_CURRENT = "thresholded_uniform_neural_consistency"
CALIBRATION_UNCALIBRATED = "uncalibrated"
WEIGHTING_UNIFORM = "uniform_over_accepted"

# Ben's shipped BEN-21GF.conf value for the acceptance threshold the owner's
# sweep varies (verified against the pinned commit's config).
BEN_BIDDING_THRESHOLD_DEFAULT = 0.70
BEN_EXCLUDE_SAMPLES = 0.01   # per-seat pre-filter in Ben's sampler


# ---------------------------------------------------------------------------
# public state (never the hidden source deal)
# ---------------------------------------------------------------------------
def _seatname(x) -> str:
    return x if isinstance(x, str) else SEATS[int(x)]


@dataclass(frozen=True)
class LeadProblem:
    """Immutable PUBLIC state of one opening-lead decision.

    `hand` is the leader's 13 cards as a PBN holding "S.H.D.C", e.g.
    "874.AQ94.T.97642". `auction` runs from the dealer. `strain` is one of
    C/D/H/S/N. Everything else is derived from the auction/contract by the
    caller (see build_problem). The hidden hands of the other three players
    are NOT stored — they must not influence anything downstream.
    """
    hand: str
    auction: tuple
    dealer: str
    vul: str
    contract: str
    strain: str
    declarer: str
    leader: str
    doubled: str = ""

    def legal_leads(self) -> list[str]:
        """Every PHYSICAL card in the leader's hand, suit-then-rank order.

        Note we grade PHYSICAL cards, not Ben's 32-card 'low card per suit'
        folding: touching spots simply tie on identical DD values, which is
        the correct equivalence and keeps 'evaluate every legal lead exactly
        once' literally true."""
        out = []
        for suit, holding in zip(SUITS, self.hand.split(".")):
            out.extend(suit + r for r in holding)
        return out

    def leader_i(self) -> int:
        return SEATS.index(self.leader)


def build_problem(hand: str, auction, dealer, vul, contract: str) -> LeadProblem:
    """Assemble a LeadProblem from public inputs, parsing the contract token
    'levelDENOMdeclarer[x/xx]' e.g. '3NTW', '4HEx'."""
    c = contract.strip()
    level = c[0]
    rest = c[1:]
    if rest.startswith("NT"):
        strain, rest = "N", rest[2:]
    else:
        strain, rest = rest[0], rest[1:]
    declarer = rest[0]
    doubled = rest[1:].lower()
    leader = SEATS[(SEATS.index(declarer) + 1) % 4]
    return LeadProblem(
        hand=hand, auction=tuple(auction), dealer=_seatname(dealer), vul=vul,
        contract=f"{level}{'NT' if strain=='N' else strain}{declarer}{doubled}",
        strain=strain, declarer=declarer, leader=leader, doubled=doubled)


# ---------------------------------------------------------------------------
# sampled layouts
# ---------------------------------------------------------------------------
@dataclass
class LayoutSet:
    """A shared set of complete, card-conserving deals for ONE problem.

    Every candidate lead is graded on THIS set (never a per-card resample) so
    the paired deltas are meaningful. `bidding_score`/`weight` are per-layout;
    `weight` is what the trick average uses (uniform => all equal).
    """
    problem: LeadProblem
    hands: list          # list[dict seat->pbn]; leader hand identical in all
    bidding_score: np.ndarray
    weight: np.ndarray
    sampling_model: str
    sampler_version: str
    posterior_calibration_status: str
    weighting_method: str
    score_threshold: float | None
    proposal_count: int
    requested_samples: int
    accepted_samples: int
    seed: int
    auction_replay_mode: str = "none"
    semantic_constraint_mode: str = "none"
    source_deal_independent: bool = True

    def __post_init__(self):
        self.bidding_score = np.asarray(self.bidding_score, dtype=float)
        w = np.asarray(self.weight, dtype=float)
        s = w.sum()
        self.weight = (w / s) if s > 0 else w
        _assert_card_conserving(self)

    @property
    def n(self) -> int:
        return len(self.hands)

    def ess(self) -> float:
        """Kish effective sample size of the weights. Uniform => n."""
        w = self.weight
        d = float((w ** 2).sum())
        return float((w.sum() ** 2) / d) if d > 0 else 0.0

    def provenance(self) -> dict:
        return {
            "sampling_model": self.sampling_model,
            "sampler_version": self.sampler_version,
            "posterior_calibration_status": self.posterior_calibration_status,
            "weighting_method": self.weighting_method,
            "score_threshold": self.score_threshold,
            "proposal_count": self.proposal_count,
            "requested_samples": self.requested_samples,
            "accepted_samples": self.accepted_samples,
            "ess": round(self.ess(), 2),
            "seed": self.seed,
            "auction_replay_mode": self.auction_replay_mode,
            "semantic_constraint_mode": self.semantic_constraint_mode,
            "source_deal_independent": bool(self.source_deal_independent),
        }


def _cards(pbn: str) -> set:
    out = set()
    for suit, holding in zip(SUITS, pbn.split(".")):
        out.update(suit + r for r in holding)
    return out


def _assert_card_conserving(ls: LayoutSet) -> None:
    """Every layout is a legal, card-conserving deal whose leader hand equals
    the problem's fixed leader hand."""
    lead = ls.problem.leader
    leadcards = _cards(ls.problem.hand)
    full = {s + r for s in SUITS for r in RANKS}
    for i, hd in enumerate(ls.hands):
        if set(hd) != set(SEATS):
            raise ValueError(f"layout {i}: seats {sorted(hd)} != NESW")
        seen = set()
        for seat, pbn in hd.items():
            cs = _cards(pbn)
            if len(cs) != 13:
                raise ValueError(f"layout {i} seat {seat}: {len(cs)} cards")
            if seen & cs:
                raise ValueError(f"layout {i}: duplicate card {seen & cs}")
            seen |= cs
        if seen != full:
            raise ValueError(f"layout {i}: not a full 52-card deal")
        if _cards(hd[lead]) != leadcards:
            raise ValueError(f"layout {i}: leader hand mutated")


# ---------------------------------------------------------------------------
# double-dummy evaluation (real DDS via endplay; no Ben)
# ---------------------------------------------------------------------------
_DD_CACHE: dict = {}


def _card_token(card) -> str:
    """endplay Card -> our physical token e.g. 'H4','SA'. Suit from
    card.suit.name[0] (c/d/h/s), rank from card.rank.name ('R2'..'RA') second
    char. NO folding: 2..9 stay distinct, exactly as dealt."""
    suit = {"clubs": "C", "diamonds": "D", "hearts": "H",
            "spades": "S"}[card.suit.name]
    rank = card.rank.name[1]          # 'R4' -> '4', 'RT' -> 'T', 'RA' -> 'A'
    return suit + rank


def _dd_defensive_tricks(problem: LeadProblem, hd: dict) -> dict:
    """Defensive DD tricks for EVERY physical leader card on one full deal.

    Uses endplay.solve_board with the leader on lead and the true strain, so
    each returned value is directly 'tricks the defence takes on best play if
    the leader leads THIS EXACT physical card'. endplay returns one row per
    physical card in hand — no 32-code folding, no random low-pip substitution
    — so H4 and H9 (and H2, H3, ...) are graded as themselves. Deterministic
    and exact, hence memoisable by (deal, strain, leader).
    """
    from endplay.types import Deal, Denom, Player
    from endplay.dds import solve_board

    pbn = "N:" + " ".join(hd[s] for s in SEATS)
    key = (pbn, problem.strain, problem.leader)
    if key in _DD_CACHE:
        return _DD_CACHE[key]
    d = Deal(pbn)
    d.trump = {"C": Denom.clubs, "D": Denom.diamonds, "H": Denom.hearts,
               "S": Denom.spades, "N": Denom.nt}[problem.strain]
    d.first = getattr(Player, {"N": "north", "E": "east",
                               "S": "south", "W": "west"}[problem.leader])
    out = {}
    for card, tricks in solve_board(d):
        out[_card_token(card)] = int(tricks)
    _DD_CACHE[key] = out
    return out


def card_level_trace(problem: LeadProblem, hd: dict) -> list:
    """Per-card DDS audit trace for ONE layout (low-card-bug audit, req 6).

    Returns, for every physical leader card, the exact DDS input (suit, rank,
    leader seat, strain), the physical card token echoed back from the DDS
    result, and the returned defensive-trick value. Proves the requested
    physical card is the one graded — no substitution, no folding, no
    honor/low reuse.
    """
    from endplay.types import Deal, Denom, Player
    from endplay.dds import solve_board

    pbn = "N:" + " ".join(hd[s] for s in SEATS)
    d = Deal(pbn)
    d.trump = {"C": Denom.clubs, "D": Denom.diamonds, "H": Denom.hearts,
               "S": Denom.spades, "N": Denom.nt}[problem.strain]
    d.first = getattr(Player, {"N": "north", "E": "east",
                               "S": "south", "W": "west"}[problem.leader])
    returned = {}
    for card, tricks in solve_board(d):
        returned[_card_token(card)] = (card.suit.name, card.rank.name, int(tricks))
    trace = []
    for tok in problem.legal_leads():
        suit, rank = tok[0], tok[1]
        suit_name, rank_name, tricks = returned.get(tok, (None, None, None))
        trace.append({
            "candidate": tok,
            "dds_input_suit": suit,
            "dds_input_rank": rank,
            "dds_input_leader": problem.leader,
            "dds_input_strain": problem.strain,
            "dds_returned_suit": suit_name,
            "dds_returned_rank": rank_name,
            "dds_returned_token": tok if suit_name else None,
            "def_tricks": tricks,
            "matched": suit_name is not None
            and {"clubs": "C", "diamonds": "D", "hearts": "H",
                 "spades": "S"}[suit_name] == suit
            and rank_name[1] == rank,
        })
    return trace


@dataclass
class LeadEval:
    """Per-card defensive-trick evidence on ONE shared LayoutSet.

    def_tricks[card] is a length-n array (one entry per layout). Every legal
    physical lead is present exactly once and all use the SAME layouts.
    """
    problem: LeadProblem
    cards: list
    def_tricks: dict
    weight: np.ndarray
    bidding_score: np.ndarray

    def weighted_mean(self) -> dict:
        w = self.weight
        return {c: float(np.average(self.def_tricks[c], weights=w))
                for c in self.cards}

    def ranking(self) -> list:
        m = self.weighted_mean()
        return sorted(self.cards, key=lambda c: -m[c])


def evaluate_layouts(ls: LayoutSet, dd_fn=None) -> LeadEval:
    """Double-dummy every physical lead on every layout (shared set).

    Enforces the owner's invariants: exactly the 13 physical leads, each once,
    all on the same layouts.
    """
    dd_fn = dd_fn or _dd_defensive_tricks
    p = ls.problem
    cards = p.legal_leads()
    if len(cards) != 13 or len(set(cards)) != 13:
        raise ValueError("leader must hold exactly 13 distinct cards")
    per = {c: np.empty(ls.n, dtype=float) for c in cards}
    for i, hd in enumerate(ls.hands):
        dt = dd_fn(p, hd)
        for c in cards:
            if c not in dt:
                raise ValueError(f"DD did not score lead {c} on layout {i}")
            per[c][i] = dt[c]
    return LeadEval(problem=p, cards=cards, def_tricks=per,
                    weight=ls.weight.copy(), bidding_score=ls.bidding_score.copy())


def card_level_audit(ls: LayoutSet, ev: LeadEval,
                     focus: list | None = None) -> dict:
    """End-to-end card-correctness audit over the whole shared LayoutSet
    (low-card-bug requirement 8).

    Proves each physical candidate keeps its own aggregation slot: reports the
    candidate->aggregation-index map, per-card mean/rank, per-layout value
    summary for the focus cards, and the number of layouts on which each pair
    of focus cards produces DIFFERENT DD values (so equal values are shown to
    come from DDS agreement, not from candidate merging).
    """
    m = ev.weighted_mean()
    order = ev.ranking()
    cards = ev.cards
    mapping = []
    for idx, c in enumerate(cards):
        arr = ev.def_tricks[c]
        mapping.append({
            "candidate": c,
            "aggregation_index": idx,
            "n_layouts": int(arr.shape[0]),
            "mean_def_tricks": round(m[c], 4),
            "rank": order.index(c) + 1,
            "min": float(arr.min()) if arr.size else None,
            "max": float(arr.max()) if arr.size else None,
        })
    focus = [c for c in (focus or []) if c in ev.def_tricks]
    pair_diffs = {}
    for i in range(len(focus)):
        for j in range(i + 1, len(focus)):
            a, b = focus[i], focus[j]
            diff = ev.def_tricks[a] != ev.def_tricks[b]
            pair_diffs[f"{a}_vs_{b}"] = {
                "layouts_differ": int(diff.sum()),
                "layouts_equal": int((~diff).sum()),
                "mean_a": round(m[a], 4), "mean_b": round(m[b], 4),
            }
    return {
        "n_candidates": len(cards),
        "all_distinct": len(set(cards)) == len(cards),
        "candidate_to_index": mapping,
        "focus_pair_differences": pair_diffs,
    }


# ---------------------------------------------------------------------------
# delta diagnostics (owner requirement 4) — diagnostics ONLY, never ranking
# ---------------------------------------------------------------------------
def _weighted_quantile(x, q, w):
    idx = np.argsort(x)
    x, w = np.asarray(x)[idx], np.asarray(w)[idx]
    cw = np.cumsum(w)
    cw /= cw[-1]
    return float(np.interp(q, cw, x))


def delta_report(best: np.ndarray, runner: np.ndarray,
                 weight: np.ndarray | None = None,
                 n_boot: int = 2000, seed: int = 0) -> dict:
    """Per-layout delta = DD(best) - DD(runner-up) diagnostics.

    These describe WHY the mean-DD gap is what it is (tails, win/loss mix);
    they do NOT replace the mean-DD ranking. Cap for the winsorised mean is
    the owner's abs(delta) <= 2.
    """
    best = np.asarray(best, dtype=float)
    runner = np.asarray(runner, dtype=float)
    delta = best - runner
    n = delta.shape[0]
    w = np.ones(n) if weight is None else np.asarray(weight, dtype=float)
    w = w / w.sum() if w.sum() > 0 else w
    ess = float((w.sum() ** 2) / (w ** 2).sum()) if (w ** 2).sum() > 0 else 0.0

    mean = float(np.average(delta, weights=w))
    var = float(np.average((delta - mean) ** 2, weights=w))
    sd = var ** 0.5
    se = sd / (ess ** 0.5) if ess > 0 else float("nan")
    median = _weighted_quantile(delta, 0.5, w)

    # bootstrap CI on the weighted mean (resample layout indices ~ weights)
    rng = np.random.default_rng(seed)
    boots = np.empty(n_boot)
    idx_all = np.arange(n)
    for b in range(n_boot):
        pick = rng.choice(idx_all, size=n, replace=True, p=w)
        boots[b] = delta[pick].mean()
    ci = (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5)))

    wins = float(w[delta > 1e-9].sum())
    losses = float(w[delta < -1e-9].sum())
    ties = float(w[np.abs(delta) <= 1e-9].sum())
    cond_win = float(np.average(delta[delta > 1e-9],
                                weights=w[delta > 1e-9])) if wins > 0 else 0.0
    cond_loss = float(np.average(delta[delta < -1e-9],
                                 weights=w[delta < -1e-9])) if losses > 0 else 0.0

    def trimmed(frac):
        lo = _weighted_quantile(delta, frac, w)
        hi = _weighted_quantile(delta, 1 - frac, w)
        m = (delta >= lo) & (delta <= hi)
        return float(np.average(delta[m], weights=w[m])) if m.any() else mean

    winsor = np.clip(delta, -2.0, 2.0)
    winsor_mean = float(np.average(winsor, weights=w))

    def tail_contrib(frac, top=True):
        # share of the (weighted) total delta mass contributed by the top/bottom
        # `frac` of layouts by delta value
        thr = _weighted_quantile(delta, 1 - frac if top else frac, w)
        m = (delta >= thr) if top else (delta <= thr)
        total = float((w * delta).sum())
        part = float((w[m] * delta[m]).sum())
        return (part / total) if abs(total) > 1e-12 else 0.0

    return {
        "n": n, "ess": round(ess, 2),
        "mean": round(mean, 4), "median": round(median, 4),
        "sd": round(sd, 4), "se": round(se, 4),
        "boot_ci95": [round(ci[0], 4), round(ci[1], 4)],
        "win_rate": round(wins, 4), "loss_rate": round(losses, 4),
        "tie_rate": round(ties, 4),
        "cond_mean_win": round(cond_win, 4),
        "cond_mean_loss": round(cond_loss, 4),
        "trimmed_mean_1pct": round(trimmed(0.01), 4),
        "trimmed_mean_5pct": round(trimmed(0.05), 4),
        "winsorized_mean_cap2": round(winsor_mean, 4),
        "top_contrib_1pct": round(tail_contrib(0.01, True), 4),
        "top_contrib_5pct": round(tail_contrib(0.05, True), 4),
        "top_contrib_10pct": round(tail_contrib(0.10, True), 4),
        "bottom_contrib_1pct": round(tail_contrib(0.01, False), 4),
        "bottom_contrib_5pct": round(tail_contrib(0.05, False), 4),
        "bottom_contrib_10pct": round(tail_contrib(0.10, False), 4),
    }


def is_tail_dominated(report: dict) -> bool:
    """Heuristic: the headline mean is driven by extreme observations.

    True when a tiny fraction of layouts supplies most of the signed delta
    mass AND the robust (trimmed) mean substantially disagrees with the raw
    mean (or flips sign). Diagnostic only.
    """
    mean = report["mean"]
    trimmed = report["trimmed_mean_5pct"]
    top1 = abs(report["top_contrib_1pct"])
    top5 = abs(report["top_contrib_5pct"])
    if abs(mean) < 1e-9:
        return top5 > 0.9
    flips = (np.sign(trimmed) != np.sign(mean))
    shrinks = abs(trimmed) < 0.5 * abs(mean)
    concentrated = top1 > 0.5 or top5 > 0.8
    return bool(concentrated and (flips or shrinks))


# ---------------------------------------------------------------------------
# strata + leave-one-stratum-out (owner requirement 5)
# ---------------------------------------------------------------------------
def _hcp(pbn: str) -> int:
    v = {"A": 4, "K": 3, "Q": 2, "J": 1}
    return sum(v.get(r, 0) for suit in pbn.split(".") for r in suit)


def _shape(pbn: str) -> tuple:
    return tuple(len(s) for s in pbn.split("."))


def _shape_class(pbn: str) -> str:
    s = sorted(_shape(pbn), reverse=True)
    if s in ([4, 3, 3, 3], [4, 4, 3, 2], [5, 3, 3, 2]):
        return "balanced"
    if s in ([5, 4, 2, 2], [6, 3, 2, 2], [5, 4, 3, 1], [6, 3, 3, 1]):
        return "semibalanced"
    return "unbalanced"


def _suit_len(pbn: str, suit: str) -> int:
    return len(pbn.split(".")[SUITS.index(suit)])


def _score_bin(s: float) -> str:
    for lo in (0.90, 0.85, 0.80, 0.75, 0.70):
        if s >= lo:
            return {0.90: ".90+", 0.85: ".85-.90", 0.80: ".80-.85",
                    0.75: ".75-.80", 0.70: ".70-.75"}[lo]
    return "<.70"


def _missing_honor_stratum(problem: LeadProblem, hd: dict,
                           led_suit: str | None = None) -> str:
    """Location+length of the KEY missing honor in the reference (led) suit.

    `led_suit` is the suit whose lead is under scrutiny (the decision's suit);
    when omitted we fall back to the leader's longest suit. The key honor is
    the highest one the leader does NOT hold in that suit. Reports which hidden
    hand holds it and that hand's length in the suit.
    """
    if led_suit is None:
        lengths = {s: _suit_len(problem.hand, s) for s in SUITS}
        led_suit = max(SUITS, key=lambda s: lengths[s])
    suit = led_suit
    held = set(problem.hand.split(".")[SUITS.index(suit)])
    honor = next((h for h in "AKQJ" if h not in held), None)
    if honor is None:
        return f"{suit}:all-top-honors-held"
    for seat in SEATS:
        if seat == problem.leader:
            continue
        if honor in set(hd[seat].split(".")[SUITS.index(suit)]):
            role = _role(problem, seat)
            ln = _suit_len(hd[seat], suit)
            return f"{suit}{honor}@{role}(len{ln})"
    return f"{suit}{honor}@none"


def _role(problem: LeadProblem, seat: str) -> str:
    di = SEATS.index(problem.declarer)
    roles = {problem.declarer: "declarer",
             SEATS[(di + 1) % 4]: "leader",
             SEATS[(di + 2) % 4]: "dummy",
             SEATS[(di + 3) % 4]: "partner"}
    return roles[seat]


def _strata_keys(problem: LeadProblem, ls: LayoutSet,
                 led_suit: str | None = None) -> dict:
    """Return {stratifier_name: array of per-layout string keys}.

    `led_suit` is the suit of the decision under scrutiny (the compared/best
    lead's suit); it drives the partner/declarer/dummy length and missing-honor
    strata. Falls back to the leader's longest suit."""
    di = SEATS.index(problem.declarer)
    dummy = SEATS[(di + 2) % 4]
    partner = SEATS[(di + 3) % 4]
    declarer = problem.declarer
    led = led_suit or max(SUITS, key=lambda s: _suit_len(problem.hand, s))

    keys = {"score_bin": [], "partner_led_len": [], "declarer_led_len": [],
            "dummy_led_len": [], "missing_key_honor": [],
            "declarer_hcp_bin": [], "declarer_shape": []}
    for i, hd in enumerate(ls.hands):
        keys["score_bin"].append(_score_bin(ls.bidding_score[i]))
        keys["partner_led_len"].append(f"{led}={_suit_len(hd[partner], led)}")
        keys["declarer_led_len"].append(f"{led}={_suit_len(hd[declarer], led)}")
        keys["dummy_led_len"].append(f"{led}={_suit_len(hd[dummy], led)}")
        keys["missing_key_honor"].append(
            _missing_honor_stratum(problem, hd, led))
        keys["declarer_hcp_bin"].append(_hcp_bin(_hcp(hd[declarer])))
        keys["declarer_shape"].append(_shape_class(hd[declarer]))
    return {k: np.array(v) for k, v in keys.items()}


def _hcp_bin(h: int) -> str:
    for lo in (20, 17, 14, 11, 8, 5):
        if h >= lo:
            return f"{lo}+"
    return "<5"


def strata_report(problem: LeadProblem, ls: LayoutSet, ev: LeadEval,
                  best: str, runner: str, led_suit: str | None = None) -> dict:
    """Per-stratum count/%/mean-score/mean-delta/total-contribution/W-L-T, for
    each stratifier, plus leave-one-stratum-out ranking/gap shifts.

    `led_suit` defaults to the suit of `best` — the length/missing-honor strata
    are then about the suit actually under scrutiny. Diagnostic only — the
    headline ranking is always the full-set mean DD.
    """
    w = ls.weight
    led_suit = led_suit or best[0]
    delta = ev.def_tricks[best] - ev.def_tricks[runner]
    total_mass = float((w * delta).sum())
    keys = _strata_keys(problem, ls, led_suit)
    full_mean = float(np.average(delta, weights=w))

    out = {"best": best, "runner_up": runner,
           "full_mean_delta": round(full_mean, 4), "stratifiers": {}}
    for name, arr in keys.items():
        rows = []
        loso = []
        for val in sorted(set(arr.tolist())):
            m = arr == val
            wm = w[m]
            share = float(wm.sum())
            if share <= 0:
                continue
            dl = delta[m]
            rows.append({
                "stratum": val,
                "count": int(m.sum()),
                "weight_share": round(share, 4),
                "mean_score": round(float(np.average(ls.bidding_score[m],
                                                     weights=wm)), 4),
                "mean_delta": round(float(np.average(dl, weights=wm)), 4),
                "delta_contribution": round(
                    float((wm * dl).sum()), 4),
                "contribution_share": round(
                    float((wm * dl).sum()) / total_mass, 4)
                if abs(total_mass) > 1e-12 else 0.0,
                "win": round(float(wm[dl > 1e-9].sum()), 4),
                "loss": round(float(wm[dl < -1e-9].sum()), 4),
                "tie": round(float(wm[np.abs(dl) <= 1e-9].sum()), 4),
            })
            # leave THIS stratum out: recompute best-vs-runner mean gap
            keep = ~m
            if keep.any():
                wk = w[keep]
                new_ranking_mean = {
                    c: float(np.average(ev.def_tricks[c][keep], weights=wk))
                    for c in ev.cards}
                new_best = max(new_ranking_mean, key=lambda c: new_ranking_mean[c])
                srt = sorted(new_ranking_mean.values(), reverse=True)
                loso.append({
                    "removed": val,
                    "new_best": new_best,
                    "best_changed": new_best != best,
                    "new_top_gap": round(srt[0] - srt[1], 4)
                    if len(srt) > 1 else 0.0,
                    "new_best_minus_runner": round(
                        new_ranking_mean[best] - new_ranking_mean[runner], 4),
                })
        out["stratifiers"][name] = {"rows": rows, "leave_one_out": loso}
    return out


# ---------------------------------------------------------------------------
# pure sampler acceptance/weighting math (owner requirement 6) — Ben-free,
# so the three modes' logic is unit-testable with synthetic probability inputs
# ---------------------------------------------------------------------------
def bidding_consistency_scores(prob: np.ndarray, bid_counts,
                               use_distance: bool = True,
                               exclude: float = BEN_EXCLUDE_SAMPLES) -> np.ndarray:
    """Faithful re-implementation of Ben's per-deal auction-consistency score.

    `prob[i, seat, turn]` is the neural bidder's probability of the ACTUAL
    call the (LHO, partner, RHO) seat made at each of its turns for sampled
    deal i (pad unused turns with 1.0). `bid_counts=(lho,partner,rho)`.

    Per seat: min over that seat's turns (Ben's process_bidding). Then, with
    use_distance (Ben's BEN-21GF default): partner double-weighted bid-count
    average, scaled to [0,1]:
        distance = (1-s_lho)*lho + 2*(1-s_par)*par + (1-s_rho)*rho
        score    = (max_distance - distance) / max_distance
    Without use_distance: the single worst seat score. Deals where any seat
    falls below `exclude` at any of its turns are rejected (score -1).
    """
    prob = np.asarray(prob, dtype=float)
    lho_n, par_n, rho_n = bid_counts
    per_seat_min = prob.min(axis=2)               # (n, 3)
    below = (prob < exclude).any(axis=(1, 2))     # any turn below exclude
    if use_distance:
        maxd = lho_n + 2 * par_n + rho_n
        if maxd == 0:
            return np.ones(prob.shape[0])
        dist = ((1 - per_seat_min[:, 0]) * lho_n
                + 2 * (1 - per_seat_min[:, 1]) * par_n
                + (1 - per_seat_min[:, 2]) * rho_n)
        score = (maxd - dist) / maxd
    else:
        score = per_seat_min.min(axis=1)
    score = np.where(below, -1.0, score)
    return score


def accept_thresholded(scores: np.ndarray, threshold: float) -> np.ndarray:
    """Ben's acceptance: keep deals with score >= threshold (mask)."""
    return np.asarray(scores, dtype=float) >= threshold


def replay_exact_mask(reproduced: np.ndarray) -> np.ndarray:
    """Ben exact-replay acceptance: keep a deal ONLY if the bidder reproduces
    EVERY observed call/pass for every seat/turn (all True). `reproduced[i]`
    is a boolean array over (seat, turn) of 'argmax == actual call'."""
    reproduced = np.asarray(reproduced)
    return reproduced.reshape(reproduced.shape[0], -1).all(axis=1)


def likelihood_log_weights(logprob: np.ndarray) -> tuple:
    """Ben-likelihood weighting via log-sum-exp normalisation.

    `logprob[i]` is the summed log P of every observed call under the neural
    per-call probabilities for deal i (a genuine per-legal-call likelihood).
    Returns (weights, ess). Numerically stable; returns uniform if all -inf.
    """
    lp = np.asarray(logprob, dtype=float)
    finite = np.isfinite(lp)
    if not finite.any():
        w = np.ones(lp.shape[0]) / lp.shape[0]
        return w, float(lp.shape[0])
    m = lp[finite].max()
    ex = np.where(finite, np.exp(lp - m), 0.0)
    s = ex.sum()
    w = ex / s if s > 0 else np.ones_like(ex) / ex.shape[0]
    ess = float((w.sum() ** 2) / (w ** 2).sum()) if (w ** 2).sum() > 0 else 0.0
    return w, ess


# ---------------------------------------------------------------------------
# source-deal independence proof (owner requirement 2)
# ---------------------------------------------------------------------------
def problem_fingerprint(problem: LeadProblem, seed: int) -> str:
    """A hash of ONLY the public state + seed. Two runs whose fingerprints
    match MUST produce identical results regardless of the hidden source
    deal — which is exactly what source-deal independence means."""
    payload = "|".join([problem.hand, " ".join(problem.auction),
                        problem.dealer, problem.vul, problem.contract,
                        str(seed)])
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def result_signature(ev: LeadEval, ls: LayoutSet) -> str:
    """Order-sensitive digest of the graded layouts + per-card trick vectors,
    used to prove identical public state + seed => identical results."""
    h = hashlib.sha256()
    for hd in ls.hands:
        h.update(("N:" + " ".join(hd[s] for s in SEATS)).encode())
    for c in sorted(ev.cards):
        h.update(c.encode())
        h.update(ev.def_tricks[c].tobytes())
    h.update(ls.weight.tobytes())
    return h.hexdigest()[:16]


# ---------------------------------------------------------------------------
# quality flag (owner requirement 7)
# ---------------------------------------------------------------------------
def quality_flag(reports: dict, min_ess: float = 100.0) -> str:
    """Cross-sampler / cross-threshold verdict.

    `reports` maps a label ("current@.70", "ben-replay", ...) to that run's
    {winner, delta_report}. Returns one of:
      robust               same winner everywhere, adequate ESS, positive CI,
                           not tail-dominated;
      sampler_sensitive    winner changes or the gap materially collapses;
      insufficient_evidence inadequate N/ESS or CI straddles 0;
      tail_dominated       an extreme-observation-driven mean dominates.
    """
    if not reports:
        return "insufficient_evidence"
    winners = {r["winner"] for r in reports.values()}
    esss = [r["delta_report"]["ess"] for r in reports.values()]
    cis = [r["delta_report"]["boot_ci95"] for r in reports.values()]
    means = [r["delta_report"]["mean"] for r in reports.values()]
    tails = [is_tail_dominated(r["delta_report"]) for r in reports.values()]

    if any(tails):
        return "tail_dominated"
    if min(esss) < min_ess or any(lo <= 0 <= hi for lo, hi in cis):
        return "insufficient_evidence"
    if len(winners) > 1:
        return "sampler_sensitive"
    # gap collapse: any run's mean below a quarter of the largest
    mx = max(abs(m) for m in means)
    if mx > 0 and min(abs(m) for m in means) < 0.25 * mx:
        return "sampler_sensitive"
    return "robust"
