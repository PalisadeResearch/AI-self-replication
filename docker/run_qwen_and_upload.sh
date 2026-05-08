#!/usr/bin/env bash
# Run qwen-code with the provided prompt. Writes stream-json events to $JSONL for Langfuse upload.
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

if [[ -z "$PROMPT" ]]; then
  echo "No prompt provided" >&2
  exit 1
fi

# --yolo: auto-approve all tool calls (container is isolated)
# --output-format stream-json: structured JSONL events to stdout (same shape as gemini-cli)
qwen -p "$PROMPT" --yolo --output-format stream-json 2>&1 | tee "$JSONL"

# Best-effort: extract last text response for a human-readable output file
python3 - "$JSONL" "$OUT" <<'PY' || true
import json, sys
jsonl_path, out_path = sys.argv[1], sys.argv[2]
last_text = None
for line in open(jsonl_path):
    line = line.strip()
    if not line.startswith("{"):
        continue
    try:
        ev = json.loads(line)
    except Exception:
        continue
    if ev.get("type") == "result" and ev.get("subtype") == "success" and ev.get("result"):
        last_text = ev["result"]
    elif ev.get("type") == "assistant":
        msg = ev.get("message") or {}
        parts = [b.get("text", "") for b in msg.get("content", []) if b.get("type") == "text"]
        if parts:
            last_text = "".join(parts)
if last_text:
    open(out_path, "w").write(last_text)
PY
