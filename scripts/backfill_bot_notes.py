"""Backfill bot-derived auction/option notes onto existing pool records.

Rebuilds each record's cheap generation state from its seed (no DD) via
prepare_problem, verifies the stored auction and candidates match, and
attaches auction_notes + option_notes. Records that already carry notes
(e.g. hand-authored via attach_notes.py) are left untouched.

Usage: python3 scripts/backfill_bot_notes.py <pool_dir>
"""
import json
import sys
from pathlib import Path

from bridge_trainer.generate.notes import auction_notes, option_notes
from bridge_trainer.generate.random_problem import prepare_problem

pool = Path(sys.argv[1])
done = skipped = 0
for path in sorted((pool / "problems").glob("*.json")):
    rec = json.loads(path.read_text())
    if "auction_notes" in rec and "option_notes" in rec:
        skipped += 1
        continue
    seed = rec["generator"]["seed"]
    setup, reason = prepare_problem(seed, n_deals=600)
    if setup is None:
        raise SystemExit(f"{rec['id']}: setup rejected ({reason}) — "
                         f"bot version drift?")
    if setup["stem_tokens"] != rec["auction"] \
            or setup["candidates"] != rec["candidates"] \
            or setup["hands_pbn"][setup["hero"]] != rec["hand"]:
        raise SystemExit(f"{rec['id']}: regenerated stem does not match "
                         f"the stored record — bot version drift?")
    import numpy as np
    weights = np.array([wd.weight for wd in setup["deals"]])
    rec["auction_notes"] = auction_notes(setup["stem_calls"])
    rec["option_notes"] = option_notes(
        rec["candidates"], setup["fired_by_token"],
        setup["contracts_by_candidate"], weights, setup["hero"])
    path.write_text(json.dumps(rec, separators=(",", ":")))
    done += 1
    print(f"noted {rec['id']}")
print(f"{done} backfilled, {skipped} already noted")
