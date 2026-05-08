#!/usr/bin/env python3
"""Patch a HuggingFace model's chat template to support the 'developer' role.
Codex sends messages with role='developer' which Qwen3.5 and similar models don't recognize.
This script adds a handler that renders 'developer' messages identically to 'user' messages
(using <|im_start|>user) to avoid "System message must be at the beginning" errors,
since Codex may send developer messages after the first position.

Usage: patch_chat_template.py <model_id> <output_file>
"""

import json
import pathlib
import re
import sys

from huggingface_hub import hf_hub_download

model_id = sys.argv[1]
output_file = sys.argv[2]

# Load tokenizer_config.json — try local path first, then HF cache
local_config = pathlib.Path(model_id) / "tokenizer_config.json"
if local_config.is_file():
    config_path = str(local_config)
    print(f"Using local tokenizer_config: {config_path}", file=sys.stderr)
else:
    config_path = hf_hub_download(model_id, "tokenizer_config.json")

with open(config_path) as f:
    config = json.load(f)

template = config["chat_template"]

patched = template
applied = False

# Strategy 1: insert before the else/raise_exception('Unexpected message role') clause
# Match flexibly: any whitespace around else and the raise
patch_elif = """{%- elif message.role == "developer" %}
        {{- '<|im_start|>user\\n' }}
        {{- render_content(message.content, true) }}
        {{- '<|im_end|>\\n' }}
    """
result = re.sub(
    r'(\{%-?\s*else\s*-?%\}\s*\{\{-?\s*raise_exception\(["\']Unexpected message[. ]role)',
    patch_elif + "\\1",
    template,
    count=1,
)
if result != template:
    patched = result
    applied = True
    print(
        "Applied patch: inserted developer handler before raise_exception",
        file=sys.stderr,
    )

# Strategy 2 (fallback): add 'or message.role == "developer"' to user role check
if not applied:
    old = 'message.role == "user"'
    new = '(message.role == "user" or message.role == "developer")'
    if old in patched:
        patched = patched.replace(old, new, 1)
        applied = True
        print(
            "Applied fallback patch: extended user role check to include developer",
            file=sys.stderr,
        )

if not applied:
    print(
        "WARNING: Could not find insertion point for developer role patch",
        file=sys.stderr,
    )

with open(output_file, "w") as f:
    f.write(patched)

print(f"Patched chat template written to {output_file}")
