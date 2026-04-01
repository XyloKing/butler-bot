#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude/state"
REVIEW_FILE="$STATE_DIR/last_human_review_ok"
mkdir -p "$STATE_DIR"

date +%s > "$REVIEW_FILE"
exit 0
