"""Public-state opening-lead evaluator.

This is the single, deterministic answer to the owner's question:

    "Given ONLY the opening leader's 13 cards, the public auction,
     contract/declarer, vulnerability, dealer, and declared bidding-system
     assumptions, which physical opening card has the highest expected
     defensive tricks over legal hidden layouts?"

Two responsibilities live here and nowhere else:

  * ``score_layouts`` — double-dummy EACH of the 13 physical cards separately
    (endplay, the same DDS the rest of the project uses), converting the raw
    result to defensive tricks with a convention verified in tests. NO 7..2
    folding happens before or during scoring; the fold is a Ben-policy concept
    only (see engine/lead_cards.py).

  * ``evaluate_leads_from_public_state`` — the purity boundary. It receives a
    ``sampler`` callable that may see ONLY the public state and a seed. The
    original full deal can be handed in as ``source_deal`` for audit, but it is
    deleted immediately and can never reach the sampler or the scorer.

Both are pure of Ben/TensorFlow (endplay + numpy only), so they run in normal
CI. The Ben engine supplies a sampler + policy through engine/ben.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

import numpy as np
from endplay.dds import solve_all_boards
from endplay.types import Deal, Denom, Player

from .lead_cards import (SEATS, physical_cards, token_from_endplay_card)
from .lead_invariants import check_dds_result, check_layout, checks_enabled
from .lead_verdict import LeadEvaluation

_DENOM = {"S": Denom.spades, "H": Denom.hearts, "D": Denom.diamonds,
          "C": Denom.clubs, "NT": Denom.nt}
_PLAYER = {0: Player.north, 1: Player.east, 2: Player.south, 3: Player.west}

_SOLVE_CHUNK = 200   # endplay MAXNOOFBOARDS


@dataclass(frozen=True)
class Contract:
    """A public final contract. ``declarer_i`` is an absolute seat 0..3 = NESW."""
    level: int
    denom: str            # "S" / "H" / "D" / "C" / "NT"
    declarer_i: int
    doubled: str = ""     # "", "x", "xx"

    @property
    def leader_i(self) -> int:
        """Opening leader = declarer's left-hand opponent."""
        return (self.declarer_i + 1) % 4

    @classmethod
    def from_fc(cls, fc: dict) -> "Contract":
        return cls(int(fc["level"]), fc["denom"], int(fc["declarer_i"]),
                   fc.get("doubled", ""))

    def __str__(self) -> str:
        return f"{self.level}{self.denom}{SEATS[self.declarer_i]}{self.doubled}"


@dataclass(frozen=True)
class Layout:
    """One sampled hidden layout, hands indexed by ABSOLUTE seat N,E,S,W.

    ``accept`` records why the sampler kept this layout (replayed auction or
    the constraint/rule ids it satisfied) so a debug artifact can explain the
    posterior — it never influences scoring.
    """
    hands: tuple                       # (N, E, S, W) PBN strings
    sample_index: int = -1
    sample_seed: int | None = None
    accept: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PublicState:
    """Everything the evaluator is allowed to condition on."""
    leader_hand: str
    auction: tuple                     # public auction tokens from the dealer
    contract: Contract
    dealer_i: int
    vul: tuple                         # (ns_vul, ew_vul)


@dataclass
class SampleResult:
    """A sampler's output: the layouts plus audit metadata."""
    layouts: list
    quality: float = 1.0
    meta: dict = field(default_factory=dict)


class Sampler(Protocol):
    """A layout sampler. It is handed ONLY the public state and a seed, which
    is what makes the evaluator provably free of source-deal leakage."""

    def __call__(self, public: PublicState, sampler_seed: int,
                 config: "EvalConfig") -> SampleResult: ...


PolicyFn = Callable[[PublicState], dict]   # -> {physical_card: probability}


@dataclass(frozen=True)
class EvalConfig:
    n_samples: int = 128
    check_invariants: bool = False


def opening_leader_for_contract(contract: Contract) -> int:
    """Absolute seat of the opening leader for a contract (declarer's LHO).
    A named function so the invariant layer and callers share one definition."""
    return contract.leader_i


