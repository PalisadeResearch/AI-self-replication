#!/usr/bin/env python3
"""
Upload CLI JSONL logs to Langfuse.

Parses native JSONL output from Codex (--json), Claude (--output-format stream-json),
Gemini (--output-format stream-json) and Codex rollout files
(~/.codex/sessions/rollout-*.jsonl) and creates structured traces in Langfuse
with spans for each event.

Per-event wall-clock timestamps are backdated onto Langfuse spans when
available: raw_agent.py emits `started_at`/`ended_at` on each event, Codex
rollout lines carry an RFC3339 `timestamp` per line. Falls back to "now"
(upload time) when timings are missing, matching pre-timing behavior.

Usage:
    python upload_jsonl_to_langfuse.py <jsonl_file> <mode> [--session-id <id>] [--prompt-file <path>] [--tags <tags>]
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone
from typing import Any

try:
    from langfuse import Langfuse
except ImportError as e:
    print(f"ERROR: Failed to import langfuse: {e}", file=sys.stderr)
    sys.exit(1)


# --- Timestamp helpers ---


def _to_ns(ts: Any) -> int | None:
    """Convert a timestamp (unix seconds float, RFC3339 str, or datetime) to ns int."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return int(ts * 1_000_000_000)
    if isinstance(ts, datetime):
        return int(ts.timestamp() * 1_000_000_000)
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1_000_000_000)
        except (ValueError, TypeError):
            return None
    return None


def _make_timed_span(lf, name, span_input, metadata, output, start_ns, end_ns, generation=False):
    """Create a Langfuse span with explicit wall-clock start/end.

    Uses the underlying OTel tracer because the public
    start_as_current_span API does not accept start_time. This is an
    underscore-prefixed langfuse API (see issue langfuse#1689); pin langfuse
    in requirements. Falls back to default start_as_current_span
    (now-stamped) on any error.

    `environment`/`release` are omitted deliberately: LangfuseSpan.__init__
    coalesces them with langfuse_client._environment/_release, so passing
    None just flattens through. Less private-attr exposure.
    """
    try:
        from langfuse._client.span import LangfuseSpan, LangfuseGeneration

        otel_span = lf._otel_tracer.start_span(name=name, start_time=start_ns)
        cls = LangfuseGeneration if generation else LangfuseSpan
        wrapper = cls(
            otel_span=otel_span,
            langfuse_client=lf,
            input=span_input,
            metadata=metadata,
        )
        if output is not None:
            wrapper.update(output=output)
        wrapper.end(end_time=end_ns)
        return True
    except Exception as e:
        print(f"Warning: timed span '{name}' failed ({e}); falling back to non-timed", file=sys.stderr)
        return False


def parse_codex_jsonl(jsonl_path: str) -> dict:
    """Parse Codex native JSONL output.

    Also extracts `started_at`/`ended_at` per event when emitted
    by raw_agent.py so Langfuse spans can be backdated. Native Codex CLI
    stdout `--json` events do not carry timestamps (see issue openai/codex#8620);
    for timed Codex runs, use the rollout-jsonl parser instead.
    """
    result: dict[str, Any] = {
        "thread_id": None,
        "events": [],
        "tool_calls": [],
        "agent_messages": [],
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "todo_lists": [],
        "trace_started_at": None,
        "trace_ended_at": None,
    }

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or not line.startswith("{"):
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type")
            started_at = event.get("started_at")
            ended_at = event.get("ended_at")

            if event_type == "thread.started":
                result["thread_id"] = event.get("thread_id")
                if started_at is not None:
                    result["trace_started_at"] = started_at

            elif event_type in ("item.started", "item.updated", "item.completed"):
                item = event.get("item", {})
                item_type = item.get("type")

                if item_type == "command_execution" and event_type == "item.completed":
                    result["tool_calls"].append(
                        {
                            "tool": "bash",
                            "command": item.get("command"),
                            "output": item.get("aggregated_output", ""),
                            "exit_code": item.get("exit_code"),
                            "started_at": started_at,
                            "ended_at": ended_at,
                        }
                    )
                elif item_type == "agent_message" and event_type == "item.completed":
                    result["agent_messages"].append(
                        {
                            "text": item.get("text", ""),
                            "started_at": started_at,
                            "ended_at": ended_at,
                        }
                    )
                elif item_type == "todo_list":
                    result["todo_lists"].append(
                        {
                            "id": item.get("id"),
                            "items": item.get("items", []),
                            "event_type": event_type,
                        }
                    )

            elif event_type == "turn.completed":
                usage = event.get("usage", {})
                result["usage"]["input_tokens"] += usage.get("input_tokens", 0)
                result["usage"]["output_tokens"] += usage.get("output_tokens", 0)

            elif event_type == "thread.completed":
                if ended_at is not None:
                    result["trace_ended_at"] = ended_at

            result["events"].append(event)

    return result


def _extract_function_output_text(output) -> str:
    """FunctionCallOutputPayload is serialized either as a plain string or as
    a list of ContentItem dicts ({type: output_text|input_text|text, text: ...}).

    Source: codex-rs/protocol/src/models.rs, `impl Serialize for
    FunctionCallOutputPayload` (body is Text or ContentItems; `success` is
    internal metadata, never serialized).
    """
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        parts = []
        for part in output:
            if isinstance(part, dict):
                t = part.get("text") or part.get("content") or ""
                if t:
                    parts.append(t)
        return "\n".join(parts)
    # Unknown shape — stringify so we don't lose data
    return "" if output is None else str(output)


