"""M0 feasibility spike (see spec).

Fix a hand, generate deals under a LOOSE and a TIGHT constraint set with a
vectorized NumPy rejection sampler, measure acceptance rate + wall clock for
n=2000, DD-solve both sets for two contracts, and print a paired IMP
comparison with a naive CI.

Scenario: favorable vul, auction (1H) - 1S - (3H) - ?  We sit South with
    S:K93 H:752 D:A854 C:T62
Hidden seats: West (1H opener), North (1S overcall), East (3H weak raise).
Contracts compared: 3S by North vs 3H by West (i.e. bid 3S vs Pass).
"""
from __future__ import annotations

import time

import numpy as np
from endplay.dds import calc_all_tables
from endplay.types import Contract, Deal, Denom, Penalty, Player, Vul

# ---------------------------------------------------------------- card model
# Card index 0..51 = suit*13 + rank, suit order S,H,D,C, rank 0=A .. 12=2
SUIT_NAMES = "SHDC"
RANK_NAMES = "AKQJT98765432"
HCP = np.array([4, 3, 2, 1] + [0] * 9, dtype=np.int8)


def parse_hand(s: str) -> list[int]:
    """'K93.752.A854.T62' -> card indices."""
    out = []
    for suit, holding in enumerate(s.split(".")):
        for ch in holding:
            out.append(suit * 13 + RANK_NAMES.index(ch))
    assert len(out) == 13, s
    return out


MY_HAND = "K93.752.A854.T62"  # South
my_cards = parse_hand(MY_HAND)
remaining = np.array(sorted(set(range(52)) - set(my_cards)), dtype=np.int8)
rem_suit = remaining // 13
rem_hcp = HCP[remaining % 13]

# Hidden seats dealt from permutation slices, order: West, North, East
SLICES = {"W": slice(0, 13), "N": slice(13, 26), "E": slice(26, 39)}


