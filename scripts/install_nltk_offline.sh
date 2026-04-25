#!/usr/bin/env bash
# Manually install the NLTK corpora that TextAttack constraints need by
# fetching the upstream zip files with curl (which uses macOS's system CA
# trust store) and unpacking them into the venv's nltk_data directory.
#
# Use this when `python -c "import nltk; nltk.download(...)"` keeps failing
# with `CERTIFICATE_VERIFY_FAILED` even after pointing Python at certifi.
#
# Usage:
#     bash /Users/macmacmac/Documents/sentinel/scripts/install_nltk_offline.sh
#
# Idempotent: a resource that's already installed is skipped silently.

set -uo pipefail

REPO_ROOT="/Users/macmacmac/Documents/sentinel"
VENV_NLTK="${REPO_ROOT}/venv/nltk_data"

# Each entry: <subdir>:<resource_name>
RESOURCES=(
    "taggers:averaged_perceptron_tagger"
    "taggers:averaged_perceptron_tagger_eng"
    "taggers:universal_tagset"
    "tokenizers:punkt"
    "tokenizers:punkt_tab"
    "corpora:stopwords"
    "corpora:wordnet"
    "corpora:omw-1.4"
)

BASE_URL="https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages"

mkdir -p "$VENV_NLTK"
log() { printf "[nltk] %s\n" "$*"; }

ok=0
fail=0
for entry in "${RESOURCES[@]}"; do
    subdir="${entry%%:*}"
    name="${entry##*:}"
    target="${VENV_NLTK}/${subdir}/${name}"
    if [ -d "$target" ] && [ "$(ls -A "$target" 2>/dev/null)" ]; then
        log "skip ${subdir}/${name} (already installed)"
        ok=$((ok+1))
        continue
    fi
    mkdir -p "${VENV_NLTK}/${subdir}"
    url="${BASE_URL}/${subdir}/${name}.zip"
    tmp="$(mktemp /tmp/nltk_${name}_XXXX.zip)"
    log "fetch ${subdir}/${name}"
    if curl -fsSL "$url" -o "$tmp"; then
        if unzip -q -o "$tmp" -d "${VENV_NLTK}/${subdir}/"; then
            log "  installed -> ${target}"
            ok=$((ok+1))
        else
            log "  unzip failed for ${name}"
            fail=$((fail+1))
        fi
    else
        log "  download failed for ${url}"
        fail=$((fail+1))
    fi
    rm -f "$tmp"
done

echo
log "summary: ${ok} installed, ${fail} failed"
log "nltk_data root: ${VENV_NLTK}"
echo
echo "Sanity check — confirm the perceptron tagger landed:"
ls "${VENV_NLTK}/taggers/" 2>&1
echo

if [ "$fail" -gt 0 ]; then
    exit 1
fi
exit 0