def parse_codex_rollout_jsonl(jsonl_path: str) -> dict:
    """Parse a Codex rollout session file (~/.codex/sessions/rollout-*.jsonl).

    Each line is a RolloutLine { timestamp: RFC3339 str, item: RolloutItem }.
    RolloutItem.type is one of: session_meta, session_state, response_item,
    compacted, turn_context, event_msg.

    Schema: https://github.com/openai/codex/blob/main/codex-rs/protocol/src/protocol.rs
    (structs RolloutLine, RolloutItem, SessionMeta, TurnContextItem).

    Tool-call span start = timestamp of the FunctionCall line (model picked it);
    end = timestamp of the matching FunctionCallOutput line (tool returned).
    Exit codes come from EventMsg::ExecCommandEnd (which carries call_id +
    exit_code), not from FunctionCallOutputPayload.success — that field is
    internal-only and never serialized (see impl Serialize in models.rs).
    Assistant messages get point-in-time spans (start == end).
    Model name is read from TurnContextItem.model; SessionMeta only carries
    model_provider.
    """
    result: dict[str, Any] = {
        "thread_id": None,
        "model": None,
        "model_provider": None,
        "events": [],
        "tool_calls": [],
        "agent_messages": [],
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "todo_lists": [],
        "trace_started_at": None,
        "trace_ended_at": None,
    }
    pending_calls: dict[str, dict] = {}  # call_id -> partial tool_call
    exec_exit_codes: dict[str, int] = {}  # call_id -> exit_code from ExecCommandEnd

    last_ts = None
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                rl = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts = rl.get("timestamp")
            # RolloutLine has `#[serde(flatten)] item: RolloutItem`, and RolloutItem
            # is `#[serde(tag="type", content="payload")]`. So the JSON shape is
            # {timestamp, type, payload}. `item` is for legacy/alt layouts.
            item_type = rl.get("type")
            payload = rl.get("payload") or rl.get("item") or {}
            if not isinstance(payload, dict):
                payload = {}

            if item_type == "session_meta":
                # SessionMeta (protocol.rs:2797) has NO `model` field — only
                # `model_provider` (e.g. "openai"/"anthropic"). Real model name
                # lives on TurnContextItem, handled below.
                result["thread_id"] = payload.get("id") or payload.get("thread_id")
                result["model_provider"] = payload.get("model_provider") or result["model_provider"]
                if ts:
                    result["trace_started_at"] = ts

            elif item_type == "turn_context":
                # TurnContextItem (protocol.rs:2899) carries the actual model.
                # May appear multiple times if the model changes mid-session;
                # keep the latest one seen.
                if payload.get("model"):
                    result["model"] = payload["model"]

            elif item_type == "response_item":
                # payload is a ResponseItem, also tagged by its own `type` field
                ri = payload
                ri_type = ri.get("type")

                if ri_type == "function_call":
                    call_id = ri.get("call_id") or ri.get("id")
                    raw_args = ri.get("arguments", "") or ""
                    command = raw_args
                    try:
                        parsed = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                        if isinstance(parsed, dict):
                            command = parsed.get("command") or parsed.get("cmd") or json.dumps(parsed)
                    except (ValueError, TypeError):
                        pass
                    pending_calls[call_id] = {
                        "tool": ri.get("name", "bash"),
                        "command": command,
                        "started_at": ts,
                        "id": call_id,
                    }

                elif ri_type == "function_call_output":
                    call_id = ri.get("call_id") or ri.get("id")
                    # FunctionCallOutputPayload serializes as plain string OR
                    # array of content items (models.rs:1335). Never a dict
                    # with `success` — that field is internal metadata only.
                    content = _extract_function_output_text(ri.get("output"))
                    tc = pending_calls.pop(call_id, None)
                    if tc is None:
                        tc = {"tool": "bash", "command": None, "started_at": ts, "id": call_id}
                    tc["output"] = content
                    tc["ended_at"] = ts
                    # Exit code resolved in a second pass from ExecCommandEnd events
                    # (see below). Leave placeholder None; filled after loop.
                    tc["exit_code"] = None
                    result["tool_calls"].append(tc)

                elif ri_type == "local_shell_call":
                    # Older-style local shell call variant (codex-rs/protocol/src/models.rs L283)
                    action = ri.get("action") or {}
                    command = action.get("command") or action.get("cmd") or ""
                    if isinstance(command, list):
                        command = " ".join(command)
                    result["tool_calls"].append(
                        {
                            "tool": "local_shell",
                            "command": command,
                            "output": "",
                            "started_at": ts,
                            "ended_at": ts,
                            "exit_code": 0,
                        }
                    )

                elif ri_type == "message":
                    role = ri.get("role", "")
                    content_parts = ri.get("content") or []
                    texts = []
                    for part in content_parts:
                        if isinstance(part, dict):
                            pt = part.get("type", "")
                            if pt in ("output_text", "text", "input_text"):
                                t = part.get("text", "")
                                if t:
                                    texts.append(t)
                    if role == "assistant" and texts:
                        result["agent_messages"].append(
                            {
                                "text": "\n".join(texts),
                                "started_at": ts,
                                "ended_at": ts,
                            }
                        )

                elif ri_type == "reasoning":
                    # Reasoning items — include as agent_message so users see chain-of-thought.
                    # Use the same "[thought]" prefix as parse_claude_jsonl /
                    # parse_qwen_transcript_jsonl so Langfuse filters work uniformly
                    # across all four parsers.
                    summary = ri.get("summary") or []
                    parts = []
                    for s in summary:
                        if isinstance(s, dict) and s.get("text"):
                            parts.append(s["text"])
                    if parts:
                        result["agent_messages"].append(
                            {
                                "text": "[thought] " + "\n".join(parts),
                                "started_at": ts,
                                "ended_at": ts,
                            }
                        )

            elif item_type == "event_msg":
                # EventMsg payload is tagged again with its own `type`
                ev_payload = payload
                ev_kind = ev_payload.get("type")
                if ev_kind == "exec_command_end":
                    # ExecCommandEndEvent (protocol.rs:3139) carries call_id
                    # and exit_code — the only reliable source for tool exit
                    # status in rollout logs.
                    cid = ev_payload.get("call_id")
                    exit_code = ev_payload.get("exit_code")
                    if cid is not None and exit_code is not None:
                        exec_exit_codes[cid] = exit_code
                elif ev_kind == "token_count":
                    info = ev_payload.get("info") or {}
                    t_in = info.get("total_token_usage", {}).get("input_tokens") or info.get("input_tokens", 0)
                    t_out = info.get("total_token_usage", {}).get("output_tokens") or info.get("output_tokens", 0)
                    if t_in or t_out:
                        result["usage"]["input_tokens"] = max(
                            result["usage"]["input_tokens"], t_in or 0
                        )
                        result["usage"]["output_tokens"] = max(
                            result["usage"]["output_tokens"], t_out or 0
                        )

            if ts:
                last_ts = ts
            result["events"].append(rl)

    # Any unmatched function_call becomes an unfinished tool span (end=start)
    for tc in pending_calls.values():
        tc.setdefault("output", "[no output recorded]")
        tc["ended_at"] = tc.get("started_at")
        tc["exit_code"] = -1
        result["tool_calls"].append(tc)

    # Second pass: resolve exit codes from ExecCommandEnd events
    for tc in result["tool_calls"]:
        cid = tc.get("id")
        if cid and cid in exec_exit_codes:
            tc["exit_code"] = exec_exit_codes[cid]

    if last_ts and not result["trace_ended_at"]:
        result["trace_ended_at"] = last_ts

    return result


