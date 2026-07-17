#!/usr/bin/env bash
# Install the Ben engine (github.com/lorserker/ben, GPL-3.0) next to this
# repo, with a Python 3.12 venv (the vendored DDS binary targets 3.12).
# Idempotent: safe to re-run; fast when everything is cached.
#
# Usage: scripts/setup_ben.sh [BEN_HOME] [VENV]
set -euo pipefail

BEN_HOME="${1:-${BEN_HOME:-$HOME/ben}}"
VENV="${2:-${BEN_VENV:-$HOME/benv}}"
BEN_COMMIT="2b534146415dcacb2f783bd9015b36df44dcf2bb"  # pinned 2026-07-17
PYTHON="${PYTHON:-python3.12}"

if [ ! -d "$BEN_HOME/src" ]; then
  git clone https://github.com/lorserker/ben.git "$BEN_HOME"
fi
git -C "$BEN_HOME" fetch -q origin "$BEN_COMMIT" 2>/dev/null || true
git -C "$BEN_HOME" checkout -q "$BEN_COMMIT" 2>/dev/null || \
  echo "warning: pinned commit unavailable (shallow clone?) — using HEAD"

if [ ! -x "$VENV/bin/python" ]; then
  "$PYTHON" -m venv "$VENV"
fi
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q tensorflow
"$VENV/bin/pip" install -q -r "$BEN_HOME/requirements.txt"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
"$VENV/bin/pip" install -q -e "$REPO_DIR"

BEN_HOME="$BEN_HOME" "$VENV/bin/python" - << 'EOF'
import os, sys
sys.path.insert(0, os.path.join(os.environ["BEN_HOME"], "src"))
from ddsolver.ddsolver import DDSolver  # noqa: F401  (verifies dds3 loads)
print("ben setup OK:", os.environ["BEN_HOME"])
EOF

echo "Run: BEN_HOME=$BEN_HOME $VENV/bin/python -m bridge_trainer.app.cli ben-forge --count 20"
