"""Single-dummy correction layer (INV5).

Double-dummy play assumes perfect declarers AND perfect defenders. This
layer smears each contract's DD trick count into a small distribution of
single-dummy outcomes using an editable table of trick-delta probabilities,
keyed by denomination type. The corrected score is the expectation over that
distribution.

The correction is applied SYMMETRICALLY to every contract inside a
comparison — never selectively (INV5). Reports always show both the raw and
corrected verdicts; when they disagree the problem is labelled "inside the
DD fog".

The default table is a deliberately mild prior; edit
bridge_trainer/dd/correction_table.yaml to taste.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

SUPPORTED_SCHEMA_VERSIONS = (1,)
DEFAULT_TABLE = Path(__file__).parent / "correction_table.yaml"


class CorrectionTable:
    def __init__(self, data: dict, source: str = "<inline>"):
        version = data.get("schema_version")
        if version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"{source}: unsupported correction schema_version {version!r}")
        self.source = source
        self.deltas: dict[str, dict[int, float]] = {}
        for kind in ("suit", "nt"):
            spec = {int(k): float(v) for k, v in data[kind].items()}
            total = sum(spec.values())
            if abs(total - 1.0) > 1e-9:
                raise ValueError(
                    f"{source}: {kind} delta probabilities sum to {total}, not 1")
            self.deltas[kind] = spec

    def distribution(self, denom: str) -> dict[int, float]:
        """{trick_delta: probability} for a contract in this denomination."""
        return self.deltas["nt" if denom == "NT" else "suit"]


@lru_cache(maxsize=1)
def load_default_correction() -> CorrectionTable:
    """Cached: the table is read-only and the producer calls this per seed."""
    with open(DEFAULT_TABLE) as f:
        return CorrectionTable(yaml.safe_load(f), source=str(DEFAULT_TABLE))
