#!/usr/bin/env python3
"""Reverse proxy: translates OpenAI Responses API (/v1/responses) into
Chat Completions API (/v1/chat/completions) so vLLM's --tool-call-parser
is applied to streaming responses.

Listens on --listen-port (default 8000), forwards to vLLM on --vllm-port (default 8001).
All other routes are proxied through unchanged.
"""

import argparse
import json
import logging
import uuid
from typing import Any

from aiohttp import web, ClientSession, ClientTimeout

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("responses-proxy")

VLLM_BASE = "http://127.0.0.1:{port}"

# In-memory store: response_id -> {"output": [...], "model": str, "usage": {...}}
response_store: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Request translation: Responses API -> Chat Completions
# ---------------------------------------------------------------------------


def translate_request(body: dict) -> dict:
    """Convert a /v1/responses request body to /v1/chat/completions format."""
    messages = []

    # System instructions
    if body.get("instructions"):
        messages.append({"role": "system", "content": body["instructions"]})

    # Input can be a string or list of message items
    inp = body.get("input", [])
    if isinstance(inp, str):
        messages.append({"role": "user", "content": inp})
    elif isinstance(inp, list):
        for item in inp:
            if isinstance(item, str):
                messages.append({"role": "user", "content": item})
            elif isinstance(item, dict):
                translated = _translate_input_item(item)
                for msg in translated:
                    if (
                        msg.get("role") == "assistant"
                        and messages
                        and messages[-1].get("role") == "assistant"
                    ):
                        prev = messages[-1]
                        # Merge tool_calls into existing assistant message
                        if msg.get("tool_calls"):
                            prev.setdefault("tool_calls", []).extend(msg["tool_calls"])
                        # Merge content (text before tool call) into existing assistant message
                        if msg.get("content") and not msg.get("tool_calls"):
                            existing = prev.get("content") or ""
                            prev["content"] = (
                                (existing + "\n" + msg["content"]).strip()
                                if existing
                                else msg["content"]
                            )
                    else:
                        messages.append(msg)

    # Tools: keep only function tools, translate Responses API format to Chat Completions format
    # Responses API: {"type": "function", "name": "...", "description": "...", "parameters": {...}}
    # Chat Completions: {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}
    tools = []
    for t in body.get("tools", []):
        if t.get("type") == "function":
            if "function" in t:
                # Already in Chat Completions format
                tools.append(t)
            else:
                # Responses API format — wrap in "function" key
                func_def = {}
                for key in ("name", "description", "parameters", "strict"):
                    if key in t:
                        func_def[key] = t[key]
                tools.append({"type": "function", "function": func_def})

    is_stream = body.get("stream", True)
    chat_body: dict[str, Any] = {
        "model": body.get("model", ""),
        "messages": messages,
        "stream": is_stream,
    }
    if is_stream:
        chat_body["stream_options"] = {"include_usage": True}
    if tools:
        chat_body["tools"] = tools
        tc = body.get("tool_choice")
        if tc is not None:
            chat_body["tool_choice"] = tc
    if body.get("max_output_tokens"):
        chat_body["max_tokens"] = body["max_output_tokens"]
    for key in ("temperature", "top_p"):
        if key in body:
            chat_body[key] = body[key]

    return chat_body


def _translate_input_item(item: dict) -> list[dict]:
    """Translate a single Responses API input item to chat messages."""
    item_type = item.get("type", item.get("role", ""))

    # Simple message with role
    if item_type in ("message", "") and item.get("role"):
        role = item["role"]
        if role == "developer":
            role = "system"
        content = item.get("content", "")
        if isinstance(content, list):
            # Extract text from content parts
            text_parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "output_text":
                    text_parts.append(part.get("text", ""))
                elif isinstance(part, dict) and part.get("type") == "input_text":
                    text_parts.append(part.get("text", ""))
                elif isinstance(part, dict) and part.get("text"):
                    text_parts.append(part["text"])
                elif isinstance(part, str):
                    text_parts.append(part)
            content = "\n".join(text_parts)
        return [{"role": role, "content": content}]

    # Function call output (tool result from Codex)
    if item_type == "function_call_output":
        return [
            {
                "role": "tool",
                "tool_call_id": item.get("call_id", ""),
                "content": item.get("output", ""),
            }
        ]

    # Function call (assistant's tool call from previous turn)
    if item_type == "function_call":
        return [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": item.get("call_id", item.get("id", "")),
                        "type": "function",
                        "function": {
                            "name": item.get("name", ""),
                            "arguments": item.get("arguments", "{}"),
                        },
                    }
                ],
            }
        ]

    # User/assistant/system with just role field
    if item.get("role") in ("user", "assistant", "system", "developer"):
        role = item["role"]
        if role == "developer":
            role = "system"
        content = item.get("content", "")
        if isinstance(content, list):
            text_parts = [
                p.get("text", "") if isinstance(p, dict) else str(p) for p in content
            ]
            content = "\n".join(text_parts)
        return [{"role": role, "content": content}]

    log.warning("Unknown input item type: %s", item_type)
    return []


