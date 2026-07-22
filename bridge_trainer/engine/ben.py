"""Adapter around the ben engine (github.com/lorserker/ben, GPL-3.0).

Ben stays an external checkout (BEN_HOME); everything the generator
needs goes through this class so the GPL boundary and the API surface
live in one file.

Seats and dealers are indices 0..3 = N,E,S,W. Auctions here are plain
token lists starting from the dealer ("1H", "P", "X", ...); padding to
Ben's N-first convention happens internally.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

import numpy as np

SEATS = "NESW"
BEN_HOME_DEFAULT = "/home/user/ben"
CONF_REL = "src/config/BEN-21GF.conf"

_engine = None  # process singleton (models are ~1 GB in RAM)


def to_ben(tok: str) -> str:
    """Our tokens (P, 1NT) -> ben's (PASS, 1N)."""
    if tok == "P":
        return "PASS"
    return tok.replace("NT", "N")


def from_ben(tok: str) -> str:
    if tok == "PASS":
        return "P"
    if len(tok) == 2 and tok[1] == "N":
        return tok[0] + "NT"
    return tok


def pad(dealer_i: int, auction: list[str]) -> list[str]:
    return ["PAD_START"] * dealer_i + [to_ben(t) for t in auction]


# -- card tokens: our "SK" = suit letter + rank -----------------------------
_RANKS = "AKQJT98765432"


def cards_of(hand_pbn: str) -> list[str]:
    """'K93.752.A854.T62' -> ['SK','S9','S3','H7',...] in S,H,D,C order."""
    out = []
    for suit, holding in zip("SHDC", hand_pbn.split(".")):
        out.extend(suit + r for r in holding)
    return out


def lead_code32(token: str) -> int:
    """Ben's 32-card lead code: suit*8 + rank, with all spot cards (7..2)
    folded into slot 7 (one 'low card' lead per suit). Suit order S,H,D,C."""
    return "SHDC".index(token[0]) * 8 + min(_RANKS.index(token[1]), 7)


@dataclass
class PolicyItem:
    bid: str
    p: float
    alert: bool | None = None
    explanation: str | None = None


@dataclass
class Evaluation:
    """Paired candidate evaluation on one shared sample set."""
    bids: list[str]
    ev: dict                      # bid -> np.ndarray per-sample expected score
    contracts: dict               # bid -> list[str] per-sample final contract
    auctions: dict                # bid -> list[str] per-sample rollout auction
    n_samples: int
    quality: float
    sample_deals: list[str] = field(default_factory=list)  # pbn-ish 4-hand rows


