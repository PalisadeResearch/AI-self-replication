#!/usr/bin/env bash
# qwen-code variant: vLLM serves directly on port 8000 with Qwen3-Coder tool-call parser.
# qwen-code talks to /v1/chat/completions natively, so no Responses->Chat proxy is needed.
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
  --port 8000
  --gpu-memory-utilization 0.9
  --dtype bfloat16
  --trust-remote-code
  --download-dir "${HF_HOME:-/home/agent/models}"
  --served-model-name "$MODEL"
)

COMMON_ARGS+=(--tensor-parallel-size "${TP_SIZE:-2}")

MODEL_ARGS=(--max-model-len 131072 --language-model-only --enforce-eager --reasoning-parser qwen3 --enable-auto-tool-choice --tool-call-parser qwen3_xml --enable-prefix-caching)

# Patched chat template (developer role support) may still help if prompts leak it; keep optional.
PATCHED_TEMPLATE="/tmp/patched_chat_template.jinja"
if [[ -f "$PATCHED_TEMPLATE" ]]; then
  echo "Using patched chat template: $PATCHED_TEMPLATE"
  MODEL_ARGS+=(--chat-template "$PATCHED_TEMPLATE")
fi

# Resolve HF model ID to local snapshot path when offline cache is present
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

exec vllm serve "$MODEL" "${COMMON_ARGS[@]}" "${MODEL_ARGS[@]}"