def seat_features(perm: np.ndarray, seat: str):
    cards = perm[:, SLICES[seat]]  # actual card ids 0..51
    hcp = HCP[cards % 13].sum(axis=1)
    lengths = {s: (cards // 13 == i).sum(axis=1) for i, s in enumerate(SUIT_NAMES)}
    return hcp, lengths


def generate(constraints, n, seed, max_attempts=4_000_000, batch=50_000):
    """Rejection-sample deals; constraints = {seat: fn(hcp, lengths) -> mask}."""
    rng = np.random.default_rng(seed)
    kept: list[np.ndarray] = []
    attempts = 0
    t0 = time.perf_counter()
    while sum(len(k) for k in kept) < n and attempts < max_attempts:
        perm = rng.permuted(np.tile(remaining, (batch, 1)), axis=1)
        attempts += batch
        mask = np.ones(batch, dtype=bool)
        for seat, pred in constraints.items():
            hcp, lengths = seat_features(perm[mask], seat)
            sub = pred(hcp, lengths)
            idx = np.flatnonzero(mask)
            mask[idx[~sub]] = False
            if not mask.any():
                break
        if mask.any():
            kept.append(perm[mask])
    elapsed = time.perf_counter() - t0
    deals = np.concatenate(kept)[:n] if kept else np.empty((0, 39), dtype=np.int8)
    return deals, attempts, elapsed


def to_endplay_deal(row: np.ndarray) -> Deal:
    def hand_str(cards):
        by_suit = ["", "", "", ""]
        for c in sorted(cards):
            by_suit[c // 13] += RANK_NAMES[c % 13]
        return ".".join(by_suit)

    w = hand_str(row[SLICES["W"]])
    nh = hand_str(row[SLICES["N"]])
    e = hand_str(row[SLICES["E"]])
    return Deal(f"N:{nh} {e} {MY_HAND} {w}")


# ---------------------------------------------------------------- constraints
def loose(seat, hcp, lengths):
    if seat == "W":  # 1H opener
        return (hcp >= 11) & (hcp <= 21) & (lengths["H"] >= 5)
    if seat == "N":  # 1S overcall, light style
        return (hcp >= 7) & (hcp <= 17) & (lengths["S"] >= 5)
    return (hcp >= 2) & (hcp <= 9) & (lengths["H"] >= 3)  # E: 3H weak


def tight(seat, hcp, lengths):
    if seat == "W":
        return (
            (hcp >= 12) & (hcp <= 17) & (lengths["H"] >= 5) & (lengths["H"] <= 6)
            & (lengths["S"] <= 3)
        )
    if seat == "N":
        return (
            (hcp >= 8) & (hcp <= 14) & (lengths["S"] == 5) & (lengths["H"] <= 2)
        )
    return (hcp >= 3) & (hcp <= 8) & (lengths["H"] == 4) & (lengths["S"] <= 3)


IMP_BOUNDS = [20, 50, 90, 130, 170, 220, 270, 320, 370, 430, 500, 600, 750,
              900, 1100, 1300, 1500, 1750, 2000, 2250, 2500, 3000, 3500, 4000]


def imps(diff: int) -> int:
    sign = 1 if diff >= 0 else -1
    a = abs(diff)
    return sign * sum(1 for b in IMP_BOUNDS if a >= b)


def run_case(name, preds, n=2000, seed=42):
    constraints = {s: (lambda h, l, s=s: preds(s, h, l)) for s in "WNE"}
    deals_np, attempts, gen_elapsed = generate(constraints, n, seed)
    got = len(deals_np)
    rate = got / attempts if attempts else 0.0
    print(f"\n=== {name} ===")
    print(f"generation: {got}/{n} deals, attempts={attempts}, "
          f"acceptance={rate:.4%}, wall={gen_elapsed:.2f}s")

    deals = [to_endplay_deal(r) for r in deals_np]
    t0 = time.perf_counter()
    tables = []
    for i in range(0, len(deals), 40):  # DDS ddTableDeals holds max 40
        tables.extend(calc_all_tables(
            deals[i:i + 40], exclude=[Denom.diamonds, Denom.clubs, Denom.nt]))
    dd_elapsed = time.perf_counter() - t0
    print(f"DD solve ({got} deals, spades+hearts tables): {dd_elapsed:.2f}s")

    # Paired comparison: 3S by N (we bid) vs 3H by W (we pass). Favorable vul:
    # NS not vul, EW vul. Scores from NS perspective.
    diffs = []
    for tbl in tables:
        tricks_3s = int(tbl[Denom.spades, Player.north])
        tricks_3h = int(tbl[Denom.hearts, Player.west])
        c3s = Contract(level=3, denom=Denom.spades, declarer=Player.north,
                       penalty=Penalty.passed, result=tricks_3s - 9)
        c3h = Contract(level=3, denom=Denom.hearts, declarer=Player.west,
                       penalty=Penalty.passed, result=tricks_3h - 9)
        ns_3s = c3s.score(Vul.ew)          # our declaration, we are NV
        ns_3h = -c3h.score(Vul.ew)         # their declaration, they are V
        diffs.append(imps(ns_3s - ns_3h))
    diffs = np.array(diffs, dtype=float)
    mean, se = diffs.mean(), diffs.std(ddof=1) / np.sqrt(len(diffs))
    print(f"paired IMPs (3S vs Pass, +=3S better): "
          f"EV={mean:+.2f} IMPs, naive 95% CI [{mean-1.96*se:+.2f}, {mean+1.96*se:+.2f}]")
    p_gain = (diffs > 0).mean()
    p_loss = (diffs < 0).mean()
    print(f"P(gain)={p_gain:.1%} P(loss)={p_loss:.1%} P(push)={1-p_gain-p_loss:.1%}")
    return rate, gen_elapsed, dd_elapsed


if __name__ == "__main__":
    run_case("LOOSE", loose)
    run_case("TIGHT", tight)