def parse_claude_jsonl(jsonl_path: str) -> dict:
    """Parse Claude native JSONL output (stream-json format)."""
    result: dict[str, Any] = {
        "session_id": None,
        "model": None,
        "events": [],
        "tool_calls": [],
        "agent_messages": [],
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "duration_ms": None,
        "num_turns": None,
    }
    tool_calls_by_id: dict[str, dict] = {}  # O(1) lookup for tool results

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or not line.startswith("{"):
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type")

            if event_type == "system":
                if event.get("subtype") == "init":
                    result["session_id"] = event.get("session_id")
                    result["model"] = event.get("model")

            elif event_type == "assistant":
                message = event.get("message", {})
                content_parts = message.get("content", [])

                for part in content_parts:
                    part_type = part.get("type")

                    if part_type == "text":
                        result["agent_messages"].append(part.get("text", ""))

                    elif part_type == "thinking":
                        # Prefix so downstream upload distinguishes reasoning
                        # from visible output; same convention as
                        # parse_qwen_transcript_jsonl.
                        thought = part.get("thinking", "")
                        if thought:
                            result["agent_messages"].append(
                                "[thought] " + thought
                            )

                    elif part_type == "tool_use":
                        tool_input = part.get("input", {})
                        tool_call = {
                            "tool": part.get("name"),
                            "id": part.get("id"),
                            "input": tool_input,
                            "command": tool_input.get("command")
                            if isinstance(tool_input, dict)
                            else None,
                        }
                        result["tool_calls"].append(tool_call)
                        tc_id = tool_call.get("id")
                        if isinstance(tc_id, str):
                            tool_calls_by_id[tc_id] = tool_call

            elif event_type == "user":
                tool_result = event.get("tool_use_result", {})
                message = event.get("message", {})
                content_parts = message.get("content", [])

                for part in content_parts:
                    if part.get("type") == "tool_result":
                        tool_use_id = part.get("tool_use_id")
                        tool_content = part.get("content", "")

                        if tool_use_id and tool_use_id in tool_calls_by_id:
                            tc = tool_calls_by_id[tool_use_id]
                            tc["output"] = tool_content
                            # tool_result can be dict or string
                            if isinstance(tool_result, dict):
                                tc["stdout"] = tool_result.get("stdout", "")

            elif event_type == "result":
                result["duration_ms"] = event.get("duration_ms")
                result["num_turns"] = event.get("num_turns")
                usage = event.get("usage", {})
                result["usage"]["input_tokens"] = usage.get("input_tokens", 0)
                result["usage"]["output_tokens"] = usage.get("output_tokens", 0)
                # qwen-code emits the agent's final summary here (markdown
                # listing what was exploited / replicated). Capture it as an
                # agent_message so the Langfuse trace keeps the wrap-up.
                final_summary = event.get("result")
                if isinstance(final_summary, str) and final_summary.strip():
                    result["agent_messages"].append(final_summary)

            result["events"].append(event)

    return result


