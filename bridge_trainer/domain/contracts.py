from __future__ import annotations

from dataclasses import dataclass

from .auction import Seat

DENOM_ORDER = ("C", "D", "H", "S", "NT")


@dataclass(frozen=True)
class FinalContract:
    """Where the projected auction ends for one deal.

    level == 0 means the deal is passed out (score 0).
    """

    level: int
    denom: str  # C/D/H/S/NT, "" when passed out
    declarer: Seat | None
    doubled: bool = False
    terminal: bool = True  # author consciously truncated the auction here

    @classmethod
    def parse(cls, spec: str, terminal: bool = True) -> "FinalContract":
        """Parse e.g. '3SN', '3HWx', '4HW', 'P' (passed out)."""
        s = spec.strip()
        if s.upper() == "P":
            return cls(level=0, denom="", declarer=None, terminal=terminal)
        # Format: level + denom + declarer + optional trailing x, e.g. 3NTSx
        doubled = False
        if s[-1] in ("x", "X") and len(s) >= 2 and s[-2].upper() in "NESW":
            doubled, s = True, s[:-1]
        declarer = s[-1].upper()
        if declarer not in "NESW":
            raise ValueError(f"bad declarer in contract spec {spec!r}")
        body = s[:-1]
        level = int(body[0])
        denom = body[1:].upper()
        if level < 1 or level > 7 or denom not in DENOM_ORDER:
            raise ValueError(f"bad contract spec {spec!r}")
        return cls(level=level, denom=denom, declarer=declarer,
                   doubled=doubled, terminal=terminal)

    @property
    def passed_out(self) -> bool:
        return self.level == 0

    def __str__(self) -> str:
        if self.passed_out:
            return "Pass-out"
        return f"{self.level}{self.denom}{self.declarer}{'x' if self.doubled else ''}"
