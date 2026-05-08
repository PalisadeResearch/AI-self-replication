#!/usr/bin/env bash
set -euo pipefail
LOG_DIR="/home/agent/.logs"
mkdir -p "$LOG_DIR"
RUN_ID=$(date +%s)
JSONL="$LOG_DIR/run-$RUN_ID.jsonl"
OUT="$LOG_DIR/run-$RUN_ID-output.txt"
if [[ "${1:-}" == "--stdin" ]]; then
  PROMPT=$(cat)
  PROMPT_FILE=""
elif [[ -n "${1:-}" && -f "${1:-}" ]]; then
  PROMPT_FILE="$1"
  PROMPT=$(cat "$1")
else
  PROMPT="${*:-}"
  PROMPT_FILE=""
fi
if [[ -z "$PROMPT" ]]; then echo "No prompt provided" >&2; exit 1; fi

if [[ "${API_PROVIDER:-openai}" == "raw" ]]; then
  # Raw SDK agent loop (Anthropic/OpenAI/Google)
  AGENT_ARGS=(--model "${MODEL:-gpt-5.4}" --json-log "$JSONL" --max-steps "${MAX_AGENT_STEPS:-80}")
  if [[ -n "$PROMPT_FILE" ]]; then
    AGENT_ARGS+=(--prompt-file "$PROMPT_FILE")
  else
    AGENT_ARGS+=(--prompt "$PROMPT")
  fi
  python3 /opt/raw_agent.py "${AGENT_ARGS[@]}" 2>&1 | tee "$OUT"
elif [[ "${API_PROVIDER:-openai}" == "anthropic" ]]; then
  # Claude Code CLI: native Anthropic API support
  claude -p "$PROMPT" \
    --dangerously-skip-permissions \
    --model "${MODEL:-claude-opus-4-6}" \
    --output-format stream-json \
    --verbose \
    --max-turns 50 \
    2>&1 | tee "$JSONL"
else
  # Codex CLI: OpenAI API
  codex exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check --json -o "$OUT" "$PROMPT" 2>&1 | tee "$JSONL"
fi
