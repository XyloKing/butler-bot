#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude/state"
REVIEW_FILE="$STATE_DIR/last_human_review_ok"
MAX_AGE_SECONDS=1800

mkdir -p "$STATE_DIR"

now=$(date +%s)

if [[ ! -f "$REVIEW_FILE" ]]; then
  cat <<'JSON'
{"permissionDecision":"deny","permissionDecisionReason":"Blocked: no recent human-code review marker found. Review the code for AI-shaped redundancy, bad abstractions, robotic naming, and maintainability, then mark review complete."}
JSON
  exit 0
fi

stamp=$(cat "$REVIEW_FILE" 2>/dev/null || echo 0)
age=$(( now - stamp ))

if (( age > MAX_AGE_SECONDS )); then
  cat <<'JSON'
{"permissionDecision":"deny","permissionDecisionReason":"Blocked: human-code review marker is stale. Re-check code quality and mark review complete again."}
JSON
  exit 0
fi

cat <<'JSON'
{"permissionDecision":"allow"}
JSON
exit 0