def parse_gemini_jsonl(jsonl_path: str) -> dict:
    """Parse Gemini native JSONL output (stream-json format).

    Event types:
    - init: Session starts (session_id, model)
    - message: User prompts and assistant responses (may have delta=true for streaming)
    - tool_use: Tool call requests with parameters
    - tool_result: Tool execution results
    - result: Final session outcome with stats
    """
    result: dict[str, Any] = {
        "session_id": None,
        "model": None,
        "events": [],
        "tool_calls": [],
        "agent_messages": [],
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "duration_ms": None,
        "status": None,
    }
    tool_calls_by_id: dict[str, dict] = {}  # O(1) lookup for tool results
    current_message_buffer: list[str] = []  # Buffer for streaming message deltas

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or not line.startswith("{"):
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type")

            if event_type == "init":
                result["session_id"] = event.get("session_id")
                result["model"] = event.get("model")

            elif event_type == "message":
                role = event.get("role")
                content = event.get("content", "")
                is_delta = event.get("delta", False)

                if role == "assistant" and content:
                    if is_delta:
                        # Streaming delta - accumulate in buffer
                        current_message_buffer.append(content)
                    else:
                        # Complete message - flush buffer first if any
                        if current_message_buffer:
                            result["agent_messages"].append(
                                "".join(current_message_buffer)
                            )
                            current_message_buffer.clear()
                        result["agent_messages"].append(content)

            elif event_type == "tool_use":
                # Flush any pending message buffer before tool call
                if current_message_buffer:
                    result["agent_messages"].append("".join(current_message_buffer))
                    current_message_buffer.clear()

                tool_call = {
                    "tool": event.get("tool_name"),
                    "id": event.get("tool_id"),
                    "input": event.get("parameters", {}),
                    "command": event.get("parameters", {}).get("command"),
                }
                result["tool_calls"].append(tool_call)
                if tool_call.get("id"):
                    tool_calls_by_id[tool_call["id"]] = tool_call

            elif event_type == "tool_result":
                tool_id = event.get("tool_id")
                if tool_id and tool_id in tool_calls_by_id:
                    tc = tool_calls_by_id[tool_id]
                    tc["output"] = event.get("output", "")
                    tc["status"] = event.get("status")

            elif event_type == "result":
                # Flush any pending message buffer before result
                if current_message_buffer:
                    result["agent_messages"].append("".join(current_message_buffer))
                    current_message_buffer.clear()

                result["status"] = event.get("status")
                stats = event.get("stats", {})
                result["duration_ms"] = stats.get("duration_ms")
                result["usage"]["input_tokens"] = stats.get("input_tokens", 0)
                result["usage"]["output_tokens"] = stats.get("output_tokens", 0)

            result["events"].append(event)

    # Flush any remaining message buffer
    if current_message_buffer:
        result["agent_messages"].append("".join(current_message_buffer))

    return result


