#!/usr/bin/env python3
"""Read one run directory's transcript and print the metrics that fill a results row.

Handles the four transcript shapes already in this repository:

  codex     event_msg/token_count -> payload.info.total_token_usage   (JSONL)
  omp       message.message.usage, summed over messages               (JSONL)
  opencode  info.tokens + info.cost                                   (JSON)
  dsh       assistant/message.data.usage, summed over messages        (JSONL)

Costs are OpenRouter-equivalent USD, using the same rates and the same
three-part split as the note on index.html: uncached input at the prompt
rate, cached input at the cache-read rate, and output (reasoning included)
at the completion rate.

Usage:
    ./extract_metrics.py <run-dir> [--model glm|qwen|luna|sol|astra] [--row]

--row prints the <tr> to paste into index.html instead of JSON.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# USD per million tokens: (uncached input, cache read, output)
RATES = {
    "glm":   (0.075,  0.015, 0.250),
    "qwen":  (0.420,  0.085, 3.000),
    "luna":  (0.200,  0.020, 1.200),
    "sol":   (1.000,  0.100, 5.000),
    "astra": (10.000, 1.000, 50.000),
}

LABELS = {
    "glm": "GLM 5.3 Flash Max",
    "qwen": "Qwen 3.8 27B x-high",
    "luna": "Luna 5.6 Max",
    "sol": "SOL 5.6 Max",
    "astra": "Astra 6.0 Max",
}


ERROR_MARKERS = (
    '"success":false',
    '"is_error":true',
    '"isError":true',
    "Script failed",
    "Script error:",
    "command not found",
)


def is_tool_error(payload):
    """Tool results carry no common error flag across harnesses, so match markers.

    Definitions differ from the hand-counted Tool errors column on index.html;
    this one is at least applied identically to every run.
    """
    body = json.dumps(payload)
    return any(marker in body for marker in ERROR_MARKERS)


def ts(value):
    """ISO-8601 string or epoch ms/s -> aware datetime."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def read_jsonl(path):
    with open(path) as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def find_transcript(run_dir):
    for name in ("transcript.jsonl", "transcript.json"):
        path = os.path.join(run_dir, name)
        if os.path.exists(path):
            return path
    sys.exit(f"no transcript.jsonl or transcript.json in {run_dir}")


def detect(path, first):
    if path.endswith(".json"):
        return "opencode"
    if first.get("type") == "session_meta":
        return "codex"
    if first.get("type") == "session" and "delegationDepth" in first:
        return "dsh"
    return "omp"


def parse_codex(path):
    started = finished = first_output = None
    usage = {}
    calls = errors = 0
    for event in read_jsonl(path):
        stamp = ts(event.get("timestamp"))
        payload = event.get("payload") or {}
        kind = payload.get("type")
        if event.get("type") == "event_msg":
            if kind == "item_completed":
                item = payload.get("item") or {}
                if (item.get("item_type") or item.get("type")) == "McpToolCall":
                    calls += 1
            if kind == "task_started":
                started = started or stamp
            elif kind == "task_complete":
                finished = stamp
            elif kind == "token_count":
                total = (payload.get("info") or {}).get("total_token_usage")
                if total:
                    usage = total
                    first_output = first_output or stamp
        elif event.get("type") == "response_item":
            if kind in ("function_call", "custom_tool_call"):
                calls += 1
            elif kind in ("function_call_output", "custom_tool_call_output"):
                if is_tool_error(payload):
                    errors += 1
        if stamp:
            finished = finished or stamp
    return {
        "started": started,
        "finished": finished,
        "first_output": first_output,
        "input": usage.get("input_tokens", 0),
        "cached": usage.get("cached_input_tokens", 0),
        "output": usage.get("output_tokens", 0),
        "reasoning": usage.get("reasoning_output_tokens"),
        "tool_calls": calls,
        "tool_errors": errors,
    }


def parse_omp(path):
    started = finished = first_output = None
    totals = {"input": 0, "output": 0, "cacheRead": 0}
    calls = errors = 0
    for event in read_jsonl(path):
        stamp = ts(event.get("timestamp"))
        if stamp:
            started = started or stamp
            finished = stamp
        message = event.get("message") or {}
        usage = message.get("usage") or {}
        if usage:
            first_output = first_output or stamp
            for key in totals:
                totals[key] += usage.get(key) or 0
        for part in message.get("content") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") in ("tool_use", "tool-call", "toolCall"):
                calls += 1
            if part.get("type") in ("tool_result", "tool-result", "toolResult"):
                if part.get("is_error") or part.get("isError"):
                    errors += 1
    return {
        "started": started,
        "finished": finished,
        "first_output": first_output,
        "input": totals["input"] + totals["cacheRead"],
        "cached": totals["cacheRead"],
        "output": totals["output"],
        "reasoning": None,
        "tool_calls": calls,
        "tool_errors": errors,
    }


def parse_opencode(path):
    with open(path) as handle:
        data = json.load(handle)
    info = data.get("info") or {}
    tokens = info.get("tokens") or {}
    cache = tokens.get("cache") or {}
    time = info.get("time") or {}
    calls = errors = 0
    for message in data.get("messages") or []:
        for part in message.get("parts") or []:
            if part.get("type") == "tool":
                calls += 1
                state = part.get("state") or {}
                if state.get("status") == "error":
                    errors += 1
    return {
        "started": ts(time.get("created")),
        "finished": ts(time.get("completed") or time.get("updated")),
        "first_output": None,
        "input": (tokens.get("input") or 0) + (cache.get("read") or 0),
        "cached": cache.get("read") or 0,
        # OpenCode reports reasoning separately; the generated total is the sum.
        "output": (tokens.get("output") or 0) + (tokens.get("reasoning") or 0),
        "reasoning": tokens.get("reasoning"),
        "tool_calls": calls,
        "tool_errors": errors,
    }


