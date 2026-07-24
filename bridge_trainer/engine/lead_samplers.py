"""Layout samplers for the opening-lead audit.

Every sampler takes ONLY a `LeadProblem` (public state) plus an integer seed
and returns a `LayoutSet`. None of them receives the hidden source deal, so
source-deal independence holds by construction; the offline samplers are also
deterministic in the seed.

Modes (owner requirement 6):

  * ``BenCurrentSampler``   the production thresholded-uniform neural-
                            consistency sampler (requires the Ben venv);
  * ``BenReplaySampler``    Ben exact replay — accept only complete deals whose
                            bidder reproduces every observed call (requires Ben);
  * ``UniformSampler``      a Ben-free, unconstrained, card-conserving baseline
                            — an HONEST non-posterior used for offline audit
                            plumbing and as a sampler-sensitivity counterpoint;
  * ``ConstraintSampler``   Ben-free; applies EXPLICIT accumulated auction
                            constraints (per-seat HCP / suit-length / suit-
                            quality / denial / exclusion bands, optionally
                            derived from the auction by the rule engine) as an
                            importance-weighted modelled prior;
  * ``SyntheticSampler``    explicit layouts/scores for tests and fixtures.

Ben-likelihood weighting and a formal-rule sampler are provided only where
their prerequisites genuinely exist (see the module docstrings); they are not
faked.
"""
from __future__ import annotations

import hashlib

import numpy as np

from .lead_posterior import (
    RANKS, SEATS, SUITS, LayoutSet, LeadProblem,
    CALIBRATION_UNCALIBRATED, SAMPLING_MODEL_CURRENT, WEIGHTING_UNIFORM,
    BEN_BIDDING_THRESHOLD_DEFAULT, problem_fingerprint)

SAMPLER_VERSION = "lead-posterior-audit/1"


def _cards(pbn: str) -> list:
    out = []
    for suit, holding in zip(SUITS, pbn.split(".")):
        out.extend(suit + r for r in holding)
    return out


def _pbn(cards) -> str:
    by = {s: [] for s in SUITS}
    for c in cards:
        by[c[0]].append(c[1])
    order = {r: i for i, r in enumerate(RANKS)}
    return ".".join("".join(sorted(by[s], key=lambda r: order[r]))
                    for s in SUITS)


def _seed_int(problem: LeadProblem, seed: int) -> int:
    h = hashlib.sha256(f"{problem_fingerprint(problem, seed)}".encode())
    return int.from_bytes(h.digest()[:8], "big")


class UniformSampler:
    """Unconstrained card-conserving uniform completions of the leader hand.

    Deals the 39 unseen cards uniformly at random into the other three seats
    (13 each). It applies NO auction constraint, so it is NOT the production
    distribution and NOT a posterior — its labels say exactly that. It exists
    so the audit machinery runs end-to-end on real DDS without Ben, and as a
    deliberate sampler-sensitivity baseline (its ranking SHOULD differ from a
    bidding-aware sampler on real boards).
    """
    sampling_model = "uniform_unconstrained"
    posterior_calibration_status = "not_a_posterior"

    def sample(self, problem: LeadProblem, requested: int, seed: int) -> LayoutSet:
        rng = np.random.default_rng(_seed_int(problem, seed))
        lead = problem.leader
        others = [s for s in SEATS if s != lead]
        leadcards = set(_cards(problem.hand))
        unseen = [s + r for s in SUITS for r in RANKS if s + r not in leadcards]
        hands = []
        for _ in range(requested):
            deck = list(unseen)
            rng.shuffle(deck)
            hd = {lead: problem.hand}
            for k, seat in enumerate(others):
                hd[seat] = _pbn(deck[k * 13:(k + 1) * 13])
            hands.append(hd)
        n = len(hands)
        return LayoutSet(
            problem=problem, hands=hands,
            bidding_score=np.ones(n), weight=np.ones(n),
            sampling_model=self.sampling_model, sampler_version=SAMPLER_VERSION,
            posterior_calibration_status=self.posterior_calibration_status,
            weighting_method=WEIGHTING_UNIFORM, score_threshold=None,
            proposal_count=n, requested_samples=requested, accepted_samples=n,
            seed=seed, auction_replay_mode="none",
            semantic_constraint_mode="none", source_deal_independent=True)


