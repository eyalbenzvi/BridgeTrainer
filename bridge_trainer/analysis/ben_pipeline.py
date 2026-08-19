"""Ben-based analysis pipeline: ONE bridge brain for everything.

Per the owner's direction (DECISIONS.md §10): the hand-written system
tables, the rejection sampler's auction constraints and the heuristic
continuation agents are all replaced by the Ben engine (BEN-21GF) — the
same neural bidder that generates this project's practice problems:

  * layout sampling: Ben samples the hidden hands consistent with the
    auction AS BEN UNDERSTANDS IT (bot.sample_hands_for_auction);
  * candidates: Ben's own policy distribution at the decision point;
  * continuations: Ben bids ALL FOUR seats to completion on every sampled
    layout for every candidate (bidding_rollout) — real auctions, not
    heuristics;
  * scoring: double-dummy on each rollout's final contract, hero-positive
    duplicate scores, all candidates paired on identical layouts (INV1).

The statistics/report layers are reused unchanged: per-sample scores feed
scoring.comparison.compare_candidates, and the report renders from the
same facts structure (single policy entry keyed "realistic", labeled Ben).

Honesty notes surfaced in the report:
  * Ben's sampler `quality` (0..1) measures how consistent the sampled
    worlds are with the entered auction under Ben's system — a LOW value
    means the auction contains calls Ben's system reads differently
    (special agreements, off-system style) and the analysis is degraded;
  * scores are raw double-dummy at the rollout contract (no single-dummy
    smear on this path);
  * Ben's own choice at the decision point is printed as an anchor.

Requires the external Ben checkout (BEN_HOME; scripts/setup_ben.sh).
"""
from __future__ import annotations

import os
import time
from collections import Counter

import numpy as np

from ..domain.auction import SEATS, partner_of
from ..scoring.comparison import compare_candidates
from ..scoring.stats import weighted_ci
from ..validate.auction_state import replay
from .pipeline import (AnalysisRequest, AnalysisResult, PolicyOutcome,
                       RepresentativeDeal, TOSS_UP_PRECISION_IMPS,
                       _mp_percent, _validate)
from .systems.interpreter import CallMeaning

BLOCK_SAMPLES = 200
MAX_SAMPLES = 1600
SAMPLE_TIME_BUDGET_S = 420   # stop extending past this; Cloud Run kills the
                             # request at 900s and Eventarc would redeliver
MENU_P_FLOOR = 0.02      # forge's P_OPTION: policy mass that earns a seat
MENU_MAX = 6
QUALITY_WARN = 0.8       # sampler-quality thresholds for report warnings
QUALITY_BAD = 0.5
BEN_POLICY_KEY = "realistic"   # facts slot the report treats as primary

_ENGINE = None


def _should_stop(mean: float, half: float, n: int) -> bool:
    """Sequential stop WITHOUT the first-crossing bias.

    Stopping the moment ``mean > half`` inflates borderline verdicts: on a
    true near-zero difference the loop halts on whichever side drifts up
    first and reports an edge the size of the CI (a shipped report showed
    the exact signature, +0.43 against ±0.40). Stop only on a precision
    target, or on clear dominance (mean > 2*CI, a ~4-sigma boundary that
    first-crossing barely biases) once the sample is respectable.
    """
    if half <= TOSS_UP_PRECISION_IMPS:
        return True
    return n >= 3 * BLOCK_SAMPLES and mean > 2.0 * half


MAX_EXTRA_CANDIDATES = 4
MENU_FILL_FLOOR = 0.001   # only pure numeric noise stays out of the menu
MAX_PLANS = 6


def _menu_from_policy(policy) -> list[str]:
    """Owner spec (round 5): evaluate the next-ranked calls too, up to
    MENU_MAX — the 2% floor no longer gates EVALUATION (a 0.9% 3NT over a
    preempt must be measured), it only decides which candidates the report
    gives a summary card. The fill floor keeps <0.1% numeric noise out."""
    return [it.bid for it in policy if it.p >= MENU_FILL_FLOOR][:MENU_MAX]


def _plans_by_candidate(triples) -> dict[str, dict[str, str]]:
    """[[candidate, partner_reply, my_call], ...] -> {cand: {reply: my}}.
    First rule wins on duplicate (cand, reply) pairs; bounded by MAX_PLANS."""
    plans: dict[str, dict[str, str]] = {}
    for row in list(triples or [])[:MAX_PLANS]:
        if not isinstance(row, (list, tuple)) or len(row) != 3:
            continue
        cand, reply, mine = (str(t).upper()[:3] for t in row)
        plans.setdefault(cand, {}).setdefault(reply, mine)
    return plans