def parse_dsh(path):
    """Duration sums active turn time, so a pause between turns is excluded."""
    active = 0.0
    turn_open = None
    started = first_output = None
    totals = {"input": 0, "output": 0, "cached": 0}
    calls = errors = 0
    for event in read_jsonl(path):
        kind = event.get("type")
        stamp = ts(event.get("time") or event.get("createdAt"))
        data = event.get("data") or {}
        if stamp:
            started = started or stamp
        if kind == "turn/start":
            turn_open = stamp
        elif kind == "turn/end" and turn_open and stamp:
            active += (stamp - turn_open).total_seconds()
            turn_open = None
        elif kind == "assistant/chunk":
            first_output = first_output or stamp
        elif kind == "assistant/message":
            # inputTokens here is uncached only; cache reads are counted separately.
            usage = data.get("usage") or {}
            totals["input"] += usage.get("inputTokens") or 0
            totals["output"] += usage.get("outputTokens") or 0
            totals["cached"] += usage.get("cacheReadTokens") or 0
        elif kind == "tool/call":
            calls += 1
        elif kind == "tool/result":
            if is_tool_error(data):
                errors += 1
    return {
        "started": started,
        "finished": None,
        "first_output": first_output,
        "duration_override": active or None,
        "input": totals["input"] + totals["cached"],
        "cached": totals["cached"],
        "output": totals["output"],
        "reasoning": None,
        "tool_calls": calls,
        "tool_errors": errors,
    }


PARSERS = {
    "codex": parse_codex,
    "omp": parse_omp,
    "opencode": parse_opencode,
    "dsh": parse_dsh,
}


def guess_model(run_dir):
    name = os.path.basename(os.path.abspath(run_dir)).lower()
    for key in ("glm", "qwen", "luna", "sol", "astra"):
        if key in name:
            return key
    return None


def human_duration(seconds):
    if seconds is None:
        return "—"
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}m {rest:06.3f}s" if minutes else f"{rest:.3f}s"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    parser.add_argument("--model", choices=sorted(RATES))
    parser.add_argument("--harness")
    parser.add_argument("--file", help="output artifact to link from the File column")
    parser.add_argument("--row", action="store_true", help="print an index.html <tr>")
    args = parser.parse_args()

    path = find_transcript(args.run_dir)
    first = next(iter(read_jsonl(path)), {}) if path.endswith(".jsonl") else {}
    harness = args.harness or detect(path, first)
    raw = PARSERS[detect(path, first)](path)

    model = args.model or guess_model(args.run_dir)
    if not model:
        sys.exit("could not infer the model from the directory name; pass --model")

    duration = raw.get("duration_override")
    if duration is None and raw["started"] and raw["finished"]:
        duration = (raw["finished"] - raw["started"]).total_seconds()
    ttft = None
    if raw["started"] and raw["first_output"]:
        ttft = (raw["first_output"] - raw["started"]).total_seconds()

    total_input = raw["input"]
    cached = raw["cached"]
    uncached = max(total_input - cached, 0)
    output = raw["output"]
    in_rate, cache_rate, out_rate = RATES[model]
    input_cost = uncached * in_rate / 1e6
    cache_cost = cached * cache_rate / 1e6
    output_cost = output * out_rate / 1e6

    row = {
        "model": LABELS[model],
        "harness": harness,
        "duration_s": round(duration, 3) if duration else None,
        "ttft_s": round(ttft, 3) if ttft else None,
        "input_tokens": total_input,
        "output_tokens": output,
        "reasoning_tokens": raw["reasoning"],
        "total_tokens": total_input + output,
        "input_cost": round(input_cost, 6),
        "cache_read_cost": round(cache_cost, 6),
        "output_cost": round(output_cost, 6),
        "total_cost": round(input_cost + cache_cost + output_cost, 6),
        "cached_input_pct": round(100 * cached / total_input, 2) if total_input else None,
        "tool_calls": raw["tool_calls"],
        "tool_errors": raw["tool_errors"],
    }

    if not args.row:
        print(json.dumps(row, indent=2))
        return

    def metric(value, text=None):
        if value is None:
            return '<td class="metric" data-sort="">—</td>'
        return f'<td class="metric" data-sort="{value}">{text if text is not None else f"{value:,}"}</td>'

    def cost(value):
        return f'<td class="metric cost" data-sort="{value}">${value:.6f}</td>'

    link = args.file or "recommendation.html"
    cells = [
        f'<td class="model">{row["model"]}</td>',
        f'<td class="harness">{row["harness"]}</td>',
        f'<td class="file"><a class="open" href="{os.path.basename(os.path.abspath(args.run_dir))}/{link}">Open</a></td>',
        metric(row["duration_s"], human_duration(row["duration_s"])),
        metric(row["ttft_s"], f'{row["ttft_s"]:.3f}s' if row["ttft_s"] else None),
        metric(row["input_tokens"]),
        metric(row["output_tokens"]),
        metric(row["reasoning_tokens"]),
        metric(row["total_tokens"]),
        cost(row["input_cost"]),
        cost(row["cache_read_cost"]),
        cost(row["output_cost"]),
        cost(row["total_cost"]),
        metric(row["cached_input_pct"], f'{row["cached_input_pct"]:.2f}%' if row["cached_input_pct"] else None),
        metric(row["tool_calls"]),
        metric(row["tool_errors"]),
    ]
    print("<tr>" + "".join(cells) + "</tr>")


if __name__ == "__main__":
    main()
