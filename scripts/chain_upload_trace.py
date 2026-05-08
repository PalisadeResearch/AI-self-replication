#!/usr/bin/env python3
"""Upload a qwen-code stream-json JSONL log to Langfuse as a trace with spans.

Usage: python3 chain_upload_trace.py <jsonl-path> --tags tag1,tag2,...
       python3 chain_upload_trace.py <jsonl-path> --tags-file /opt/chain/tags.txt

Reads Langfuse credentials from environment:
  LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone

import requests

PK = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip('"')
SK = os.environ.get("LANGFUSE_SECRET_KEY", "").strip('"')
HOST = os.environ.get("LANGFUSE_BASE_URL", "https://us.cloud.langfuse.com").strip('"')


def parse_args():
    jsonl_path = None
    tags = []
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "--tags" and i + 1 < len(sys.argv):
            tags = [t.strip() for t in sys.argv[i + 1].split(",") if t.strip()]
            i += 2
        elif sys.argv[i] == "--tags-file" and i + 1 < len(sys.argv):
            with open(sys.argv[i + 1]) as f:
                tags = [t.strip() for t in f.read().strip().split(",") if t.strip()]
            i += 2
        elif not jsonl_path:
            jsonl_path = sys.argv[i]
            i += 1
        else:
            i += 1
    return jsonl_path, tags


def parse_jsonl(path):
    """Parse qwen-code stream-json JSONL into spans for Langfuse."""
    spans = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue

            ev_type = ev.get("type", "")
            ts = ev.get("timestamp") or datetime.now(timezone.utc).isoformat()

            if ev_type == "assistant":
                msg = ev.get("message") or {}
                content_parts = msg.get("content", [])
                text_parts = [
                    b.get("text", "") for b in content_parts if b.get("type") == "text"
                ]
                tool_parts = [b for b in content_parts if b.get("type") == "tool_use"]
                if text_parts:
                    spans.append(
                        {
                            "name": "assistant_message",
                            "input": None,
                            "output": "\n".join(text_parts)[:30000],
                            "timestamp": ts,
                        }
                    )
                for tp in tool_parts:
                    spans.append(
                        {
                            "name": f"tool_call:{tp.get('name', 'unknown')}",
                            "input": json.dumps(tp.get("input", {}))[:10000],
                            "output": None,
                            "timestamp": ts,
                        }
                    )

            elif ev_type == "tool_result":
                content = ev.get("content", "")
                if isinstance(content, list):
                    content = "\n".join(
                        b.get("text", "") for b in content if isinstance(b, dict)
                    )
                spans.append(
                    {
                        "name": "tool_result",
                        "input": None,
                        "output": str(content)[:30000],
                        "timestamp": ts,
                    }
                )

            elif ev_type == "result":
                spans.append(
                    {
                        "name": f"result:{ev.get('subtype', 'unknown')}",
                        "input": None,
                        "output": str(ev.get("result", ""))[:30000],
                        "timestamp": ts,
                    }
                )

    return spans


def upload(trace_id, tags, spans):
    events = []
    now = datetime.now(timezone.utc).isoformat()

    events.append(
        {
            "id": str(uuid.uuid4()),
            "type": "trace-create",
            "timestamp": now,
            "body": {
                "id": trace_id,
                "name": "chain_agent_run",
                "tags": tags,
            },
        }
    )

    for s in spans:
        ts = s.get("timestamp") or now
        body = {
            "id": str(uuid.uuid4()),
            "traceId": trace_id,
            "name": s["name"],
            "startTime": ts,
            "endTime": ts,
        }
        if s.get("input"):
            body["input"] = {"command": s["input"]}
        if s.get("output"):
            body["output"] = s["output"]

        events.append(
            {
                "id": str(uuid.uuid4()),
                "type": "span-create",
                "timestamp": ts,
                "body": body,
            }
        )

    uploaded = 0
    for i in range(0, len(events), 50):
        chunk = events[i : i + 50]
        r = requests.post(
            f"{HOST}/api/public/ingestion",
            json={"batch": chunk},
            auth=(PK, SK),
            timeout=120,
        )
        if r.status_code not in (200, 207):
            print(f"ERROR {r.status_code}: {r.text[:300]}", file=sys.stderr)
            return False
        uploaded += len(chunk)

    return True


def main():
    jsonl_path, tags = parse_args()
    if not jsonl_path or not os.path.isfile(jsonl_path):
        print(
            f"Usage: {sys.argv[0]} <jsonl-path> --tags tag1,tag2,...", file=sys.stderr
        )
        sys.exit(1)

    if not PK or not SK:
        print(
            "ERROR: LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY not set", file=sys.stderr
        )
        sys.exit(1)

    spans = parse_jsonl(jsonl_path)
    trace_id = uuid.uuid4().hex
    print(f"Uploading {len(spans)} spans as trace {trace_id} with tags: {tags}")

    ok = upload(trace_id, tags, spans)
    if ok:
        print(f"Uploaded trace {trace_id} ({len(spans)} spans)")
        with open(jsonl_path + ".uploaded", "w") as f:
            f.write(trace_id)
    else:
        print("Upload failed", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
