"""Sampler calibration against REAL complete deals (owner requirement 6).

The audit's other diagnostics all live *inside* the sampled world. This module
steps outside it: given a set of REAL, fully-known deals grouped by auction
family, it asks whether a sampler's distribution over the hidden hands looks
like the real hidden hands do. It is a posterior-predictive check, not a claim
of correctness — we report measured divergences and honestly label a family
`calibrated` or `miscalibrated`, per feature and overall.

Method (Ben-free; runs on any sampler):

  * Group real deals by `auction_family_key` (the public auction defines the
    family). Within a family the leader hand and the exact hidden hands differ
    board to board, but the auction — hence what the bidding announced — is
    shared.
  * REAL distribution: pool the real hidden hands across the family's boards
    (one hidden layout per board), by role (declarer / dummy / partner).
  * MODEL distribution: for each board, run the sampler on that board's PUBLIC
    state (leader hand + auction + contract) and pool the sampled hidden hands
    by role across every board and every sampled layout.
  * Compare the two on: HCP, shape class, announced-suit lengths, the
    declarer+dummy fit in each announced suit, controls (A=2, K=1), and
    key-honor locations (which role holds each suit's A / K). Divergence is
    total-variation distance over the (binned) marginals, in [0, 1].

A uniform sampler that ignores the auction SHOULD look miscalibrated on the
announced-suit lengths and HCP of the bidders; a constraint/likelihood sampler
that respects the auction should be closer. The harness measures that; it never
assumes it.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from .lead_posterior import (
    SUITS, SEATS, build_problem, _hcp, _shape_class, _suit_len)

HONORS = "AKQJ"
CONTROL_VALUE = {"A": 2, "K": 1}


# ---------------------------------------------------------------------------
# auction family + roles
# ---------------------------------------------------------------------------
def auction_family_key(auction, *, drop_trailing_passes: bool = True) -> str:
    """Canonical key for the auction family (the public bidding).

    Two boards are in the same family iff their auctions are identical. By
    default trailing passes (which carry no extra meaning) are dropped so
    '1S P 2C P 3D P 3NT P P P' and a truncation before the final passes map
    together; leading/internal passes are meaningful and kept.
    """
    toks = list(auction)
    if drop_trailing_passes:
        while toks and toks[-1] == "P":
            toks.pop()
    return " ".join(toks)


def announced_suits(auction) -> list:
    """Suits named by a natural bid anywhere in the auction (S/H/D/C, no NT),
    in first-appearance order. These are the 'announced' suits whose lengths a
    calibrated sampler should reproduce."""
    seen = []
    for t in auction:
        if t in ("P", "X", "XX"):
            continue
        denom = t[1:]
        if denom in SUITS and denom not in seen:
            seen.append(denom)
    return seen


def _role_map(declarer: str) -> dict:
    di = SEATS.index(declarer)
    return {SEATS[di]: "declarer", SEATS[(di + 1) % 4]: "leader",
            SEATS[(di + 2) % 4]: "dummy", SEATS[(di + 3) % 4]: "partner"}


HIDDEN_ROLES = ("declarer", "dummy", "partner")


# ---------------------------------------------------------------------------
# per-hand features
# ---------------------------------------------------------------------------
def _controls(pbn: str) -> int:
    return sum(CONTROL_VALUE.get(r, 0)
               for suit in pbn.split(".") for r in suit)


def hand_features(pbn: str) -> dict:
    """Scalar/categorical features of one hand used for calibration."""
    return {
        "hcp": _hcp(pbn),
        "shape_class": _shape_class(pbn),
        "controls": _controls(pbn),
        "suit_len": {s: _suit_len(pbn, s) for s in SUITS},
        "has_A": {s: ("A" in pbn.split(".")[SUITS.index(s)]) for s in SUITS},
        "has_K": {s: ("K" in pbn.split(".")[SUITS.index(s)]) for s in SUITS},
    }


# ---------------------------------------------------------------------------
# distribution collection
# ---------------------------------------------------------------------------
def _blank_accumulator():
    return {
        "n": 0,
        "hcp": [], "controls": [],
        "shape_class": [],
        "suit_len": {s: [] for s in SUITS},
        "has_A": {s: [] for s in SUITS},
        "has_K": {s: [] for s in SUITS},
        "weight": [],
    }


def _accumulate(acc: dict, pbn: str, weight: float = 1.0) -> None:
    f = hand_features(pbn)
    acc["n"] += 1
    acc["hcp"].append(f["hcp"])
    acc["controls"].append(f["controls"])
    acc["shape_class"].append(f["shape_class"])
    acc["weight"].append(weight)
    for s in SUITS:
        acc["suit_len"][s].append(f["suit_len"][s])
        acc["has_A"][s].append(f["has_A"][s])
        acc["has_K"][s].append(f["has_K"][s])


def collect_family_distributions(deals: list, sampler, requested: int,
                                 seed: int, contract_of=None,
                                 dealer="N", vul="None") -> dict:
    """Pool real and sampled hidden-hand features (by role) over one family.

    `deals` is a list of dicts: {"hands": {seat:pbn}, "auction": [...],
    "contract": "3NTW", optionally "dealer"/"vul"/"leader"}. The sampler is run
    on each board's PUBLIC state; the real hidden hands come from `hands`.
    Returns {"real": {role: acc}, "model": {role: acc}, "n_boards": k}.
    """
    real = {r: _blank_accumulator() for r in HIDDEN_ROLES}
    model = {r: _blank_accumulator() for r in HIDDEN_ROLES}
    for bi, deal in enumerate(deals):
        auction = deal["auction"]
        contract = deal.get("contract") or (contract_of and contract_of(deal))
        dlr = deal.get("dealer", dealer)
        v = deal.get("vul", vul)
        leader_hand = None
        # public state needs the leader hand; derive leader from the contract
        problem0 = build_problem(deal["hands"][SEATS[0]], auction, dlr, v,
                                 contract)
        roles = _role_map(problem0.declarer)
        inv = {role: seat for seat, role in roles.items()}
        leader_seat = inv["leader"]
        leader_hand = deal["hands"][leader_seat]
        problem = build_problem(leader_hand, auction, dlr, v, contract)
        # real hidden hands (one layout per board)
        for role in HIDDEN_ROLES:
            _accumulate(real[role], deal["hands"][inv[role]], 1.0)
        # sampled hidden hands (many layouts per board)
        ls = sampler.sample(problem, requested, seed + bi)
        w = ls.weight
        for i, hd in enumerate(ls.hands):
            for role in HIDDEN_ROLES:
                _accumulate(model[role], hd[inv[role]], float(w[i]))
    return {"real": real, "model": model, "n_boards": len(deals)}


# ---------------------------------------------------------------------------
# divergence metrics
# ---------------------------------------------------------------------------
def _weighted_hist(values, weights, categories) -> np.ndarray:
    idx = {c: i for i, c in enumerate(categories)}
    h = np.zeros(len(categories), dtype=float)
    for v, w in zip(values, weights):
        h[idx[v]] += w
    s = h.sum()
    return h / s if s > 0 else h


def _tv(values_a, w_a, values_b, w_b, categories) -> float:
    """Total-variation distance between two categorical/integer marginals."""
    ha = _weighted_hist(values_a, w_a, categories)
    hb = _weighted_hist(values_b, w_b, categories)
    return float(0.5 * np.abs(ha - hb).sum())


def _wmean(values, weights) -> float:
    v = np.asarray(values, float)
    w = np.asarray(weights, float)
    return float(np.average(v, weights=w)) if w.sum() > 0 and v.size else 0.0


def compare_role(real: dict, model: dict, suits_of_interest: list,
                 tol: float = 0.20) -> dict:
    """Per-feature real-vs-model divergence for one role.

    Scalar/integer features (HCP, controls, announced-suit lengths, and the
    honor-location indicators) are compared by total-variation distance over
    their integer support; shape class over its three categories. `within_tol`
    flags features whose TV distance is at or below `tol`.
    """
    out = {"real_n": real["n"], "model_n": model["n"], "features": {}}
    if real["n"] == 0 or model["n"] == 0:
        out["insufficient"] = True
        return out

    def add(name, cats, rv, rw, mv, mw, real_mean=None, model_mean=None):
        tv = _tv(rv, rw, mv, mw, cats)
        entry = {"tv_distance": round(tv, 4), "within_tol": bool(tv <= tol)}
        if real_mean is not None:
            entry["real_mean"] = round(real_mean, 3)
            entry["model_mean"] = round(model_mean, 3)
            entry["mean_abs_diff"] = round(abs(real_mean - model_mean), 3)
        out["features"][name] = entry

    add("hcp", list(range(0, 38)),
        real["hcp"], real["weight"], model["hcp"], model["weight"],
        _wmean(real["hcp"], real["weight"]), _wmean(model["hcp"], model["weight"]))
    add("controls", list(range(0, 13)),
        real["controls"], real["weight"], model["controls"], model["weight"],
        _wmean(real["controls"], real["weight"]),
        _wmean(model["controls"], model["weight"]))
    add("shape_class", ["balanced", "semibalanced", "unbalanced"],
        real["shape_class"], real["weight"],
        model["shape_class"], model["weight"])
    for s in suits_of_interest:
        add(f"len_{s}", list(range(0, 14)),
            real["suit_len"][s], real["weight"],
            model["suit_len"][s], model["weight"],
            _wmean(real["suit_len"][s], real["weight"]),
            _wmean(model["suit_len"][s], model["weight"]))
        add(f"hasA_{s}", [False, True],
            real["has_A"][s], real["weight"], model["has_A"][s], model["weight"],
            _wmean(np.array(real["has_A"][s], float), real["weight"]),
            _wmean(np.array(model["has_A"][s], float), model["weight"]))
        add(f"hasK_{s}", [False, True],
            real["has_K"][s], real["weight"], model["has_K"][s], model["weight"],
            _wmean(np.array(real["has_K"][s], float), real["weight"]),
            _wmean(np.array(model["has_K"][s], float), model["weight"]))
    worst = max((e["tv_distance"] for e in out["features"].values()), default=0.0)
    off = sorted(k for k, e in out["features"].items() if not e["within_tol"])
    out["max_tv_distance"] = round(worst, 4)
    out["off_features"] = off
    return out


def compare_fit(dist: dict, suits_of_interest: list, tol: float = 0.20) -> dict:
    """Declarer+dummy fit (combined length) per announced suit: real vs model.

    The declarer/dummy are partners, so their combined length in a bid suit is
    the partnership fit the auction implies. Compared board-paired for the real
    side and layout-paired for the model side, by TV over 0..13.
    """
    real, model = dist["real"], dist["model"]
    out = {"features": {}}
    for s in suits_of_interest:
        rd = np.array(real["declarer"]["suit_len"][s])
        ru = np.array(real["dummy"]["suit_len"][s])
        md = np.array(model["declarer"]["suit_len"][s])
        mu = np.array(model["dummy"]["suit_len"][s])
        rw = np.array(real["declarer"]["weight"])
        mw = np.array(model["declarer"]["weight"])
        if rd.size == 0 or md.size == 0:
            continue
        rfit = (rd + ru).tolist()
        mfit = (md + mu).tolist()
        tv = _tv(rfit, rw, mfit, mw, list(range(0, 14)))
        out["features"][f"fit_{s}"] = {
            "tv_distance": round(tv, 4), "within_tol": bool(tv <= tol),
            "real_mean": round(_wmean(rfit, rw), 3),
            "model_mean": round(_wmean(mfit, mw), 3),
        }
    return out


# ---------------------------------------------------------------------------
# top-level report
# ---------------------------------------------------------------------------
def calibrate_family(deals: list, sampler, requested: int = 256, seed: int = 1,
                     tol: float = 0.20, dealer="N", vul="None") -> dict:
    """Full calibration report for ONE auction family.

    Labels the family `calibrated` when NO role/feature exceeds the TV
    tolerance, else `miscalibrated` with the offending (role, feature) pairs.
    Requires enough real boards to form a marginal — with too few it reports
    `insufficient_real_data` rather than a false verdict.
    """
    auction = deals[0]["auction"]
    suits = announced_suits(auction)
    dist = collect_family_distributions(deals, sampler, requested, seed,
                                        dealer=dealer, vul=vul)
    roles = {r: compare_role(dist["real"][r], dist["model"][r], suits, tol)
             for r in HIDDEN_ROLES}
    fit = compare_fit(dist, suits, tol)
    off = []
    for r in HIDDEN_ROLES:
        for feat in roles[r].get("off_features", []):
            off.append(f"{r}.{feat}")
    for feat, e in fit["features"].items():
        if not e["within_tol"]:
            off.append(f"fit.{feat}")
    min_real = min(dist["real"][r]["n"] for r in HIDDEN_ROLES)
    if min_real < 5:
        label = "insufficient_real_data"
    else:
        label = "calibrated" if not off else "miscalibrated"
    return {
        "auction_family": auction_family_key(auction),
        "announced_suits": suits,
        "n_boards": dist["n_boards"],
        "sampler": getattr(sampler, "sampling_model",
                           type(sampler).__name__),
        "calibration_label": label,
        "off_features": off,
        "roles": roles,
        "fit": fit,
    }


def group_by_family(deals: list) -> dict:
    """Group real deals into auction families (keeps insertion order)."""
    fam = defaultdict(list)
    for d in deals:
        fam[auction_family_key(d["auction"])].append(d)
    return dict(fam)


def calibrate_corpus(deals: list, sampler, requested: int = 256, seed: int = 1,
                     tol: float = 0.20, min_boards: int = 5) -> dict:
    """Calibrate every auction family with enough boards; summarise.

    Returns per-family reports plus counts of calibrated / miscalibrated /
    insufficient families and the most frequently off (role, feature) pairs —
    the concrete places the sampler's hidden-hand distribution departs from
    real deals.
    """
    families = group_by_family(deals)
    reports = []
    for key, fam_deals in families.items():
        if len(fam_deals) < min_boards:
            reports.append({"auction_family": key, "n_boards": len(fam_deals),
                            "calibration_label": "insufficient_real_data"})
            continue
        reports.append(calibrate_family(fam_deals, sampler, requested, seed, tol))
    off_counts = defaultdict(int)
    for rep in reports:
        for feat in rep.get("off_features", []):
            off_counts[feat] += 1
    summary = {
        "n_families": len(reports),
        "calibrated": sum(r["calibration_label"] == "calibrated"
                          for r in reports),
        "miscalibrated": sum(r["calibration_label"] == "miscalibrated"
                             for r in reports),
        "insufficient": sum(r["calibration_label"] == "insufficient_real_data"
                            for r in reports),
        "most_off_features": sorted(off_counts.items(), key=lambda kv: -kv[1]),
    }
    return {"summary": summary, "families": reports,
            "sampler": getattr(sampler, "sampling_model",
                               type(sampler).__name__),
            "tolerance": tol}
