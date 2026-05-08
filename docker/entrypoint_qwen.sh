#!/usr/bin/env bash
# qwen-code variant entrypoint: download model into MODEL_DIR (like entrypoint_repl_root_mem.sh),
# patch chat template, write ~/.qwen/settings.json, then start vLLM on :8000 and sleep.
set -euo pipefail

export BACKEND="${BACKEND:-vllm}"
export MODEL="${MODEL:-Qwen/Qwen3.5-122B-A10B-FP8}"
export TP_SIZE="${TP_SIZE:-2}"

MODEL_DIR="${MODEL_DIR:-/home/agent/models}"

if [[ "${DOWNLOAD_IN_CONTAINER:-0}" == "1" && "$BACKEND" == "vllm" ]]; then
  mkdir -p "$MODEL_DIR"
  SLUG="models--$(echo "$MODEL" | sed 's|/|--|g')"
  if [[ ! -d "$MODEL_DIR/hub/$SLUG" ]]; then
    echo "[entrypoint_qwen] Downloading HuggingFace model $MODEL into host-1 at $MODEL_DIR..."
    cd /opt/model-vllm
    source .venv/bin/activate
    export HF_HOME="$MODEL_DIR"
    export HUGGINGFACE_HUB_CACHE="$MODEL_DIR/hub"
    python3 -c "
from huggingface_hub import snapshot_download
snapshot_download('$MODEL')
"
    echo "[entrypoint_qwen] Model download complete."
  else
    echo "[entrypoint_qwen] Model already present at $MODEL_DIR/hub/$SLUG, skipping download."
  fi
fi

# Patch chat template (optional but harmless if no 'developer' role is used by qwen-code)
PATCHED_TEMPLATE="/tmp/patched_chat_template.jinja"
if [[ ! -f "$PATCHED_TEMPLATE" && -f /opt/model-vllm/patch_chat_template.py ]]; then
  echo "[entrypoint_qwen] Patching chat template..."
  cd /opt/model-vllm
  source .venv/bin/activate
  export HF_HOME="${MODEL_DIR}"
  python3 /opt/model-vllm/patch_chat_template.py "$MODEL" "$PATCHED_TEMPLATE" || echo "[entrypoint_qwen] WARNING: chat template patch failed, continuing"
fi

# Write ~/.qwen/settings.json for the agent user.
# Ensure dir is owned by agent (container restart can desync ownership); remove stale file
# so Python's open(w) doesn't hit EACCES when overwriting.
mkdir -p /home/agent/.qwen
chown -R agent:agent /home/agent/.qwen
rm -f /home/agent/.qwen/settings.json
# Pass env explicitly to avoid sudoers env_reset dropping MODEL/VLLM_BASE_URL etc.
sudo -u agent env \
  HOME=/home/agent \
  MODEL="$MODEL" \
  BACKEND="$BACKEND" \
  TP_SIZE="$TP_SIZE" \
  VLLM_BASE_URL="${VLLM_BASE_URL:-http://127.0.0.1:8000/v1}" \
  VLLM_API_KEY="${VLLM_API_KEY:-not-needed}" \
  HF_HOME="${MODEL_DIR:-/home/agent/models}" \
  python3 /write_qwen_config.py

echo "[entrypoint_qwen] Starting vLLM on port 8000..."
sudo -u agent env \
  MODEL="$MODEL" \
  BACKEND="$BACKEND" \
  TP_SIZE="$TP_SIZE" \
  HF_HOME="${MODEL_DIR:-/home/agent/models}" \
  NCCL_P2P_DISABLE="${NCCL_P2P_DISABLE:-1}" \
  /opt/model-vllm/start.sh &
VLLM_PID=$!

VLLM_READY=0
for i in $(seq 1 180); do
  curl -sf http://127.0.0.1:8000/v1/models >/dev/null 2>&1 && { VLLM_READY=1; break; }
  sleep 5
done

if [[ "$VLLM_READY" -ne 1 ]]; then
  echo "[entrypoint_qwen] ERROR: vLLM did not become ready at http://127.0.0.1:8000" >&2
  exit 1
fi

echo "[entrypoint_qwen] vLLM ready. Container staying alive."
exec sleep infinity
