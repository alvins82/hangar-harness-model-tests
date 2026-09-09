#!/usr/bin/env python3
"""Read one run directory's transcript and print the metrics that fill a results row.

Handles the four transcript shapes in this repository:

  codex       event_msg/token_count -> payload.info.total_token_usage (JSONL)
  openrouter  assistant/message.usage, summed over turns               (JSONL)
  omp       message.message.usage, summed over messages               (JSONL)
  opencode  info.tokens + info.time                                   (JSON)
  dsh       assistant/message.data.usage, summed over messages        (JSONL)

Costs are OpenRouter-equivalent USD using the same rates and the same three-part
split as the note on the root index.html: uncached input at the prompt rate,
cached input at the cache-read rate, output (reasoning included) at the
completion rate.

Token and cost figures are pinned against the published hangar rows by
test_extract_metrics.py. Duration, TTFT and the tool counts are transcript-derived
to one stated definition per harness -- see README.md for what each means and
where it departs from the hangar table.

Usage:
    ./extract_metrics.py <run-dir> --model glm|qwen|luna|sol|astra [--row]

--row prints the <tr> for restaurant-pick/index.html instead of JSON.
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
    # Added to run the baseline's own model through this harness, so the only
    # variable between it and the Claude Code baseline is the harness.
    "opus":  (5.000,  0.500, 25.000),
}

LABELS = {
    "glm": "GLM 5.3 Flash Max",
    "qwen": "Qwen 3.8 27B x-high",
    "luna": "Luna 5.6 Max",
    "sol": "SOL 5.6 Max",
    "astra": "Astra 6.0 Max",
    "opus":  "Opus 5",
}


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
    """Identify the harness, or fail loudly.

    Guessing wrong here means emitting a plausible row of zeros, so an
    unrecognised transcript is an error rather than a default.
    """
    if path.endswith(".json"):
        return "opencode"
    if first.get("type") == "session_meta":
        return "codex"
    if first.get("type") == "session" and "delegationDepth" in first:
        return "dsh"
    if first.get("type") == "session" and "model_key" in first:
        return "openrouter"
    if first.get("type") in ("title", "session", "metadata", "model_change"):
        return "omp"
    sys.exit(
        f"cannot identify the harness from {path} (first record type "
        f"{first.get('type')!r}); pass --format to force one of "
        f"{', '.join(sorted(PARSERS))}"
    )


def parse_codex(path):
    started = finished = last = first_output = None
    usage = {}
    calls = errors = 0
    for event in read_jsonl(path):
        stamp = ts(event.get("timestamp"))
        if stamp:
            last = stamp
        payload = event.get("payload") or {}
        kind = payload.get("type")
        if event.get("type") == "event_msg":
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
            # Tool calls arrive as response items. MCP calls are also announced as
            # item_completed events with the same call_id, so counting both
            # double-counts; response items alone match the published counts.
            if kind in ("function_call", "custom_tool_call"):
                calls += 1
            elif kind in ("function_call_output", "custom_tool_call_output"):
                if codex_output_failed(payload):
                    errors += 1
    return {
        "started": started,
        # Fall back to the last event, never the first: a run killed before
        # task_complete would otherwise report a negative duration.
        "finished": finished or last,
        "first_output": first_output,
        "input": usage.get("input_tokens", 0),
        "cached": usage.get("cached_input_tokens", 0),
        "output": usage.get("output_tokens", 0),
        "reasoning": usage.get("reasoning_output_tokens"),
        "tool_calls": calls,
        "tool_errors": errors,
    }


def codex_output_failed(payload):
    """Codex tool output carries no error flag, so read the text it returns."""
    for part in payload.get("output") or []:
        if isinstance(part, dict):
            text = part.get("text") or ""
            if text.startswith("Script failed") or "Script error:" in text:
                return True
    return False


def parse_omp(path):
    started = finished = first_output = None
    totals = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}
    reasoning = None
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
            # Present on some models only; absent means the harness did not
            # report it, which the table shows as a dash rather than a zero.
            if "reasoningTokens" in usage:
                reasoning = (reasoning or 0) + (usage["reasoningTokens"] or 0)
        for part in message.get("content") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") in ("tool_use", "tool-call", "toolCall"):
                calls += 1
            elif part.get("type") in ("tool_result", "tool-result", "toolResult"):
                if part.get("is_error") or part.get("isError") or part.get("error"):
                    errors += 1
    return {
        "started": started,
        "finished": finished,
        "first_output": first_output,
        "input": totals["input"] + totals["cacheRead"],
        "cached": totals["cacheRead"],
        "cache_write": totals["cacheWrite"],
        "output": totals["output"],
        "reasoning": reasoning,
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
                if (part.get("state") or {}).get("status") == "error":
                    errors += 1
    return {
        "started": ts(time.get("created")),
        # The session carries created/updated only; updated is the end of the
        # session and reproduces the published durations exactly.
        "finished": ts(time.get("updated")),
        "first_output": None,
        "input": (tokens.get("input") or 0) + (cache.get("read") or 0),
        "cached": cache.get("read") or 0,
        "cache_write": cache.get("write") or 0,
        # OpenCode reports reasoning outside its output count; the generated
        # total published on the hangar table is the sum.
        "output": (tokens.get("output") or 0) + (tokens.get("reasoning") or 0),
        "reasoning": tokens.get("reasoning"),
        "tool_calls": calls,
        "tool_errors": errors,
    }


def parse_dsh(path):
    """Duration sums active turn time, so a pause between turns is excluded.

    TTFT is measured from the first turn/start rather than the session record,
    which can predate the first turn by many minutes on a resumed session.
    """
    active = 0.0
    turn_open = first_turn = first_output = None
    totals = {"input": 0, "output": 0, "cached": 0}
    calls = errors = 0
    for event in read_jsonl(path):
        kind = event.get("type")
        stamp = ts(event.get("time") or event.get("createdAt"))
        data = event.get("data") or {}
        if kind == "turn/start":
            turn_open = stamp
            first_turn = first_turn or stamp
        elif kind == "turn/end" and turn_open and stamp:
            active += (stamp - turn_open).total_seconds()
            turn_open = None
        elif kind == "assistant/chunk":
            first_output = first_output or stamp
        elif kind == "assistant/message":
            # inputTokens is uncached only; cache reads are a separate field.
            # Compaction requests are excluded, matching the published rows.
            usage = data.get("usage") or {}
            totals["input"] += usage.get("inputTokens") or 0
            totals["output"] += usage.get("outputTokens") or 0
            totals["cached"] += usage.get("cacheReadTokens") or 0
        elif kind == "tool/call":
            calls += 1
        elif kind == "tool/result":
            if data.get("error") or data.get("isError"):
                errors += 1
    return {
        "started": first_turn,
        "finished": None,
        "duration_override": active or None,
        "first_output": first_output,
        "input": totals["input"] + totals["cached"],
        "cached": totals["cached"],
        "output": totals["output"],
        "reasoning": None,
        "tool_calls": calls,
        "tool_errors": errors,
    }


def parse_openrouter(path):
    """The runner in openrouter/ writes this shape.

    OpenRouter reports prompt_tokens inclusive of cached_tokens, and
    completion_tokens inclusive of reasoning_tokens, matching how the hangar
    table defines its Input and Output columns.
    """
    started = finished = first_output = None
    totals = {"input": 0, "cached": 0, "output": 0}
    reasoning = None
    calls = errors = 0
    ttft = None
    truncated = True
    for event in read_jsonl(path):
        kind = event.get("type")
        stamp = ts(event.get("time"))
        if kind in ("session/end", "session/complete"):
            truncated = False
        if kind == "turn/start":
            started = started or stamp
        elif kind == "assistant/message":
            usage = event.get("usage") or {}
            totals["input"] += usage.get("prompt_tokens") or 0
            totals["output"] += usage.get("completion_tokens") or 0
            totals["cached"] += (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
            detail = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
            if detail is not None:
                reasoning = (reasoning or 0) + detail
            if ttft is None and event.get("ttft_s") is not None:
                ttft = event["ttft_s"]
            first_output = first_output or stamp
        elif kind == "tool/call":
            calls += 1
        elif kind == "tool/result":
            if event.get("error"):
                errors += 1
        if stamp:
            # Last event wins. Pinning this to the first timestamp yields a
            # duration of zero, or a negative one on a truncated run.
            finished = stamp
    return {
        "started": started,
        "finished": finished,
        "first_output": first_output,
        # The runner measures TTFT directly off the stream, which beats
        # inferring it from event timestamps.
        "ttft_override": ttft,
        "input": totals["input"],
        "cached": totals["cached"],
        "output": totals["output"],
        "reasoning": reasoning,
        "tool_calls": calls,
        "tool_errors": errors,
        # No terminal event means the process was killed rather than finishing,
        # so the row describes a partial run.
        "truncated": truncated,
    }


PARSERS = {
    "codex": parse_codex,
    "openrouter": parse_openrouter,
    "omp": parse_omp,
    "opencode": parse_opencode,
    "dsh": parse_dsh,
}


def human_duration(seconds):
    if seconds is None:
        return "—"
    if seconds < 0:
        return f"invalid ({seconds:.3f}s)"
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}m {rest:06.3f}s" if minutes else f"{rest:.3f}s"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    # Required: inferring it from the directory name silently misprices
    # hangar-codex-luna56-max, whose transcript records gpt-5.6-sol.
    parser.add_argument("--model", choices=sorted(RATES), required=True)
    parser.add_argument("--harness", help="label for the Harness column")
    parser.add_argument("--format", choices=sorted(PARSERS), help="force a transcript format")
    parser.add_argument("--file", default="recommendation.html", help="artifact to link")
    parser.add_argument("--row", action="store_true", help="print an index.html <tr>")
    args = parser.parse_args()

    path = find_transcript(args.run_dir)
    first = next(iter(read_jsonl(path)), {}) if path.endswith(".jsonl") else {}
    fmt = args.format or detect(path, first)
    raw = PARSERS[fmt](path)

    duration = raw.get("duration_override")
    if duration is None and raw["started"] and raw["finished"]:
        duration = (raw["finished"] - raw["started"]).total_seconds()
    ttft = raw.get("ttft_override")
    if ttft is None and raw["started"] and raw["first_output"]:
        ttft = (raw["first_output"] - raw["started"]).total_seconds()

    total_input = raw["input"]
    cached = min(raw["cached"], total_input)
    uncached = max(total_input - cached, 0)
    output = raw["output"]
    in_rate, cache_rate, out_rate = RATES[args.model]
    input_cost = uncached * in_rate / 1e6
    cache_cost = cached * cache_rate / 1e6
    output_cost = output * out_rate / 1e6

    if raw.get("cache_write"):
        print(f"warning: {raw['cache_write']:,} cache-write tokens are not priced",
              file=sys.stderr)

    row = {
        "model": LABELS[args.model],
        "harness": args.harness or fmt,
        "duration_s": round(duration, 3) if duration is not None else None,
        "ttft_s": round(ttft, 3) if ttft is not None else None,
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
    if raw.get("truncated"):
        row["truncated"] = True
        print("warning: no terminal event in the transcript -- this run was "
              "killed rather than finishing, so the row is partial",
              file=sys.stderr)

    if not args.row:
        print(json.dumps(row, indent=2))
        return

    def metric(value, text=None):
        if value is None:
            return '<td class="metric" data-sort="">—</td>'
        return f'<td class="metric" data-sort="{value}">{text if text is not None else f"{value:,}"}</td>'

    def cost(value):
        return f'<td class="metric cost" data-sort="{value}">${value:.6f}</td>'

    # The results table lives in restaurant-pick/ and run directories sit at the
    # repository root, so the link needs to climb out.
    href = f'../{os.path.basename(os.path.abspath(args.run_dir))}/{args.file}'
    pct = row["cached_input_pct"]
    cells = [
        f'<td class="model">{row["model"]}</td>',
        f'<td class="harness">{row["harness"]}</td>',
        f'<td class="file"><a class="open" href="{href}">Open</a></td>',
        # Score, Fabrications and Booking checks are hand-scored from
        # score.json against RUBRIC.md; emitted empty for the operator to fill.
        '<td class="metric" data-sort="">—</td>',
        '<td class="metric" data-sort="">—</td>',
        '<td class="status">—</td>',
        metric(row["duration_s"], human_duration(row["duration_s"])),
        metric(row["ttft_s"], f'{row["ttft_s"]:.3f}s' if row["ttft_s"] is not None else None),
        metric(row["input_tokens"]),
        metric(row["output_tokens"]),
        metric(row["reasoning_tokens"]),
        metric(row["total_tokens"]),
        cost(row["input_cost"]),
        cost(row["cache_read_cost"]),
        cost(row["output_cost"]),
        cost(row["total_cost"]),
        metric(pct, f'{pct:.2f}%' if pct is not None else None),
        metric(row["tool_calls"]),
        metric(row["tool_errors"]),
    ]
    print("<tr>" + "".join(cells) + "</tr>")


if __name__ == "__main__":
    main()