def _deal_for(hands_abs, denom: str, leader_i: int) -> Deal:
    """Build an endplay Deal in absolute NESW order with the trump strain set
    and the opening leader on lead."""
    if denom not in _DENOM:
        raise ValueError(f"unknown denomination {denom!r}")
    deal = Deal("N:" + " ".join(hands_abs))
    deal.trump = _DENOM[denom]
    deal.first = _PLAYER[leader_i]
    return deal


def score_layouts(layouts, contract: Contract, candidates,
                  *, check: bool = False, problem_id: str = "",
                  displayed_leader_hand: str | None = None) -> dict:
    """Per-physical-card defensive tricks over the given layouts.

    Returns ``{physical_card: np.ndarray}`` where entry ``i`` is the number of
    tricks the DEFENSE takes, double-dummy, when that exact card is led against
    ``contract`` on layout ``i``. endplay's ``solve_all_boards`` returns, for
    the player on lead, the tricks that player's side (the defence) can make
    after each legal lead — so the value IS defensive tricks directly (declarer
    tricks would be ``13 - value``). Verified in tests/test_lead_evaluate.py.

    Every one of the 13 physical cards is solved separately; spot cards are
    never folded here.
    """
    leader_i = contract.leader_i
    n = len(layouts)
    def_tricks = {c: np.empty(n, dtype=float) for c in candidates}
    run_checks = check or checks_enabled()

    deals = []
    for si, lay in enumerate(layouts):
        if run_checks:
            check_layout(lay.hands, contract, leader_i,
                         displayed_leader_hand or lay.hands[leader_i],
                         candidates, sample_index=si, problem_id=problem_id,
                         sample_seed=lay.sample_seed)
        deals.append(_deal_for(lay.hands, contract.denom, leader_i))

    solved = []
    for start in range(0, n, _SOLVE_CHUNK):
        solved.extend(solve_all_boards(deals[start:start + _SOLVE_CHUNK]))

    for si, sb in enumerate(solved):
        per_card = {token_from_endplay_card(card): int(tricks)
                    for card, tricks in sb}
        # Always verify DDS returned exactly the candidate cards: this is the
        # cheap, decisive guard against a collapsed / illegal candidate.
        check_dds_result(per_card, candidates, sample_index=si,
                         problem_id=problem_id,
                         sample_seed=layouts[si].sample_seed)
        for card in candidates:
            def_tricks[card][si] = per_card[card]
    return def_tricks


def evaluate_leads_from_public_state(
        leader_hand: str, public_auction, contract: Contract,
        dealer_i: int, vul, sampler_seed: int, config: EvalConfig,
        *, sampler: Sampler, policy: PolicyFn | None = None,
        source_deal=None, problem_id: str = "") -> LeadEvaluation:
    """Grade every opening lead using only public information.

    ``source_deal`` is accepted for audit callers but is dropped on the first
    line; it is structurally impossible for it to influence the sampler, the
    scorer, or the policy from here on.
    """
    del source_deal   # audit-only; MUST NOT influence evaluation

    public = PublicState(leader_hand=leader_hand,
                         auction=tuple(public_auction), contract=contract,
                         dealer_i=dealer_i, vul=tuple(vul))
    candidates = physical_cards(leader_hand)

    result = sampler(public, sampler_seed, config)
    def_tricks = score_layouts(result.layouts, contract, candidates,
                               check=config.check_invariants,
                               problem_id=problem_id,
                               displayed_leader_hand=leader_hand)

    softmax = dict(policy(public)) if policy is not None \
        else {c: 0.0 for c in candidates}

    sample_deals = [" ".join(lay.hands) for lay in result.layouts[:200]]
    return LeadEvaluation(
        cards=candidates, def_tricks=def_tricks, softmax=softmax,
        n_samples=len(result.layouts), quality=float(result.quality),
        contract=str(contract), doubled=bool(contract.doubled),
        sample_deals=sample_deals, sampling=dict(result.meta))