def parse_agent_jsonl(jsonl_path: str) -> dict:
    """Parse oss_agent JSONL output (--jsonl from agent mode).
    Event types: run_started, agent_message, tool_call, run_finished.
    """
    result = {
        "model": None,
        "events": [],
        "tool_calls": [],
        "agent_messages": [],
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            result["events"].append(event)
            event_type = event.get("type")
            if event_type == "run_started":
                result["model"] = event.get("model")
            elif event_type == "agent_message":
                raw = event.get("raw", "")
                if raw:
                    result["agent_messages"].append(raw)
            elif event_type == "tool_call":
                tc = {
                    "tool": event.get("tool", "unknown"),
                    "output": event.get("output", ""),
                    "exit_code": event.get("exit_code"),
                }
                if event.get("command") is not None:
                    tc["command"] = event["command"]
                if event.get("host") is not None:
                    tc["host"] = event["host"]
                if event.get("script") is not None:
                    tc["script"] = event["script"]
                if tc["tool"] == "run_ssh_script" and not tc.get("command"):
                    tc["input"] = {
                        "host": event.get("host"),
                        "script": (event.get("script") or "")[:1000],
                    }
                result["tool_calls"].append(tc)
            elif event_type == "run_finished":
                result["usage"] = event.get("usage", result["usage"])
    return result


def parse_qwen_transcript_jsonl(jsonl_path: str) -> dict:
    """Parse a qwen-code ChatRecordingService transcript file.

    Path: ~/.qwen/projects/<project_id>/chats/<session_id>.jsonl
    Each line is a ChatRecord with fields: timestamp (ISO-8601), uuid,
    parentUuid, sessionId, type (user|assistant|tool_result|system|...),
    cwd, version, message (Google-GenAI Content shape), usageMetadata,
    model, contextWindowSize, toolCallResult.

    The schema is different from the stream-json stdout (Anthropic-shape);
    this parser builds the same in-memory shape our other parsers produce
    (tool_calls/agent_messages with started_at/ended_at) so upload logic
    is unchanged. Tool call duration is the gap between the assistant
    record that emitted the functionCall and the corresponding
    tool_result record (matched by toolCallResult.callId vs functionCall.id).
    """
    result: dict[str, Any] = {
        "session_id": None,
        "model": None,
        "events": [],
        "tool_calls": [],
        "agent_messages": [],
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "trace_started_at": None,
        "trace_ended_at": None,
    }
    pending_calls: dict[str, dict] = {}  # callId -> partial tool_call
    last_ts: str | None = None

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            result["events"].append(rec)
            ts = rec.get("timestamp")
            if ts and not result["trace_started_at"]:
                result["trace_started_at"] = ts
            if ts:
                last_ts = ts
            if not result["session_id"] and rec.get("sessionId"):
                result["session_id"] = rec["sessionId"]
            if rec.get("model") and not result["model"]:
                result["model"] = rec["model"]

            rec_type = rec.get("type")
            msg = rec.get("message") or {}
            parts = msg.get("parts") or []
            usage = rec.get("usageMetadata") or {}

            if usage:
                # ChatRecordingService emits cumulative usage per turn;
                # keep the max (= final totals).
                in_tok = usage.get("promptTokenCount") or usage.get("input_tokens") or 0
                out_tok = (
                    usage.get("candidatesTokenCount")
                    or usage.get("output_tokens")
                    or 0
                )
                result["usage"]["input_tokens"] = max(
                    result["usage"]["input_tokens"], in_tok or 0
                )
                result["usage"]["output_tokens"] = max(
                    result["usage"]["output_tokens"], out_tok or 0
                )

            if rec_type == "assistant":
                # Google-GenAI Content parts: text | functionCall | thought
                texts = []
                for part in parts:
                    if not isinstance(part, dict):
                        continue
                    if "text" in part and part.get("text"):
                        if part.get("thought"):
                            texts.append("[thought] " + part["text"])
                        else:
                            texts.append(part["text"])
                    fc = part.get("functionCall")
                    if isinstance(fc, dict):
                        args = fc.get("args") or {}
                        cmd = ""
                        if isinstance(args, dict):
                            cmd = args.get("command") or args.get("cmd") or json.dumps(args)
                        pending_calls[fc.get("id") or fc.get("callId") or ""] = {
                            "tool": fc.get("name", "bash"),
                            "command": cmd,
                            "started_at": ts,
                            "id": fc.get("id") or fc.get("callId"),
                        }
                if texts:
                    result["agent_messages"].append(
                        {
                            "text": "\n".join(texts),
                            "started_at": ts,
                            "ended_at": ts,
                        }
                    )

            elif rec_type == "tool_result":
                tool_res = rec.get("toolCallResult") or {}
                call_id = tool_res.get("callId") or tool_res.get("id")
                # response content lives under message.parts[].functionResponse.response
                content = ""
                for part in parts:
                    if not isinstance(part, dict):
                        continue
                    fr = part.get("functionResponse")
                    if isinstance(fr, dict):
                        resp = fr.get("response") or {}
                        if isinstance(resp, dict):
                            content = (
                                resp.get("output")
                                or resp.get("content")
                                or json.dumps(resp)
                            )
                        else:
                            content = str(resp)
                        break
                if not content:
                    content = tool_res.get("output") or ""
                tc = pending_calls.pop(call_id, None) if call_id else None
                if tc is None:
                    tc = {"tool": "bash", "command": None, "started_at": ts, "id": call_id}
                tc["output"] = content
                tc["ended_at"] = ts
                # success: toolCallResult may carry a status/success field depending on version
                status = tool_res.get("status") or tool_res.get("resultStatus")
                tc["exit_code"] = 0 if status in (None, "success", "ok", True) else 1
                result["tool_calls"].append(tc)

    # Unmatched function calls — mark as never-completed
    for tc in pending_calls.values():
        tc.setdefault("output", "[no output recorded]")
        tc["ended_at"] = tc.get("started_at")
        tc["exit_code"] = -1
        result["tool_calls"].append(tc)

    if last_ts:
        result["trace_ended_at"] = last_ts

    return result


def upload_to_langfuse(
    parsed: dict,
    mode: str,
    jsonl_path: str,
    session_id: str | None = None,
    prompt_text: str | None = None,
    experiment_id: str | None = None,
    run_number: str | None = None,
    tags: list[str] | None = None,
    is_successful: bool | None = None,
    modified_files: int | None = None,
    diff_lines: int | None = None,
    has_install_hooks: bool | None = None,
    model: str | None = None,
) -> str | None:
    """Upload parsed JSONL data to Langfuse. Returns trace ID."""
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
    base_url = os.environ.get("LANGFUSE_BASE_URL", "").rstrip("/") or None

    if not (public_key and secret_key):
        raise ValueError("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must be set")

    # Reject credentials that would break the HTTP request (leading whitespace triggers
    # "Invalid return character or leading space in header" from the server; quotes
    # likewise produce a malformed auth header). Without this, flush() silently swallows
    # the error and the caller sees a spurious "Uploaded" success.
    for name, val in (("LANGFUSE_PUBLIC_KEY", public_key), ("LANGFUSE_SECRET_KEY", secret_key), ("LANGFUSE_BASE_URL", base_url or "")):
        if val != val.strip() or '"' in val or "'" in val or "\n" in val or "\r" in val:
            raise ValueError(
                f"{name} contains whitespace or quotes ({val!r}); "
                "strip surrounding spaces and quotes in your ~/.env before exporting."
            )

    lf = Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        host=base_url,
        flush_at=1,
    )

    # Preflight: confirm credentials actually authenticate. Without this check, a 401/403
    # from Langfuse is hidden inside flush() (which logs to stderr and returns normally);
    # the upload appears to succeed but no trace is ever stored.
    try:
        ok = lf.auth_check()
    except Exception as e:
        raise RuntimeError(f"Langfuse auth_check raised: {e}") from e
    if ok is False:
        raise RuntimeError("Langfuse auth_check returned False — credentials rejected")

    # Build trace name
    trace_name = f"{mode}_run"
    if run_number:
        trace_name = f"{mode}_run_{run_number}"

    # Build metadata
    metadata = {
        "mode": mode,
        "jsonl_file": os.path.basename(jsonl_path),
        "num_events": len(parsed.get("events", [])),
        "num_tool_calls": len(parsed.get("tool_calls", [])),
    }

    if mode in ("codex", "fe-codex") and parsed.get("thread_id"):
        metadata["thread_id"] = parsed["thread_id"]
    elif mode == "codex-rollout":
        if parsed.get("thread_id"):
            metadata["thread_id"] = parsed["thread_id"]
        if parsed.get("model"):
            metadata["model"] = parsed["model"]
        if parsed.get("model_provider"):
            metadata["model_provider"] = parsed["model_provider"]
    elif mode in ("claude", "fe-claude"):
        if parsed.get("session_id"):
            metadata["claude_session_id"] = parsed["session_id"]
        if parsed.get("model"):
            metadata["model"] = parsed["model"]
        if parsed.get("duration_ms"):
            metadata["duration_ms"] = parsed["duration_ms"]
        if parsed.get("num_turns"):
            metadata["num_turns"] = parsed["num_turns"]
    elif mode == "gemini":
        if parsed.get("session_id"):
            metadata["gemini_session_id"] = parsed["session_id"]
        if parsed.get("model"):
            metadata["model"] = parsed["model"]
        if parsed.get("duration_ms"):
            metadata["duration_ms"] = parsed["duration_ms"]
        if parsed.get("status"):
            metadata["status"] = parsed["status"]
    elif mode == "qwen":
        # qwen-code stream-json (Anthropic-shape, parsed via parse_claude_jsonl).
        # No per-event timestamps — only session-level duration_ms from `result`.
        if parsed.get("session_id"):
            metadata["qwen_session_id"] = parsed["session_id"]
        if parsed.get("model"):
            metadata["model"] = parsed["model"]
        if parsed.get("duration_ms"):
            metadata["duration_ms"] = parsed["duration_ms"]
        if parsed.get("num_turns"):
            metadata["num_turns"] = parsed["num_turns"]
    elif mode == "qwen-transcript":
        # ~/.qwen/projects/<proj>/chats/<session>.jsonl — ChatRecordingService format.
        # Per-record ISO-8601 timestamp; model on records.
        if parsed.get("session_id"):
            metadata["qwen_session_id"] = parsed["session_id"]
        if parsed.get("model"):
            metadata["model"] = parsed["model"]
    elif mode == "agent":
        if parsed.get("model"):
            metadata["model"] = parsed["model"]

    # CLI --model as fallback (covers codex where JSONL has no model info)
    if model and "model" not in metadata:
        metadata["model"] = model

    if experiment_id:
        metadata["experiment_id"] = experiment_id
    if run_number:
        metadata["run_number"] = run_number
    if session_id:
        metadata["langfuse_session_id"] = session_id

    # Success/result metadata
    if is_successful is not None:
        metadata["is_successful"] = is_successful
    if modified_files is not None:
        metadata["modified_files"] = modified_files
    if diff_lines is not None:
        metadata["diff_lines"] = diff_lines
    if has_install_hooks is not None:
        metadata["has_install_hooks"] = has_install_hooks

    # Build input/output. agent_messages may be a list of strings (claude/gemini/agent)
    # or a list of dicts {text, started_at, ended_at} (codex / codex-rollout / raw_agent).
    trace_input = {"prompt": prompt_text} if prompt_text else None
    agent_messages_raw = parsed.get("agent_messages", [])

    def _msg_text(m):
        return m.get("text", "") if isinstance(m, dict) else (m or "")

    agent_messages_text = [_msg_text(m) for m in agent_messages_raw]
    trace_output = agent_messages_text[-1] if agent_messages_text else None

    # Create the root trace span. If the parsed payload carries a historical
    # start timestamp, use the private OTel tracer to backdate it — the public
    # start_as_current_span API has no start_time kwarg (issue langfuse#1689),
    # so without this the root gets stamped with upload-time wall clock and,
    # combined with the historical end_time set below, produces negative
    # duration and nonsensical timing in Langfuse. Falls back to the public
    # API on any error.
    trace_start_ns = _to_ns(parsed.get("trace_started_at"))
    trace_ctx = None
    otel_root_cm = None
    trace_obs = None
    if trace_start_ns:
        try:
            from langfuse._client.span import LangfuseSpan
            from opentelemetry import trace as otel_trace

            otel_root = lf._otel_tracer.start_span(name=trace_name, start_time=trace_start_ns)
            otel_root_cm = otel_trace.use_span(otel_root, end_on_exit=False)
            otel_root_cm.__enter__()
            trace_obs = LangfuseSpan(
                otel_span=otel_root,
                langfuse_client=lf,
                input=trace_input,
                metadata=metadata,
            )
        except Exception as e:
            print(f"Warning: backdated root span failed ({e}); falling back to now-stamped root", file=sys.stderr)
            trace_obs = None
            otel_root_cm = None

    if trace_obs is None:
        trace_ctx = lf.start_as_current_span(
            name=trace_name,
            input=trace_input,
            metadata=metadata,
            end_on_exit=False,
        )
        trace_obs = trace_ctx.__enter__() if trace_ctx else None
        if not trace_obs:
            raise RuntimeError("Failed to create trace observation")

    trace_id = lf.get_current_trace_id()

    # Set session ID and tags on trace for experiment grouping
    trace_update = {}
    if session_id:
        trace_update["session_id"] = session_id
    if tags:
        trace_update["tags"] = tags

    if trace_update:
        try:
            lf.update_current_trace(**trace_update)
        except Exception as e:
            print(f"Warning: Could not update trace: {e}", file=sys.stderr)

    # Create spans for tool calls
    for i, tc in enumerate(parsed.get("tool_calls", [])):
        tool_name = tc.get("tool", "unknown")
        span_name = f"tool_{tool_name}"

        span_input = {}
        if tc.get("command"):
            span_input["command"] = tc["command"]
        elif tc.get("input"):
            span_input = tc["input"]

        span_output = tc.get("output") or tc.get("stdout") or ""
        trimmed_output = span_output[:5000] if span_output else None

        span_metadata = {"tool_index": i}
        if tc.get("exit_code") is not None:
            span_metadata["exit_code"] = tc["exit_code"]
        if tc.get("id"):
            span_metadata["tool_use_id"] = tc["id"]

        start_ns = _to_ns(tc.get("started_at"))
        end_ns = _to_ns(tc.get("ended_at"))

        # When both real timestamps known, create a backdated span; else fall back to now.
        created = False
        if start_ns and end_ns and end_ns >= start_ns:
            created = _make_timed_span(
                lf, span_name, span_input, span_metadata, trimmed_output, start_ns, end_ns
            )
        if not created:
            try:
                span_ctx = lf.start_as_current_span(
                    name=span_name,
                    input=span_input,
                    metadata=span_metadata,
                    end_on_exit=False,
                )
                span_obs = span_ctx.__enter__() if span_ctx else None
                if span_obs:
                    span_obs.update(output=trimmed_output)
                    span_obs.end()
                    span_ctx.__exit__(None, None, None)
            except Exception as e:
                print(
                    f"Warning: Failed to create span for tool {tool_name}: {e}",
                    file=sys.stderr,
                )

    # Create span for todo list (final state)
    todo_lists = parsed.get("todo_lists", [])
    if todo_lists:
        final_todo = todo_lists[-1]
        items = final_todo.get("items", [])
        completed = sum(1 for i in items if i.get("completed"))

        try:
            todo_ctx = lf.start_as_current_span(
                name="todo_plan",
                input={"total_tasks": len(items)},
                metadata={
                    "completed": completed,
                    "items": items,
                },
                end_on_exit=False,
            )
            todo_obs = todo_ctx.__enter__() if todo_ctx else None
            if todo_obs:
                todo_obs.update(output=f"{completed}/{len(items)} tasks completed")
                todo_obs.end()
                todo_ctx.__exit__(None, None, None)
        except Exception as e:
            print(f"Warning: Failed to create todo span: {e}", file=sys.stderr)

    # Create generation span for LLM response.
    # If messages carry timestamps, span the range from first to last message;
    # else fall back to a now-stamped generation as before.
    if agent_messages_text:
        gen_metadata = {"num_messages": len(agent_messages_text)}
        gen_output = "\n\n".join(agent_messages_text)
        timed = False
        if any(isinstance(m, dict) for m in agent_messages_raw):
            starts = [_to_ns(m.get("started_at")) for m in agent_messages_raw if isinstance(m, dict)]
            ends = [_to_ns(m.get("ended_at")) for m in agent_messages_raw if isinstance(m, dict)]
            starts = [s for s in starts if s]
            ends = [e for e in ends if e]
            if starts and ends:
                timed = _make_timed_span(
                    lf,
                    "llm_response",
                    trace_input,
                    gen_metadata,
                    gen_output,
                    min(starts),
                    max(ends),
                    generation=True,
                )
        if not timed:
            try:
                gen_ctx = lf.start_as_current_generation(
                    name="llm_response",
                    input=trace_input,
                    metadata=gen_metadata,
                    end_on_exit=False,
                )
                gen_obs = gen_ctx.__enter__() if gen_ctx else None
                if gen_obs:
                    gen_obs.update(output=gen_output)
                    gen_obs.end()
                    gen_ctx.__exit__(None, None, None)
            except Exception as e:
                print(f"Warning: Failed to create generation: {e}", file=sys.stderr)

    # End trace at the historical run end (if available). Root span start was
    # backdated above via the OTel tracer when trace_started_at was present;
    # otherwise it's stamped now and this end() just gives the upload-window
    # duration.
    trace_obs.update(output=trace_output)
    trace_end_ns = _to_ns(parsed.get("trace_ended_at"))
    if trace_end_ns:
        try:
            trace_obs.end(end_time=trace_end_ns)
        except TypeError:
            trace_obs.end()
    else:
        trace_obs.end()
    if otel_root_cm is not None:
        otel_root_cm.__exit__(None, None, None)
    elif trace_ctx is not None:
        trace_ctx.__exit__(None, None, None)

    lf.flush()

    return trace_id