class SyntheticSampler:
    """Build a LayoutSet from explicit hands/scores/weights (tests, fixtures).

    `layouts` is a list of {seat: pbn}; `scores`/`weights` default to ones.
    Lets a test construct tail-dominated or sampler-sensitive scenarios with
    exact control while still exercising the real invariant checks.
    """
    def __init__(self, layouts, scores=None, weights=None,
                 sampling_model="synthetic",
                 posterior_calibration_status="synthetic",
                 weighting_method=WEIGHTING_UNIFORM, score_threshold=None):
        self.layouts = layouts
        self.scores = scores
        self.weights = weights
        self.sampling_model = sampling_model
        self.posterior_calibration_status = posterior_calibration_status
        self.weighting_method = weighting_method
        self.score_threshold = score_threshold

    def sample(self, problem: LeadProblem, requested: int, seed: int) -> LayoutSet:
        n = len(self.layouts)
        scores = np.ones(n) if self.scores is None else np.asarray(self.scores, float)
        weights = np.ones(n) if self.weights is None else np.asarray(self.weights, float)
        return LayoutSet(
            problem=problem, hands=list(self.layouts),
            bidding_score=scores, weight=weights,
            sampling_model=self.sampling_model, sampler_version=SAMPLER_VERSION,
            posterior_calibration_status=self.posterior_calibration_status,
            weighting_method=self.weighting_method,
            score_threshold=self.score_threshold,
            proposal_count=n, requested_samples=requested, accepted_samples=n,
            seed=seed, source_deal_independent=True)


class FixtureSampler(SyntheticSampler):
    """Load a LayoutSet from a JSON fixture captured once from a real sampler.

    Fixture schema: {"sampling_model":..., "score_threshold":...,
    "layouts":[{"N":pbn,...}], "scores":[...], "weights":[...]}. Sampled full
    deals belong ONLY in such audit/debug fixtures, never in normal UI output.
    """
    @classmethod
    def from_json(cls, path):
        import json
        with open(path) as f:
            d = json.load(f)
        return cls(
            layouts=d["layouts"], scores=d.get("scores"),
            weights=d.get("weights"),
            sampling_model=d.get("sampling_model", "fixture"),
            posterior_calibration_status=d.get("posterior_calibration_status",
                                               "fixture"),
            weighting_method=d.get("weighting_method", WEIGHTING_UNIFORM),
            score_threshold=d.get("score_threshold"))


class BenCurrentSampler:
    """Adapter over the production Ben opening-lead sampler.

    This is the REAL pipeline the audit is about: propose full deals
    consistent with the leader hand, score each by neural bidding-consistency,
    accept those with score >= ``threshold`` (Ben's ``bidding_threshold_
    sampling``), and average double-dummy tricks uniformly over the accepted
    set. It requires the Ben venv (BEN_HOME); without it, ``sample`` raises a
    clear error rather than fabricating layouts. Honest labels are baked in:
    ``thresholded_uniform_neural_consistency`` / ``uncalibrated`` /
    ``uniform_over_accepted``.
    """
    sampling_model = SAMPLING_MODEL_CURRENT
    posterior_calibration_status = CALIBRATION_UNCALIBRATED

    def __init__(self, engine=None, threshold: float = BEN_BIDDING_THRESHOLD_DEFAULT):
        self.engine = engine
        self.threshold = threshold

    def _get_engine(self):
        if self.engine is not None:
            return self.engine
        from .ben import get_engine
        return get_engine()

    def sample(self, problem: LeadProblem, requested: int, seed: int) -> LayoutSet:
        engine = self._get_engine()
        # Set Ben's acceptance threshold for THIS run (the owner's swept knob).
        prev = getattr(engine.sampler, "bidding_threshold_sampling", None)
        engine.sampler.bidding_threshold_sampling = self.threshold
        try:
            layouts, scores, proposals = _ben_sample_layouts(
                engine, problem, requested)
        finally:
            if prev is not None:
                engine.sampler.bidding_threshold_sampling = prev
        n = len(layouts)
        return LayoutSet(
            problem=problem, hands=layouts,
            bidding_score=np.asarray(scores, float), weight=np.ones(n),
            sampling_model=self.sampling_model, sampler_version=SAMPLER_VERSION,
            posterior_calibration_status=self.posterior_calibration_status,
            weighting_method=WEIGHTING_UNIFORM, score_threshold=self.threshold,
            proposal_count=proposals, requested_samples=requested,
            accepted_samples=n, seed=seed, auction_replay_mode="none",
            semantic_constraint_mode="none",
            # Ben seeds its sampler from calculate_seed(hand_str) — a function of
            # the LEADER HAND ONLY — and lead_evaluate never receives the source
            # hands, so the accepted set is independent of the source deal.
            source_deal_independent=True)


