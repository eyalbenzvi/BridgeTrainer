"""Mode-aware metrics and ranking for opening-lead problems.

The Opening Lead Trainer has exactly TWO training modes:

  ``MP``  (Matchpoints) — rank leads by highest EXPECTED DEFENSIVE TRICKS.
  ``IMP``               — rank leads by highest EXPECTED IMP VALUE, derived
                          from the final duplicate score.

Both modes are computed from the SAME shared evidence — the per-sample
double-dummy defensive-trick arrays the existing deal-generation /
auction-consistency / DD pipeline already produces (``engine.lead_evaluate``).
Only the ranking objective differs; every candidate lead always carries all
four aggregate metrics (expected defensive tricks, expected duplicate score,
expected IMP value, set probability) regardless of mode.

IMP baseline
------------
Converting a duplicate score to IMPs needs a reference score. No IMP baseline
existed for lead problems before ``LEAD_ALGO_VERSION`` 2 (leads were graded on
tricks only; the bidding pipeline compares candidate CALLS pairwise, which has
no analogue for a 13-way lead choice), so the centralized, configurable
baseline below was introduced:

  ``datum_mean_v1`` — a Butler-style datum. On each sampled layout the
  baseline score is the MEAN defender score across all candidate leads on
  that same layout; a lead's per-sample IMP value is
  ``imps(lead_score - datum)`` and its expected IMP value is the (weighted)
  mean over samples.

To swap the baseline, change ``LEAD_IMP_BASELINE`` (and bump its ``version``)
or pass an explicit ``baseline=`` to :func:`compute_lead_metrics`; the chosen
baseline metadata is persisted with every evaluation so stored records stay
self-describing.
"""
from __future__ import annotations

import numpy as np

from .tables import contract_score, imps_array

# ---- the two training modes -------------------------------------------------
MODE_MP = "MP"
MODE_IMP = "IMP"
TRAINING_MODES = (MODE_MP, MODE_IMP)

# ranking objective per mode; the ONLY thing that differs between modes
RANKING_METRICS = {MODE_MP: "exp_def_tricks", MODE_IMP: "exp_imps"}

MODE_GOALS = {
    MODE_MP: "Goal: maximize expected defensive tricks.",
    MODE_IMP: "Goal: maximize expected IMP value from the final score.",
}

# Bump when the evaluation/ranking algorithm changes shape or semantics.
# Version 1 = legacy tricks-only grading (records without a `training` block).
LEAD_ALGO_VERSION = 2

# The one centralized IMP baseline (see module docstring).
LEAD_IMP_BASELINE = {
    "id": "datum_mean_v1",
    "version": 1,
    "description": "Butler-style datum: per-sample mean defender score "
                   "across all candidate leads on the same layout.",
}

# Cards within these of the mode maximum count as tied-best for that mode.
TIE_EPS_MP = 0.05    # defensive tricks (matches lead_verdict.TIE_EPS)
TIE_EPS_IMP = 0.05   # IMPs

SUITS = "SHDC"
_RANK_ORDER = "AKQJT98765432"


def declarer_vulnerable(vul: str, declarer: str) -> bool:
    """Is the declaring side vulnerable? ``vul`` is the stored name
    ("None" / "NS" / "EW" / "Both"/"All"); ``declarer`` a seat letter."""
    v = str(vul or "None").replace("-", "")
    if v in ("Both", "All"):
        return True
    if v in ("NS", "EW"):
        return declarer in v
    return False


def parse_contract_full(contract: str) -> tuple[int, str, int, str]:
    """Split ``{level}{denom}{declarer}{doubled}`` (conventions.contract_str)
    into (level, denom, doubled_count, declarer): '4HE' -> (4, 'H', 0, 'E');
    '3NTWx' -> (3, 'NT', 1, 'W'); '6SSxx' -> (6, 'S', 2, 'S')."""
    level = int(contract[0])
    rest = contract[1:]
    doubled = 0
    if rest.endswith("xx"):
        doubled, rest = 2, rest[:-2]
    elif rest.endswith("x"):
        doubled, rest = 1, rest[:-1]
    return level, rest[:-1], doubled, rest[-1]


