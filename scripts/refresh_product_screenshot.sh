#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./scripts/refresh_product_screenshot.sh --source /absolute/path/to/new-screenshot.png [--label "UI refresh"]

Examples:
  ./scripts/refresh_product_screenshot.sh --source /Users/me/Desktop/product-screenshot.png
  ./scripts/refresh_product_screenshot.sh --source /Users/me/Desktop/product-screenshot.png --label "Added preflight and live status"

What it does:
  - validates the source screenshot exists and is a PNG
  - archives the current repo screenshot, if present
  - copies the new screenshot into docs/images/product-screenshot-current.png
  - records refresh metadata in docs/images/product-screenshot.json

Notes:
  - keep using the same repo target path so README.md and docs/index.html do not need edits
  - macOS screenshots are PNG by default, so they work well with this flow
EOF
}

SOURCE=""
LABEL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --source requires a file path." >&2
        exit 1
      fi
      SOURCE="$2"
      shift 2
      ;;
    --label)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --label requires text." >&2
        exit 1
      fi
      LABEL="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$SOURCE" ]]; then
  echo "ERROR: --source is required." >&2
  usage >&2
  exit 1
fi

if [[ ! -f "$SOURCE" ]]; then
  echo "ERROR: Source file not found: $SOURCE" >&2
  exit 1
fi

case "${SOURCE##*.}" in
  png|PNG)
    ;;
  *)
    echo "ERROR: Source must be a PNG file so the repo keeps a consistent screenshot asset." >&2
    exit 1
    ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGE_DIR="$REPO_ROOT/docs/images"
ARCHIVE_DIR="$IMAGE_DIR/archive"
TARGET_IMAGE="$IMAGE_DIR/product-screenshot-current.png"
TARGET_META="$IMAGE_DIR/product-screenshot.json"

mkdir -p "$ARCHIVE_DIR"

timestamp_utc="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
timestamp_slug="$(date -u '+%Y%m%dT%H%M%SZ')"
archive_path=""

if [[ -f "$TARGET_IMAGE" ]]; then
  archive_path="$ARCHIVE_DIR/product-screenshot-current-$timestamp_slug.png"
  cp "$TARGET_IMAGE" "$archive_path"
  echo "Archived previous screenshot to: $archive_path"
fi

cp "$SOURCE" "$TARGET_IMAGE"
echo "Updated screenshot: $TARGET_IMAGE"

cat > "$TARGET_META" <<EOF
{
  "asset": "docs/images/product-screenshot-current.png",
  "updated_at_utc": "$timestamp_utc",
  "source_basename": "$(basename "$SOURCE")",
  "label": "${LABEL}",
  "archived_previous_asset": "$(basename "$archive_path")"
}
EOF

echo "Wrote metadata: $TARGET_META"
echo
echo "Next step:"
echo "  Review README.md and docs/index.html in GitHub or locally. Both reference the same screenshot path."
