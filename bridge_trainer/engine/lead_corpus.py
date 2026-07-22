"""Blind-labelled validation corpus for the opening-lead audit (requirement 6).

Each case carries an EXPECTED label fixed BEFORE the pipeline runs; the runner
compares the pipeline's observed verdict against that blind label and reports
agreement plus ace-win / robustness / mapping-failure / leak-failure rates.

The synthetic cases (controlled DD via injected `dd_fn`) run fully in CI with
no Ben and give ground truth for: stable controls, a suspected ace-overpreference
control, low-card mapping, a source-leak probe, a tail-dominated fixture, and a
sampler-sensitive fixture. Real expert-suspect boards (needing Ben) are listed
with their recorded labels and run only when an engine is supplied.

Do NOT claim improvement merely because diagnostics exist — the report states
measured agreement with the blind labels, nothing more.
"""
from __future__ import annotations

from dataclasses import dataclass

from .lead_posterior import (
    SUITS, RANKS, build_problem, evaluate_layouts, delta_report, quality_flag,
    correctness_gate, card_level_audit, result_signature)
from .lead_samplers import SyntheticSampler

AUCTION = "1S P 2C P 3D P 3NT P P P".split()


def _full_deal(hand: str) -> dict:
    """A card-conserving 4-hand deal whose North hand is `hand` (the other
    hands are filler; DD is injected via dd_fn, so they don't matter)."""
    held = set()
    for s, holding in zip(SUITS, hand.split(".")):
        held |= {s + r for r in holding}
    rest = [s + r for s in SUITS for r in RANKS if s + r not in held]

    def pbn(cards):
        by = {s: [] for s in SUITS}
        for c in cards:
            by[c[0]].append(c[1])
        order = {r: i for i, r in enumerate(RANKS)}
        return ".".join("".join(sorted(by[s], key=lambda r: order[r]))
                        for s in SUITS)
    return {"N": hand, "E": pbn(rest[0:13]), "S": pbn(rest[13:26]),
            "W": pbn(rest[26:39])}


def _const_dd(values):
    def fn(problem, hd):
        return dict(values)
    return fn


def _tail_dd(base, spike_card, spike_value, spike_frac=0.005):
    """DD where spike_card equals base+spike on a tiny fraction of layouts and
    ties otherwise — a tail-dominated signal keyed off layout identity."""
    calls = {"i": 0}

    def fn(problem, hd):
        v = dict(base)
        # deterministic 'layout index' from the dummy hand string
        h = hash(hd["S"]) % 1000
        if h < int(spike_frac * 1000) + 1:
            v[spike_card] = spike_value
        calls["i"] += 1
        return v
    return fn


@dataclass
class CorpusCase:
    id: str
    category: str
    blind_label: dict          # expected verdict, set before running
    hand: str
    samplers: list             # [(label, SyntheticSampler, dd_fn)]
    requested: int = 200
    compare: tuple | None = None
    needs_engine: bool = False
    note: str = ""


def synthetic_corpus() -> list:
    """Ground-truth synthetic cases (CI-safe)."""
    N = 200
    cases = []

    # 1. stable control: DT clearly best on every layout -> robust, winner DT
    hand = "874.AQ94.T.97642"
    layouts = [_full_deal(hand)] * N
    base = {c: 1 for c in _leads(hand)}
    base["DT"] = 3
    cases.append(CorpusCase(
        id="stable_control_DT", category="stable_control",
        blind_label={"state": "robust", "winner": "DT",
                     "gate_pass": True, "ace_is_winner": False},
        hand=hand,
        samplers=[("a", SyntheticSampler(layouts), _const_dd(base)),
                  ("b", SyntheticSampler(layouts), _const_dd(base))]))

    # 2. ace-overpreference control: the ace is clearly NOT best (a low club is)
    #    -> winner must not be the ace (no spurious pro-ace pull)
    base2 = {c: 1 for c in _leads(hand)}
    base2["C7"] = 3        # passive club best; HA stays at 1
    cases.append(CorpusCase(
        id="ace_not_best_control", category="ace_overpreference",
        blind_label={"state": "robust", "winner": "C7",
                     "gate_pass": True, "ace_is_winner": False},
        hand=hand,
        samplers=[("a", SyntheticSampler(layouts), _const_dd(base2)),
                  ("b", SyntheticSampler(layouts), _const_dd(base2))]))

    # 3. low-card mapping: distinct low-heart values must survive as distinct
    hand3 = "2.AQ942.T3.97643"
    lay3 = [_full_deal(hand3)] * N
    base3 = {c: 1 for c in _leads(hand3)}
    base3.update({"HA": 1, "HQ": 2, "H9": 3, "H4": 4, "H2": 5})
    cases.append(CorpusCase(
        id="low_card_mapping", category="low_card_mapping",
        blind_label={"state": "robust", "winner": "H2",
                     "gate_pass": True, "ace_is_winner": False,
                     "all_distinct": True},
        hand=hand3,
        samplers=[("a", SyntheticSampler(lay3), _const_dd(base3)),
                  ("b", SyntheticSampler(lay3), _const_dd(base3))]))

    # 4. source-leak probe: identical public state+seed twice -> same signature
    cases.append(CorpusCase(
        id="source_leak_probe", category="source_leak",
        blind_label={"state": "robust", "gate_pass": True,
                     "signatures_identical": True},
        hand=hand,
        samplers=[("a", SyntheticSampler(layouts), _const_dd(base)),
                  ("b", SyntheticSampler(layouts), _const_dd(base))]))

    # 5. tail-dominated: HA ties except a rare +7 spike -> insufficient_evidence
    base5 = {c: 1 for c in _leads(hand)}
    cases.append(CorpusCase(
        id="tail_dominated_HA", category="tail_dominated",
        blind_label={"state": "insufficient_evidence"},
        hand=hand, compare=("HA", "DT"),
        samplers=[("a", SyntheticSampler(layouts),
                   _tail_dd(base5, "HA", 8, spike_frac=0.005))]))

    # 6. sampler-sensitive: two samplers with opposite winners
    baseA = {c: 1 for c in _leads(hand)}; baseA["HA"] = 3
    baseB = {c: 1 for c in _leads(hand)}; baseB["C7"] = 3
    cases.append(CorpusCase(
        id="sampler_sensitive", category="sampler_sensitive",
        blind_label={"state": "sampler_sensitive"},
        hand=hand,
        samplers=[("A", SyntheticSampler(layouts), _const_dd(baseA)),
                  ("B", SyntheticSampler(layouts), _const_dd(baseB))]))

    return cases


