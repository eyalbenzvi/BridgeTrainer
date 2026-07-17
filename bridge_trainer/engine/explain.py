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
            entry["text"] = ""   # bids that show nothing get no note (r3 #5)
        elif tok in ("X", "XX"):
            entry["text"] = f"{text_head}: {info.double_type or 'double'}."
        else:
            entry["text"] = f"{text_head}: {info.category}."
        if seat_i == spot.hero_i and tok != "P":
            # what YOUR bid told partner (owner r3 #3)
            who = "told partner"
            if info.convention:
                entry["text"] = f"{text_head}: {info.convention}."
            else:
                meaning = _meaning_from_partner(
                    engine, spot, spot.stem[:j + 1], spot.hero_i)
                entry["text"] = (f"{text_head}: {who} " + meaning + "."
                                 ) if meaning else \
                    f"{text_head}: {info.double_type or info.category}."
            out.append(entry)
            continue
        if seat_i == spot.hero_i:
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


def _meaning_from_partner(engine, spot, prefix, subject_i) -> str | None:
    """What subject_i's last call in `prefix` SHOWED, measured: sample
    layouts consistent with the auction through that call from the
    subject's PARTNER's viewpoint (we hold the full deal), then
    summarize the subject-seat hands — the population of hands that
    make this call in the engine's 2/1 style."""
    partner_i = (subject_i + 2) % 4
    try:
        bot = engine.bot(spot.hands[partner_i], partner_i,
                         spot.dealer_i, spot.vul)
        hands_np, n = engine.sample_prefix(bot, spot.dealer_i, prefix)
    except Exception:
        return None
    if n < BAND_N_MIN:
        return None
    feats = seat_features(hands_np, subject_i,
                          engine.models.n_cards_bidding)
    lo, hi = round(feats["hcp_p10"]), round(feats["hcp_p90"])
    parts = [f"shows {lo}-{hi} HCP"]
    longs = [s for s in "SHDC" if feats["len_avg"][s] >= 4.6]
    for s in longs:
        parts.append(f"{feats['len_avg'][s]:.1f} {SUIT_GLYPH[s]} on average")
    if not longs and feats["balanced_share"] >= 0.55:
        parts.append(f"balanced {feats['balanced_share']:.0%} of the time")
    return ", ".join(parts) + f" (n={n}, measured)"


def _continuations(spot, ev, bid) -> str | None:
    """What the consecutive bids can be: the distribution of the next
    calls in the verdict rollouts after this option."""
    from collections import Counter
    tails = []
    nexts = Counter()
    for auc in ev.auctions.get(bid, []):
        toks = auc.split()
        cont = toks[len(spot.stem) + 1:]
        if cont:
            nexts[cont[0]] += 1
            tails.append(" ".join(cont[:3]))
    if not nexts:
        return None
    n = sum(nexts.values())
    partner = "partner" if True else ""
    head = "; ".join(f"{_call_name(c)} ({cnt / n:.0%})"
                     for c, cnt in nexts.most_common(3))
    common_tail = Counter(tails).most_common(1)[0]
    tail_txt = ""
    if common_tail[1] / n >= 0.3 and common_tail[0]:
        pretty = " ".join(_call_name(t) for t in common_tail[0].split())
        tail_txt = f"; most common continuation: {pretty}" \
                   f" ({common_tail[1] / n:.0%})"
    return f"Next call is usually {head}{tail_txt}."


def option_explanations(spot, verdict, policy_map, engine=None,
                        ev=None) -> list[dict]:
    out = []
    ordered = [r["bid"] for r in verdict.table]
    for row in verdict.table:
        b = row["bid"]
        info = classify(spot.stem + [b] if b not in ("P", "X", "XX") or True
                        else spot.stem, spot.dealer_i, len(spot.stem))
        contracts = ", ".join(
            f"{c} ({cnt / verdict.measured['n_samples']:.0%})"
            for c, cnt in row["top_contracts"])
        meaning = _meaning_from_partner(engine, spot, spot.stem + [b],
                                        spot.hero_i) if engine else None
        conv = info.convention or info.double_type or info.category
        lines = [
            f"{_call_name(b)} — {conv}" + (f": {meaning}." if meaning
                                           else "."),
        ]
        if ev is not None:
            cont = _continuations(spot, ev, b)
            if cont:
                lines.append(cont)
        lines += [
            f"A strong engine chooses this {policy_map.get(b, 0):.0%} of the "
            f"time here.",
            f"Where it leads: {contracts}.",
        ]
        if b == verdict.best:
            by = verdict.measured.get("winner_by", "")
            other = [x for x in verdict.measured['top2'] if x != b]
            vs = _call_name(other[0]) if other else "the alternative"
            lines.append(
                f"The winner ({by}): {verdict.measured['gap_imps']:+.1f} "
                f"IMPs vs {vs} (±{verdict.measured['ci']:.1f}); wins on "
                f"{verdict.measured.get('p_top_wins', 0):.0%} of layouts "
                f"against {verdict.measured.get('p_second_wins', 0):.0%}.")
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
