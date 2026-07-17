"""Explanations: given-bidding meaning bands + option explanations.
All computed (samples + auction mechanics + evaluation numbers), never
asserted — docs/ben_execution_plan.md §3.3 + v2 amendments 1, 2, 9, 11.
"""
from __future__ import annotations

import numpy as np

from .ben import seat_features
from .conventions import classify, seat_of

SEATS = "NESW"
SUIT_GLYPH = {"S": "♠", "H": "♥", "D": "♦", "C": "♣", "NT": "NT"}
BAND_N_MIN = 30


def _call_name(tok: str) -> str:
    if tok in ("P", "X", "XX"):
        return {"P": "Pass", "X": "Double", "XX": "Redouble"}[tok]
    return tok[0] + SUIT_GLYPH[tok[1:]]


def _band_sentence(feats: dict, seat_name: str, artificial: bool,
                   convention: str | None) -> str:
    lo, hi = round(feats["hcp_p10"]), round(feats["hcp_p90"])
    longs = [s for s in "SHDC" if feats["len_avg"][s] >= 4.6]
    if artificial:
        major4 = max(feats["len4plus"]["H"], feats["len4plus"]["S"])
        bits = [f"{convention}" if convention else "artificial"]
        if convention and "Stayman" in convention:
            bits.append(f"{major4:.0%} of consistent hands held a 4-card "
                        f"major; the call says nothing about clubs "
                        f"(avg {feats['len_avg']['C']:.1f})")
        else:
            bits.append(f"consistent hands: {lo}-{hi} HCP")
        return "; ".join(bits)
    parts = [f"{lo}-{hi} HCP"]
    for s in longs:
        parts.append(f"{feats['len_avg'][s]:.1f} {SUIT_GLYPH[s]} on average")
    if feats["balanced_share"] >= 0.6:
        parts.append(f"balanced {feats['balanced_share']:.0%} of the time")
    return ", ".join(parts)


def stem_explanations(engine, spot, hero_bot) -> list[dict]:
    """One entry per stem call: mechanical classification + empirical
    band from layouts consistent with the auction THROUGH that call."""
    out = []
    for j, tok in enumerate(spot.stem):
        seat_i = seat_of(spot.dealer_i, j)
        info = classify(spot.stem, spot.dealer_i, j)
        entry = {
            "idx": j, "seat": SEATS[seat_i], "call": tok,
            "category": info.category, "convention": info.convention,
            "artificial": info.artificial, "double_type": info.double_type,
            "band": None, "n": 0,
        }
        text_head = f"{_call_name(tok)} ({SEATS[seat_i]})"
        if tok == "P":
            entry["text"] = f"{text_head}: nothing shown yet." if j < 2 else \
                f"{text_head}: limited — no action available or chosen."
        elif tok in ("X", "XX"):
            entry["text"] = f"{text_head}: {info.double_type or 'double'}."
        else:
            entry["text"] = f"{text_head}: {info.category}."
        if seat_i == spot.hero_i:
            entry["text"] = f"{text_head}: your own call."
            out.append(entry)
            continue
        # empirical band through this call (hero-conditioned sampling)
        if tok != "P":
            try:
                hands_np, n = engine.sample_prefix(
                    hero_bot, spot.dealer_i, spot.stem[:j + 1])
            except Exception:
                hands_np, n = None, 0
            if n >= BAND_N_MIN:
                feats = seat_features(hands_np, seat_i,
                                      engine.models.n_cards_bidding)
                entry["band"] = feats
                entry["n"] = n
                entry["text"] = (
                    f"{text_head}: {info.convention or info.double_type or info.category} — "
                    + _band_sentence(feats, SEATS[seat_i], info.artificial,
                                     info.convention)
                    + f" (n={n}, measured)")
        out.append(entry)
    return out


def option_explanations(spot, verdict, policy_map) -> list[dict]:
    out = []
    ordered = [r["bid"] for r in verdict.table]
    for row in verdict.table:
        b = row["bid"]
        info = classify(spot.stem + [b] if b not in ("P", "X", "XX") or True
                        else spot.stem, spot.dealer_i, len(spot.stem))
        contracts = ", ".join(
            f"{c} ({cnt / verdict.measured['n_samples']:.0%})"
            for c, cnt in row["top_contracts"])
        lines = [
            f"{_call_name(b)} — {info.convention or info.double_type or info.category}.",
            f"A strong engine chooses this {policy_map.get(b, 0):.0%} of the "
            f"time here.",
            f"Where it leads: {contracts}.",
        ]
        if b == verdict.best:
            if verdict.toss_up:
                tied = ", ".join(_call_name(x) for x in
                                 [verdict.best] + verdict.toss_up_with)
                lines.append(
                    f"The panel would split: {tied} scored within the noise "
                    f"(gap {verdict.measured['gap_imps']:+.1f} IMPs, "
                    f"±{verdict.measured['ci']:.1f}).")
            else:
                lines.append(
                    f"Best in simulation: {verdict.measured['gap_imps']:+.1f} "
                    f"IMPs vs {_call_name(verdict.measured['top2'][1])} "
                    f"(±{verdict.measured['ci']:.1f}) — a real edge, not a "
                    f"landslide.")
        else:
            lines.append(
                f"Scored {row['ev_imp_vs_top']:+.1f} IMPs vs the top choice "
                f"(±{row['ci']:.1f}); wins on {row['p_gain']:.0%} of layouts, "
                f"pushes on {row['p_push']:.0%}.")
        if any(d["bid"] == b for d in verdict.dead):
            lines.append("Best on essentially no layout in this simulation — "
                         "shown for completeness.")
        if b == "X" and "doubled_heavy" in verdict.flags:
            lines.append("Caveat: much of this margin flows through doubled "
                         "contracts, where double-dummy defense is too good — "
                         "treat the exact number with care.")
        out.append({"bid": b, "text": " ".join(lines),
                    "category": info.category,
                    "convention": info.convention,
                    "double_type": info.double_type})
    return out
