#!/usr/bin/env bash
# Replication-host entrypoint:
#   1. Optionally downloads model weights inside the container (when
#      DOWNLOAD_IN_CONTAINER=1; needs temporary network access at startup).
#   2. Patches the model's chat template so Codex's 'developer' role is accepted.
#   3. Writes ~/.codex/config.toml via /write_codex_config.py.
#   4. Starts vLLM (:8001) + Responses->Chat proxy (:8000) in the background.
#   5. Waits for the proxy to serve /v1/models, then blocks on sleep infinity.
set -euo pipefail

export BACKEND="${BACKEND:-vllm}"
export MODEL="${MODEL:-Qwen/Qwen3.5-122B-A10B-FP8}"
export TP_SIZE="${TP_SIZE:-2}"

# MODEL_DIR: where to put HF cache inside the container.
#  - With --ephemeral-dir on the host, /data/models is mounted from ephemeral.
#  - Otherwise /home/agent/models (container filesystem).
MODEL_DIR="${MODEL_DIR:-/home/agent/models}"

mkdir -p "$HOME/.codex" "$HOME/.cache/huggingface" "$MODEL_DIR"

if [[ "${DOWNLOAD_IN_CONTAINER:-0}" == "1" && "$BACKEND" == "vllm" ]]; then
  SLUG="models--$(echo "$MODEL" | sed 's|/|--|g')"
  if [[ ! -d "$MODEL_DIR/hub/$SLUG" ]]; then
    echo "[entrypoint] Downloading HuggingFace model $MODEL into $MODEL_DIR (no host mount)..."
    cd /opt/model-vllm
    source .venv/bin/activate
    export HF_HOME="$MODEL_DIR"
    export HUGGINGFACE_HUB_CACHE="$MODEL_DIR/hub"
    python3 -c "from huggingface_hub import snapshot_download; snapshot_download('$MODEL')"
    echo "[entrypoint] Model download complete."
  else
    echo "[entrypoint] Model already present at $MODEL_DIR/hub/$SLUG, skipping download."
  fi
fi

# Patch chat template: Codex sends role='developer' which Qwen3.5 doesn't
# recognise by default.
PATCHED_TEMPLATE="/tmp/patched_chat_template.jinja"
if [[ ! -f "$PATCHED_TEMPLATE" && -f /opt/model-vllm/patch_chat_template.py ]]; then
  echo "[entrypoint] Patching chat template for developer role support..."
  cd /opt/model-vllm
  source .venv/bin/activate
  export HF_HOME="$MODEL_DIR"
  python3 /opt/model-vllm/patch_chat_template.py "$MODEL" "$PATCHED_TEMPLATE" \
    || echo "[entrypoint] WARNING: chat template patch failed, continuing without patch"
fi

# Write Codex config (points at local proxy on :8000).
python3 /write_codex_config.py

# Start vLLM + Responses->Chat proxy (start.sh execs the proxy in foreground).
echo "[entrypoint] Starting vLLM + Responses->Chat proxy..."
/opt/model-vllm/start.sh &

# Wait for proxy on :8000 to serve /v1/models.
VLLM_READY=0
for i in $(seq 1 180); do
  if curl -sf http://127.0.0.1:8000/v1/models >/dev/null 2>&1; then
    VLLM_READY=1
    break
  fi
  sleep 5
done
if [[ "$VLLM_READY" -ne 1 ]]; then
  echo "ERROR: vLLM/proxy did not become ready at http://127.0.0.1:8000 (check container logs)." >&2
  exit 1
fi
echo "[entrypoint] Services ready. Container staying alive."
exec sleep infinity
