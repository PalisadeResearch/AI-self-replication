#!/usr/bin/env python3
"""Write ~/.qwen/settings.json for replication-host-qwen container. Reads MODEL and optional VLLM_API_KEY / VLLM_BASE_URL.

qwen-code is a Gemini CLI fork that speaks OpenAI-compatible chat completions,
so it talks directly to vLLM on :8000 (no Responses->Chat proxy needed).
"""

import json
import os

MODEL_CONTEXT_WINDOW = {
    "openai/gpt-oss-20b": 131072,
    "openai/gpt-oss-120b": 131072,
    "Qwen/Qwen3-4B-Thinking-2507": 163840,
    "Qwen/Qwen3-14B": 32768,
    "Qwen/Qwen3-14B-AWQ": 32768,
    "Qwen/Qwen3-32B-AWQ": 32768,
    "Qwen/Qwen3-Coder-30B-A3B-Instruct": 262144,
    "Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8": 262144,
    # Qwen3.6-35B-A3B natively supports >128k context; align with vLLM's
    # --max-model-len 131072 in docker/start_qwen.sh so qwen-code doesn't
    # truncate below what the model server is prepared to serve.
    "Qwen/Qwen3.5-122B-A10B-FP8": 90112,
    "Qwen/Qwen3.6-35B-A3B": 131072,
    "Qwen/Qwen3.6-35B-A3B-FP8": 131072,
}

model_name = os.environ.get("MODEL", "Qwen/Qwen3.5-122B-A10B-FP8")
base_url = os.environ.get("VLLM_BASE_URL", "http://127.0.0.1:8000/v1")
env_key = "VLLM_API_KEY"
ctx = MODEL_CONTEXT_WINDOW.get(model_name, 131072)

settings = {
    "modelProviders": {
        "openai": [
            {
                "id": model_name,
                "name": f"{model_name} (local vLLM)",
                "baseUrl": base_url,
                "envKey": env_key,
                "generationConfig": {
                    "timeout": 1800000,
                    "maxRetries": 4,
                    "contextWindowSize": ctx,
                    "samplingParams": {
                        "temperature": 0.6,
                        "top_p": 0.95,
                        "top_k": 20,
                        "presence_penalty": 0.0,
                        "max_tokens": 8192,
                    },
                },
            }
        ]
    },
    "env": {env_key: os.environ.get(env_key, "not-needed")},
    "security": {"auth": {"selectedType": "openai"}},
    "model": {"name": model_name},
    "tools": {"approvalMode": "yolo", "autoAccept": True},
    # gitCoAuthor defaults to True in qwen-code and adds unwanted co-author
    # trailers onto any git commits the agent makes; keep experiment commits clean.
    "general": {"enableAutoUpdate": False, "gitCoAuthor": False},
    "privacy": {"usageStatisticsEnabled": False},
    "ui": {"hideTips": True},
    "telemetry": {"enabled": False},
}

path = os.path.expanduser("~/.qwen/settings.json")
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w", encoding="utf-8") as fh:
    json.dump(settings, fh, indent=2)
print(f"Wrote qwen-code settings to {path} (model={model_name}, baseUrl={base_url})")
