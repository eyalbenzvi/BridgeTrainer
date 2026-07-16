"""Vectorized NumPy rejection DealSource (build-order item 1).

My hand is fixed; the remaining 39 cards are shuffled in batches and split
13/13/13 to the hidden seats. Cheap features are evaluated first with
short-circuiting: HCP masks cut the batch before suit lengths are computed,
and exclusion predicates only run on survivors. Soft margin bands become
importance weights on the accepted deals (INV2); hands matching an exclusion
predicate get weight 0.

Acceptance rate is logged in GenerationDiagnostics on every run to drive the
decision on reserve dealers (spec build-order item 5).
"""
from __future__ import annotations

import time

import numpy as np
from endplay.types import Deal

from ..domain.auction import SEATS, Seat
from ..domain.constraints import SUITS, ConstraintProfile, SeatConstraints
from ..domain.deals import GenerationDiagnostics, WeightedDeal
from ..domain.interfaces import GenerationBudget
from ..semantics.predicates import PREDICATES
from .features import SeatFeatures, hand_to_pbn, parse_hand_pbn


class RejectionDealSource:
    def __init__(self, my_seat: Seat, batch_size: int = 50_000):
        self.my_seat = my_seat
        self.batch_size = batch_size
        self.hidden_seats = [s for s in SEATS if s != my_seat]

    def generate(
        self,
        my_hand: str,
        constraints: ConstraintProfile,
        n: int,
        seed: int,
        budget: GenerationBudget | None = None,
    ) -> tuple[list[WeightedDeal], GenerationDiagnostics]:
        budget = budget or GenerationBudget()
        my_cards = parse_hand_pbn(my_hand)
        remaining = np.array(sorted(set(range(52)) - set(my_cards)), dtype=np.int8)
        slices = {s: slice(i * 13, (i + 1) * 13)
                  for i, s in enumerate(self.hidden_seats)}

        rng = np.random.default_rng(seed)
        kept_rows: list[np.ndarray] = []
        kept_weights: list[np.ndarray] = []
        attempts = 0
        t0 = time.perf_counter()

        while (
            sum(len(r) for r in kept_rows) < n
            and attempts < budget.max_attempts
            and time.perf_counter() - t0 < budget.max_seconds
        ):
            batch = min(self.batch_size, budget.max_attempts - attempts)
            perm = rng.permuted(np.tile(remaining, (batch, 1)), axis=1)
            attempts += batch

            rows, weights = self._filter_batch(perm, constraints, slices)
            if len(rows):
                kept_rows.append(rows)
                kept_weights.append(weights)

        elapsed = time.perf_counter() - t0
        if kept_rows:
            all_rows = np.concatenate(kept_rows)[:n]
            all_weights = np.concatenate(kept_weights)[:n]
        else:
            all_rows = np.empty((0, 39), dtype=np.int8)
            all_weights = np.empty(0, dtype=np.float64)

        deals = [
            WeightedDeal(deal=self._to_deal(row, my_hand, slices), weight=float(w))
            for row, w in zip(all_rows, all_weights)
        ]
        wsum = all_weights.sum()
        ess = float(wsum * wsum / (all_weights ** 2).sum()) if len(all_weights) else 0.0
        diagnostics = GenerationDiagnostics(
            attempts=attempts,
            acceptance_rate=len(deals) / attempts if attempts else 0.0,
            effective_sample_size=ess,
            unrecognized_calls=list(constraints.unrecognized_calls),
            elapsed_s=elapsed,
            shortfall=max(0, n - len(deals)),
        )
        return deals, diagnostics

    # ------------------------------------------------------------------
    def _filter_batch(self, perm, constraints, slices):
        B = len(perm)
        weights = np.ones(B, dtype=np.float64)
        alive = np.ones(B, dtype=bool)

        # Stage 1 (cheapest): HCP band weights per seat, short-circuit.
        for seat in self.hidden_seats:
            sc = constraints.seats.get(seat)
            if sc is None:
                continue
            idx = np.flatnonzero(alive)
            if not len(idx):
                return perm[:0], weights[:0]
            f = SeatFeatures(cards=perm[idx][:, slices[seat]])
            w = sc.hcp_weights[f.hcp]
            ok = w > 0
            weights[idx[ok]] *= w[ok]
            alive[idx[~ok]] = False

        # Stage 2: suit-length + suit-quality band weights + denials.
        for seat in self.hidden_seats:
            sc = constraints.seats.get(seat)
            if sc is None:
                continue
            idx = np.flatnonzero(alive)
            if not len(idx):
                return perm[:0], weights[:0]
            f = SeatFeatures(cards=perm[idx][:, slices[seat]])
            w = np.ones(len(idx), dtype=np.float64)
            for suit in SUITS:
                w *= sc.suit_weights[suit][f.suit_lengths[suit]]
                w *= sc.suit_hcp_weights[suit][f.suit_hcp[suit]]
            for d in sc.denials:
                hit = ((f.hcp >= d.hcp_lo) & (f.hcp <= d.hcp_hi)
                       & (f.suit_lengths[d.suit] >= d.min_len))
                w *= np.where(hit, d.weight, 1.0)
            ok = w > 0
            weights[idx[ok]] *= w[ok]
            alive[idx[~ok]] = False

        # Stage 3 (most expensive): exclusion predicates -> weight 0.
        for seat in self.hidden_seats:
            sc = constraints.seats.get(seat)
            if sc is None or not sc.exclusions:
                continue
            idx = np.flatnonzero(alive)
            if not len(idx):
                return perm[:0], weights[:0]
            f = SeatFeatures(cards=perm[idx][:, slices[seat]])
            excluded = np.zeros(len(idx), dtype=bool)
            for name in sc.exclusions:
                excluded |= PREDICATES[name](f)
            alive[idx[excluded]] = False

        return perm[alive], weights[alive]

    def _to_deal(self, row, my_hand: str, slices) -> Deal:
        hands = {self.my_seat: my_hand}
        for seat in self.hidden_seats:
            hands[seat] = hand_to_pbn(row[slices[seat]])
        return Deal("N:{N} {E} {S} {W}".format(**hands))
