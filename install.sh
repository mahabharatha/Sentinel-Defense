#!/usr/bin/env bash
# Sentinel one-click installer.
#
# Deterministic, reproducible setup for local development, CI, and servers.
# Idempotent: safe to re-run. Will not overwrite an existing venv unless --force
# is passed.
#
# Usage:
#   ./install.sh              # full install with all framework dependencies
#   ./install.sh --core       # lightweight install (API + schemas only)
#   ./install.sh --force      # wipe and recreate the venv
#   ./install.sh --skip-data  # do not scaffold data/ directories
#   ./install.sh --help       # show this message
#
# Exit codes:
#   0  success
#   1  missing prerequisite (python3.11+, pip, etc.)
#   2  dependency install failed
#   3  post-install verification failed

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
cd "${REPO_ROOT}"

PROFILE="full"
FORCE_VENV=0
SKIP_DATA=0

for arg in "$@"; do
  case "$arg" in
    --core) PROFILE="core" ;;
    --full) PROFILE="full" ;;
    --force) FORCE_VENV=1 ;;
    --skip-data) SKIP_DATA=1 ;;
    --help|-h)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      echo "Run '$0 --help' for usage." >&2
      exit 1
      ;;
  esac
done

log() { printf "[install] %s\n" "$*"; }
err() { printf "[install][error] %s\n" "$*" >&2; }

# --- 1. Prerequisite check ---
find_python() {
  for candidate in python3.11 python3.12 python3.13 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      local version
      version="$("$candidate" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
      local major minor
      major="${version%%.*}"
      minor="${version##*.}"
      if [[ "$major" -eq 3 && "$minor" -ge 11 ]]; then
        echo "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON="$(find_python || true)"
if [[ -z "$PYTHON" ]]; then
  err "Python 3.11+ is required (project pins requires-python >=3.11)."
  err "Install it via pyenv, Homebrew, apt, or from python.org and re-run."
  exit 1
fi
log "using $PYTHON ($($PYTHON --version 2>&1))"

# --- 2. Virtualenv ---
VENV_DIR="${REPO_ROOT}/venv"
if [[ -d "$VENV_DIR" && "$FORCE_VENV" -eq 1 ]]; then
  log "removing existing venv/ (per --force)"
  rm -rf "$VENV_DIR"
fi
if [[ ! -d "$VENV_DIR" ]]; then
  log "creating venv at $VENV_DIR"
  "$PYTHON" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

log "upgrading pip / wheel / setuptools"
python -m pip install --upgrade pip wheel setuptools >/dev/null

# --- 3. Requirements ---
if [[ "$PROFILE" == "core" ]]; then
  REQ_FILE="requirements-core.txt"
  log "installing CORE dependencies from $REQ_FILE"
else
  REQ_FILE="requirements.txt"
  log "installing FULL dependencies from $REQ_FILE (this can take several minutes on first run)"
fi

if ! python -m pip install -r "$REQ_FILE"; then
  err "dependency install failed. Inspect the pip output above."
  exit 2
fi

# --- 4. Data directory scaffolding ---
if [[ "$SKIP_DATA" -eq 0 ]]; then
  log "scaffolding data/ layout"
  mkdir -p data/jobs data/job_reports data/demo data/matplotlib_cache
  mkdir -p data/textattack_cache data/textattack_runs data/pyrit_multimodal_smoke
  mkdir -p user_wrappers
  # Initialize empty index files if missing (matches storage.ensure_dirs contract)
  [[ -f data/wrappers.json ]] || echo '{"wrappers": []}' > data/wrappers.json
  [[ -f data/templates.json ]] || echo '{"templates": []}' > data/templates.json
fi

# --- 5. Post-install verification ---
log "verifying installation"
python - <<'PY'
import importlib, sys
required = ["fastapi", "uvicorn", "pydantic", "httpx"]
missing = []
for mod in required:
    try:
        importlib.import_module(mod)
    except ImportError:
        missing.append(mod)
if missing:
    print(f"[install][error] core modules missing after install: {missing}")
    sys.exit(3)
print("[install] core modules import cleanly")
PY

# --- 6. Summary ---
log "install complete."
log "activate the environment with:  source venv/bin/activate"
log "start the API server with:      python run.py"
log "run tests with:                 pytest tests/ -v"