def defender_score_table(level: int, denom: str, doubled: int,
                         vul: bool) -> np.ndarray:
    """Duplicate score FROM THE DEFENDERS' SIDE for each possible number of
    defensive tricks 0..13, as a length-14 array (index = defensive tricks).
    Reuses the golden-tested ``contract_score``."""
    return np.array([-contract_score(level, denom, doubled, vul, 13 - d)
                     for d in range(14)], dtype=np.int64)


def per_sample_scores(def_tricks: dict, contract: str, vul: str) -> dict:
    """Per-sample defender duplicate scores for every candidate lead.

    ``def_tricks`` maps card -> per-sample array of DEFENSIVE tricks (all
    cards share one sample set). Trick counts are rounded to the nearest
    integer before table lookup (DD counts are integral; float storage must
    not truncate)."""
    level, denom, doubled, declarer = parse_contract_full(contract)
    table = defender_score_table(level, denom, doubled,
                                 declarer_vulnerable(vul, declarer))
    return {c: table[np.rint(np.asarray(t)).astype(np.int64)]
            for c, t in def_tricks.items()}


def per_sample_imps(def_tricks: dict, contract: str, vul: str,
                    baseline: dict = LEAD_IMP_BASELINE) -> dict:
    """Per-sample IMP value of every candidate lead against the centralized
    baseline (``datum_mean_v1``: on each layout, the mean defender score
    across all candidate leads). This is the evidence the IMP mode judges
    and ranks on — shape-compatible with ``def_tricks`` so the same verdict
    machinery works in either unit."""
    if baseline["id"] != LEAD_IMP_BASELINE["id"]:
        raise ValueError(f"unknown IMP baseline {baseline['id']!r}")
    scores = per_sample_scores(def_tricks, contract, vul)
    datum = np.mean(np.stack([scores[c] for c in scores]), axis=0)
    return {c: imps_array(s - datum).astype(np.float64)
            for c, s in scores.items()}


def compute_lead_metrics(def_tricks: dict, contract: str, vul: str,
                         weights=None,
                         baseline: dict = LEAD_IMP_BASELINE) -> dict:
    """Per-lead aggregate metrics from the shared per-sample DD evidence.

    ``def_tricks`` maps card -> per-sample array of DEFENSIVE tricks (all
    cards share one sample set); ``contract`` is the stored contract string
    (e.g. '4HE', '3NTWx'); ``vul`` the stored vulnerability name.

    Returns {card: {exp_def_tricks, exp_score, exp_imps, set_prob}}. Only
    the ``datum_mean_v1`` baseline is implemented; passing an unknown
    baseline id raises rather than silently mis-scoring.
    """
    level = parse_contract_full(contract)[0]
    cards = list(def_tricks)
    n = np.asarray(def_tricks[cards[0]]).shape[0]
    if weights is None:
        w = np.full(n, 1.0 / n)
    else:
        w = np.asarray(weights, dtype=np.float64)
        w = w / w.sum()
    scores = per_sample_scores(def_tricks, contract, vul)
    imps = per_sample_imps(def_tricks, contract, vul, baseline)
    to_set = 8 - level          # defensive tricks needed to beat the contract
    out = {}
    for c in cards:
        tr = np.asarray(def_tricks[c], dtype=np.float64)
        out[c] = {
            "exp_def_tricks": float(w @ tr),
            "exp_score": float(w @ scores[c]),
            "exp_imps": float(w @ imps[c]),
            "set_prob": float(w @ (tr >= to_set)),
        }
    return out


def _card_order(card: str) -> tuple[int, int]:
    """Stable suit-then-rank order (spades first, ace first) for tie-breaks."""
    return SUITS.index(card[0]), _RANK_ORDER.index(card[1])


