#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude/state"
STAMP_FILE="$STATE_DIR/last_validation_ok"
mkdir -p "$STATE_DIR"

date +%s > "$STAMP_FILE"
exit 0