def _with_extras(candidates: list[str], extras, state) -> tuple[list, list]:
    """Union the user's must-test calls into the engine menu.

    The menu is Ben's policy over the floor, so a call Ben's style shuns
    (a 0.9% 3NT over a preempt, say) never gets evaluated even when it is
    a mainstream expert choice. The rollout layer doesn't care whether the
    policy likes the call — it forces it and continues all four hands — so
    letting the user seat extra candidates is sound. Returns the widened
    menu and which extras actually joined (legal, non-duplicate)."""
    out = list(candidates)
    added = []
    for tok in list(extras or [])[:MAX_EXTRA_CANDIDATES]:
        tok = str(tok).upper()
        if tok not in out and state.is_legal(tok):
            out.append(tok)
            added.append(tok)
    return out, added


def ben_available() -> bool:
    home = os.environ.get("BEN_HOME", os.path.expanduser("~/ben"))
    return os.path.isdir(os.path.join(home, "src"))


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from ..engine.ben import get_engine
        _ENGINE = get_engine()
    return _ENGINE


def _vul_tuple(vul: str) -> tuple:
    return (vul in ("NS", "Both"), vul in ("EW", "Both"))


def _contract_display(ben_contract: str) -> str:
    """Ben 'get_contract' format ('4SXE', '3NN', 'PASS') -> my display
    format ('4SEx', '3NTN', 'Pass-out')."""
    if ben_contract in ("PASS", None, ""):
        return "Pass-out"
    level, strain = ben_contract[0], ben_contract[1]
    declarer = ben_contract[-1]
    doubled = "X" in ben_contract[2:-1]   # '', 'X' or 'XX' between them
    denom = "NT" if strain == "N" else strain
    return f"{level}{denom}{declarer}{'x' if doubled else ''}"


def _auction_tokens(auction_str: str) -> list[str]:
    return auction_str.split()


def _first_partner_call(tokens: list[str], dealer_i: int, stem_len: int,
                        partner_seat: str) -> str:
    for idx in range(stem_len + 1, len(tokens)):
        if SEATS[(dealer_i + idx) % 4] == partner_seat:
            return tokens[idx]
    return "—"


def _continuation_pairs(tokens: list[str], dealer_i: int,
                        stem_len: int) -> list:
    pairs = [[SEATS[(dealer_i + i) % 4], tokens[i]]
             for i in range(stem_len + 1, len(tokens))]
    while pairs and pairs[-1][1] == "P":
        pairs.pop()
    return pairs


def _freqs(items: list[str], top_k: int = 6) -> list:
    n = len(items) or 1
    return [(tok, round(c / n, 4))
            for tok, c in Counter(items).most_common(top_k)]


def _concat_batches(a, b):
    """Two Evaluations of the SAME candidates on DIFFERENT sample batches,
    concatenated row-wise (adaptive sampling across fresh Ben draws)."""
    from ..engine.ben import Evaluation
    assert list(a.bids) == list(b.bids)
    n = a.n_samples + b.n_samples
    return Evaluation(
        bids=list(a.bids),
        ev={c: np.concatenate([np.asarray(a.ev[c]), np.asarray(b.ev[c])])
            for c in a.bids},
        contracts={c: list(a.contracts[c]) + list(b.contracts[c])
                   for c in a.bids},
        auctions={c: list(a.auctions[c]) + list(b.auctions[c])
                  for c in a.bids},
        n_samples=n,
        quality=(a.quality * a.n_samples + b.quality * b.n_samples) / n,
        sample_deals=list(a.sample_deals) + list(b.sample_deals),
        plan_hits={k: a.plan_hits.get(k, 0) + b.plan_hits.get(k, 0)
                   for k in set(a.plan_hits) | set(b.plan_hits)})


