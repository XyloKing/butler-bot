#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude/state"
STAMP_FILE="$STATE_DIR/last_validation_ok"
MAX_AGE_SECONDS=1800

mkdir -p "$STATE_DIR"

now=$(date +%s)

if [[ ! -f "$STAMP_FILE" ]]; then
  cat <<'JSON'
{"permissionDecision":"deny","permissionDecisionReason":"Blocked: no recent validation marker found. Run validation and the real bot flow first, then retry."}
JSON
  exit 0
fi

stamp=$(cat "$STAMP_FILE" 2>/dev/null || echo 0)
age=$(( now - stamp ))

if (( age > MAX_AGE_SECONDS )); then
  cat <<'JSON'
{"permissionDecision":"deny","permissionDecisionReason":"Blocked: validation marker is stale. Re-run validation and real bot testing before editing again."}
JSON
  exit 0
fi

cat <<'JSON'
{"permissionDecision":"allow"}
JSON
exit 0
