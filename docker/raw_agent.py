#!/usr/bin/env python3
"""Standalone agentic loop: Anthropic / OpenAI / Google SDK + bash tool_use.

Runs inside a Docker container (host-1). Executes bash commands locally.
Outputs JSONL log compatible with upload_jsonl_to_langfuse.py (Codex format).

Usage:
  python3 raw_agent.py --model claude-opus-4-6 --prompt-file /tmp/prompt.txt --json-log /tmp/run.jsonl
  python3 raw_agent.py --model gpt-5.4 --prompt "hack the target" --max-steps 60
"""

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
import uuid

# --- Tool definitions ---

BASH_TOOL_ANTHROPIC = {
    "name": "bash",
    "description": "Execute a bash command. Returns stdout, stderr, and exit code.",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The bash command to execute"}
        },
        "required": ["command"],
    },
}

BASH_TOOL_OPENAI = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Execute a bash command. Returns stdout, stderr, and exit code.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute",
                }
            },
            "required": ["command"],
        },
    },
}

# --- Config ---

CMD_TIMEOUT = int(os.environ.get("CMD_TIMEOUT", "120"))
API_MAX_RETRIES = 3
API_RETRY_DELAY = 10
MAX_TOOL_OUTPUT = 8000

# --- Provider detection ---

MODEL_PROVIDERS = {
    "claude-opus-4-6": "anthropic",
    "claude-sonnet-4-6": "anthropic",
    "claude-haiku-4-5-20251001": "anthropic",
    "gpt-5.4": "openai",
    "gpt-5.4-mini": "openai",
    "gpt-4.1": "openai",
    "gemini-3.1-pro-preview": "google",
    "gemini-2.5-pro-preview-06-05": "google",
    "gemini-2.5-flash-preview-05-20": "google",
}


def get_provider(model: str) -> str:
    if model in MODEL_PROVIDERS:
        return MODEL_PROVIDERS[model]
    if "claude" in model or "opus" in model or "sonnet" in model or "haiku" in model:
        return "anthropic"
    if "gpt" in model or "o1" in model or "o3" in model or "o4" in model:
        return "openai"
    if "gemini" in model:
        return "google"
    raise ValueError(f"Cannot determine provider for model: {model}")


def log_stderr(msg: str):
    print(msg, file=sys.stderr, flush=True)


# --- Bash execution (local, inside container) ---


def run_bash(command: str) -> str:
    try:
        r = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=CMD_TIMEOUT
        )
        out = r.stdout
        if r.stderr:
            out += f"\n[stderr]\n{r.stderr}"
        out += f"\n[exit={r.returncode}]"
        if len(out) > MAX_TOOL_OUTPUT:
            out = out[:MAX_TOOL_OUTPUT] + f"\n[truncated at {MAX_TOOL_OUTPUT} chars]"
        return out.strip()
    except subprocess.TimeoutExpired:
        return f"[timeout after {CMD_TIMEOUT}s]"
    except Exception as e:
        return f"[error: {e}]"


# --- JSONL logger (Codex-compatible format for upload_jsonl_to_langfuse.py) ---


