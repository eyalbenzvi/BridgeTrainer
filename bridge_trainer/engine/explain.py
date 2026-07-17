"""Explanations: given-bidding meaning bands + option explanations.
All computed (samples + auction mechanics + evaluation numbers), never
asserted — docs/ben_execution_plan.md §3.3 + v2 amendments 1, 2, 9, 11.
"""
from __future__ import annotations

import numpy as np

from .ben import seat_features
from .conventions import seat_of

SEATS = "NESW"
SUIT_GLYPH = {"S": "♠", "H": "♥", "D": "♦", "C": "♣", "NT": "NT"}
BAND_N_MIN = 30


def _call_name(tok: str) -> str:
    if tok in ("P", "X", "XX"):
        return {"P": "Pass", "X": "Double", "XX": "Redouble"}[tok]
    return tok[0] + SUIT_GLYPH[tok[1:]]


def _clean_card_text(text: str) -> str:
    """EPBot emits 'Stayman -- ; 7+ HCP; Artificial; Forcing' and !S/!H
    suit markers — tidy for display."""
    t = text.replace("--", "").strip(" ;")
    for filler in ("Bidable suit", "bidable suit", "Calculated bid",
                   "calculated bid"):
        t = t.replace(filler, "")
    t = t.strip(" ;")
    for k, g in SUIT_GLYPH.items():
        t = t.replace(f"!{k}", g)
    parts = [p.strip() for p in t.split(";") if p.strip()]
    return " — ".join([parts[0], ", ".join(parts[1:])]) if len(parts) > 1 \
        else (parts[0] if parts else "")


def _render_meaning(card: dict, is_pass: bool = False) -> str:
    """Compose display text from the ENGINE's card state only: meaning
    text + HCP band + minimum suit lengths. No bridge knowledge here —
    formatting only (owner r6/r7)."""
    text = _clean_card_text(card.get("text") or "")
    bits = []
    hcp = card.get("hcp")
    if hcp and not any(ch.isdigit() for ch in text):
        lo, hi = hcp
        if hi >= 37 and lo > 0:
            bits.append(f"{lo}+ HCP")
        elif hi < 37 and (lo > 0 or hi < 25):
            bits.append(f"{lo}-{hi} HCP")
    if not any(g in text for g in SUIT_GLYPH.values()):
        for st in "SHDC":
            v = card.get("minlen", {}).get(st, 0)
            if v >= 4:
                bits.append(f"{v}+ {SUIT_GLYPH[st]}")
    if is_pass:
        # a pass is worth a note only when the card says it limited the hand
        if hcp and hcp[1] <= 14:
            return f"limited — at most {hcp[1]} HCP"
        return ""
    joined = ", ".join(bits)
    if text and joined:
        return f"{text} — {joined}"
    return text or joined


def stem_explanations(engine, spot, hero_bot) -> list[dict]:
    """One entry per stem call, meaning from the ENGINE's convention
    card (text + numeric state); silent calls get no note."""
    try:
        card = engine.explain_calls(hero_bot, spot.dealer_i, spot.stem)
    except Exception:
        card = [{"text": "", "hcp": None, "minlen": {}}] * len(spot.stem)
    out = []
    for j, tok in enumerate(spot.stem):
        seat_i = seat_of(spot.dealer_i, j)
        meaning = _render_meaning(card[j], is_pass=(tok == "P"))
        entry = {
            "idx": j, "seat": SEATS[seat_i], "call": tok,
            "card": card[j],
        }
        entry["text"] = (f"{_call_name(tok)} ({SEATS[seat_i]}): {meaning}"
                         if meaning else "")
        out.append(entry)
    return out


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
                        ev=None, hero_bot=None) -> list[dict]:
    cards = {}
    if engine is not None and hero_bot is not None:
        for b in [r["bid"] for r in verdict.table]:
            try:
                cards[b] = engine.explain_calls(
                    hero_bot, spot.dealer_i, spot.stem + [b])[-1]
            except Exception:
                cards[b] = {"text": "", "hcp": None, "minlen": {}}
    out = []
    ordered = [r["bid"] for r in verdict.table]
    for row in verdict.table:
        b = row["bid"]
        contracts = ", ".join(
            f"{c} ({cnt / verdict.measured['n_samples']:.0%})"
            for c, cnt in row["top_contracts"])
        meaning = _render_meaning(
            cards.get(b, {"text": "", "hcp": None, "minlen": {}}),
            is_pass=(b == "P"))
        lines = [
            f"{_call_name(b)} — {meaning}." if meaning
            else f"{_call_name(b)}.",
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
        out.append({"bid": b, "text": " ".join(lines)})
    return out
