#!/usr/bin/env python3
"""Run the Restaurant Pick task against one OpenRouter model.

This is a fifth "harness" for the suite: a minimal tool-calling loop, so the
models in the matrix can be compared without installing Codex, OpenCode, OMP or
DSH. It is deliberately thin -- the point is to measure the model, so the loop
adds no planning, no retries and no prompting beyond PROMPT.md.

Every model gets the same four tools and the same prompt, and the transcript is
written in a format extract_metrics.py reads (`--format openrouter`).

    export OPENROUTER_API_KEY=sk-or-v1-...
    node tools_server.js 8791 &
    ./runner.py --model glm --target-date "Saturday 17 October 2026" \
        --out ../../rpick-openrouter-glm53-flash

Costs real money. Astra is $10/M input and $50/M output; the equivalent hangar
run cost $4.04. Use --dry-run to see the request without sending it.
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta, timezone

API = "https://openrouter.ai/api/v1/chat/completions"

# The five models the hangar table prices, with its own OpenRouter ids.
MODELS = {
    "glm":   "z-ai/glm-5.3-flash",
    "qwen":  "qwen/qwen3.8-27b",
    "luna":  "openai/gpt-5.6-luna",
    "sol":   "openai/gpt-5.6-sol",
    "astra": "openai/gpt-6-astra",
}

TOOLS = [
    {"type": "function", "function": {
        "name": "fetch_url",
        "description": ("HTTP request from a real browser context. Cookies persist across "
                        "calls, and SevenRooms pages are pre-loaded so its availability "
                        "endpoint will answer. SevenRooms responses are returned with "
                        "per-slot photo and description fields stripped; the documented "
                        "structure is unchanged."),
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"},
            "method": {"type": "string", "enum": ["GET", "POST"]},
            "body": {"type": "string"},
        }, "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "maps_lookup",
        "description": ("Google Maps place lookup. Returns rating, address and the opening "
                        "hours rows the panel exposes. Review counts are NOT available "
                        "from this surface and come back null."),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "search_timeout",
        "description": "Search timeout.com for articles and venue pages.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Write the final deliverable. Only recommendation.html is accepted.",
        "parameters": {"type": "object", "properties": {
            "filename": {"type": "string"},
            "content": {"type": "string"},
        }, "required": ["filename", "content"]}}},
]


def next_saturday(min_days=14):
    """The rule from PROMPT.md: a Saturday at least min_days out."""
    day = date.today() + timedelta(days=min_days)
    while day.weekday() != 5:
        day += timedelta(days=1)
    return day


def build_prompt(path, target):
    with open(path) as handle:
        text = handle.read()
    # Everything below the horizontal rule is the prompt itself.
    body = text.split("\n---\n", 1)[1].strip()
    unpadded = f"{target.year}-{target.month}-{target.day}"
    return (body
            .replace("{{TARGET_DATE}}", target.strftime("%A %-d %B %Y"))
            .replace("{{TARGET_DATE_ISO_UNPADDED}}", unpadded)
            .replace("{{TARGET_DATE_ISO}}", target.isoformat()))


def call_tool(name, args, tools_port, out_dir):
    if name == "write_file":
        filename = os.path.basename(args.get("filename", ""))
        if filename != "recommendation.html":
            return {"error": "only recommendation.html is accepted"}
        path = os.path.join(out_dir, filename)
        with open(path, "w") as handle:
            handle.write(args.get("content", ""))
        return {"written": filename, "bytes": len(args.get("content", ""))}

    route = {"fetch_url": "/fetch", "maps_lookup": "/maps",
             "search_timeout": "/timeout"}.get(name)
    if not route:
        return {"error": f"unknown tool {name}"}
    request = urllib.request.Request(
        f"http://127.0.0.1:{tools_port}{route}",
        data=json.dumps(args).encode(),
        headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read())
    except Exception as exc:  # the tool server is local; a failure is worth seeing
        return {"error": f"tool server: {exc}"}


def stream_turn(key, model, messages, log):
    """One assistant turn. Returns (message, usage, ttft_seconds)."""
    payload = {
        "model": model,
        "messages": messages,
        "tools": TOOLS,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    request = urllib.request.Request(API, data=json.dumps(payload).encode(), headers={
        "Authorization": f"Bearer {key}",
        "content-type": "application/json",
        # OpenRouter asks for these; they also make the run identifiable in the
        # dashboard alongside the other runs.
        "HTTP-Referer": "https://github.com/alvins82/hangar-harness-model-tests",
        "X-Title": "Restaurant Pick benchmark",
    })
    started = time.time()
    ttft = None
    content, tool_calls, usage, finish = "", {}, None, None

    with urllib.request.urlopen(request, timeout=1800) as response:
        for raw in response:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            if chunk.get("usage"):
                usage = chunk["usage"]
            for choice in chunk.get("choices") or []:
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    if ttft is None:
                        ttft = time.time() - started
                    content += delta["content"]
                for call in delta.get("tool_calls") or []:
                    if ttft is None:
                        ttft = time.time() - started
                    slot = tool_calls.setdefault(call.get("index", 0),
                                                 {"id": "", "name": "", "args": ""})
                    if call.get("id"):
                        slot["id"] = call["id"]
                    fn = call.get("function") or {}
                    if fn.get("name"):
                        slot["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["args"] += fn["arguments"]

    message = {"role": "assistant", "content": content or None}
    ordered = [tool_calls[k] for k in sorted(tool_calls)]
    if ordered:
        message["tool_calls"] = [
            {"id": c["id"] or f"call_{i}", "type": "function",
             "function": {"name": c["name"], "arguments": c["args"]}}
            for i, c in enumerate(ordered)]
    log({"type": "assistant/message", "finish_reason": finish,
         "usage": usage, "ttft_s": ttft, "content_chars": len(content),
         "tool_calls": [c["name"] for c in ordered]})
    return message, usage, ttft


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=sorted(MODELS), required=True)
    parser.add_argument("--out", required=True, help="run directory to create")
    parser.add_argument("--prompt", default=os.path.join(os.path.dirname(__file__), "..", "PROMPT.md"))
    parser.add_argument("--target-date", help='e.g. "Saturday 17 October 2026"; default is the next Saturday 14+ days out')
    parser.add_argument("--tools-port", type=int, default=8791)
    parser.add_argument("--max-turns", type=int, default=40)
    parser.add_argument("--dry-run", action="store_true", help="print the prompt and exit")
    args = parser.parse_args()

    target = (datetime.strptime(args.target_date, "%A %d %B %Y").date()
              if args.target_date else next_saturday())
    if target.weekday() != 5:
        sys.exit(f"{target} is a {target.strftime('%A')}, not a Saturday")
    if (target - date.today()).days < 14:
        sys.exit(f"{target} is only {(target - date.today()).days} days out; the rule is 14+")

    prompt = build_prompt(args.prompt, target)
    if args.dry_run:
        print(prompt)
        print(f"\n--- model {MODELS[args.model]} | target {target} | "
              f"{len(prompt)} chars of prompt ---", file=sys.stderr)
        return 0

    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("OPENROUTER_API_KEY is not set")

    os.makedirs(args.out, exist_ok=True)
    transcript = open(os.path.join(args.out, "transcript.jsonl"), "w")

    def log(event):
        event["time"] = datetime.now(timezone.utc).isoformat()
        transcript.write(json.dumps(event) + "\n")
        transcript.flush()

    log({"type": "session", "model": MODELS[args.model], "model_key": args.model,
         "target_date": target.isoformat(), "run_date": date.today().isoformat(),
         "prompt_chars": len(prompt), "tools": [t["function"]["name"] for t in TOOLS]})

    messages = [{"role": "user", "content": prompt}]
    started = time.time()
    calls = errors = 0

    for turn in range(args.max_turns):
        log({"type": "turn/start", "turn": turn})
        try:
            message, usage, ttft = stream_turn(key, MODELS[args.model], messages, log)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            log({"type": "error", "http": exc.code, "detail": detail})
            print(f"HTTP {exc.code}: {detail}", file=sys.stderr)
            break
        messages.append(message)
        log({"type": "turn/end", "turn": turn})

        if not message.get("tool_calls"):
            log({"type": "session/complete", "reason": "no more tool calls"})
            break

        for call in message["tool_calls"]:
            name = call["function"]["name"]
            try:
                tool_args = json.loads(call["function"]["arguments"] or "{}")
            except json.JSONDecodeError as exc:
                tool_args, result = {}, {"error": f"unparseable arguments: {exc}"}
                errors += 1
                calls += 1
                log({"type": "tool/call", "name": name, "args_raw": call["function"]["arguments"][:400]})
                log({"type": "tool/result", "name": name, "error": result["error"]})
                messages.append({"role": "tool", "tool_call_id": call["id"],
                                 "content": json.dumps(result)})
                continue

            calls += 1
            log({"type": "tool/call", "name": name,
                 "args": {k: str(v)[:300] for k, v in tool_args.items()}})
            result = call_tool(name, tool_args, args.tools_port, args.out)
            if isinstance(result, dict) and result.get("error"):
                errors += 1
            body = json.dumps(result)
            log({"type": "tool/result", "name": name, "bytes": len(body),
                 **({"error": result["error"]} if isinstance(result, dict) and result.get("error") else {})})
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": body})
    else:
        log({"type": "session/complete", "reason": f"hit --max-turns {args.max_turns}"})

    wrote = os.path.exists(os.path.join(args.out, "recommendation.html"))
    log({"type": "session/end", "duration_s": round(time.time() - started, 3),
         "tool_calls": calls, "tool_errors": errors, "produced_output": wrote})
    transcript.close()

    print(f"model      {MODELS[args.model]}")
    print(f"target     {target} ({target.strftime('%A')})")
    print(f"duration   {time.time() - started:.1f}s")
    print(f"tool calls {calls} ({errors} errors)")
    print(f"output     {'recommendation.html written' if wrote else 'NO OUTPUT PRODUCED'}")
    print(f"transcript {os.path.join(args.out, 'transcript.jsonl')}")
    return 0 if wrote else 1


if __name__ == "__main__":
    sys.exit(main())