def run_analysis_ben(req: AnalysisRequest, progress=None) -> AnalysisResult:
    """The Ben-powered analysis. Same request/result surface as the legacy
    pipeline; `system`/`overrides` fields are accepted and ignored (the
    owner removed those inputs — Ben's system defines the meanings)."""
    t0 = time.perf_counter()
    _validate(req)
    if not ben_available():
        raise RuntimeError(
            "Ben engine not installed (BEN_HOME) — run scripts/setup_ben.sh")
    engine = _engine()

    stem = req.auction[:req.decision_index]
    actual = (req.auction[req.decision_index]
              if req.decision_index < len(req.auction) else None)
    dealer_i = SEATS.index(req.dealer)
    hero_i = SEATS.index(req.my_seat)
    pard = partner_of(req.my_seat)
    bot = engine.bot(req.my_hand, hero_i, dealer_i, _vul_tuple(req.vul))

    # -- candidates: Ben's own policy at the decision point ---------------
    policy = engine.policy_full(bot, dealer_i, stem)
    ben_top = policy[0].bid if policy else "P"
    ben_top_p = float(policy[0].p) if policy else 0.0
    if req.candidates:
        candidates = list(req.candidates)
    else:
        candidates = _menu_from_policy(policy)
        if len(candidates) < 2:
            for extra in ("P", "X"):
                st = replay(req.dealer, stem)
                if extra not in candidates and st.is_legal(extra):
                    candidates.append(extra)
                if len(candidates) >= 2:
                    break
    if actual is not None and actual not in candidates:
        candidates = [actual] + candidates
    state = replay(req.dealer, stem)
    plans = _plans_by_candidate(req.plans)
    # a plan's candidate must be evaluated even if the menu skipped it —
    # planned candidates outrank plain extras for the extras cap
    extras_wanted = [c for c in plans if c not in candidates] + \
        list(req.extra_candidates or [])
    candidates, user_added = _with_extras(candidates, extras_wanted, state)
    candidates = [c for c in candidates if state.is_legal(c)]
    if not candidates:
        raise ValueError("no legal candidate actions at the decision point")

    # -- adaptive evaluation: concatenated Ben batches until the CI settles
    # (engine.merge_evaluations merges CANDIDATES on one sample set; here we
    # concatenate fresh sample BATCHES of the same candidates instead)
    #
    # Ben reseeds its sampler from hash(hero hand) on EVERY
    # sample_hands_for_auction call ("same situation -> same result" by
    # design), so seeding numpy's global RNG between batches changes
    # nothing: every batch would duplicate the first, and the CI would
    # shrink by 1/sqrt(k) on fabricated data. The batch loop must therefore
    # vary bot.hash_integer itself — that is the seed Ben's
    # get_random_generator() actually reads.
    dd_memo: dict = {}
    merged = None
    stopped_early = False
    base_hash = int(bot.hash_integer)
    batch_i = 0
    while merged is None or (merged.n_samples < MAX_SAMPLES
                             and time.perf_counter() - t0
                             < SAMPLE_TIME_BUDGET_S):
        bot.hash_integer = (base_hash + req.seed + 7919 * batch_i) % (2 ** 31)
        batch_i += 1
        batch = engine.evaluate(bot, dealer_i, stem, candidates,
                                n_samples=BLOCK_SAMPLES, dd_memo=dd_memo,
                                plans=plans or None)
        merged = batch if merged is None else _concat_batches(merged, batch)
        if progress:
            progress(merged.n_samples, MAX_SAMPLES)
        if merged.n_samples >= 2 * BLOCK_SAMPLES or merged.n_samples >= 300:
            weights = np.ones(merged.n_samples)
            cmp_probe = compare_candidates(
                {c: merged.ev[c] for c in candidates}, weights)
            top = cmp_probe.candidates[0]
            diff = cmp_probe.imp_matrix[(top.action, top.best_alternative)]
            mean, half, _ = weighted_ci(diff, weights)
            if _should_stop(mean, half, merged.n_samples):
                stopped_early = merged.n_samples < MAX_SAMPLES
                break
    bot.hash_integer = base_hash

    n = merged.n_samples
    weights = np.ones(n)
    scores = {c: np.asarray(merged.ev[c], dtype=float) for c in candidates}
    cmp_res = compare_candidates(scores, weights)
    mp_pct = _mp_percent(scores, weights)

    stem_len = len(stem)
    contract_freqs, resp_freqs, cont_tokens = {}, {}, {}
    for c in candidates:
        contract_freqs[c] = _freqs(
            [_contract_display(x) for x in merged.contracts[c]])
        toks = [_auction_tokens(a) for a in merged.auctions[c]]
        cont_tokens[c] = toks
        resp_freqs[c] = _freqs(
            [_first_partner_call(t, dealer_i, stem_len, pard) for t in toks])

    top_action = (max(mp_pct, key=mp_pct.get) if req.scoring == "MP"
                  else cmp_res.candidates[0].action)
    outcome = PolicyOutcome(
        policy=BEN_POLICY_KEY,
        he="מנוע Ben",
        he_desc="דגימה, הכרזות המשך של כל ארבעת המושבים וניקוד — כולם "
                "על ידי מנוע ההכרזות הנוירוני של הפרויקט",
        raw=cmp_res, corrected=cmp_res, mp_pct=mp_pct,
        contract_freqs=contract_freqs, partner_response_freqs=resp_freqs,
        top_action=top_action)

    # -- report metadata ----------------------------------------------------
    consistency = float(merged.quality)
    notes = [f"בנקודת ההחלטה המנוע עצמו היה בוחר {ben_top} "
             f"(הסתברות {ben_top_p * 100:.0f}%)."]
    pol_p = {it.bid: float(it.p) for it in policy}
    if user_added:
        for tok in user_added:
            notes.append(
                f"מועמד שהוספת לבדיקה: {tok} — במדיניות Ben הוא מקבל "
                f"{pol_p.get(tok, 0.0) * 100:.1f}% בנקודת ההחלטה; "
                f"ההערכה בסימולציה זהה לשאר המועמדים (המשך מלא של "
                f"כל ארבע הידיים).")
    for key, hit_n in sorted((merged.plan_hits or {}).items()):
        cand_tok, rule = key.split("|", 1)
        reply, mine = rule.split("->", 1)
        notes.append(
            f"תוכנית המשך שהגדרת ל-{cand_tok}: אחרי {reply} מהשותף "
            f"הוכרז {mine} במקום בחירת Ben — הופעלה ב-{hit_n} מתוך "
            f"{n} חלוקות (בשאר לא התקיים התנאי או שההכרזה לא "
            f"הייתה חוקית).")
    stability_note = (
        f"התאמת המכרז לשיטת המנוע: {consistency * 100:.0f}%. "
        "ההמשכים בכל חלוקה הוכרזו על ידי Ben עבור כל ארבעת המושבים עד "
        "סוף המכרז — ללא חוקים ידניים.")

    meanings = [CallMeaning(index=i, seat=SEATS[(dealer_i + i) % 4],
                            token=tok, key="ben", he="", constraints=None)
                for i, tok in enumerate(req.auction)]

    top = cmp_res.candidates[0]
    second = top.best_alternative
    diff = cmp_res.imp_matrix[(top.action, second)]
    mean, half, ess = weighted_ci(diff, weights)

    reps = _representatives_ben(req, merged, cmp_res, dealer_i, stem_len,
                                cont_tokens)

    return AnalysisResult(
        request=req, stem=stem, actual_call=actual, candidates=candidates,
        meanings=meanings, transparency_notes=notes,
        policies={BEN_POLICY_KEY: outcome},
        stable=consistency >= QUALITY_WARN, stability_note=stability_note,
        recommended=top_action, n_deals=n, ess=float(ess or n),
        acceptance_rate=consistency, shortfall=0, ci_widen=1.0,
        stopped_early=stopped_early, top_pair=(top.action, second),
        top_pair_mean_imp=mean, top_pair_ci=half,
        representative=reps, elapsed_s=time.perf_counter() - t0,
        seed=req.seed, in_dd_fog=False,
        ben_prior={c: pol_p.get(c, 0.0) for c in candidates},
        user_added=list(user_added))


