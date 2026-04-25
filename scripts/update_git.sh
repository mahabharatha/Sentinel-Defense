#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./scripts/update_git.sh [-m "commit message"] [--no-push]

Examples:
  ./scripts/update_git.sh
  ./scripts/update_git.sh -m "Update README and UI"
  ./scripts/update_git.sh --no-push

Behavior:
  - stages all tracked and untracked changes with git add -A
  - creates a commit if there are staged changes
  - pushes the current branch to origin by default
  - if no upstream exists yet, pushes with -u origin <branch>
EOF
}

COMMIT_MESSAGE=""
PUSH_CHANGES=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    -m|--message)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: $1 requires a commit message." >&2
        exit 1
      fi
      COMMIT_MESSAGE="$2"
      shift 2
      ;;
    --no-push)
      PUSH_CHANGES=0
      shift
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

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "ERROR: This directory is not inside a git repository." >&2
  exit 1
fi

BRANCH="$(git branch --show-current)"
if [[ -z "$BRANCH" ]]; then
  echo "ERROR: Could not determine the current git branch." >&2
  exit 1
fi

echo "Current branch: $BRANCH"
echo "Staging changes..."
git add -A

if git diff --cached --quiet; then
  echo "No staged changes detected. Nothing to commit."
else
  if [[ -z "$COMMIT_MESSAGE" ]]; then
    COMMIT_MESSAGE="Update project files $(date '+%Y-%m-%d %H:%M:%S')"
  fi

  echo "Creating commit: $COMMIT_MESSAGE"
  git commit -m "$COMMIT_MESSAGE"
fi

if [[ "$PUSH_CHANGES" -eq 0 ]]; then
  echo "Skipping push because --no-push was provided."
  exit 0
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  echo "ERROR: No 'origin' remote is configured." >&2
  echo "Add a remote first, for example:" >&2
  echo "  git remote add origin git@github.com:YOUR_USER/YOUR_REPO.git" >&2
  exit 1
fi

if git rev-parse --abbrev-ref --symbolic-full-name "@{u}" >/dev/null 2>&1; then
  echo "Pushing to origin/$BRANCH..."
  git push
else
  echo "No upstream branch configured. Pushing with upstream tracking..."
  git push -u origin "$BRANCH"
fi

echo "Done."
