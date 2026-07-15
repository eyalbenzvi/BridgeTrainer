"""Problem YAML loading + validation."""
from __future__ import annotations

from pathlib import Path

import yaml

from ..domain.auction import SEATS, Auction
from ..domain.problem import VULS, BiddingProblem, CandidateAction, SystemProfile

PROBLEM_SCHEMA_VERSION = 1
RULES_DIR = Path(__file__).parent.parent / "semantics" / "rules"

_REQUIRED = ("schema_version", "id", "title", "dealer", "vul", "my_seat",
             "my_hand", "auction", "our_system", "opps_system", "candidates")


class ProblemValidationError(ValueError):
    pass


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ProblemValidationError(msg)


def resolve_ruleset_path(ref: str, problem_dir: Path) -> Path:
    """Ruleset refs resolve relative to the problem file first, then to the
    packaged rules directory."""
    local = problem_dir / ref
    if local.exists():
        return local
    packaged = RULES_DIR / ref
    if packaged.exists():
        return packaged
    raise ProblemValidationError(f"ruleset not found: {ref}")


def _system(spec: dict, what: str) -> SystemProfile:
    _require(isinstance(spec, dict), f"{what} must be a mapping")
    for k in ("name", "description", "ruleset"):
        _require(k in spec, f"{what} missing {k!r}")
    return SystemProfile(name=spec["name"], description=spec["description"],
                         ruleset=spec["ruleset"])


def load_problem(path: str | Path) -> BiddingProblem:
    path = Path(path)
    with open(path) as f:
        data = yaml.safe_load(f)
    _require(isinstance(data, dict), "problem file must be a mapping")
    for k in _REQUIRED:
        _require(k in data, f"problem missing required field {k!r}")
    _require(data["schema_version"] == PROBLEM_SCHEMA_VERSION,
             f"unsupported problem schema_version {data['schema_version']!r}")
    _require(data["dealer"] in SEATS, f"bad dealer {data['dealer']!r}")
    _require(data["my_seat"] in SEATS, f"bad my_seat {data['my_seat']!r}")
    _require(data["vul"] in VULS, f"bad vul {data['vul']!r} (use {VULS})")

    auction = Auction.from_tokens(data["dealer"], [str(t) for t in data["auction"]])
    _require(len(auction.calls) >= 1, "auction must have at least one call")
    _require(auction.seat_of(len(auction.calls)) == data["my_seat"],
             "auction must end with my_seat to act")

    candidates = []
    for c in data["candidates"]:
        for k in ("call", "projection"):
            _require(k in c, f"candidate missing {k!r}")
        _require(isinstance(c["projection"], list) and c["projection"],
                 f"candidate {c['call']!r}: projection must be a non-empty list")
        _require("else" in c["projection"][-1],
                 f"candidate {c['call']!r}: projection must end with an 'else'")
        candidates.append(CandidateAction(
            call=str(c["call"]),
            label=str(c.get("label", c["call"])),
            projection=c["projection"],
        ))
    _require(len(candidates) >= 2, "need at least two candidate actions")
    _require(len({c.call for c in candidates}) == len(candidates),
             "duplicate candidate calls")

    return BiddingProblem(
        id=str(data["id"]),
        title=str(data["title"]),
        description=str(data.get("description", "")),
        dealer=data["dealer"],
        vul=data["vul"],
        my_seat=data["my_seat"],
        my_hand=str(data["my_hand"]),
        auction=auction,
        our_system=_system(data["our_system"], "our_system"),
        opps_system=_system(data["opps_system"], "opps_system"),
        candidates=candidates,
        n_deals=int(data.get("n_deals", 800)),
        breakdowns=list(data.get("breakdowns", [])),
        category=str(data.get("category", "")),
    )