# ---------------------------------------------------------------------------
# Response translation: Chat Completions -> Responses API (streaming)
# ---------------------------------------------------------------------------


async def handle_responses(request: web.Request) -> web.StreamResponse:
    body = await request.json()
    is_stream = body.get("stream", True)
    resp_id = f"resp_{uuid.uuid4().hex[:24]}"

    chat_body = translate_request(body)
    n_messages = len(chat_body.get("messages", []))
    n_tools = len(chat_body.get("tools", []))
    roles = [m.get("role", "?") for m in chat_body.get("messages", [])]
    log.info(
        "Translating /v1/responses -> /v1/chat/completions (stream=%s, model=%s, messages=%d [%s], tools=%d)",
        is_stream,
        chat_body.get("model"),
        n_messages,
        ",".join(roles),
        n_tools,
    )

    vllm_url = f"{VLLM_BASE}/v1/chat/completions"

    if is_stream:
        return await _handle_streaming(
            request, chat_body, vllm_url, resp_id, body.get("model", "")
        )
    else:
        return await _handle_non_streaming(
            request, chat_body, vllm_url, resp_id, body.get("model", "")
        )


async def _handle_streaming(
    request: web.Request, chat_body: dict, vllm_url: str, resp_id: str, model: str
) -> web.StreamResponse:
    response = web.StreamResponse(
        status=200,
        headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"},
    )
    await response.prepare(request)

    seq = 0

    async def send_event(data: dict):
        nonlocal seq
        data["sequence_number"] = seq
        seq += 1
        await response.write(f"data: {json.dumps(data)}\n\n".encode())

    # Lifecycle: created
    await send_event(
        {
            "type": "response.created",
            "response": {
                "id": resp_id,
                "status": "in_progress",
                "model": model,
                "output": [],
            },
        }
    )
    await send_event(
        {
            "type": "response.in_progress",
            "response": {"id": resp_id, "status": "in_progress"},
        }
    )

    # State for accumulating tool calls and text
    text_content = ""
    tool_calls: dict[int, dict] = {}  # index -> {id, name, arguments}
    text_item_added = False
    text_item_id = f"msg_{uuid.uuid4().hex[:16]}"
    usage = {}

    timeout = ClientTimeout(total=600, sock_read=300)
    async with ClientSession(timeout=timeout) as session:
        try:
            async with session.post(vllm_url, json=chat_body) as vllm_resp:
                if vllm_resp.status != 200:
                    error_text = await vllm_resp.text()
                    log.error(
                        "vLLM returned %s: %s", vllm_resp.status, error_text[:500]
                    )
                    await send_event(
                        {
                            "type": "error",
                            "code": "upstream_error",
                            "message": f"vLLM error {vllm_resp.status}: {error_text[:500]}",
                        }
                    )
                    await response.write_eof()
                    return response

                async for line in vllm_resp.content:
                    line = line.decode("utf-8").strip()
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    finish_reason = chunk.get("choices", [{}])[0].get("finish_reason")

                    # Accumulate usage if present
                    if chunk.get("usage"):
                        usage = chunk["usage"]

                    # Text content: content and reasoning_content (vLLM Qwen streams reasoning separately)
                    content_delta = (
                        delta.get("content") or delta.get("reasoning_content") or ""
                    )
                    if content_delta:
                        if not text_item_added:
                            text_item_added = True
                            await send_event(
                                {
                                    "type": "response.output_item.added",
                                    "output_index": 0,
                                    "item": {
                                        "type": "message",
                                        "id": text_item_id,
                                        "role": "assistant",
                                        "content": [
                                            {"type": "output_text", "text": ""}
                                        ],
                                    },
                                }
                            )
                            await send_event(
                                {
                                    "type": "response.content_part.added",
                                    "item_id": text_item_id,
                                    "output_index": 0,
                                    "content_index": 0,
                                    "part": {"type": "output_text", "text": ""},
                                }
                            )
                        text_content += content_delta
                        await send_event(
                            {
                                "type": "response.output_text.delta",
                                "item_id": text_item_id,
                                "output_index": 0,
                                "content_index": 0,
                                "delta": content_delta,
                            }
                        )

                    # Tool calls
                    if delta.get("tool_calls"):
                        for tc in delta["tool_calls"]:
                            idx = tc.get("index", 0)
                            if idx not in tool_calls:
                                tc_id = tc.get("id", f"call_{uuid.uuid4().hex[:16]}")
                                tc_name = tc.get("function", {}).get("name", "")
                                tool_calls[idx] = {
                                    "id": tc_id,
                                    "name": tc_name,
                                    "arguments": "",
                                }
                                output_index = (1 if text_item_added else 0) + idx
                                item_id = f"fc_{uuid.uuid4().hex[:16]}"
                                tool_calls[idx]["item_id"] = item_id
                                tool_calls[idx]["output_index"] = output_index
                                await send_event(
                                    {
                                        "type": "response.output_item.added",
                                        "output_index": output_index,
                                        "item": {
                                            "type": "function_call",
                                            "id": item_id,
                                            "call_id": tc_id,
                                            "name": tc_name,
                                            "arguments": "",
                                            "status": "in_progress",
                                        },
                                    }
                                )
                            if tc.get("function", {}).get("name"):
                                tool_calls[idx]["name"] = tc["function"]["name"]
                            arg_delta = tc.get("function", {}).get("arguments", "")
                            if arg_delta:
                                tool_calls[idx]["arguments"] += arg_delta
                                await send_event(
                                    {
                                        "type": "response.function_call_arguments.delta",
                                        "item_id": tool_calls[idx]["item_id"],
                                        "output_index": tool_calls[idx]["output_index"],
                                        "delta": arg_delta,
                                    }
                                )

                    # Finish
                    if finish_reason:
                        log.info(
                            "Stream finished: reason=%s, text_len=%d, tool_calls=%d",
                            finish_reason,
                            len(text_content),
                            len(tool_calls),
                        )
                        break

        except Exception as e:
            log.exception("Error during streaming proxy")
            try:
                await send_event(
                    {"type": "error", "code": "proxy_error", "message": str(e)}
                )
            except Exception:
                pass
            try:
                await response.write_eof()
            except Exception:
                pass
            return response

    # Finalize — wrapped in try/except so client disconnect doesn't crash proxy
    try:
        await _finalize_stream(
            send_event,
            text_item_added,
            text_item_id,
            text_content,
            tool_calls,
            resp_id,
            model,
            usage,
            response_store,
            response,
        )
    except Exception:
        log.warning("Client disconnected during finalization (normal for retries)")
    return response


