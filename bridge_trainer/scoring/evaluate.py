"""Evaluator implementation: per-deal scores, raw and corrected.

Raw = table score at the double-dummy trick count. Corrected = expected
table score under the single-dummy correction distribution, applied
symmetrically to every contract (INV5); the comparison layer then IMPs the
per-deal difference of these expectations. DD solving happens once per deal
set for the union of denominations needed by all candidates, so every
candidate is evaluated on identical DD data (INV1).
"""
from __future__ import annotations

import numpy as np

from ..dd.correction import CorrectionTable
from ..dd.solver import DDSolver
from ..domain.auction import Seat, side_of
from ..domain.contracts import FinalContract
from ..domain.deals import WeightedDeal
from .tables import contract_score


def needed_denoms(
        contracts_by_candidate: dict[str, list[FinalContract]]) -> set[str]:
    return {c.denom
            for contracts in contracts_by_candidate.values()
            for c in contracts if not c.passed_out}


class ScoreEvaluator:
    def __init__(self, my_seat: Seat, vul: str,
                 correction: CorrectionTable, solver: DDSolver | None = None):
        self.my_side = side_of(my_seat)
        self.vul = vul
        self.correction = correction
        self.solver = solver or DDSolver()
        self._tricks: dict[tuple[str, str], np.ndarray] = {}
        self._prepared_for: int | None = None

    def _vul_for(self, seat: Seat) -> bool:
        return self.vul == "Both" or self.vul == side_of(seat)

    def prepare(self, deals: list[WeightedDeal],
                contracts_by_candidate: dict[str, list[FinalContract]]) -> None:
        """Solve DD once for the union of denominations across candidates."""
        denoms = needed_denoms(contracts_by_candidate)
        self.set_tricks(self.solver.solve(deals, denoms), len(deals))

    def set_tricks(self, tricks: dict[tuple[str, str], np.ndarray],
                   n_deals: int) -> None:
        """Use precomputed (e.g. cached) DD trick arrays instead of solving."""
        self._tricks = tricks
        self._prepared_for = n_deals

    def evaluate(
        self,
        weighted_deals: list[WeightedDeal],
        contracts: list[FinalContract],
    ) -> tuple[np.ndarray, np.ndarray]:
        if self._prepared_for != len(weighted_deals):
            raise RuntimeError("call prepare() with this deal set first")
        n = len(weighted_deals)
        raw = np.zeros(n, dtype=np.float64)
        corrected = np.zeros(n, dtype=np.float64)
        for i, contract in enumerate(contracts):
            if contract.passed_out:
                continue
            tricks = int(self._tricks[(contract.denom, contract.declarer)][i])
            sign = 1 if side_of(contract.declarer) == self.my_side else -1
            vul = self._vul_for(contract.declarer)
            doubled = 1 if contract.doubled else 0
            raw[i] = sign * contract_score(
                contract.level, contract.denom, doubled, vul, tricks)
            expected = 0.0
            for delta, p in self.correction.distribution(contract.denom).items():
                t = min(13, max(0, tricks + delta))
                expected += p * contract_score(
                    contract.level, contract.denom, doubled, vul, t)
            corrected[i] = sign * expected
        return raw, corrected
