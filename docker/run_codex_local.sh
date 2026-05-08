#!/usr/bin/env bash
set -euo pipefail
LOG_DIR="/home/agent/.logs"
mkdir -p "$LOG_DIR"
RUN_ID=$(date +%s)
JSONL="$LOG_DIR/run-$RUN_ID.jsonl"
OUT="$LOG_DIR/run-$RUN_ID-output.txt"
if [[ "${1:-}" == "--stdin" ]]; then
  PROMPT=$(cat)
elif [[ -n "${1:-}" && -f "${1:-}" ]]; then
  PROMPT=$(cat "$1")
else
  PROMPT="${*:-}"
fi
if [[ -z "$PROMPT" ]]; then echo "No prompt provided" >&2; exit 1; fi
codex exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check --json -o "$OUT" "$PROMPT" 2>&1 | tee "$JSONL"