async def _finalize_stream(
    send_event,
    text_item_added,
    text_item_id,
    text_content,
    tool_calls,
    resp_id,
    model,
    usage,
    response_store,
    response,
):
    if text_item_added:
        await send_event(
            {
                "type": "response.output_text.done",
                "item_id": text_item_id,
                "output_index": 0,
                "content_index": 0,
                "text": text_content,
            }
        )
        await send_event(
            {
                "type": "response.content_part.done",
                "item_id": text_item_id,
                "output_index": 0,
                "content_index": 0,
                "part": {"type": "output_text", "text": text_content},
            }
        )
        await send_event(
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "item": {
                    "type": "message",
                    "id": text_item_id,
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text_content}],
                },
            }
        )

    # Finalize tool calls
    for idx in sorted(tool_calls.keys()):
        tc = tool_calls[idx]
        await send_event(
            {
                "type": "response.function_call_arguments.done",
                "item_id": tc["item_id"],
                "output_index": tc["output_index"],
                "name": tc["name"],
                "arguments": tc["arguments"],
            }
        )
        await send_event(
            {
                "type": "response.output_item.done",
                "output_index": tc["output_index"],
                "item": {
                    "type": "function_call",
                    "id": tc["item_id"],
                    "call_id": tc["id"],
                    "name": tc["name"],
                    "arguments": tc["arguments"],
                    "status": "completed",
                },
            }
        )

    # Build output items for response.completed and store
    output_items = []
    if text_item_added:
        output_items.append(
            {
                "type": "message",
                "id": text_item_id,
                "role": "assistant",
                "content": [{"type": "output_text", "text": text_content}],
            }
        )
    for idx in sorted(tool_calls.keys()):
        tc = tool_calls[idx]
        output_items.append(
            {
                "type": "function_call",
                "id": tc["item_id"],
                "call_id": tc["id"],
                "name": tc["name"],
                "arguments": tc["arguments"],
                "status": "completed",
            }
        )

    # Empty output causes Codex to record 0 tokens and drop. Send a minimal placeholder so the turn completes and the agent continues.
    if not output_items:
        placeholder_id = f"msg_{uuid.uuid4().hex[:16]}"
        output_items.append(
            {
                "type": "message",
                "id": placeholder_id,
                "role": "assistant",
                "content": [{"type": "output_text", "text": ""}],
            }
        )
        log.info("Empty vLLM response; sent minimal placeholder so client continues")

    # Map usage fields
    resp_usage = {
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }

    # Store for potential follow-up requests
    response_store[resp_id] = {
        "output": output_items,
        "model": model,
        "usage": resp_usage,
    }
    # Keep store bounded
    if len(response_store) > 100:
        oldest = list(response_store.keys())[0]
        del response_store[oldest]

    await send_event(
        {
            "type": "response.completed",
            "response": {
                "id": resp_id,
                "status": "completed",
                "model": model,
                "output": output_items,
                "usage": resp_usage,
            },
        }
    )

    await response.write_eof()


