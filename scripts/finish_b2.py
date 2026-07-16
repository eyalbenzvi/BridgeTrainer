"""Install post-verdict explanations onto the b2 records and index them.

Usage: python3 scripts/finish_b2.py <explanations.json> <pool_dir>
attach_explanation lints each body against its record (ProseError stops
the batch) and appends the mechanical flag + at-the-table lines.
"""
import json
import sys
from pathlib import Path

from bridge_trainer.finalize.prose import attach_explanation
from bridge_trainer.pool.store import ProblemPool

bodies = json.loads(Path(sys.argv[1]).read_text())
pool_dir = Path(sys.argv[2])

for path in sorted(pool_dir.glob("problems/*.json")) or \
        sorted(pool_dir.glob("*.json")):
    rec = json.loads(path.read_text())
    body = bodies.get(rec["id"])
    if body is None:
        raise SystemExit(f"no explanation for {rec['id']}")
    attach_explanation(rec, body)
    path.write_text(json.dumps(rec, separators=(",", ":")))
    print(f"attached {rec['id']} "
          f"({len(rec['quality']['prose_warnings'])} prose warnings)")

# Records judged flat into pool_dir -> arrange as a servable pool.
flat = [p for p in pool_dir.glob("*.json") if p.name != "index.json"]
if flat:
    problems = pool_dir / "problems"
    problems.mkdir(exist_ok=True)
    for p in flat:
        p.rename(problems / p.name)
ProblemPool(pool_dir).rebuild_index()
print("index:", json.loads((pool_dir / "index.json").read_text())["count"],
      "problems")