def _ben_sample_layouts(engine, problem: LeadProblem, requested: int):
    """Extract accepted full deals + bidding scores from Ben's opening-lead
    sampler for one problem. Isolated so the (Ben-only) surface is one call.

    Mirrors engine.lead_open's sampling block but returns the assembled 4-hand
    layouts (leader hand + the three sampled hands) and each deal's bidding
    score, so the audit can double-dummy them with endplay independently of
    Ben's own DD path.
    """
    from bidding import bidding as bb  # noqa: F401  (Ben import; venv only)
    import deck52

    dealer_i = SEATS.index(problem.dealer)
    leader_i = problem.leader_i()
    vuln = _vuln_tuple(problem.vul, leader_i)
    padded = _pad(dealer_i, list(problem.auction))
    bot = engine.lead_bot(problem.hand, leader_i, dealer_i, vuln)
    ben_contract = bb.get_contract(padded)
    decl_i = bb.get_decl_i(ben_contract)
    lead_index = (decl_i + 1) % 4
    bot.rng = bot.get_random_generator()
    saved = engine.sampler.sample_hands_opening_lead
    engine.sampler.sample_hands_opening_lead = requested
    try:
        accepted, scores, _ph, _psh, _q, proposals = \
            engine.sampler.generate_samples_iterative(
                padded, lead_index,
                engine.sampler.sample_boards_for_auction_opening_lead,
                engine.sampler.sample_hands_opening_lead,
                bot.rng, bot.hand_str, bot.vuln, engine.models, [], {})
    finally:
        engine.sampler.sample_hands_opening_lead = saved

    n = int(accepted.shape[0]) if hasattr(accepted, "shape") else 0
    layouts = []
    nb = engine.models.n_cards_bidding
    for i in range(n):
        # accepted rows are the 3 unseen hands (LHO, partner, RHO) relative to
        # the leader, in Ben's 32-card space where low pips (2..7) are folded
        # into an 'x' bucket. Rebuild concrete, card-conserving 52-card hands by
        # expanding the placeholders with pips NOT held by the leader, exactly
        # as Ben's DD path does (deck52.convert_cards).
        others_xx = [deck52.handxxto52str(accepted[i][j], nb) for j in range(3)]
        card_string = problem.hand + " " + " ".join(others_xx)
        filled = deck52.convert_cards(
            card_string, _card52(problem.hand), problem.hand,
            bot.get_random_generator(), nb)
        parts = filled.split(" ")
        seats = {problem.leader: parts[0]}
        for k, seat_off in enumerate((1, 2, 3)):
            seats[SEATS[(leader_i + seat_off) % 4]] = parts[1 + k]
        layouts.append(seats)
    return layouts, list(np.asarray(scores, float)[:n]), int(proposals)


def _card52(hand_pbn: str) -> int:
    """52-index of the leader's first listed card (suit*13 + rank position,
    S,H,D,C / A..2). Any leader card is a safe `opening_lead` for convert_cards
    since its pip is already excluded via the leader hand string."""
    for suit_i, holding in enumerate(hand_pbn.split(".")):
        if holding:
            return suit_i * 13 + "AKQJT98765432".index(holding[0])
    return 0


def _pad(dealer_i: int, auction):
    def to_ben(t):
        return "PASS" if t == "P" else t.replace("NT", "N")
    return ["PAD_START"] * dealer_i + [to_ben(t) for t in auction]


def _vuln_tuple(vul: str, leader_i: int):
    ns = vul in ("NS", "Both", "All")
    ew = vul in ("EW", "Both", "All")
    # Ben BotLead expects [ns, ew] style; leader-relative not needed here.
    return (ns, ew)


