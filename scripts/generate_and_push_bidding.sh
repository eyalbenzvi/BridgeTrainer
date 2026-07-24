#!/usr/bin/env bash
# Generate BIDDING problems with the Ben engine, classify them into the
# 10-category taxonomy, and push them to Firestore.
#
# This is the leads pipeline's sibling for bidding problems, with one extra
# step: bidding categories are an LLM judgment (leads are a mechanical fact of
# the contract), so between forge and push we run scripts/classify_pool.py.
# The classifier's default backend is GitHub Models (free inference tier), so
# the whole pipeline runs unattended on a GitHub Actions runner — no Claude
# Code session and no paid tokens. It needs a token with `models:read` in
# GITHUB_TOKEN (or GITHUB_MODELS_TOKEN); the forge-bidding.yml workflow grants
# the job `permissions: models: read`, which puts the scope on GITHUB_TOKEN.
#
# Firestore credentials (a Firebase service-account private key) are read, in
# order:
#   1. --key <path>                    explicit file
#   2. $GOOGLE_APPLICATION_CREDENTIALS path to the JSON file
#   3. $FIREBASE_SERVICE_ACCOUNT       the full JSON *content* (temp file,
#                                      deleted on exit)
# The key is never written inside the repo and never committed.
#
# Usage:  scripts/generate_and_push_bidding.sh [COUNT] [--key PATH]
#   COUNT         problems to generate (default 24)
#   SEED=...      override the RNG seed (default: unique per run, time-based —
#                 so re-running grows the pool instead of re-scanning the same
#                 boards; pin an explicit SEED for a reproducible batch)
#   MAX_SECONDS=… generation time budget (default 6000)
#   CHUNK_SIZE=…  bidding problems per GitHub Models call (default: the
#                 classifier's own small default; a failing chunk self-splits)
set -euo pipefail

COUNT="24"
KEY_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --key) KEY_ARG="$2"; shift 2 ;;
    *) COUNT="$1"; shift ;;
  esac
done

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BEN_HOME="${BEN_HOME:-$HOME/ben}"
VENV="${BEN_VENV:-$HOME/benv}"          # generation + classify: Ben + numpy
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
# Default seed is UNIQUE PER RUN (epoch seconds, x1000 for spacing): board
# scanning walks SEED..SEED+N, forge takes minutes, so consecutive runs share
# no boards and the pool grows instead of the push skipping same-id duplicates.
# Pin an explicit SEED for a reproducible batch.
SEED="${SEED:-$(date +%s)000}"
echo ">> forging $COUNT bidding problems (seed $SEED, ${WORKERS:-3} workers)"
BEN_HOME="$BEN_HOME" "$PY" -m bridge_trainer.app.cli \
  ben-forge --count "$COUNT" --seed "$SEED" \
  --pool "$REPO_DIR/data" \
  --workers "${WORKERS:-3}" --max-seconds "${MAX_SECONDS:-6000}"

# 4) Classify: difficulty (pure) + type (GitHub Models). Idempotent and
# resumable — already-classified records are skipped. Best-effort: a stray
# per-problem failure (rare — a failing chunk self-splits and retries) leaves
# that record untyped and is reported below, but must not block pushing the
# problems that DID classify.
echo ">> classifying bidding problems (GitHub Models)"
CLASSIFY_RC=0
CHUNK_ARGS=()
[ -n "${CHUNK_SIZE:-}" ] && CHUNK_ARGS=(--chunk-size "$CHUNK_SIZE")
"$PY" "$REPO_DIR/scripts/classify_pool.py" "$REPO_DIR/data" \
  "${CHUNK_ARGS[@]}" || CLASSIFY_RC=$?
[ "$CLASSIFY_RC" = 0 ] || echo ">> WARNING: classify reported failures (rc=$CLASSIFY_RC)"

# 5) Push the pool to Firestore (skips docs already present).
echo ">> pushing pool to Firestore"
"$FB_PY" -m bridge_trainer.app.cli pool push --pool "$REPO_DIR/data" --key "$KEY_FILE"
echo ">> done"
exit "$CLASSIFY_RC"