def _representatives_ben(req, merged, cmp_res, dealer_i, stem_len,
                         cont_tokens, big_loss=-5.0) -> list:
    """Typical / best / failure / disaster layouts with Ben's actual
    rollout continuation for each (spec 3.5)."""
    top = cmp_res.candidates[0]
    rec, alt = top.action, top.best_alternative
    diff = cmp_res.imp_matrix[(rec, alt)]
    n = min(len(diff), len(merged.sample_deals))
    order = np.argsort(diff[:n])

    def q_index(q: float) -> int:
        return int(order[min(n - 1, max(0, round(q * (n - 1))))])

    # disaster is a low PERCENTILE, not the absolute worst sample: the
    # single min of a Monte-Carlo sample is statistically unstable and
    # preferentially surfaces the engine's rare rollout breakdowns (~1%
    # tails like a conventional cuebid the responder net fails to field),
    # which then headline the report while barely moving the means.
    picks = [("typical", q_index(0.5)), ("best", q_index(0.97)),
             ("failure", q_index(0.10))]
    disaster = q_index(0.02)
    if diff[disaster] <= big_loss:
        picks.append(("disaster", disaster))

    out, seen = [], set()
    for kind, i in picks:
        if i in seen:
            continue
        seen.add(i)
        row = merged.sample_deals[i].split()
        hands = {s: row[j] for j, s in enumerate(SEATS)}
        hands[req.my_seat] = req.my_hand   # Ben x-es pips; hero is known
        out.append(RepresentativeDeal(
            kind=kind, hands=hands, imp_swing=float(diff[i]),
            contract_top=_contract_display(merged.contracts[rec][i]),
            contract_alt=_contract_display(merged.contracts[alt][i]),
            score_top=float(merged.ev[rec][i]),
            score_alt=float(merged.ev[alt][i]),
            weight=1.0,
            cont_top=_continuation_pairs(cont_tokens[rec][i], dealer_i,
                                         stem_len),
            cont_alt=_continuation_pairs(cont_tokens[alt][i], dealer_i,
                                         stem_len)))
    return out
