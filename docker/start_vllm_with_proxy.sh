#!/usr/bin/env bash
# Launch vLLM on :8001, then the Responses->Chat proxy on :8000.
# Codex talks to :8000 (proxy), proxy translates /v1/responses to /v1/chat/completions on :8001,
# so vLLM's --tool-call-parser still applies to streaming responses.
set -euo pipefail
cd /opt/model-vllm
source .venv/bin/activate
export HF_HOME=${HF_HOME:-/home/agent/models}
export TRANSFORMERS_OFFLINE=1; export HF_HUB_OFFLINE=1
export HF_MODULES_CACHE=/tmp/hf_modules
export VLLM_WORKER_MULTIPROC_METHOD=spawn
export VLLM_ALLOW_LONG_MAX_MODEL_LEN=1
export NCCL_P2P_DISABLE=${NCCL_P2P_DISABLE:-1}

COMMON_ARGS=(
  --host 127.0.0.1
  --port 8001
  --gpu-memory-utilization 0.9
  --dtype bfloat16
  --trust-remote-code
  --download-dir "${HF_HOME:-/home/agent/models}"
  --served-model-name "$MODEL"
)

COMMON_ARGS+=(--tensor-parallel-size "${TP_SIZE:-2}")

MODEL_ARGS=(--max-model-len 90112 --language-model-only --enforce-eager --reasoning-parser qwen3 --enable-auto-tool-choice --tool-call-parser qwen3_coder --enable-prefix-caching)

# Use patched chat template if available (adds developer role support for Codex)
PATCHED_TEMPLATE="/tmp/patched_chat_template.jinja"
if [[ -f "$PATCHED_TEMPLATE" ]]; then
  echo "Using patched chat template: $PATCHED_TEMPLATE"
  MODEL_ARGS+=(--chat-template "$PATCHED_TEMPLATE")
fi

# When offline, resolve HF model ID to local snapshot path so vLLM accepts the directory
if [[ -n "${HF_HOME:-}" && "$MODEL" == */* ]]; then
  SLUG="models--$(echo "$MODEL" | sed "s|/|--|g")"
  SNAPSHOTS="${HF_HOME}/hub/${SLUG}/snapshots"
  if [[ -d "$SNAPSHOTS" ]]; then
    SHORT=$(ls -1 "$SNAPSHOTS" 2>/dev/null | head -1)
    if [[ -n "$SHORT" && -f "$SNAPSHOTS/$SHORT/config.json" ]]; then
      MODEL="$SNAPSHOTS/$SHORT"
      echo "Using local snapshot: $MODEL"
    fi
  fi
fi

# Start vLLM in background on port 8001
echo "Starting vLLM on port 8001..."
vllm serve "$MODEL" "${COMMON_ARGS[@]}" "${MODEL_ARGS[@]}" &
VLLM_PID=$!

# Wait for vLLM to be healthy
echo "Waiting for vLLM to be ready on port 8001..."
for i in $(seq 1 120); do
  if curl -sf http://127.0.0.1:8001/health >/dev/null 2>&1; then
    echo "vLLM is ready (took ${i}s)"
    break
  fi
  if ! kill -0 "$VLLM_PID" 2>/dev/null; then
    echo "ERROR: vLLM process died during startup" >&2
    exit 1
  fi
  sleep 1
done

if ! curl -sf http://127.0.0.1:8001/health >/dev/null 2>&1; then
  echo "ERROR: vLLM failed to start within 120s" >&2
  exit 1
fi

# Start Responses->Chat proxy on port 8000 (foreground)
echo "Starting Responses->Chat proxy on port 8000 -> vLLM :8001..."
exec python3 /opt/model-vllm/responses_to_chat_proxy.py --listen-port 8000 --vllm-port 8001