class BenEngine:
    def __init__(self, ben_home: str = None, verbose: bool = False,
                 dds_max_threads: int = 0):
        self.ben_home = ben_home or os.environ.get("BEN_HOME", BEN_HOME_DEFAULT)
        os.environ.setdefault("BEN_HOME", self.ben_home)
        src = os.path.join(self.ben_home, "src")
        if src not in sys.path:
            sys.path.insert(0, src)
        # ben resolves some data files relative to cwd
        self._old_cwd = os.getcwd()
        os.chdir(src)

        import conf
        from nn.models_tf2 import Models
        from sample import Sample
        from ddsolver.ddsolver import DDSolver

        configuration = conf.load(os.path.join(self.ben_home, CONF_REL))
        # Verdict evidence floor (bridge review rec 3): 128 samples beats
        # the stock 50; CI half-width scales with 1/sqrt(n).
        configuration["sampling"]["sample_hands_auction"] = "128"
        # BBA/EPBot is removed entirely. The candidate set, the rollout and
        # keycard handling are ALL Ben-neural; explanations come from GIB
        # (engine/gib_explain.py). Force every BBA switch off and drop the
        # convention cards so the native EPBot library is never loaded or
        # consulted — no rule engine ever shapes a candidate, a rollout or a
        # meaning here. (The old stock config left these on, which injected
        # rule-engine bids into the candidate list and bid the rollouts.)
        for key in ("use_bba", "consult_bba", "use_bba_rollout",
                    "use_bba_to_count_aces"):
            configuration["models"][key] = "False"
        configuration["models"]["bba_our_cc"] = ""
        configuration["models"]["bba_their_cc"] = ""
        self.models = Models.from_conf(configuration, self.ben_home)
        self.sampler = Sample.from_conf(configuration, verbose)
        # dds_max_threads=0 keeps DDS's default (one solver thread per
        # core); parallel forge workers pass cpu_count // workers so
        # board-level parallelism is the only parallelism
        self.dds = DDSolver(max_threads=dds_max_threads)
        self.verbose = verbose
        self._conf_name = configuration["models"].get("name", "?")
        self.model_id = f"{self._conf_name} {os.path.basename(self.models.bidder_model.model_path) if hasattr(self.models.bidder_model, 'model_path') else 'BEN-21GF'}"

    # -- bot construction ------------------------------------------------
    def bot(self, hand_pbn: str, seat_i: int, dealer_i: int,
            vuln: tuple[bool, bool]):
        from botbidder import BotBid
        return BotBid(list(vuln), hand_pbn, self.models, self.sampler,
                      seat_i, dealer_i, self.dds, False, self.verbose)

    # -- policy at a turn --------------------------------------------------
    def policy(self, bot, dealer_i: int, auction: list[str]) -> list[PolicyItem]:
        cands, _passout = bot.get_bid_candidates(pad(dealer_i, auction))
        out = [PolicyItem(bid=from_ben(c.bid),
                          p=float(c.insta_score or 0.0),
                          alert=c.alert, explanation=c.explanation)
               for c in cands]
        out.sort(key=lambda x: -x.p)
        return out

    # -- FULL policy at a turn --------------------------------------------
    def policy_full(self, bot, dealer_i: int,
                    auction: list[str]) -> list[PolicyItem]:
        """The neural policy over EVERY legal call, read straight from the
        bidder's softmax.

        Unlike ``policy`` (``bot.get_bid_candidates``) this does NOT truncate
        at Ben's own ``search_threshold`` — 0.10 for a first bid — which
        otherwise hides legitimate lower-probability calls (e.g. a natural
        raise the network rates at 4-6%). The scanner thresholds the list
        itself (``scanner.P_OPTION``), so it needs the raw distribution.

        The argmax is identical to ``get_bid_candidates`` (both take the
        highest-softmax legal call), so replacing ``policy`` with this in the
        scanner leaves the bid-out — and therefore every board's auction —
        unchanged; only the candidate list at the decision point grows.
        """
        from bidding import bidding as bb

        padded = pad(dealer_i, auction)
        bid_softmax, _alerts = bot.next_bid_np(padded)
        p = np.asarray(bid_softmax, dtype=float).reshape(-1)
        out = []
        for idx in range(p.shape[0]):
            try:
                name = bb.ID2BID[int(idx)]
            except (KeyError, IndexError):
                continue
            if not bb.can_bid(name, padded):
                continue
            out.append(PolicyItem(bid=from_ben(name), p=float(p[idx])))
        out.sort(key=lambda x: -x.p)
        return out

    # -- the searched table call (accurate stem bidding) -------------------
    def choose(self, bot, dealer_i: int, auction: list[str]):
        resp = bot.bid(pad(dealer_i, auction))
        bid = from_ben(resp.bid)
        return bid, resp

    # -- paired evaluation of an explicit candidate list -------------------
    def evaluate(self, bot, dealer_i: int, auction: list[str],
                 bids: list[str], n_samples: int | None = None,
                 dd_memo: dict | None = None) -> Evaluation:
        """Mirror of BotBid.bid()'s rollout block, but on OUR candidate
        list, all candidates on the same sampled layouts (INV1 pairing).
        n_samples temporarily overrides the sampler's target count."""
        padded, hands_np, hands_pbn, quality = self.sample_for_auction(
            bot, dealer_i, auction, n_samples)
        return self.rollout_eval(bot, padded, bids, hands_np, hands_pbn,
                                 quality, dd_memo=dd_memo)

    def sample_for_auction(self, bot, dealer_i: int, auction: list[str],
                           n_samples: int | None = None):
        """Sample + translate ONCE for an auction; the (hands_np,
        hands_pbn) pair can then feed several rollout_eval calls (e.g. a
        prescreen slice and the full screen) with shared PBN strings."""
        saved = self.sampler._sample_hands_auction
        if n_samples:
            self.sampler._sample_hands_auction = n_samples
        try:
            padded = pad(dealer_i, auction)
            hands_np, _scores, _p_hcp, _p_shp, quality = \
                bot.sample_hands_for_auction(padded, bot.seat)
            n = hands_np.shape[0]
            hands_pbn = bot.translate_hands(hands_np, bot.hand_str, n)
            return padded, hands_np, hands_pbn, float(quality)
        finally:
            self.sampler._sample_hands_auction = saved

    def rollout_eval(self, bot, padded, bids, hands_np, hands_pbn,
                     quality: float, dd_memo: dict | None = None) -> Evaluation:
        """Rollout + DD + score the candidates on the given sample rows."""
        from bidding import bidding as ben_bidding

        n = hands_np.shape[0]
        ev, contracts, aucs = {}, {}, {}
        for bid in bids:
            ben_bid = to_ben(bid)
            auctions_np = bot.bidding_rollout(padded, ben_bid, hands_np, hands_pbn)
            cts, tricks_softmax = _tricks_dd_memo(bot, hands_pbn, auctions_np,
                                                  dd_memo)
            scores = bot.expected_score(len(padded) % 4, cts, tricks_softmax)
            ev[bid] = np.asarray(scores, dtype=float)
            contracts[bid] = list(cts)
            decoded = []
            for row in auctions_np:
                toks = [from_ben(ben_bidding.ID2BID[t]) for t in row
                        if t not in (0, 1)]  # PAD tokens
                decoded.append(" ".join(toks))
            aucs[bid] = decoded

        deals = ["%s %s %s %s" % tuple(
            _hand_str(hands_np[i, j, :], self.models.n_cards_bidding)
            for j in range(4)) for i in range(min(n, 200))]
        return Evaluation(bids=list(bids), ev=ev, contracts=contracts,
                          auctions=aucs, n_samples=n, quality=float(quality),
                          sample_deals=deals)

    # -- opening leads -----------------------------------------------------
    def lead_bot(self, hand_pbn: str, seat_i: int, dealer_i: int,
                 vuln: tuple[bool, bool]):
        from botopeninglead import BotLead
        return BotLead(list(vuln), hand_pbn, self.models, self.sampler,
                       seat_i, dealer_i, self.dds, self.verbose)

    # -- opening-lead policy + sampling (Ben) ------------------------------
    def lead_softmax(self, bot, padded, held) -> dict:
        """Ben's opening-lead policy mass per PHYSICAL card, read from its
        32-card lead space. The 32-code fold (spots 7..2 -> one 'low' slot) is
        a POLICY-only abstraction: every low spot of a suit shares that suit's
        low-slot mass. This value is used for the C1 'obvious' gate ONLY; it
        never chooses or renames the physical card DDS scores.
        """
        try:
            _cand, sm = bot.get_opening_lead_candidates(padded)
            smx = np.asarray(sm, dtype=float).reshape(-1)
        except Exception:
            smx = np.zeros(32)
        return {t: (float(smx[lead_code32(t)])
                    if lead_code32(t) < smx.shape[0] else 0.0)
                for t in held}

    def sample_lead_layouts(self, bot, padded, leader_i: int, pool_n: int,
                            sampler_seed: int | None = None):
        """Sample opening-lead layouts consistent with the public auction and
        return them as engine.lead_evaluate.Layout objects in ABSOLUTE seat
        order (N,E,S,W) — the single place Ben's hero-first sample rows are
        rotated back to absolute seats (engine.lead_cards.hero_first_to_absolute).

        No double-dummy here: layouts are the only product, so the same pool
        feeds the screening cascade and the confirm pass, and the per-physical
        -card DDS (endplay) runs downstream in lead_evaluate.score_layouts.
        """
        from bidding import bidding as bb

        from .lead_cards import hero_first_to_absolute
        from .lead_evaluate import Layout

        # cross-check the ben contract's declarer against our leader seat, so a
        # seat-rotation bug fails loudly instead of scoring the wrong hand.
        ben_contract = bb.get_contract(padded)
        decl_i = bb.get_decl_i(ben_contract)
        if (decl_i + 1) % 4 != leader_i:
            raise AssertionError(
                f"ben contract {ben_contract!r} declarer {SEATS[decl_i]} "
                f"=> leader {SEATS[(decl_i + 1) % 4]}, not {SEATS[leader_i]}")

        # deterministic per sampler_seed where possible (best effort: Ben's
        # sampler draws from bot.rng, which we seed here).
        bot.rng = (np.random.default_rng(np.asarray([sampler_seed, 0xB1DDE],
                                                     dtype=np.uint64))
                   if sampler_seed is not None else bot.get_random_generator())
        saved = self.sampler.sample_hands_opening_lead
        self.sampler.sample_hands_opening_lead = pool_n
        try:
            accepted, _sc, _ph, _psh, quality, proposal_count = \
                self.sampler.generate_samples_iterative(
                    padded, leader_i,
                    self.sampler.sample_boards_for_auction_opening_lead,
                    self.sampler.sample_hands_opening_lead,
                    bot.rng, bot.hand_str, bot.vuln, self.models, [], {})
        finally:
            self.sampler.sample_hands_opening_lead = saved

        n_over_threshold = int(accepted.shape[0]) if hasattr(accepted, "shape") \
            else 0
        navail = n_over_threshold
        if navail:
            order = np.arange(navail)
            bot.rng.shuffle(order)
            accepted = accepted[order][:pool_n]
            navail = int(accepted.shape[0])

        # Provenance of Q(layout | public info): a truncated, uniformly-weighted
        # neural bidding-consistency distribution. NOT a proven bridge posterior;
        # biddingScore is an uncalibrated NN-softmax consistency score.
        provenance = {
            "requested_samples": int(pool_n),
            "accepted_samples": int(navail),
            "n_over_threshold": int(n_over_threshold),
            "proposal_count": int(proposal_count),
            "acceptance_rate": (round(n_over_threshold / proposal_count, 4)
                                if proposal_count else 0.0),
            "sampling_model": f"{self.model_id} neural bidding-consistency",
            "weighting_method": "uniform_over_accepted",
            "score_threshold": float(self.sampler.bidding_threshold_sampling),
            "effective_sample_size": int(navail),   # ESS == n under uniform wts
            "posterior_calibration_status": "uncalibrated_neural_consistency",
            "complete": bool(navail >= pool_n),
        }

        # Build a concrete, legal 52-card deal per sample the way Ben's own
        # double_dummy_estimates does: PBN position 0 is the leader's real hand,
        # positions 1..3 are the sampled hidden hands (`accepted[i]` is exactly
        # those three, leader-first order = leader, leader+1, leader+2,
        # leader+3). deck52.convert_cards realizes the low-pip placeholders into
        # concrete spots consistent with the leader's known cards. We pass
        # opening_lead=0 (a top card, in-suit index 0) so NO card is removed —
        # unlike Ben, we want the full 52 cards present so endplay can score
        # every physical lead separately downstream.
        from deck52 import convert_cards, handxxto52str
        ncb = self.models.n_cards_bidding
        leader_full = bot.hand_str
        layouts = []
        for i in range(navail):
            sample_pbn = "N:" + leader_full + " " + " ".join(
                handxxto52str(h, ncb) for h in accepted[i])
            concrete = convert_cards(sample_pbn, 0, leader_full, bot.rng, ncb)
            hands_leader_first = concrete[2:].strip().split(" ")
            hands_abs = hero_first_to_absolute(hands_leader_first, bot.seat)
            layouts.append(Layout(hands=hands_abs, sample_index=i,
                                  sample_seed=sampler_seed,
                                  accept={"distribution": "Q_neural_consistency",
                                          "score_threshold": provenance["score_threshold"]}))
        return layouts, (float(quality) if navail else 0.0), provenance

    def lead_evaluate(self, hand_pbn: str, seat_i: int, dealer_i: int,
                      vuln: tuple[bool, bool], auction: list[str],
                      denom: str, contract: str, doubled: bool,
                      n_samples: int | None = None):
        """Grade every PHYSICAL opening lead by average double-dummy defensive
        tricks over auction-consistent layouts.

        Ben supplies the auction-consistent layout sampler and the (folded)
        lead policy; every one of the 13 physical cards is then double-dummied
        SEPARATELY with endplay (engine.lead_evaluate.score_layouts) — no spot
        folding before or during DDS. Runs through the public-state boundary
        (evaluate_leads_from_public_state), so it can only condition on public
        information. Returns a LeadEvaluation.
        """
        from .lead_evaluate import (Contract, EvalConfig, PublicState,
                                    evaluate_leads_from_public_state)
        from .lead_invariants import checks_enabled

        leader_i = seat_i
        contract_obj = Contract(int(contract[0]), denom,
                                declarer_i=(leader_i + 3) % 4,
                                doubled="xx" if doubled else "")

        engine = self

        def sampler(public: PublicState, sampler_seed, config):
            from .lead_evaluate import SampleResult
            bot = engine.lead_bot(public.leader_hand, public.contract.leader_i,
                                  public.dealer_i, public.vul)
            padded = pad(public.dealer_i, list(public.auction))
            layouts, quality, provenance = engine.sample_lead_layouts(
                bot, padded, public.contract.leader_i, config.n_samples,
                sampler_seed=sampler_seed)
            return SampleResult(layouts=layouts, quality=quality,
                                meta=provenance)

        def policy(public: PublicState):
            bot = engine.lead_bot(public.leader_hand, public.contract.leader_i,
                                  public.dealer_i, public.vul)
            padded = pad(public.dealer_i, list(public.auction))
            return engine.lead_softmax(bot, padded, cards_of(public.leader_hand))

        cfg = EvalConfig(n_samples=n_samples or 128,
                         check_invariants=checks_enabled())
        # sampler_seed derives from the public auction+hand via a STABLE digest
        # (Python's hash() is per-process salted) so repeated calls on the same
        # board reproduce; the source deal is never involved.
        import hashlib
        key = "|".join([hand_pbn, " ".join(auction), str(contract_obj)])
        seed = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)
        return evaluate_leads_from_public_state(
            hand_pbn, auction, contract_obj, dealer_i, vuln,
            sampler_seed=seed, config=cfg, sampler=sampler, policy=policy)

    def lead_open(self, hand_pbn: str, seat_i: int, dealer_i: int,
                  vuln: tuple[bool, bool], auction: list[str],
                  contract: str, doubled: bool, pool_n: int = 128,
                  obvious_p: float | None = None):
        """Sample the opening-lead layouts ONCE, then hand back a grader that
        double-dummies incremental slices — so the screening cascade can rule
        a board out after 32/64 solves instead of the full 128, and each
        layout is DD-solved at most once.

        Returns (grade, n_available, top_softmax):
          grade(n) -> LeadEvaluation over the first n sampled layouts (DDs
                      only the newly-needed ones);
          top_softmax lets the caller reject 'obvious' boards before any DD.

        Each physical card is DD-solved separately (endplay); the 32-code fold
        is used only for the policy/obvious gate. `obvious_p`: when set, apply
        the C1 gate on ben's lead policy (a cheap NN pass) BEFORE sampling; a
        board it already calls obvious returns (None, 0, top_softmax).
        """
        from .lead_classify import parse_contract
        from .lead_evaluate import Contract, score_layouts
        from .lead_invariants import checks_enabled
        from .lead_verdict import LeadEvaluation

        held = cards_of(hand_pbn)
        padded = pad(dealer_i, auction)
        leader_i = seat_i
        bot = self.lead_bot(hand_pbn, leader_i, dealer_i, vuln)

        # criterion-1 policy (cheap NN, no double-dummy)
        softmax = self.lead_softmax(bot, padded, held)
        top_soft = max(softmax.values()) if softmax else 0.0
        if obvious_p is not None and top_soft > obvious_p:
            return None, 0, top_soft

        _level, _denom, _dbl = parse_contract(contract)
        contract_obj = Contract(_level, _denom,
                                declarer_i=(leader_i + 3) % 4,
                                doubled="xx" if doubled else "")

        layouts, quality, provenance = self.sample_lead_layouts(
            bot, padded, leader_i, pool_n)
        navail = len(layouts)
        check = checks_enabled()

        state = {"solved": 0, "by_card": {c: [] for c in held}}

        def grade(n: int):
            n = min(n, navail)
            if navail and n > state["solved"]:
                sl = layouts[state["solved"]:n]
                dt = score_layouts(sl, contract_obj, held, check=check,
                                   displayed_leader_hand=hand_pbn)
                for c in held:
                    state["by_card"][c].append(dt[c])
                state["solved"] = n
            m = state["solved"]
            def_tricks = {c: (np.concatenate(state["by_card"][c])
                              if m else np.zeros(0)) for c in held}
            prov = dict(provenance)
            prov["accepted_samples"] = m
            prov["effective_sample_size"] = m
            return LeadEvaluation(
                cards=held, def_tricks=def_tricks, softmax=softmax,
                n_samples=m, quality=float(quality) if navail else 0.0,
                contract=contract, doubled=doubled, sampling=prov)

        return grade, navail, top_soft

    # Bid meanings/explanations are NOT produced here anymore. BBA/EPBot has
    # been removed; the meaning of each call comes from GIB (BBO gibrest) via
    # engine/gib_explain.py, which needs only the auction, not this engine.

    # -- meaning-band sampling at an auction prefix -------------------------
    def sample_prefix(self, bot, dealer_i: int, prefix: list[str],
                      max_boards: int = 200):
        """Layouts consistent with the auction *through* the prefix's last
        call, seen from the bot's (hero's) hand. Returns (hands_np, n)."""
        padded = pad(dealer_i, prefix)
        hands_np, _score, _p_hcp, _p_shp, _q = \
            bot.sample_hands_for_auction(padded, bot.seat)
        return hands_np[:max_boards], min(len(hands_np), max_boards)