def _ben_auction_scores(engine, problem: LeadProblem, layouts: list):
    """Per-layout (log-likelihood, exact-replay) of the OBSERVED auction under
    Ben's neural bidder run on each seat's sampled hand.

    For every call in the auction, the seat to act is scored with Ben's FULL
    per-legal-call softmax (`policy_full`, straight from the bidder's
    next_bid_np — a genuine per-legal-call probability). We accumulate
    log P(actual call) and track whether the bidder's argmax reproduces the
    actual call at every turn (exact replay). This is the independent audit
    signal for the replay and likelihood samplers.
    """
    dealer_i = SEATS.index(problem.dealer)
    auction = list(problem.auction)
    vuln = _vuln_tuple(problem.vul, 0)
    eps = 1e-6
    out = []
    for hd in layouts:
        bots = {}
        logL = 0.0
        exact = True
        for t, actual in enumerate(auction):
            seat_i = (dealer_i + t) % 4
            if seat_i not in bots:
                bots[seat_i] = engine.bot(hd[SEATS[seat_i]], seat_i, dealer_i,
                                          vuln)
            pol = engine.policy_full(bots[seat_i], dealer_i, auction[:t])
            if not pol:
                exact = False
                logL += np.log(eps)
                continue
            pmap = {it.bid: it.p for it in pol}
            p = pmap.get(actual, 0.0)
            logL += float(np.log(max(p, eps)))
            if pol[0].bid != actual:
                exact = False
        out.append((logL, exact))
    return out


class BenReplaySampler:
    """Exact Ben auction-replay audit sampler (owner requirement 2/6).

    Proposal: Ben's binfo-guided pool at a permissive threshold (broad but
    auction-plausible). Acceptance: keep a complete deal ONLY if Ben's bidder,
    run on those hands, reproduces EVERY observed call as its argmax
    (`replay_exact_mask`). Independent of the production consistency score, so
    it is a genuine cross-check. Weighting uniform over the exact-replay set.
    """
    sampling_model = "ben_exact_auction_replay"
    posterior_calibration_status = "exact_replay_filter"

    def __init__(self, engine=None, pool_threshold: float = 0.30,
                 pool_multiplier: int = 3):
        self.engine = engine
        self.pool_threshold = pool_threshold
        self.pool_multiplier = pool_multiplier

    def sample(self, problem, requested, seed):
        from .lead_posterior import replay_exact_mask
        engine = self.engine or _default_engine()
        pool = BenCurrentSampler(engine=engine, threshold=self.pool_threshold)
        ls = pool.sample(problem, requested * self.pool_multiplier, seed)
        scores = _ben_auction_scores(engine, problem, ls.hands)
        reproduced = np.array([[[ex]] for (_lg, ex) in scores])  # (n,1,1) bool
        mask = replay_exact_mask(reproduced)
        hands = [ls.hands[i] for i in range(len(ls.hands)) if mask[i]]
        n = len(hands)
        return LayoutSet(
            problem=problem, hands=hands,
            bidding_score=np.ones(n), weight=np.ones(n),
            sampling_model=self.sampling_model, sampler_version=SAMPLER_VERSION,
            posterior_calibration_status=self.posterior_calibration_status,
            weighting_method="uniform_over_exact_replay", score_threshold=None,
            proposal_count=ls.n, requested_samples=requested,
            accepted_samples=n, seed=seed,
            auction_replay_mode="exact", semantic_constraint_mode="none",
            source_deal_independent=True)


class BenLikelihoodSampler:
    """Auction-likelihood-weighted audit sampler (owner requirement 2).

    Proposal: Ben's binfo-guided pool. Weight: self-normalized via stable
    log-sum-exp of the observed auction's log-likelihood under Ben's per-call
    softmax (`likelihood_log_weights`), with ESS reported. Honestly labelled:
    the proposal is binfo-guided (not uniform), so the weights are auction-
    likelihood importance weights, not a calibrated posterior; ESS states how
    usable they are.
    """
    sampling_model = "ben_auction_likelihood_weighted"
    posterior_calibration_status = "importance_weighted_uncalibrated"

    def __init__(self, engine=None, pool_threshold: float = 0.30,
                 pool_multiplier: int = 2):
        self.engine = engine
        self.pool_threshold = pool_threshold
        self.pool_multiplier = pool_multiplier

    def sample(self, problem, requested, seed):
        from .lead_posterior import likelihood_log_weights
        engine = self.engine or _default_engine()
        pool = BenCurrentSampler(engine=engine, threshold=self.pool_threshold)
        ls = pool.sample(problem, requested * self.pool_multiplier, seed)
        scores = _ben_auction_scores(engine, problem, ls.hands)
        logL = np.array([lg for (lg, _ex) in scores])
        weights, _ess = likelihood_log_weights(logL)
        return LayoutSet(
            problem=problem, hands=list(ls.hands),
            bidding_score=logL, weight=weights,
            sampling_model=self.sampling_model, sampler_version=SAMPLER_VERSION,
            posterior_calibration_status=self.posterior_calibration_status,
            weighting_method="auction_likelihood_logsumexp",
            score_threshold=None, proposal_count=ls.n,
            requested_samples=requested, accepted_samples=len(ls.hands),
            seed=seed, auction_replay_mode="none",
            semantic_constraint_mode="none", source_deal_independent=True)


