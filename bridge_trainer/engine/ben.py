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
    def __init__(self, ben_home: str = None, verbose: bool = False):
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
        # No BBA (.NET DLL): pure NN + our own exclusion of keycard turns.
        for key in ("consult_bba", "use_bba_rollout", "use_bba_to_count_aces"):
            configuration["models"][key] = "False"
        # Verdict evidence floor (bridge review rec 3): 128 samples beats
        # the stock 50; CI half-width scales with 1/sqrt(n).
        configuration["sampling"]["sample_hands_auction"] = "128"
        self.models = Models.from_conf(configuration, self.ben_home)
        self.sampler = Sample.from_conf(configuration, verbose)
        self.dds = DDSolver()
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

    # -- the searched table call (accurate stem bidding) -------------------
    def choose(self, bot, dealer_i: int, auction: list[str]):
        resp = bot.bid(pad(dealer_i, auction))
        bid = from_ben(resp.bid)
        return bid, resp

    # -- paired evaluation of an explicit candidate list -------------------
    def evaluate(self, bot, dealer_i: int, auction: list[str],
                 bids: list[str]) -> Evaluation:
        """Mirror of BotBid.bid()'s rollout block, but on OUR candidate
        list, all candidates on the same sampled layouts (INV1 pairing)."""
        from bidding import bidding as ben_bidding

        padded = pad(dealer_i, auction)
        hands_np, sorted_score, _p_hcp, _p_shp, quality = \
            bot.sample_hands_for_auction(padded, bot.seat)
        n = hands_np.shape[0]
        hands_pbn = bot.translate_hands(hands_np, bot.hand_str, n)

        ev, contracts, aucs = {}, {}, {}
        for bid in bids:
            ben_bid = to_ben(bid)
            auctions_np = bot.bidding_rollout(padded, ben_bid, hands_np, hands_pbn)
            cts, tricks_softmax = bot.expected_tricks_dd(hands_pbn, auctions_np, ben_bid)
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

    # -- meaning-band sampling at an auction prefix -------------------------
    def sample_prefix(self, bot, dealer_i: int, prefix: list[str],
                      max_boards: int = 200):
        """Layouts consistent with the auction *through* the prefix's last
        call, seen from the bot's (hero's) hand. Returns (hands_np, n)."""
        padded = pad(dealer_i, prefix)
        hands_np, _score, _p_hcp, _p_shp, _q = \
            bot.sample_hands_for_auction(padded, bot.seat)
        return hands_np[:max_boards], min(len(hands_np), max_boards)


def _hand_str(hand_row, n_cards) -> str:
    from util import hand_to_str
    return hand_to_str(hand_row, n_cards)


def get_engine(verbose: bool = False) -> BenEngine:
    global _engine
    if _engine is None:
        _engine = BenEngine(verbose=verbose)
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
