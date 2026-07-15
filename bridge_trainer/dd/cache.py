"""Deal-set disk cache with the INV4 cache key.

Key = hash(my_hand, constraint profile, system profiles, dealer,
vulnerability, seed, schema versions, library versions). Dealer and
vulnerability in the key are mandatory even though generation itself does
not depend on them: a cached deal set is only valid for the exact problem
setup it was generated for.
"""
from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path

import endplay
import numpy

from .. import __version__ as trainer_version
from ..domain.constraints import ConstraintProfile
from ..domain.deals import GenerationDiagnostics, WeightedDeal

SEMANTICS_SCHEMA_VERSION = 1
PROBLEM_SCHEMA_VERSION = 1
SAMPLER_VERSION = 1  # bump when the sampler's sampling distribution changes


def library_versions() -> dict[str, str]:
    return {
        "bridge_trainer": trainer_version,
        "endplay": endplay.__version__,
        "numpy": numpy.__version__,
        "python": platform.python_version(),
    }


def deal_set_cache_key(
    my_hand: str,
    constraints: ConstraintProfile,
    system_fingerprints: dict[str, str],
    dealer: str,
    vul: str,
    seed: int,
    n: int,
) -> str:
    payload = {
        "my_hand": my_hand,
        "constraints": constraints.fingerprint(),
        "systems": system_fingerprints,
        "dealer": dealer,          # mandatory in key (INV4)
        "vul": vul,                # mandatory in key (INV4)
        "seed": seed,
        "n": n,
        "schema_versions": {
            "semantics": SEMANTICS_SCHEMA_VERSION,
            "problem": PROBLEM_SCHEMA_VERSION,
            "sampler": SAMPLER_VERSION,
        },
        "library_versions": library_versions(),
    }
    blob = json.dumps(payload, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()


class DealSetCache:
    """Stores deal sets (PBN + weights + diagnostics) as JSON per key,
    plus DD trick tables keyed by (deal-set key, denominations)."""

    def __init__(self, root: str | Path = ".trainer_cache"):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / f"deals_{key}.json"

    def _dd_path(self, key: str, denoms: set[str]) -> Path:
        return self.root / f"dd_{key}_{'-'.join(sorted(denoms))}.json"

    def load(self, key: str) -> tuple[list[WeightedDeal], GenerationDiagnostics] | None:
        path = self._path(key)
        if not path.exists():
            return None
        from endplay.types import Deal
        data = json.loads(path.read_text())
        deals = [WeightedDeal(deal=Deal(p), weight=w)
                 for p, w in zip(data["pbn"], data["weights"])]
        d = data["diagnostics"]
        diagnostics = GenerationDiagnostics(
            attempts=d["attempts"],
            acceptance_rate=d["acceptance_rate"],
            effective_sample_size=d["effective_sample_size"],
            unrecognized_calls=d["unrecognized_calls"],
            elapsed_s=d["elapsed_s"],
            shortfall=d["shortfall"],
        )
        return deals, diagnostics

    def store(self, key: str, deals: list[WeightedDeal],
              diagnostics: GenerationDiagnostics) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        data = {
            "pbn": [str(wd.deal) for wd in deals],
            "weights": [wd.weight for wd in deals],
            "diagnostics": diagnostics.to_dict(),
        }
        self._path(key).write_text(json.dumps(data))

    def load_tricks(self, key: str, denoms: set[str]):
        """Cached DD trick arrays, or None. Valid for the exact deal set the
        key identifies (INV4), so no extra key material is needed."""
        import numpy as np
        path = self._dd_path(key, denoms)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return {(dn, pl): np.array(v, dtype=np.int8)
                for k, v in data.items()
                for dn, pl in [k.split("|")]}

    def store_tricks(self, key: str, denoms: set[str], tricks) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        data = {f"{dn}|{pl}": arr.tolist() for (dn, pl), arr in tricks.items()}
        self._dd_path(key, denoms).write_text(json.dumps(data))