def _default_engine():
    from .ben import get_engine
    return get_engine()


# ---------------------------------------------------------------------------
# explicit auction-constraint sampler (owner requirement 3, first bullet)
# ---------------------------------------------------------------------------
def _pbn_to_seats(pbn: str) -> dict:
    """'N:874.AQ94.T.97642 KT652... ...' -> {'N':..,'E':..,'S':..,'W':..}."""
    body = pbn.split(":", 1)[1] if ":" in pbn else pbn
    parts = body.strip().split()
    return {SEATS[i]: parts[i] for i in range(4)}


DEFAULT_RULESETS = ("our_2over1.yaml", "opps_sound.yaml")


def constraint_profile_from_auction(problem: LeadProblem,
                                    our_ruleset: str | None = None,
                                    opps_ruleset: str | None = None):
    """Derive an accumulated per-seat ConstraintProfile from the PUBLIC auction
    via the existing rule engine (owner requirement 3, first bullet).

    The rule engine walks every concealed call — including passes — and merges
    each recognised call's soft HCP/suit-length/suit-quality/denial/exclusion
    constraints into that seat's profile (conjunction => weights multiply).
    Calls with no matching rule degrade GRACEFULLY: known constraints still
    apply and the gap is surfaced in `unrecognized_calls`. Returns
    (ConstraintProfile, system_label). Ben-free; depends only on public state.
    """
    from pathlib import Path
    # Import `dealing` fully BEFORE `semantics` to break a latent import cycle
    # (semantics.predicates <-> dealing.rejection): if semantics.engine is the
    # first of the two touched, predicates is still mid-init when rejection
    # imports it. Loading dealing first makes the order safe from any entrypoint.
    from ..dealing import rejection as _rejection  # noqa: F401
    from ..semantics.engine import RuleEngine, load_ruleset
    from ..domain.auction import Auction

    rules_dir = Path(__file__).resolve().parent.parent / "semantics" / "rules"
    our = load_ruleset(rules_dir / (our_ruleset or DEFAULT_RULESETS[0]))
    opps = load_ruleset(rules_dir / (opps_ruleset or DEFAULT_RULESETS[1]))
    engine = RuleEngine(our, opps, my_seat=problem.leader)
    auction = Auction.from_tokens(problem.dealer, list(problem.auction))
    profile = engine.extract(auction)
    label = f"rule_engine:{our.system}+{opps.system}"
    return profile, label


