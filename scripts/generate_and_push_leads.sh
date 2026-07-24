#!/usr/bin/env bash
# Generate opening-lead problems with the Ben engine and push them to Firestore.
#
# Designed to run on a Claude Code server (or any machine): it sets up Ben,
# forges N lead problems into data/, then uploads them to the Firestore
# `problems` collection. Repeatable — safe to run again to grow the pool.
#
# Credentials (a Firebase service-account private key) are read, in order:
#   1. --key <path>                    explicit file
#   2. $GOOGLE_APPLICATION_CREDENTIALS path to the JSON file
#   3. $FIREBASE_SERVICE_ACCOUNT       the full JSON *content* (written to a
#                                      temp file, deleted on exit)
# The key is never written inside the repo and never committed.
#
# Usage:  scripts/generate_and_push_leads.sh [COUNT] [--key PATH]
#   COUNT         problems to generate (default 96)
#   MODE=MP|IMP   target training mode (default MP): which mode's gates
#                 select the boards — MP forges trick-decision problems,
#                 IMP forges score-swing (expected-IMP) problems
#   SEED=...      override the RNG seed (default: unique per run, time-based —
#                 so re-running grows the pool instead of re-scanning the same
#                 boards; pin an explicit SEED for a reproducible batch)
#   MAX_SECONDS=… generation time budget (default 6000)
set -euo pipefail

COUNT="96"
KEY_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --key) KEY_ARG="$2"; shift 2 ;;
    *) COUNT="$1"; shift ;;
  esac
done

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BEN_HOME="${BEN_HOME:-$HOME/ben}"
VENV="${BEN_VENV:-$HOME/benv}"          # generation: Ben + TensorFlow (protobuf <6)
FB_VENV="${FB_VENV:-$HOME/fbenv}"       # push: firebase-admin (protobuf >=6)
PY="$VENV/bin/python"
FB_PY="$FB_VENV/bin/python"

# 1) Ensure the Ben engine + venv exist (idempotent; fast once cached).
# firebase-admin lives in a SEPARATE venv on purpose: it needs protobuf >=6,
# which is incompatible with the TensorFlow that Ben requires (protobuf <6).
PYTHON="${PYTHON:-python3.12}" bash "$REPO_DIR/scripts/setup_ben.sh" "$BEN_HOME" "$VENV"
if [ ! -x "$FB_PY" ]; then
  "${PYTHON:-python3.12}" -m venv "$FB_VENV"
  "$FB_VENV/bin/pip" install -q --upgrade pip
  "$FB_VENV/bin/pip" install -q -e "${REPO_DIR}[firestore]"
fi

# 2) Resolve the service-account key.
KEY_FILE=""
CLEANUP=0
if [ -n "$KEY_ARG" ]; then
  KEY_FILE="$KEY_ARG"
elif [ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]; then
  KEY_FILE="$GOOGLE_APPLICATION_CREDENTIALS"
elif [ -n "${FIREBASE_SERVICE_ACCOUNT:-}" ]; then
  KEY_FILE="$(mktemp)"; CLEANUP=1
  printf '%s' "$FIREBASE_SERVICE_ACCOUNT" > "$KEY_FILE"
fi
trap '[ "$CLEANUP" = 1 ] && rm -f "$KEY_FILE"' EXIT
if [ -z "$KEY_FILE" ] || [ ! -s "$KEY_FILE" ]; then
  echo "error: no Firebase service-account key found." >&2
  echo "  provide --key PATH, or set GOOGLE_APPLICATION_CREDENTIALS (path)," >&2
  echo "  or set FIREBASE_SERVICE_ACCOUNT (the JSON content)." >&2
  exit 1
fi

# 3) Generate the problems into data/.
# WORKERS>1 runs board-level parallel workers (each holds a ~1.2 GB engine);
# 0 = auto (min(3, cpus)). Default 3 to match the 4-core reference box.
#
# Default seed is UNIQUE PER RUN (epoch seconds, ×1000 for spacing). A day- or
# hour-flattened default made every re-run on the same day/hour re-derive the
# SAME boards -> identical problem ids -> the Firestore push skipped all of
# them ("uploaded 0"), so the pool never grew. Board scanning walks
# SEED..SEED+N, and forge runs take minutes, so consecutive runs sit well
# beyond that window and share no boards. Pin an explicit SEED for a
# reproducible batch.
SEED="${SEED:-$(date +%s)000}"
MODE="${MODE:-MP}"
echo ">> forging $COUNT lead problems (mode $MODE, seed $SEED, ${WORKERS:-3} workers)"
BEN_HOME="$BEN_HOME" "$PY" -m bridge_trainer.app.cli \
  lead-forge --mode "$MODE" --count "$COUNT" --seed "$SEED" \
  --pool "$REPO_DIR/data" \
  --workers "${WORKERS:-3}" --max-seconds "${MAX_SECONDS:-6000}"

# 4) Push the pool to Firestore (skips docs already present).
echo ">> pushing pool to Firestore"
"$FB_PY" -m bridge_trainer.app.cli pool push --pool "$REPO_DIR/data" --key "$KEY_FILE"
echo ">> done"
