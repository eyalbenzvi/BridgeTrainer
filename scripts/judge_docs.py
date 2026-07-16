"""Judge finalization docs through the hardened shell + DD stack.

Usage: python3 scripts/judge_docs.py <spots.json> <docs.json> <out_dir>
Writes one record JSON per surviving problem plus a report to stdout.
Explanations on these records are DRAFTS — the post-verdict writer +
prose linter installs the shipping text before deployment.
"""
import json
import sys
from pathlib import Path

from bridge_trainer.finalize.batch import dedupe_deals, judge_spot
from bridge_trainer.finalize.schema import FinalizationError

spots_path, docs_path, out_dir = (Path(sys.argv[1]), Path(sys.argv[2]),
                                  Path(sys.argv[3]))
docs = json.loads(docs_path.read_text())
spots = {f"{s['lin']}-{s['board']}": s
         for s in json.loads(spots_path.read_text())}

records, failures = [], {}
for key, doc in docs.items():
    try:
        rec = judge_spot(spots[key], doc, n_deals=600)
        records.append(rec)
        v = rec["verdict"]
        print(f"OK   {rec['id']:11} accepted={'/'.join(v['accepted']):12} "
              f"toss_up={v['toss_up']} margin={rec['difficulty']:7} "
              f"ess={rec['quality']['ess']}")
    except FinalizationError as exc:
        failures[key] = str(exc)
        print(f"FAIL {key:11} {exc}")

records, dups = dedupe_deals(records)
if dups:
    print("deduped (same physical deal):", dups)

out_dir.mkdir(parents=True, exist_ok=True)
for rec in records:
    (out_dir / f"{rec['id']}.json").write_text(json.dumps(rec, indent=1))
print(f"\n{len(records)} records -> {out_dir}; {len(failures)} failures")