class ConstraintSampler:
    """Deal card-conserving hidden hands consistent with EXPLICIT accumulated
    auction constraints (owner requirement 3, first bullet).

    Given a `ConstraintProfile` (per concealed seat: weighted HCP bands,
    suit-length bands, suit-quality bands, conditional denials, and named
    exclusion predicates for shape/convention meaning) this fixes the leader's
    hand and rejection-samples the other three hands so that the accumulated
    auction constraints are satisfied. Soft margin bands become per-deal
    IMPORTANCE WEIGHTS, so the trick average is weight-aware and ESS is
    reported.

    Honest labelling (requirement 3): the constraints are a hand-authored,
    per-seat MODELLED PRIOR, not a calibrated deal posterior, and the per-seat
    band model does not encode cross-hand partnership fits — so the status is
    `modelled_prior_uncalibrated`, never "probability". What IS gained over the
    uniform baseline is that the accepted deals honour the auction's explicit
    HCP / suit-length / shape / convention constraints instead of ignoring the
    auction entirely.

    Ben-free, deterministic in the seed, and source-deal independent (the
    profile and RNG seed both derive only from public state).
    """
    sampling_model = "auction_constraint_bands"
    posterior_calibration_status = "modelled_prior_uncalibrated"

    def __init__(self, profile=None, semantic_constraint_mode: str = "explicit",
                 batch_size: int = 20_000, max_seconds: float = 15.0,
                 unrecognized_calls=None):
        self.profile = profile
        self.semantic_constraint_mode = semantic_constraint_mode
        self.batch_size = batch_size
        self.max_seconds = max_seconds
        self.unrecognized_calls = list(unrecognized_calls or [])

    @classmethod
    def from_auction(cls, problem: LeadProblem, our_ruleset: str | None = None,
                     opps_ruleset: str | None = None, **kw):
        """Build a sampler whose constraints are derived from the auction via
        the rule engine (requirement 3: 'where available'). Unrecognised calls
        are recorded and reported, not silently dropped."""
        profile, label = constraint_profile_from_auction(
            problem, our_ruleset, opps_ruleset)
        return cls(profile=profile, semantic_constraint_mode=label,
                   unrecognized_calls=list(profile.unrecognized_calls), **kw)

    def sample(self, problem: LeadProblem, requested: int, seed: int) -> LayoutSet:
        from ..domain.constraints import ConstraintProfile
        from ..domain.interfaces import GenerationBudget
        from ..dealing.rejection import RejectionDealSource

        profile = self.profile if self.profile is not None else ConstraintProfile()
        # How many concealed seats actually carry a constraint (drives the
        # honest 'did the auction constrain anything?' diagnostic).
        constrained_seats = sorted(
            s for s in profile.seats
            if s != problem.leader and s in ("N", "E", "S", "W"))
        src = RejectionDealSource(my_seat=problem.leader,
                                  batch_size=self.batch_size)
        budget = GenerationBudget(max_seconds=self.max_seconds)
        deals, diag = src.generate(problem.hand, profile, requested,
                                   _seed_int(problem, seed), budget=budget)
        hands = [_pbn_to_seats(d.deal.to_pbn()) for d in deals]
        weights = np.array([d.weight for d in deals], dtype=float)
        if weights.size == 0:
            weights = np.ones(0)
        n = len(hands)
        ls = LayoutSet(
            problem=problem, hands=hands,
            bidding_score=np.ones(n), weight=weights,
            sampling_model=self.sampling_model, sampler_version=SAMPLER_VERSION,
            posterior_calibration_status=self.posterior_calibration_status,
            weighting_method="constraint_importance_bands",
            score_threshold=None, proposal_count=int(diag.attempts),
            requested_samples=requested, accepted_samples=n, seed=seed,
            auction_replay_mode="none",
            semantic_constraint_mode=self.semantic_constraint_mode,
            source_deal_independent=True)
        # attach diagnostics the audit surfaces (not part of the invariant set)
        ls.constraint_diagnostics = {
            "constrained_seats": constrained_seats,
            "any_constraint_applied": bool(constrained_seats),
            "unrecognized_calls": list(self.unrecognized_calls
                                       or profile.unrecognized_calls),
            "acceptance_rate": round(float(diag.acceptance_rate), 6),
            "shortfall": int(diag.shortfall),
            "generator_ess": round(float(diag.effective_sample_size), 2),
        }
        return ls


class PerBoardConstraintSampler:
    """Adapter: derives auction constraints PER BOARD via the rule engine
    (ARCH-10 — moved here from the CLI layer so engine logic no longer lives in
    the interface module).

    The calibration harness calls ``sample(problem, ...)`` with each board's
    public state; this builds the matching ``ConstraintSampler`` on the fly so a
    whole real-deal corpus can be calibrated with a single ``--sampler
    constraint`` flag (each family/board carries its own auction)."""
    sampling_model = "auction_constraint_bands"

    def sample(self, problem: LeadProblem, requested: int, seed: int) -> LayoutSet:
        return ConstraintSampler.from_auction(problem).sample(
            problem, requested, seed)


SAMPLERS = {
    "uniform": UniformSampler,
    "current": BenCurrentSampler,
    "ben-replay": BenReplaySampler,
    "ben-likelihood": BenLikelihoodSampler,
    "constraint": ConstraintSampler,
}