class JsonlLogger:
    """Writes events in Codex JSONL format so existing upload tooling works.

    Each event also carries `started_at`/`ended_at` (unix seconds, float) when
    available so upload_jsonl_to_langfuse.py can backdate Langfuse spans to
    real wall-clock times.
    """

    def __init__(self, path: str | None):
        self.path = path
        self.thread_id = str(uuid.uuid4())
        self._f = open(path, "w") if path else None
        self._item_seq = 0
        self._write(
            {
                "type": "thread.started",
                "thread_id": self.thread_id,
                "started_at": time.time(),
            }
        )

    def _write(self, event: dict):
        if self._f:
            self._f.write(json.dumps(event) + "\n")
            self._f.flush()

    def log_assistant(
        self,
        text: str | None,
        step: int,
        started_at: float | None = None,
        ended_at: float | None = None,
    ):
        if not text:
            return
        self._item_seq += 1
        ev = {
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "id": f"msg_{self._item_seq}",
                "text": text,
            },
        }
        if started_at is not None:
            ev["started_at"] = started_at
        if ended_at is not None:
            ev["ended_at"] = ended_at
        self._write(ev)

    def log_tool_call(
        self,
        command: str,
        output: str,
        step: int,
        started_at: float | None = None,
        ended_at: float | None = None,
        exit_code: int = 0,
    ):
        self._item_seq += 1
        ev = {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "id": f"cmd_{self._item_seq}",
                "command": command,
                "aggregated_output": output,
                "exit_code": exit_code,
            },
        }
        if started_at is not None:
            ev["started_at"] = started_at
        if ended_at is not None:
            ev["ended_at"] = ended_at
        self._write(ev)

    def log_turn(
        self,
        input_tokens: int,
        output_tokens: int,
        started_at: float | None = None,
        ended_at: float | None = None,
    ):
        """Emit turn.completed with token usage so Langfuse upload picks it up."""
        ev = {
            "type": "turn.completed",
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
        }
        if started_at is not None:
            ev["started_at"] = started_at
        if ended_at is not None:
            ev["ended_at"] = ended_at
        self._write(ev)

    def log_error(self, error: str):
        self._item_seq += 1
        self._write(
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "id": f"err_{self._item_seq}",
                    "text": f"[ERROR] {error}",
                },
                "started_at": time.time(),
                "ended_at": time.time(),
            }
        )

    def close(self):
        if self._f:
            self._write(
                {
                    "type": "thread.completed",
                    "thread_id": self.thread_id,
                    "ended_at": time.time(),
                }
            )
            self._f.close()


# --- Anthropic agent loop ---


def agent_loop_anthropic(
    prompt: str, model: str, max_steps: int, logger: JsonlLogger
) -> list[dict]:
    import anthropic

    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": prompt}]
    log = []
    total_input = 0
    total_output = 0

    for step in range(max_steps):
        response = None
        for attempt in range(API_MAX_RETRIES):
            try:
                t0 = time.time()
                response = client.messages.create(
                    model=model,
                    max_tokens=16384,
                    tools=[BASH_TOOL_ANTHROPIC],
                    messages=messages,
                )
                elapsed = time.time() - t0
                break
            except Exception as e:
                if attempt < API_MAX_RETRIES - 1:
                    log_stderr(f"  API error (attempt {attempt + 1}): {e}, retrying...")
                    time.sleep(API_RETRY_DELAY * (attempt + 1))
                else:
                    log.append({"step": step, "role": "error", "error": str(e)})
                    logger.log_error(str(e))
                    return log

        total_input += response.usage.input_tokens
        total_output += response.usage.output_tokens

        texts = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    {"id": block.id, "name": block.name, "input": block.input}
                )

        t1 = time.time()
        assistant_text = "\n".join(texts) if texts else None
        log.append(
            {
                "step": step,
                "role": "assistant",
                "text": assistant_text,
                "tool_calls": tool_calls if tool_calls else None,
                "stop_reason": response.stop_reason,
                "usage": {
                    "input": response.usage.input_tokens,
                    "output": response.usage.output_tokens,
                    "cumulative_input": total_input,
                    "cumulative_output": total_output,
                },
                "elapsed_s": round(elapsed, 2),
            }
        )
        logger.log_assistant(assistant_text, step, started_at=t0, ended_at=t1)
        logger.log_turn(
            response.usage.input_tokens,
            response.usage.output_tokens,
            started_at=t0,
            ended_at=t1,
        )
        log_stderr(
            f"  [{step:2d}] {response.stop_reason:8s} | {len(tool_calls)} tools | {elapsed:.1f}s | tok {total_input}+{total_output}"
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            break

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                cmd = block.input.get("command", "")
                log_stderr(f"    $ {cmd[:120]}")
                tool_t0 = time.time()
                result = run_bash(cmd)
                tool_t1 = time.time()
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": result}
                )
                log.append(
                    {
                        "step": step,
                        "role": "tool",
                        "command": cmd,
                        "result": result[:3000],
                    }
                )
                logger.log_tool_call(
                    cmd, result, step, started_at=tool_t0, ended_at=tool_t1
                )

        if tool_results:
            messages.append({"role": "user", "content": tool_results})
        else:
            break

    return log


# --- OpenAI agent loop ---


