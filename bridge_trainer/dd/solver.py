"""Chunked wrapper around endplay's CalcAllTables and SolveAllBoards.

DDS's ddTableDeals structure holds at most 40 deals per call (measured in
the M0 spike; endplay's own guard is wrong), so we chunk. Denominations not
needed by any projected contract are excluded, which is the main lever on
wall clock.

When per-deal requirements are known (`needed`), strains required on only a
small fraction of the deals are solved per-board with SolveAllBoards (trump
set, declarer's LHO on lead; declarer tricks = 13 - best defence) instead of
being included in every table: a table pays for 4 declarers x all included
strains on every deal, so a strain that only a rare contract reaches is far
cheaper solved alone. Strains needed on many deals stay in the tables, where
DDS's transposition-table reuse across entries wins (measured: full-set
targeted solving is NOT faster than tables — only the rare-strain split is).
"""
from __future__ import annotations

import numpy as np
from endplay.dds import calc_all_tables, solve_all_boards
from endplay.types import Deal, Denom, Player

from ..domain.deals import WeightedDeal

_CHUNK_TABLES = 40   # ddTableDeals capacity
_CHUNK_BOARDS = 200  # dds MAXNOOFBOARDS
_DENOMS = {"S": Denom.spades, "H": Denom.hearts, "D": Denom.diamonds,
           "C": Denom.clubs, "NT": Denom.nt}
_LHO = {"N": "E", "E": "S", "S": "W", "W": "N"}

# A strain needed on at most this fraction of deals is solved per-board
# instead of inside every table.
RARE_STRAIN_FRAC = 0.25


class DDSolver:
    def solve(
        self,
        deals: list[WeightedDeal],
        denoms: set[str],
        needed: list[set[tuple[str, str]]] | None = None,
    ) -> dict[tuple[str, str], np.ndarray]:
        """DD tricks per (denom, declarer) across all deals.

        Returns arrays of shape (len(deals),) keyed by e.g. ("H", "W").

        `needed` (optional) lists the (denom, declarer) pairs actually
        required for each deal. When given, rare strains are solved
        per-board; entries never listed in `needed` are left 0 for those
        strains, so callers must only read entries they declared.
        """
        if not denoms:
            return {}
        unknown = denoms - set(_DENOMS)
        if unknown:
            raise ValueError(f"unknown denominations {unknown}")
        if needed is None:
            return self._solve_tables(deals, denoms)

        n = len(deals)
        need_count = {dn: 0 for dn in denoms}
        for pairs in needed:
            for dn in {p[0] for p in pairs}:
                need_count[dn] += 1
        table_denoms = {dn for dn in denoms
                        if need_count[dn] > RARE_STRAIN_FRAC * n}
        out = self._solve_tables(deals, table_denoms)
        rare = denoms - table_denoms
        if rare:
            out.update(self._solve_boards(deals, rare, needed))
        return out

    # ------------------------------------------------------------------
    def _solve_tables(
        self, deals: list[WeightedDeal], denoms: set[str]
    ) -> dict[tuple[str, str], np.ndarray]:
        if not denoms:
            return {}
        exclude = [d for k, d in _DENOMS.items() if k not in denoms]
        n = len(deals)
        out = {(dn, pl): np.zeros(n, dtype=np.int8)
               for dn in denoms for pl in "NESW"}
        for start in range(0, n, _CHUNK_TABLES):
            chunk = deals[start:start + _CHUNK_TABLES]
            tables = calc_all_tables((wd.deal for wd in chunk), exclude=exclude)
            for i, tbl in enumerate(tables):
                for dn in denoms:
                    for pl in "NESW":
                        out[(dn, pl)][start + i] = int(
                            tbl[_DENOMS[dn], Player.find(pl)])
        return out

    def _solve_boards(
        self,
        deals: list[WeightedDeal],
        denoms: set[str],
        needed: list[set[tuple[str, str]]],
    ) -> dict[tuple[str, str], np.ndarray]:
        n = len(deals)
        out = {(dn, pl): np.zeros(n, dtype=np.int8)
               for dn in denoms for pl in "NESW"}
        boards: list[Deal] = []
        index: list[tuple[int, str, str]] = []
        for i, (wd, pairs) in enumerate(zip(deals, needed)):
            for dn, decl in sorted(pairs):
                if dn not in denoms:
                    continue
                b = Deal(str(wd.deal))
                b.trump = _DENOMS[dn]
                b.first = Player.find(_LHO[decl])
                boards.append(b)
                index.append((i, dn, decl))
        for start in range(0, len(boards), _CHUNK_BOARDS):
            solved = solve_all_boards(boards[start:start + _CHUNK_BOARDS])
            for (i, dn, decl), sb in zip(index[start:start + _CHUNK_BOARDS],
                                         solved):
                best_defence = max(t for _, t in sb)
                out[(dn, decl)][i] = 13 - best_defence
        return out
