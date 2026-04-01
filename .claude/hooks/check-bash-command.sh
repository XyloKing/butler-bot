#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude/state"
STAMP_FILE="$STATE_DIR/last_validation_ok"
mkdir -p "$STATE_DIR"

payload="$(cat)"
command_text="$(printf '%s' "$payload" | tr '\n' ' ')"

allow_patterns=(
  "pytest"
  "python -m pytest"
  "python .*\\.py"
  "python3 .*\\.py"
  "uv run"
  "poetry run"
  "npm test"
  "pnpm test"
  "yarn test"
  "bun test"
  "npm run test"
  "pnpm run test"
  "npm run lint"
  "pnpm run lint"
  "npm run build"
  "pnpm run build"
  "\\.claude/hooks/mark-human-review\\.sh"
)

for pattern in "${allow_patterns[@]}"; do
  if echo "$command_text" | grep -Eiq "$pattern"; then
    cat <<'JSON'
{"permissionDecision":"allow"}
JSON
    exit 0
  fi
done

if echo "$command_text" | grep -Eiq 'git push'; then
  now=$(date +%s)

  if [[ ! -f "$STAMP_FILE" ]]; then
    cat <<'JSON'
{"permissionDecision":"deny","permissionDecisionReason":"Blocked git push: no recent validation recorded. Run validation and real bot-flow testing first."}
JSON
    exit 0
  fi

  stamp=$(cat "$STAMP_FILE" 2>/dev/null || echo 0)
  age=$(( now - stamp ))

  if (( age > 1800 )); then
    cat <<'JSON'
{"permissionDecision":"deny","permissionDecisionReason":"Blocked git push: validation is stale. Re-run validation and real-flow testing before pushing."}
JSON
    exit 0
  fi
fi

cat <<'JSON'
{"permissionDecision":"allow"}
JSON
exit 0
