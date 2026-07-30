"""Dev-only preview harness for dashboard.html and history.html.

Generates the web app into a scratch directory and rewrites the chosen page so
`window.BT` is a stub backed by a deterministic set of fake attempt documents.
That lets the page be opened (and screenshotted) without Firebase, an account,
or a real answering history.

    python3 scripts/dash_preview.py --out /tmp/dashprev
    python3 scripts/dash_preview.py --out /tmp/histprev --page history

Not shipped to users — nothing in bridge_trainer imports it.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from bridge_trainer.app.webapp import write_app

BID_TYPES = [
    "open_or_pass", "preempt_decision", "enter_auction", "compete_or_sell",
    "invite_or_game", "slam_try", "choice_of_strain", "double_or_bid",
    "sacrifice_decision", "describe_hand",
]
LEAD_TYPES = ["lead_part_score", "lead_3nt", "lead_suit_game", "lead_slam",
              "lead_doubled"]
CALLS = ["1NT", "2C", "2H", "3NT", "4S", "X", "P", "2S", "4H", "5C"]
CARDS = [s + r for s in "SHDC" for r in "AKQJT98765432"]
OUTCOMES = ["winner", "accepted-alt", "suboptimal", "dead"]

# per-type mean score, so the preview shows a believable strength profile
BID_SKILL = {
    "open_or_pass": 88, "preempt_decision": 61, "enter_auction": 74,
    "compete_or_sell": 55, "invite_or_game": 79, "slam_try": 47,
    "choice_of_strain": 71, "double_or_bid": 64, "sacrifice_decision": 52,
    "describe_hand": 83,
}
LEAD_SKILL = {"lead_part_score": 70, "lead_3nt": 78, "lead_suit_game": 66,
              "lead_slam": 58, "lead_doubled": 62}


def _score(mean: float, rng: random.Random) -> int:
    """A score drawn around `mean` with the real scale's mass at 100 and 0."""
    x = rng.gauss(mean, 22)
    if x >= 97:
        return 100
    if x <= 3:
        return 0 if rng.random() < 0.4 else 1
    return int(max(1, min(94, round(x))))


def make_attempts(n: int = 180, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    out: list[dict] = []
    t0 = 1_750_000_000  # fixed epoch -> deterministic, no wall-clock in output
    for i in range(n):
        lead = rng.random() < 0.45
        kind = "lead" if lead else "bidding"
        typ = rng.choice(LEAD_TYPES if lead else BID_TYPES)
        base = (LEAD_SKILL if lead else BID_SKILL)[typ]
        # a mild improvement trend over the history
        base += (i / n) * 12 - 6
        sc = _score(base, rng)
        cost = 0.0 if sc >= 100 else round(max(0.0, (100 - sc) / 100 * 3.4
                                               * rng.uniform(0.5, 1.6)), 2)
        a = {
            "problemId": f"p{i:04d}",
            "kind": kind,
            "type": typ,
            "difficultyLevel": rng.choice([1, 2, 2, 3, 3, 3, 4, 4, 5]),
            "chosenCall": rng.choice(CARDS if lead else CALLS),
            "acceptedSet": [rng.choice(CARDS if lead else CALLS)],
            "gradedCost": cost,
            "outcomeClass": ("winner" if sc >= 100
                             else "dead" if sc == 0 else "suboptimal"),
            "score": sc,
            "isFirstAttempt": True,
            "attemptCount": 1 + (1 if rng.random() < 0.2 else 0),
            "ts": {"seconds": t0 + i * 3600},
            "firstTs": {"seconds": t0 + i * 3600},
        }
        if lead:
            a["trainingMode"] = "IMP" if rng.random() < 0.4 else "MP"
        out.append(a)
    # a handful of retries (not first attempts) so "total attempts" > "answered"
    for a in rng.sample(out, min(22, len(out) // 4)):
        r = dict(a)
        r["isFirstAttempt"] = False
        r["score"] = min(100, a["score"] + rng.randint(5, 30))
        out.append(r)
    return out


# pendingCount/pendingIds are part of the real API and the pages call them
# through a guard, but the log marks individual rows from pendingIds -- so the
# stub answers both rather than relying on the guard.
STUB = """<script>
window.BT = {
  start(cb) {
    cb();
    // the real layer dispatches this from a .finally once the authoritative
    // sync lands; the log distinguishes "still loading" from "no history" on it
    setTimeout(() => window.dispatchEvent(new Event("bt-attempts-synced")), 50);
  },
  allAttempts() { return Promise.resolve(window.__MOCK_ATTEMPTS__); },
  fetchIndex() { return Promise.resolve({problems: window.__MOCK_POOL__}); },
  user() { return {uid: "preview"}; },
  pendingCount() { return 0; },
  pendingIds() { return []; },
};
</script>"""


def make_pool(attempts: list[dict], seed: int = 11) -> list[dict]:
    """A fake pool index: every answered problem plus unanswered headroom in
    each type, so the coverage section and the recommendation's pool guard
    (which needs SESSION_SIZE unanswered problems in a type) have something to
    work with."""
    rng = random.Random(seed)
    rows = [{"id": a["problemId"], "kind": a["kind"], "type": a["type"]}
            for a in attempts if a.get("isFirstAttempt", True)]
    for typ in BID_TYPES + LEAD_TYPES:
        kind = "lead" if typ in LEAD_TYPES else "bidding"
        for i in range(rng.randint(14, 40)):
            rows.append({"id": f"pool-{typ}-{i}", "kind": kind, "type": typ})
    return rows


def build(out_dir: Path, attempts: list[dict], empty: bool = False,
          which: str = "dashboard") -> Path:
    write_app(out_dir)
    page = out_dir / (which + ".html")
    html = page.read_text(encoding="utf-8")
    data = ("<script>window.__MOCK_ATTEMPTS__ = " + json.dumps(
        [] if empty else attempts).replace("</", "<\\/") + ";\n"
        "window.__MOCK_POOL__ = " + json.dumps(
            [] if empty else make_pool(attempts)).replace("</", "<\\/")
        + ";</script>")
    html = html.replace(
        '<script type="module" src="bt-firebase.js"></script>',
        data + "\n" + STUB)
    page.write_text(html, encoding="utf-8")
    return page


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=180)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--empty", action="store_true")
    ap.add_argument("--page", choices=("dashboard", "history"),
                    default="dashboard")
    args = ap.parse_args()
    out = Path(args.out)
    page = build(out, make_attempts(args.n, args.seed), empty=args.empty,
                 which=args.page)
    print(page)


if __name__ == "__main__":
    main()