def rank_leads(metrics: dict, mode: str) -> list[str]:
    """Cards best-first under the mode's objective, with DETERMINISTIC
    tie-breakers.

    MP ranks by expected defensive tricks; IMP ranks by expected IMP value
    (never by tricks — its tie-breaker is the expected duplicate score, a
    score-domain quantity). Final tie-break is fixed card order, so equal
    inputs always produce identical rankings.
    """
    if mode not in TRAINING_MODES:
        raise ValueError(f"unknown training mode {mode!r}")
    primary = RANKING_METRICS[mode]
    secondary = "exp_score"

    def key(card: str):
        m = metrics[card]
        return (-m[primary], -m[secondary], *_card_order(card))

    return sorted(metrics, key=key)


def accepted_set(metrics: dict, mode: str) -> list[str]:
    """Cards tied for best under the mode's objective (within the mode's
    tie epsilon), in ranking order."""
    ranking = rank_leads(metrics, mode)
    primary = RANKING_METRICS[mode]
    eps = TIE_EPS_MP if mode == MODE_MP else TIE_EPS_IMP
    best = metrics[ranking[0]][primary]
    return [c for c in ranking if metrics[c][primary] >= best - eps]


def mode_rankings(metrics: dict) -> dict:
    """Per-mode ranking summary: recommended card, tied-accepted set, the
    ranking metric name, and a card -> 1-based rank map."""
    out = {}
    for mode in TRAINING_MODES:
        ranking = rank_leads(metrics, mode)
        out[mode] = {
            "ranking_metric": RANKING_METRICS[mode],
            "goal": MODE_GOALS[mode],
            "recommended": ranking[0],
            "accepted": accepted_set(metrics, mode),
            "rank": {c: i + 1 for i, c in enumerate(ranking)},
        }
    return out


def training_block(n_samples: int, sample_counts: dict | None = None,
                   target_mode: str = MODE_MP) -> dict:
    """The persisted evaluation/run metadata for a mode-aware lead record:
    algorithm version, the mode the board was FORGED for (whose gates
    selected it as interesting), per-mode ranking metric + goal, sample
    counts, and the IMP baseline metadata."""
    if target_mode not in TRAINING_MODES:
        raise ValueError(f"unknown training mode {target_mode!r}")
    return {
        "algorithm_version": LEAD_ALGO_VERSION,
        "target_mode": target_mode,
        "n_samples": n_samples,
        "sample_counts": sample_counts or {"confirm": n_samples},
        "modes": {
            MODE_MP: {"ranking_metric": RANKING_METRICS[MODE_MP],
                      "goal": MODE_GOALS[MODE_MP]},
            MODE_IMP: {"ranking_metric": RANKING_METRICS[MODE_IMP],
                       "goal": MODE_GOALS[MODE_IMP],
                       "imp_baseline": dict(LEAD_IMP_BASELINE)},
        },
    }


def legacy_training_block() -> dict:
    """Training metadata for pre-mode (algorithm version 1) lead records:
    tricks-only evidence, so only MP is supported. Written by the Firestore
    backfill so old documents stay readable and self-describing."""
    return {
        "algorithm_version": 1,
        "modes": {
            MODE_MP: {"ranking_metric": RANKING_METRICS[MODE_MP],
                      "goal": MODE_GOALS[MODE_MP]},
        },
    }


def supported_modes(rec: dict) -> list[str]:
    """Which training modes a stored lead record can serve. Legacy records
    (no ``training`` block, or one without IMP metadata) are MP-only —
    they carry no per-sample score evidence, and the old universal
    average-tricks ranking must never determine IMP recommendations."""
    modes = (rec.get("training") or {}).get("modes") or {}
    return [m for m in TRAINING_MODES if m in modes] or [MODE_MP]


def target_mode_of(rec: dict) -> str:
    """Which training mode a stored lead record was FORGED for — i.e. whose
    acceptance gates selected the board as interesting. Legacy and
    pre-split records were all selected by the tricks (MP) gates."""
    mode = (rec.get("training") or {}).get("target_mode", MODE_MP)
    return mode if mode in TRAINING_MODES else MODE_MP