def _tricks_dd_memo(bot, hands_pbn, auctions_np, dd_memo: dict | None):
    """Bit-identical mirror of BotBid.expected_tricks_dd with an optional
    deal-level cache. Key: (pbn, strain, rotated leader) — complete for
    this call pattern because current_trick=[] and solutions=1 are
    constants, the PBN string itself encodes the seat rotation, and DDS
    is exact (identical inputs => identical tricks regardless of batch
    composition). The payoff is cross-CANDIDATE within one board:
    rollouts of different candidates frequently converge to the same
    final contract on the same shared sample. (Cross-STAGE hits are ~0:
    Ben's pip randomization in translate_hands is position-dependent, so
    screen and confirm PBNs differ for the same abstract deal.)"""
    from bidding import bidding as ben_bidding
    from collections import defaultdict

    n_samples = auctions_np.shape[0]
    assert len(hands_pbn) == n_samples
    decl_tricks_softmax = np.zeros((n_samples, 14), dtype=np.int32)
    contracts = []
    groups = defaultdict(list)
    for i in range(n_samples):
        sample_auction = [ben_bidding.ID2BID[b]
                          for b in list(auctions_np[i, :]) if b != 1]
        contract = ben_bidding.get_contract(sample_auction)
        if contract is None:
            contracts.append("PASS")
            continue
        contracts.append(contract)
        strain = 'NSHDC'.index(contract[1])
        declarer = 'NESW'.index(contract[-1])
        leader = (declarer + 1) % 4
        leader = (leader + 4 - bot.seat) % 4
        key = (hands_pbn[i], strain, leader)
        if dd_memo is not None and key in dd_memo:
            decl_tricks_softmax[i, dd_memo[key]] = 1
        else:
            groups[(strain, leader)].append(i)

    for (strain, leader), indices in groups.items():
        pbns = [hands_pbn[i] for i in indices]
        dd_solved = bot.ddsolver.solve(strain, leader, [], pbns, 1)
        for j, i in enumerate(indices):
            tricks = 13 - dd_solved["max"][j]
            decl_tricks_softmax[i, tricks] = 1
            if dd_memo is not None:
                dd_memo[(hands_pbn[i], strain, leader)] = tricks
    return contracts, decl_tricks_softmax


