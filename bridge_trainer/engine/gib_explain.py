"""GIB bid-meaning explainer (BBO ``gibrest`` service) — the replacement for
the removed BBA/EPBot convention-card path.

Why GIB: the bids come from Ben (neural), which returns no textual meaning.
GIB is BBO's own rule engine; asked to interpret an auction it returns the
canonical 2/1 meaning of the last call ("Weak two bid -- 6+ !H; 10- HCP",
"Forcing two over one", "Stayman", "Blackwood", ...). A bid's meaning depends
only on the auction, so this needs no hand and no local engine — one HTTP GET
per call. Deterministic (GIB is rule-based, not ML), cached per auction prefix.

Network use is *intentional but frugal*: only explanations go over the wire
(~one call per bid, a handful per problem); Ben's bidding, the rollout and the
double-dummy scoring all stay local. A network failure yields an empty card so
generation never breaks — the call simply renders without a note.
"""
from __future__ import annotations

import html
import os
import re
import ssl
import time
import urllib.parse
import urllib.request

ENDPOINT = "https://gibrest.bridgebase.com/u_bm/u_bm.php"
SUIT_GLYPH = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}
_THROTTLE_S = 0.1

_CACHE: dict[str, str] = {}


def _ssl_context() -> ssl.SSLContext | None:
    """Trust a proxy CA bundle when the environment provides one (sandboxed
    runs go through an HTTPS proxy); otherwise use the default context."""
    for var in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE"):
        p = os.environ.get(var)
        if p and os.path.exists(p):
            return ssl.create_default_context(cafile=p)
    for p in ("/root/.ccr/ca-bundle.crt",):
        if os.path.exists(p):
            return ssl.create_default_context(cafile=p)
    return None


_SSL = _ssl_context()


def _tok(t: str) -> str:
    """Our token -> GIB token: P->p, X->x, XX->xx, 1NT->1n, 2H->2h."""
    if t == "P":
        return "p"
    if t in ("X", "XX"):
        return t.lower()
    return t[0] + ("n" if t[1:] == "NT" else t[1:].lower())


def auction_str(tokens: list[str]) -> str:
    return "-".join(_tok(t) for t in tokens)


def _fetch(s: str) -> str:
    """GIB meaning string for the LAST call of GIB-auction string ``s``.
    Cached; returns "" on any network/parse failure (never raises)."""
    if s in _CACHE:
        return _CACHE[s]
    url = ENDPOINT + "?" + urllib.parse.urlencode({"t": "g", "s": s})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BridgeTrainer"})
        with urllib.request.urlopen(req, timeout=30, context=_SSL) as resp:
            body = resp.read().decode("utf-8", "replace")
        matches = re.findall(r'<r\b[^>]*\bm="([^"]*)"', body)
        meaning = html.unescape(matches[-1]) if matches else ""
    except Exception:
        return ""  # transient failure — don't cache, render without a note
    _CACHE[s] = meaning
    time.sleep(_THROTTLE_S)  # be polite to BBO's servers
    return meaning


_EMPTY = {"text": "", "hcp": None, "minlen": {}, "maxlen": {}, "forcing": False}
_SUIT_RANGE = re.compile(r"^(\d+)(?:-(\d+))?\s*([+-])?\s*!([CDHS])$", re.I)
_HCP = re.compile(r"^(\d+)(?:-(\d+))?\s*([+-])?\s*HCP$", re.I)


def parse_meaning(m: str) -> dict:
    """GIB's meaning string -> a card dict (same shape the renderer expects):
    ``{text, hcp:(lo,hi), minlen{}, maxlen{}, forcing, gib_raw}``.

    Grammar: ``<name> -- <suit ranges>; <HCP>; <total points>; <extra>`` where
    a suit range is ``6+ !H`` / ``1-3 !S`` / ``2- !S`` and HCP is ``12+ HCP`` /
    ``10- HCP`` / ``11-21 HCP``. Total-points and prose clauses are ignored."""
    card = dict(_EMPTY, minlen={}, maxlen={}, gib_raw=m)
    if not m:
        return card
    if "--" in m:
        name, _, rest = m.partition("--")
        card["text"] = name.strip()
    else:
        rest = m  # no convention name — the whole string is constraints
    for part in rest.split(";"):
        p = part.strip()
        if not p:
            continue
        sm = _SUIT_RANGE.match(p)
        if sm:
            lo, hi, sign, st = sm.group(1, 2, 3, 4)
            lo = int(lo)
            if hi is not None:
                mn, mx = lo, int(hi)
            elif sign == "+":
                mn, mx = lo, 13
            elif sign == "-":
                mn, mx = 0, lo
            else:
                mn, mx = lo, lo
            card["minlen"][st.upper()] = mn
            card["maxlen"][st.upper()] = mx
            continue
        hm = _HCP.match(p)
        if hm:
            lo, hi, sign = hm.group(1, 2, 3)
            lo = int(lo)
            if hi is not None:
                card["hcp"] = (lo, int(hi))
            elif sign == "+":
                card["hcp"] = (lo, 37)
            elif sign == "-":
                card["hcp"] = (0, lo)
            else:
                card["hcp"] = (lo, lo)
            continue
        if "forcing" in p.lower() or "game force" in p.lower():
            card["forcing"] = True
    if not card["text"] and not card["minlen"] and card["hcp"] is None:
        card["text"] = m.strip()  # nothing parsed — keep GIB's phrase verbatim
    return card


def reachable() -> bool:
    """Live check that GIB (BBO ``gibrest``) is reachable and answering.

    When it is NOT — the network policy denies egress to BBO, OR BBO itself
    blocks/rate-limits the API — every ``_fetch`` returns "" and problems are
    written with EMPTY bid explanations (the exact silent failure that stranded
    a batch of note-less problems). Both causes look identical here: this
    returns False on a network exception AND on an HTTP 200 that carries no
    meaning (a block/rate-limit body). The batch makers call it before starting
    so they fail fast with a clear message instead of publishing unexplained
    problems. Bypasses the cache so it always hits the network; a 1NT opening
    always has a canonical GIB meaning, so a non-empty answer means it is up."""
    try:
        url = ENDPOINT + "?" + urllib.parse.urlencode(
            {"t": "g", "s": auction_str(["1NT"])})
        req = urllib.request.Request(
            url, headers={"User-Agent": "BridgeTrainer"})
        with urllib.request.urlopen(req, timeout=30, context=_SSL) as resp:
            body = resp.read().decode("utf-8", "replace")
        return bool(re.findall(r'<r\b[^>]*\bm="([^"]*)"', body))
    except Exception:
        return False


def card_for_auction(tokens: list[str]) -> dict:
    """Card for the LAST call in ``tokens`` (our tokens, from the dealer).
    Total by design — any failure yields an empty card so a single odd
    call can never crash a whole generation run."""
    try:
        if not tokens:
            return dict(_EMPTY, minlen={}, maxlen={}, gib_raw="")
        return parse_meaning(_fetch(auction_str(tokens)))
    except Exception:
        return dict(_EMPTY, minlen={}, maxlen={}, gib_raw="")