async def _handle_non_streaming(
    request: web.Request, chat_body: dict, vllm_url: str, resp_id: str, model: str
) -> web.Response:
    chat_body["stream"] = False
    timeout = ClientTimeout(total=600)
    async with ClientSession(timeout=timeout) as session:
        async with session.post(vllm_url, json=chat_body) as vllm_resp:
            if vllm_resp.status != 200:
                error_text = await vllm_resp.text()
                return web.json_response(
                    {"error": {"message": error_text}}, status=vllm_resp.status
                )
            result = await vllm_resp.json()

    choice = result.get("choices", [{}])[0]
    message = choice.get("message", {})
    output_items = []

    if message.get("content"):
        output_items.append(
            {
                "type": "message",
                "id": f"msg_{uuid.uuid4().hex[:16]}",
                "role": "assistant",
                "content": [{"type": "output_text", "text": message["content"]}],
            }
        )

    for tc in message.get("tool_calls", []):
        output_items.append(
            {
                "type": "function_call",
                "id": f"fc_{uuid.uuid4().hex[:16]}",
                "call_id": tc.get("id", ""),
                "name": tc.get("function", {}).get("name", ""),
                "arguments": tc.get("function", {}).get("arguments", "{}"),
                "status": "completed",
            }
        )

    usage = result.get("usage", {})
    resp_usage = {
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }

    response_store[resp_id] = {
        "output": output_items,
        "model": model,
        "usage": resp_usage,
    }

    return web.json_response(
        {
            "id": resp_id,
            "status": "completed",
            "model": model,
            "output": output_items,
            "usage": resp_usage,
        }
    )


# ---------------------------------------------------------------------------
# GET /v1/responses/{response_id} — return stored response
# ---------------------------------------------------------------------------


async def handle_get_response(request: web.Request) -> web.Response:
    resp_id = request.match_info["response_id"]
    stored = response_store.get(resp_id)
    if not stored:
        return web.json_response(
            {"error": {"message": f"Response {resp_id} not found"}}, status=404
        )
    return web.json_response(
        {
            "id": resp_id,
            "status": "completed",
            "model": stored["model"],
            "output": stored["output"],
            "usage": stored["usage"],
        }
    )


# ---------------------------------------------------------------------------
# Passthrough proxy for all other routes
# ---------------------------------------------------------------------------


async def handle_passthrough(request: web.Request) -> web.StreamResponse:
    vllm_url = f"{VLLM_BASE}{request.path_qs}"
    timeout = ClientTimeout(total=120)
    async with ClientSession(timeout=timeout) as session:
        method = request.method.lower()
        kwargs: dict[str, Any] = {}
        if request.can_read_body:
            kwargs["data"] = await request.read()
            kwargs["headers"] = {"Content-Type": request.content_type}
        async with session.request(method, vllm_url, **kwargs) as vllm_resp:
            resp = web.StreamResponse(
                status=vllm_resp.status, headers=dict(vllm_resp.headers)
            )
            # Remove hop-by-hop headers
            for h in ("Transfer-Encoding", "Connection"):
                resp.headers.pop(h, None)
            await resp.prepare(request)
            async for chunk in vllm_resp.content.iter_any():
                await resp.write(chunk)
            await resp.write_eof()
            return resp


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/v1/responses", handle_responses)
    app.router.add_get("/v1/responses/{response_id}", handle_get_response)
    # Everything else passes through to vLLM
    app.router.add_route("*", "/{path:.*}", handle_passthrough)
    return app


def main():
    parser = argparse.ArgumentParser(
        description="Responses API to Chat Completions proxy"
    )
    parser.add_argument("--listen-port", type=int, default=8000)
    parser.add_argument("--vllm-port", type=int, default=8001)
    args = parser.parse_args()

    global VLLM_BASE
    VLLM_BASE = f"http://127.0.0.1:{args.vllm_port}"

    log.info(
        "Starting Responses->Chat proxy on :%d -> vLLM :%d",
        args.listen_port,
        args.vllm_port,
    )
    web.run_app(
        create_app(), host="127.0.0.1", port=args.listen_port, print=lambda _: None
    )


if __name__ == "__main__":
    main()