def _hand_str(hand_row, n_cards) -> str:
    from util import hand_to_str
    return hand_to_str(hand_row, n_cards)


def get_engine(verbose: bool = False, dds_max_threads: int = 0) -> BenEngine:
    global _engine
    if _engine is None:
        _engine = BenEngine(verbose=verbose, dds_max_threads=dds_max_threads)
    return _engine


def seat_features(hands_np, seat_i: int, n_cards: int) -> dict:
    """HCP + suit-length stats for one seat across sampled layouts.

    Ben's binary hand rows are one-hot card vectors with pips grouped
    (n_cards per deck); suit blocks are contiguous S,H,D,C."""
    per = n_cards // 4
    rows = hands_np[:, seat_i, :]
    # HCP: within each suit block the first 4 entries are A,K,Q,J
    hcp_w = np.zeros(n_cards)
    for s in range(4):
        hcp_w[s * per:s * per + 4] = [4, 3, 2, 1]
    hcp = rows @ hcp_w
    lengths = {}
    for s, name in enumerate("SHDC"):
        lengths[name] = rows[:, s * per:(s + 1) * per].sum(axis=1)
    dist = np.stack([lengths[x] for x in "SHDC"], axis=1)
    balanced = (dist.min(axis=1) >= 2) & ((dist == 2).sum(axis=1) <= 1)
    return {
        "n": int(rows.shape[0]),
        "hcp_p10": float(np.percentile(hcp, 10)),
        "hcp_p90": float(np.percentile(hcp, 90)),
        "hcp_avg": float(hcp.mean()),
        "len_avg": {k: float(v.mean()) for k, v in lengths.items()},
        "len4plus": {k: float((v >= 4).mean()) for k, v in lengths.items()},
        "len5plus": {k: float((v >= 5).mean()) for k, v in lengths.items()},
        "balanced_share": float(balanced.mean()),
    }
