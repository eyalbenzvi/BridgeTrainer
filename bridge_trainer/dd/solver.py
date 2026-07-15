"""Chunked wrapper around endplay's CalcAllTables.

DDS's ddTableDeals structure holds at most 40 deals per call (measured in
the M0 spike; endplay's own guard is wrong), so we chunk. Denominations not
needed by any projected contract are excluded, which is the main lever on
wall clock.
"""
from __future__ import annotations

import numpy as np
from endplay.dds import calc_all_tables
from endplay.types import Denom, Player

from ..domain.deals import WeightedDeal

_CHUNK = 40
_DENOMS = {"S": Denom.spades, "H": Denom.hearts, "D": Denom.diamonds,
           "C": Denom.clubs, "NT": Denom.nt}


class DDSolver:
    def solve(
        self, deals: list[WeightedDeal], denoms: set[str]
    ) -> dict[tuple[str, str], np.ndarray]:
        """DD tricks per (denom, declarer) across all deals.

        Returns arrays of shape (len(deals),) keyed by e.g. ("H", "W").
        """
        if not denoms:
            return {}
        unknown = denoms - set(_DENOMS)
        if unknown:
            raise ValueError(f"unknown denominations {unknown}")
        exclude = [d for k, d in _DENOMS.items() if k not in denoms]

        n = len(deals)
        out = {(dn, pl): np.zeros(n, dtype=np.int8)
               for dn in denoms for pl in "NESW"}
        for start in range(0, n, _CHUNK):
            chunk = deals[start:start + _CHUNK]
            tables = calc_all_tables((wd.deal for wd in chunk), exclude=exclude)
            for i, tbl in enumerate(tables):
                for dn in denoms:
                    for pl in "NESW":
                        out[(dn, pl)][start + i] = int(
                            tbl[_DENOMS[dn], Player.find(pl)])
        return out
