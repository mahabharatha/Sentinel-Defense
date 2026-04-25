#!/usr/bin/env bash
# One-shot smoke runner: stop any old server, start a fresh one, wait for it
# to come up, run the full built-in template smoke, collect the output,
# and stop the server on exit.
#
# Just run this one file from anywhere:
#     /Users/macmacmac/Documents/sentinel/scripts/run_full_smoke.sh
#
# Or from inside the repo:
#     bash scripts/run_full_smoke.sh
#
# Environment knobs (all optional):
#   SENTINEL_HOST      default http://127.0.0.1:8000
#   SENTINEL_TIMEOUT   per-template seconds, default 900
#   SENTINEL_SKIP      comma list of template indexes to skip
#   SENTINEL_ONLY      comma list of template indexes to run
#   SENTINEL_EXTRA     extra args to forward to the smoke driver
#
# Exit codes:
#   0  every template clean
#   1  one or more templates had issues
#   2  server never came up
#   3  venv missing or broken

set -uo pipefail

REPO_ROOT="/Users/macmacmac/Documents/sentinel"
HOST_URL="${SENTINEL_HOST:-http://127.0.0.1:8000}"
PORT="$(printf '%s' "$HOST_URL" | sed -E 's#^https?://[^:]+:##; s#/.*##')"
TIMEOUT_PER_TEMPLATE="${SENTINEL_TIMEOUT:-900}"
OUT_DIR="${REPO_ROOT}/data/smoke_runs"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_JSON="${OUT_DIR}/smoke_${STAMP}.json"
SERVER_LOG="${OUT_DIR}/server_${STAMP}.log"
SMOKE_LOG="${OUT_DIR}/smoke_${STAMP}.log"

mkdir -p "$OUT_DIR"

log() { printf "[smoke] %s\n" "$*" | tee -a "$SMOKE_LOG"; }
fail() { printf "[smoke][fatal] %s\n" "$*" | tee -a "$SMOKE_LOG" >&2; exit "${2:-1}"; }

# --- 1. Sanity checks ---
cd "$REPO_ROOT" || fail "repo not found at $REPO_ROOT" 3
if [ ! -x "venv/bin/python" ]; then
    fail "venv missing or broken at $REPO_ROOT/venv (run ./install.sh)" 3
fi

log "repo: $REPO_ROOT"
log "host: $HOST_URL"
log "output json: $OUT_JSON"
log "server log: $SERVER_LOG"

# --- 2. Stop any old server on the same port ---
log "stopping any prior sentinel server"
pkill -f "run.py" 2>/dev/null || true
sleep 1

# --- 3. Clear stale bytecode so the restarted server picks up edits ---
log "clearing __pycache__ (skipping venv)"
find "$REPO_ROOT" -type d -name __pycache__ -not -path "*/venv/*" -exec rm -rf {} + 2>/dev/null || true

# --- 4. Start the server in the background ---
log "starting server in background"
(
    cd "$REPO_ROOT"
    ./venv/bin/python run.py --host 127.0.0.1 --port "$PORT"
) > "$SERVER_LOG" 2>&1 &
SERVER_PID=$!
log "server pid: $SERVER_PID"

cleanup() {
    log "stopping server (pid $SERVER_PID)"
    kill "$SERVER_PID" 2>/dev/null || true
    sleep 1
    kill -9 "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# --- 5. Wait for /api/options to return 200 ---
log "waiting for server to come up on $HOST_URL"
READY=0
for i in $(seq 1 60); do
    if "${REPO_ROOT}/venv/bin/python" -c "import urllib.request; urllib.request.urlopen('${HOST_URL}/api/options', timeout=2)" >/dev/null 2>&1; then
        READY=1
        log "server ready after ${i}s"
        break
    fi
    sleep 1
done
if [ "$READY" -eq 0 ]; then
    log "server did not come up; last 30 lines of server log:"
    tail -30 "$SERVER_LOG" | sed 's/^/  | /' | tee -a "$SMOKE_LOG"
    exit 2
fi

# --- 6. Build the smoke command ---
SMOKE_ARGS=(--host "$HOST_URL" --timeout "$TIMEOUT_PER_TEMPLATE" --json-out "$OUT_JSON")
if [ -n "${SENTINEL_ONLY:-}" ]; then
    SMOKE_ARGS+=(--only "$SENTINEL_ONLY")
fi
if [ -n "${SENTINEL_SKIP:-}" ]; then
    SMOKE_ARGS+=(--skip "$SENTINEL_SKIP")
fi
if [ -n "${SENTINEL_EXTRA:-}" ]; then
    # shellcheck disable=SC2206
    EXTRA_ARR=(${SENTINEL_EXTRA})
    SMOKE_ARGS+=("${EXTRA_ARR[@]}")
fi

log "running smoke driver: ${SMOKE_ARGS[*]}"
set +e
# PYTHONUNBUFFERED=1 forces line-by-line flushing through the tee pipe so
# per-template progress is visible in real time instead of appearing only
# after the driver finishes.
PYTHONUNBUFFERED=1 "${REPO_ROOT}/venv/bin/python" -u "${REPO_ROOT}/scripts/smoke_all_builtins.py" "${SMOKE_ARGS[@]}" 2>&1 | tee -a "$SMOKE_LOG"
RC=${PIPESTATUS[0]}
set -e

log "smoke driver exited with rc=$RC"
log "full smoke log:   $SMOKE_LOG"
log "verdict json:     $OUT_JSON"
log "server log:       $SERVER_LOG"

# trap already stops the server
exit "$RC"