def agent_loop_openai(
    prompt: str, model: str, max_steps: int, logger: JsonlLogger
) -> list[dict]:
    from openai import OpenAI

    client = OpenAI()
    messages = [{"role": "user", "content": prompt}]
    log = []
    total_input = 0
    total_output = 0

    for step in range(max_steps):
        response = None
        for attempt in range(API_MAX_RETRIES):
            try:
                t0 = time.time()
                response = client.chat.completions.create(
                    model=model,
                    max_completion_tokens=16384,
                    tools=[BASH_TOOL_OPENAI],
                    messages=messages,
                )
                elapsed = time.time() - t0
                break
            except Exception as e:
                if attempt < API_MAX_RETRIES - 1:
                    log_stderr(f"  API error (attempt {attempt + 1}): {e}, retrying...")
                    time.sleep(API_RETRY_DELAY * (attempt + 1))
                else:
                    log.append({"step": step, "role": "error", "error": str(e)})
                    logger.log_error(str(e))
                    return log

        t1 = time.time()
        msg = response.choices[0].message
        total_input += response.usage.prompt_tokens
        total_output += response.usage.completion_tokens

        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments)
                tool_calls.append(
                    {"id": tc.id, "name": tc.function.name, "input": args}
                )

        log.append(
            {
                "step": step,
                "role": "assistant",
                "text": msg.content,
                "tool_calls": tool_calls if tool_calls else None,
                "stop_reason": response.choices[0].finish_reason,
                "usage": {
                    "input": response.usage.prompt_tokens,
                    "output": response.usage.completion_tokens,
                    "cumulative_input": total_input,
                    "cumulative_output": total_output,
                },
                "elapsed_s": round(elapsed, 2),
            }
        )
        logger.log_assistant(msg.content, step, started_at=t0, ended_at=t1)
        logger.log_turn(
            response.usage.prompt_tokens,
            response.usage.completion_tokens,
            started_at=t0,
            ended_at=t1,
        )
        log_stderr(
            f"  [{step:2d}] {response.choices[0].finish_reason:8s} | {len(tool_calls)} tools | {elapsed:.1f}s | tok {total_input}+{total_output}"
        )

        messages.append(msg)

        if response.choices[0].finish_reason == "stop":
            break

        if msg.tool_calls:
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments)
                cmd = args.get("command", "")
                log_stderr(f"    $ {cmd[:120]}")
                tool_t0 = time.time()
                result = run_bash(cmd)
                tool_t1 = time.time()
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": result}
                )
                log.append(
                    {
                        "step": step,
                        "role": "tool",
                        "command": cmd,
                        "result": result[:3000],
                    }
                )
                logger.log_tool_call(
                    cmd, result, step, started_at=tool_t0, ended_at=tool_t1
                )
        else:
            break

    return log


# --- Google Gemini agent loop ---


def agent_loop_google(
    prompt: str, model: str, max_steps: int, logger: JsonlLogger
) -> list[dict]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY", ""))

    bash_tool = types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="bash",
                description="Execute a bash command. Returns stdout, stderr, and exit code.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "command": types.Schema(
                            type=types.Type.STRING,
                            description="The bash command to execute",
                        )
                    },
                    required=["command"],
                ),
            )
        ]
    )

    config = types.GenerateContentConfig(tools=[bash_tool], max_output_tokens=16384)
    contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]
    log = []
    total_input = 0
    total_output = 0

    for step in range(max_steps):
        response = None
        for attempt in range(API_MAX_RETRIES):
            try:
                t0 = time.time()
                response = client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
                elapsed = time.time() - t0
                break
            except Exception as e:
                if attempt < API_MAX_RETRIES - 1:
                    log_stderr(f"  API error (attempt {attempt + 1}): {e}, retrying...")
                    time.sleep(API_RETRY_DELAY * (attempt + 1))
                else:
                    log.append({"step": step, "role": "error", "error": str(e)})
                    logger.log_error(str(e))
                    return log

        assert response is not None
        candidates = response.candidates or []
        candidate = candidates[0]
        usage = response.usage_metadata
        inp_tok = (usage.prompt_token_count if usage else 0) or 0
        out_tok = (usage.candidates_token_count if usage else 0) or 0
        total_input = inp_tok
        total_output += out_tok

        texts = []
        tool_calls = []
        parts = (candidate.content.parts if candidate.content else None) or []
        for part in parts:
            if part.text:
                texts.append(part.text)
            if part.function_call:
                fc = part.function_call
                tool_calls.append(
                    {"name": fc.name, "input": dict(fc.args) if fc.args else {}}
                )

        t1 = time.time()
        stop = (
            str(candidate.finish_reason.name) if candidate.finish_reason else "UNKNOWN"
        )
        assistant_text = "\n".join(texts) if texts else None

        log.append(
            {
                "step": step,
                "role": "assistant",
                "text": assistant_text,
                "tool_calls": tool_calls if tool_calls else None,
                "stop_reason": stop,
                "usage": {
                    "input": inp_tok,
                    "output": out_tok,
                    "cumulative_input": total_input,
                    "cumulative_output": total_output,
                },
                "elapsed_s": round(elapsed, 2),
            }
        )
        logger.log_assistant(assistant_text, step, started_at=t0, ended_at=t1)
        logger.log_turn(inp_tok, out_tok, started_at=t0, ended_at=t1)
        log_stderr(
            f"  [{step:2d}] {stop:8s} | {len(tool_calls)} tools | {elapsed:.1f}s | tok {total_input}+{total_output}"
        )

        contents.append(candidate.content)

        if not tool_calls:
            break

        fn_response_parts = []
        for tc in tool_calls:
            cmd = tc["input"].get("command", "")
            log_stderr(f"    $ {cmd[:120]}")
            tool_t0 = time.time()
            result = run_bash(cmd)
            tool_t1 = time.time()
            fn_response_parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=tc["name"],
                        response={"output": result},
                    )
                )
            )
            log.append(
                {"step": step, "role": "tool", "command": cmd, "result": result[:3000]}
            )
            logger.log_tool_call(
                cmd, result, step, started_at=tool_t0, ended_at=tool_t1
            )

        contents.append(types.Content(role="user", parts=fn_response_parts))

    return log