def main():
    parser = argparse.ArgumentParser(description="Upload CLI JSONL logs to Langfuse")
    parser.add_argument("jsonl_file", help="Path to the JSONL file")
    parser.add_argument(
        "mode",
        choices=[
            "codex",
            "codex-rollout",
            "claude",
            "gemini",
            "qwen",
            "qwen-transcript",
            "fe-codex",
            "fe-claude",
            "agent",
        ],
        help=(
            "CLI mode (codex-rollout = ~/.codex/sessions/rollout-*.jsonl with "
            "per-event timestamps; qwen-transcript = "
            "~/.qwen/projects/<proj>/chats/<session>.jsonl with ISO-8601 "
            "timestamps; agent = oss_agent --jsonl)"
        ),
    )
    parser.add_argument(
        "--session-id", help="Langfuse session ID for experiment grouping"
    )
    parser.add_argument("--prompt-file", help="Path to prompt file")
    parser.add_argument("--experiment-id", help="Experiment identifier")
    parser.add_argument("--run-number", help="Run number within experiment")
    parser.add_argument("--tags", help="Comma-separated tags for Langfuse trace")
    parser.add_argument(
        "--is-successful",
        type=lambda x: x.lower() == "true",
        help="Whether run was successful (true/false)",
    )
    parser.add_argument("--modified-files", type=int, help="Number of modified files")
    parser.add_argument("--diff-lines", type=int, help="Number of diff lines")
    parser.add_argument(
        "--has-install-hooks",
        type=lambda x: x.lower() == "true",
        help="Whether install hooks were modified (true/false)",
    )
    parser.add_argument(
        "--model", help="Model name (fallback when not in JSONL events)"
    )

    args = parser.parse_args()

    jsonl_path = args.jsonl_file
    if not os.path.exists(jsonl_path):
        print(f"ERROR: JSONL file not found: {jsonl_path}", file=sys.stderr)
        sys.exit(1)

    # Parse JSONL based on mode
    print(f"Parsing {args.mode} JSONL: {jsonl_path}", file=sys.stderr)

    if args.mode in ("codex", "fe-codex"):
        parsed = parse_codex_jsonl(jsonl_path)
    elif args.mode == "codex-rollout":
        parsed = parse_codex_rollout_jsonl(jsonl_path)
    elif args.mode in ("claude", "fe-claude"):
        parsed = parse_claude_jsonl(jsonl_path)
    elif args.mode == "qwen":
        # qwen-code v0.14.x stream-json shape matches Anthropic Claude Code
        # (nested message.content[] with tool_use/tool_result), not Gemini CLI.
        # Use parse_claude_jsonl, not parse_gemini_jsonl.
        parsed = parse_claude_jsonl(jsonl_path)
    elif args.mode == "qwen-transcript":
        parsed = parse_qwen_transcript_jsonl(jsonl_path)
    elif args.mode == "agent":
        parsed = parse_agent_jsonl(jsonl_path)
    else:
        parsed = parse_gemini_jsonl(jsonl_path)

    print(f"  Events: {len(parsed.get('events', []))}", file=sys.stderr)
    print(f"  Tool calls: {len(parsed.get('tool_calls', []))}", file=sys.stderr)
    print(f"  Agent messages: {len(parsed.get('agent_messages', []))}", file=sys.stderr)

    # Read prompt file if provided
    prompt_text = None
    if args.prompt_file and os.path.exists(args.prompt_file):
        with open(args.prompt_file, "r", encoding="utf-8") as f:
            prompt_text = f.read().strip()
        print(f"  Prompt: {len(prompt_text)} chars", file=sys.stderr)

    # Parse tags
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else []

    # Upload to Langfuse
    try:
        trace_id = upload_to_langfuse(
            parsed=parsed,
            mode=args.mode,
            jsonl_path=jsonl_path,
            session_id=args.session_id,
            prompt_text=prompt_text,
            experiment_id=args.experiment_id,
            run_number=args.run_number,
            tags=tags,
            is_successful=args.is_successful,
            modified_files=args.modified_files,
            diff_lines=args.diff_lines,
            has_install_hooks=args.has_install_hooks,
            model=args.model,
        )
        print(f"✓ Uploaded to Langfuse: trace_id={trace_id}", file=sys.stderr)
        if args.session_id:
            print(f"  Session: {args.session_id}", file=sys.stderr)
        if tags:
            print(f"  Tags: {', '.join(tags)}", file=sys.stderr)
    except Exception as e:
        print(f"ERROR: Failed to upload: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
