#!/usr/bin/env bash
set -euo pipefail

# Add a collaborator to a GitHub repository using the official REST API.
#
# Official GitHub docs:
# https://docs.github.com/en/rest/collaborators/collaborators#add-a-repository-collaborator
#
# Notes:
# - This script expects a GitHub username, because the REST collaborator endpoint
#   is /repos/{owner}/{repo}/collaborators/{username}.
# - For personal repositories, omitting the permission value is the safest default.
# - Use a fine-grained PAT or classic token with repository admin rights.

OWNER="${GITHUB_OWNER:-BartAttack}"
REPO="${GITHUB_REPO:-universal-adverserial-ai-testing-kit}"
TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
PERMISSION="${GITHUB_PERMISSION:-}"
API_VERSION="${GITHUB_API_VERSION:-2022-11-28}"

usage() {
  cat <<'EOF'
Usage:
  GH_TOKEN=github_pat_xxx ./scripts/add_repo_collaborator.sh <github-username> [permission]

Examples:
  GH_TOKEN=github_pat_xxx ./scripts/add_repo_collaborator.sh octocat
  GH_TOKEN=github_pat_xxx ./scripts/add_repo_collaborator.sh octocat push

Optional environment variables:
  GITHUB_OWNER        Repository owner. Default: BartAttack
  GITHUB_REPO         Repository name. Default: universal-adverserial-ai-testing-kit
  GH_TOKEN            GitHub token. Falls back to GITHUB_TOKEN.
  GITHUB_PERMISSION   Optional permission value to send in the request body.
  GITHUB_API_VERSION  GitHub API version header. Default: 2022-11-28

Valid permission examples:
  pull, triage, push, maintain, admin

Important:
  The GitHub REST collaborator endpoint expects a GitHub username, not an email address.
  If you only know an email address, invite the person through the GitHub web UI or ask them for their GitHub username.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 1 || $# -gt 2 ]]; then
  usage
  exit 1
fi

USERNAME="$1"
if [[ $# -eq 2 ]]; then
  PERMISSION="$2"
fi

if [[ -z "$TOKEN" ]]; then
  echo "ERROR: GH_TOKEN or GITHUB_TOKEN is required." >&2
  exit 1
fi

if [[ "$USERNAME" == *"@"* ]]; then
  echo "ERROR: '$USERNAME' looks like an email address." >&2
  echo "The GitHub REST collaborator endpoint requires a GitHub username." >&2
  echo "Use the GitHub web UI to invite by email, or rerun this script with the collaborator's GitHub username." >&2
  exit 1
fi

TMP_BODY="$(mktemp)"
trap 'rm -f "$TMP_BODY"' EXIT

URL="https://api.github.com/repos/${OWNER}/${REPO}/collaborators/${USERNAME}"

if [[ -n "$PERMISSION" ]]; then
  HTTP_CODE="$(
    curl -sS -o "$TMP_BODY" -w "%{http_code}" \
      -L \
      -X PUT \
      -H "Accept: application/vnd.github+json" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "X-GitHub-Api-Version: ${API_VERSION}" \
      "$URL" \
      -d "{\"permission\":\"${PERMISSION}\"}"
  )"
else
  HTTP_CODE="$(
    curl -sS -o "$TMP_BODY" -w "%{http_code}" \
      -L \
      -X PUT \
      -H "Accept: application/vnd.github+json" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "X-GitHub-Api-Version: ${API_VERSION}" \
      "$URL"
  )"
fi

case "$HTTP_CODE" in
  201)
    echo "Invitation created for '${USERNAME}' on ${OWNER}/${REPO}."
    cat "$TMP_BODY"
    ;;
  204)
    echo "Collaborator '${USERNAME}' already has access, or access was granted without a new invitation."
    ;;
  403)
    echo "ERROR: Forbidden. Check that your token has admin access to the repository." >&2
    cat "$TMP_BODY" >&2
    exit 1
    ;;
  404)
    echo "ERROR: Repository or user not found, or the token cannot access the repository." >&2
    cat "$TMP_BODY" >&2
    exit 1
    ;;
  422)
    echo "ERROR: Validation failed or GitHub rejected the invite." >&2
    cat "$TMP_BODY" >&2
    exit 1
    ;;
  *)
    echo "ERROR: Unexpected HTTP status ${HTTP_CODE}." >&2
    cat "$TMP_BODY" >&2
    exit 1
    ;;
esac

