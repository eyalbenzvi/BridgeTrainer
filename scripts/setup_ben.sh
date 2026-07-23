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
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -d "$BEN_HOME/src" ]; then
  git clone https://github.com/lorserker/ben.git "$BEN_HOME"
fi
git -C "$BEN_HOME" fetch -q origin "$BEN_COMMIT" 2>/dev/null || true
git -C "$BEN_HOME" checkout -q "$BEN_COMMIT" 2>/dev/null || \
  echo "warning: pinned commit unavailable (shallow clone?) — using HEAD"

# BBA/EPBot is NOT used by this project: bidding, the candidate set, the
# rollout and keycard handling are all Ben-neural, and bid explanations come
# from GIB (bridge_trainer/engine/gib_explain.py). The engine is configured
# with every BBA switch off (see engine/ben.py), so the native EPBot library
# is never loaded. Remove its binaries and convention cards outright so the
# rule engine cannot be invoked even by accident.
rm -rf "$BEN_HOME/bin/BBA" "$BEN_HOME/BBA" 2>/dev/null || true

# Ben 0.8.5 (upstream fdd6c78a, "Testing BBA for bidding_rollout") broke
# get_auction_binary_sampling for numpy-matrix auctions: every sample's NN
# input encodes SAMPLE 0's auction history (auction[:, i][0]), so once the
# per-sample rollout auctions diverge, bidders respond to the wrong auction.
# Upstream never hits it (stock configs bid rollouts with BBA); our pure-NN
# rollouts (use_bba_rollout off) run straight through it, which corrupted
# candidate evidence — RKC 4NT passed out, splinters raised as natural, etc.
# The patch restores the pre-0.8.5 per-sample indexing; engine/ben.py refuses
# to start on an unpatched checkout.
PATCH="$REPO_DIR/scripts/ben_rollout_context.patch"
if git -C "$BEN_HOME" apply --reverse --check "$PATCH" 2>/dev/null; then
  echo "ben rollout-context patch already applied"
else
  git -C "$BEN_HOME" apply "$PATCH"
  echo "ben rollout-context patch applied"
fi

if [ ! -x "$VENV/bin/python" ]; then
  "$PYTHON" -m venv "$VENV"
fi
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q tensorflow
"$VENV/bin/pip" install -q -r "$BEN_HOME/requirements.txt"
"$VENV/bin/pip" install -q -e "$REPO_DIR"

BEN_HOME="$BEN_HOME" "$VENV/bin/python" - << 'EOF'
import os, sys
sys.path.insert(0, os.path.join(os.environ["BEN_HOME"], "src"))
from ddsolver.ddsolver import DDSolver  # noqa: F401  (verifies dds3 loads)
print("ben setup OK:", os.environ["BEN_HOME"])
EOF

echo "Run: BEN_HOME=$BEN_HOME $VENV/bin/python -m bridge_trainer.app.cli ben-forge --count 20"
