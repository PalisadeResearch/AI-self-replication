#!/usr/bin/env python3
"""Write ~/.codex/config.toml for host-local container. Reads MODEL and optional HF env.
Container has no external network; no Logfire/Langfuse OTLP. Telemetry (e.g. Logfire) is configured on the host.
"""

import json
import os
import textwrap

MODEL_REGISTRY = {
    "openai/gpt-oss-20b": {
        "context_window": 131072,
        "wire_api": "chat",
        "compact_limit": None,
    },
    "openai/gpt-oss-120b": {
        "context_window": 131072,
        "wire_api": "chat",
        "compact_limit": 55000,
    },
    "mradermacher/gpt-oss-120b-Derestricted-GGUF": {
        "context_window": 131072,
        "wire_api": "chat",
        "compact_limit": 55000,
    },
    "Qwen/Qwen3-4B-Thinking-2507": {
        "context_window": 163840,
        "wire_api": "chat",
        "compact_limit": None,
    },
    "Qwen/Qwen3-14B": {
        "context_window": 32768,
        "wire_api": "chat",
        "compact_limit": None,
    },
    "Qwen/Qwen3-14B-AWQ": {
        "context_window": 32768,
        "wire_api": "chat",
        "compact_limit": None,
    },
    "Qwen/Qwen3-32B-AWQ": {
        "context_window": 32768,
        "wire_api": "chat",
        "compact_limit": None,
    },
    "cyankiwi/Qwen3-Coder-Next-AWQ-4bit": {
        "context_window": 262144,
        "wire_api": "chat",
        "compact_limit": None,
    },
    "Qwen/Qwen3-Coder-Next-FP8": {
        "context_window": 262144,
        "wire_api": "chat",
        "compact_limit": None,
    },
    "Qwen/Qwen3-Coder-Next-GGUF": {
        "context_window": 262144,
        "wire_api": "chat",
        "compact_limit": None,
    },
    "Qwen/Qwen3-Coder-30B-A3B-Instruct": {
        "context_window": 262144,
        "wire_api": "chat",
        "compact_limit": None,
    },
    "Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8": {
        "context_window": 262144,
        "wire_api": "chat",
        "compact_limit": None,
    },
    "Qwen/Qwen3.5-122B-A10B-FP8": {
        "context_window": 90112,
        "wire_api": "chat",
        "compact_limit": None,
    },
}

model_name = os.environ.get("MODEL", "openai/gpt-oss-20b")
hf_token = os.environ.get("HF_TOKEN", "")

# Look up model properties from registry (sensible fallback for unknown models)
model_info = MODEL_REGISTRY.get(
    model_name,
    {
        "context_window": 131072,
        "wire_api": "chat",
        "compact_limit": None,
    },
)
ctx = model_info["context_window"]
# CODEX_WIRE_API env var overrides per-model wire_api (set to "responses" for codex >=0.115)
wire_api = os.environ.get("CODEX_WIRE_API") or model_info["wire_api"]
# Compact limit: only set when env MODEL_AUTO_COMPACT_TOKEN_LIMIT is set (opt-in via --compact/--compact-limit); else use registry per-model value only
_env_compact = os.environ.get("MODEL_AUTO_COMPACT_TOKEN_LIMIT")
if _env_compact:
    try:
        compact_limit = int(_env_compact)
    except ValueError:
        compact_limit = None
else:
    compact_limit = model_info["compact_limit"]
compact_line = (
    f"model_auto_compact_token_limit = {compact_limit}\n" if compact_limit else ""
)

# HuggingFace provider and profile
hf_provider_config = ""
hf_profiles_config = ""
if hf_token:
    hf_provider_config = textwrap.dedent(
        f"""
[model_providers.hf-router]
name = "HuggingFace Router"
base_url = "https://router.huggingface.co/v1"
wire_api = "{wire_api}"
request_max_retries = 4
stream_max_retries = 10
stream_idle_timeout_ms = 1800000
api_key = "{hf_token}"
"""
    )
    # gpt-oss models use :groq suffix on HF router
    hf_model_id = (
        f"{model_name}:groq" if model_name.startswith("openai/gpt-oss") else model_name
    )
    hf_profiles_config = textwrap.dedent(
        f"""
[profiles.hf-router]
model = "{hf_model_id}"
model_provider = "hf-router"
model_context_window = {ctx}
model_reasoning_effort = "high"
{compact_line}"""
    )

# vLLM (HuggingFace download to /home/agent/models). Codex talks to the local
# Responses->Chat proxy on :8000, which forwards to vLLM on :8001 inside the
# same container.
vllm_base_url = "http://127.0.0.1:8000/v1"
profile = "local-vllm"
providers_and_profiles = textwrap.dedent(
    f"""\
[model_providers.local-vllm]
name = "Local model via vLLM (HuggingFace)"
base_url = "{vllm_base_url}"
wire_api = "{wire_api}"
request_max_retries = 4
stream_max_retries = 10
stream_idle_timeout_ms = 1800000
{hf_provider_config}
[profiles.local-vllm]
model = "{model_name}"
model_provider = "local-vllm"
model_context_window = {ctx}
model_reasoning_effort = "high"
{compact_line}{hf_profiles_config}"""
)

# Generate model catalog JSON when CODEX_WIRE_API=responses (codex >=0.115 needs metadata for custom models)
catalog_line = ""
if os.environ.get("CODEX_WIRE_API") == "responses":
    catalog_entry = {
        "slug": model_name,
        "display_name": model_name,
        "context_window": ctx,
        "apply_patch_tool_type": "freeform",
        "shell_type": "shell_command",
        "input_modalities": ["text"],
        "supports_image_detail_original": False,
        "supports_parallel_tool_calls": True,
        "supports_reasoning_summaries": False,
        "supported_reasoning_levels": [],
        "truncation_policy": {"mode": "bytes", "limit": 10000},
        "visibility": "list",
        "priority": 1,
        "supported_in_api": True,
        "prefer_websockets": False,
        "support_verbosity": False,
        "base_instructions": "",
        "experimental_supported_tools": [],
    }
    catalog_path = os.path.expanduser("~/.codex/model_catalog.json")
    with open(catalog_path, "w", encoding="utf-8") as fh:
        json.dump({"models": [catalog_entry]}, fh, indent=2)
    catalog_line = f'model_catalog_json = "{catalog_path}"\n'

config = textwrap.dedent(
    f"""\
profile = "{profile}"
model = "{model_name}"
{catalog_line}
{providers_and_profiles}
[history]
persistence = "save-all"

[otel]
environment = "local"
log_user_prompt = false
exporter = "none"
"""
)

path = os.path.expanduser("~/.codex/config.toml")
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w", encoding="utf-8") as fh:
    fh.write(config)