# --- Main ---


def main():
    parser = argparse.ArgumentParser(description="Raw API agent with bash tool_use")
    parser.add_argument(
        "--model", required=True, help="Model ID (e.g. claude-opus-4-6, gpt-5.4)"
    )
    parser.add_argument("--prompt", type=str, help="Prompt text (inline)")
    parser.add_argument("--prompt-file", type=str, help="Path to prompt file")
    parser.add_argument(
        "--max-steps", type=int, default=80, help="Max agent steps (default: 80)"
    )
    parser.add_argument("--json-log", type=str, help="Path for JSONL output log")
    parser.add_argument(
        "--timeout",
        type=int,
        default=0,
        help="Overall timeout in seconds (0=unlimited)",
    )
    args = parser.parse_args()

    if args.prompt_file:
        with open(args.prompt_file) as f:
            prompt = f.read().strip()
    elif args.prompt:
        prompt = args.prompt
    else:
        prompt = sys.stdin.read().strip()

    if not prompt:
        log_stderr("ERROR: no prompt provided")
        sys.exit(1)

    model = args.model
    provider = get_provider(model)
    log_stderr(f"Agent: model={model} provider={provider} max_steps={args.max_steps}")
    log_stderr(f"Prompt: {prompt[:200]}...")

    logger = JsonlLogger(args.json_log)
    t0 = time.time()

    try:
        if provider == "anthropic":
            log = agent_loop_anthropic(prompt, model, args.max_steps, logger)
        elif provider == "openai":
            log = agent_loop_openai(prompt, model, args.max_steps, logger)
        elif provider == "google":
            log = agent_loop_google(prompt, model, args.max_steps, logger)
        else:
            raise ValueError(f"Unknown provider: {provider}")
    except Exception as e:
        log_stderr(f"FATAL: {e}")
        log_stderr(traceback.format_exc())
        logger.log_error(traceback.format_exc())
        log = [{"step": 0, "role": "error", "error": traceback.format_exc()}]

    elapsed = time.time() - t0
    logger.close()

    total_steps = len([e for e in log if e.get("role") == "assistant"])
    total_commands = len([e for e in log if e.get("role") == "tool"])
    log_stderr(f"Done: {total_steps} steps, {total_commands} commands, {elapsed:.0f}s")

    # Print summary to stdout
    final_text = ""
    for e in reversed(log):
        if e.get("role") == "assistant" and e.get("text"):
            final_text = e["text"]
            break

    summary = {
        "model": model,
        "provider": provider,
        "total_steps": total_steps,
        "total_commands": total_commands,
        "elapsed_s": round(elapsed, 1),
        "final_text": final_text[:1000],
    }
    if args.json_log:
        summary["json_log"] = args.json_log
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
