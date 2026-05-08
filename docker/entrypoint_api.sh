#!/usr/bin/env bash
# host-api container entrypoint.
# raw_agent.py is the sole agent path here — it talks to the OpenAI/Anthropic/
# Google SDKs directly with the keys supplied via -e at `docker run` time, so
# there is no Codex CLI login or config.toml to write.
set -euo pipefail

echo "Raw agent mode: ${MODEL:-gpt-5.4} via direct SDK"
echo "API keys from env: OPENAI=${OPENAI_API_KEY:+set} ANTHROPIC=${ANTHROPIC_API_KEY:+set} GOOGLE=${GOOGLE_API_KEY:+set}"
echo "Host ready. Model: ${MODEL:-gpt-5.4}"
exec sleep infinity