def real_board_registry() -> list:
    """Expert-suspect real boards with recorded labels (need Ben to run)."""
    return [
        {"id": "lead1-0284459a", "category": "ace_overpreference",
         "auction": "1S P 2C P 3D P 3NT P P P", "contract": "3NTW",
         "recorded_label": "sampler_sensitive",
         "note": "HA best @.70 but ben-replay picks a passive club; decay + "
                 "independent-sampler disagreement."},
        {"id": "lead1-02faf4ff", "category": "sampler_sensitive",
         "auction": "1C P 1H P 2NT P 3H P 4H P P P", "contract": "4HE",
         "recorded_label": "sampler_sensitive",
         "note": "SA winner flips to DT at tau=.80; CI crosses 0 at .90."},
        {"id": "lead1-03473cc7", "category": "stable_control",
         "auction": "1D P 1H P 1S P 4H P P P", "contract": "4HN",
         "recorded_label": "robust",
         "note": "CA robust across all thresholds and Ben-native."},
    ]


def _leads(hand: str) -> list:
    out = []
    for s, holding in zip(SUITS, hand.split(".")):
        out.extend(s + r for r in holding)
    return out


def run_case(case: CorpusCase, seed: int = 1, n_boot: int = 500) -> dict:
    problem = build_problem(case.hand, AUCTION, "E", "Both", "3NTW")
    reports = {}
    gate = None
    sigs = []
    winner0 = all_distinct = None
    for label, sampler, dd_fn in case.samplers:
        ls = sampler.sample(problem, case.requested, seed)
        ev = evaluate_layouts(ls, dd_fn=dd_fn)
        sigs.append(result_signature(ev, ls))
        order = ev.ranking()
        a, b = (case.compare if case.compare else (order[0], order[1]))
        dr = delta_report(ev.def_tricks[a], ev.def_tricks[b],
                          weight=ls.weight, n_boot=n_boot, seed=seed)
        reports[label] = {"winner": order[0], "delta_report": dr}
        if gate is None:
            ls2 = sampler.sample(problem, case.requested, seed)
            gate = correctness_gate(problem, ls, ev, ls2,
                                    evaluate_layouts(ls2, dd_fn=dd_fn))
            winner0 = order[0]
            all_distinct = card_level_audit(ls, ev)["all_distinct"]
    state = quality_flag(reports)
    observed = {
        "state": state, "winner": winner0,
        "gate_pass": gate["passed"],
        "ace_is_winner": winner0.endswith("A"),
        "all_distinct": all_distinct,
        "signatures_identical": len(set(sigs)) == 1,
    }
    # agreement: every key present in the blind label must match
    agree = all(observed.get(k) == v for k, v in case.blind_label.items())
    return {"id": case.id, "category": case.category,
            "blind_label": case.blind_label, "observed": observed,
            "agree": agree}


def run_corpus(seed: int = 1, n_boot: int = 500) -> dict:
    results = [run_case(c, seed=seed, n_boot=n_boot) for c in synthetic_corpus()]
    n = len(results)
    agree = sum(r["agree"] for r in results)
    robust = sum(r["observed"]["state"] == "robust" for r in results)
    ace_wins = sum(bool(r["observed"]["ace_is_winner"]) for r in results
                   if r["observed"]["winner"])
    mapping_failures = sum(
        1 for r in results if r["category"] == "low_card_mapping"
        and not r["observed"]["all_distinct"])
    leak_failures = sum(
        1 for r in results if r["category"] == "source_leak"
        and not r["observed"]["signatures_identical"])
    return {
        "n_cases": n,
        "label_agreement_rate": round(agree / n, 4),
        "robustness_rate": round(robust / n, 4),
        "ace_win_rate": round(ace_wins / n, 4),
        "mapping_failures": mapping_failures,
        "source_leak_failures": leak_failures,
        "cases": results,
        "real_board_registry": real_board_registry(),
    }
