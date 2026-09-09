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

# USD per million tokens: (uncached input, cache read, output). Same rates as
# the hangar table, so the running estimate matches what extract_metrics reports.
RATES = {
    "glm":   (0.075,  0.015, 0.250),
    "qwen":  (0.420,  0.085, 3.000),
    "luna":  (0.200,  0.020, 1.200),
    "sol":   (1.000,  0.100, 5.000),
    "astra": (10.000, 1.000, 50.000),
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
                # strict=False: Qwen emits raw control characters inside its
                # reasoning field, which the strict decoder rejects.
                chunk = json.loads(data, strict=False)
            except json.JSONDecodeError:
                continue
            if chunk.get("usage"):
                usage = chunk["usage"]
            for choice in chunk.get("choices") or []:
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]
                delta = choice.get("delta") or {}
                # Reasoning arrives in its own field and is the model's first
                # real output, so it counts toward TTFT; otherwise a model that
                # thinks for seven minutes looks like it stalled.
                if delta.get("reasoning") and ttft is None:
                    ttft = time.time() - started
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
    # Astra is $10/M input and $50/M output; one loop that will not settle can
    # spend more than the account holds. Stop on cost, not just on turns.
    parser.add_argument("--max-cost", type=float, default=2.00,
                        help="abort once estimated spend passes this many USD")
    # A run that researches until it is killed produces nothing scoreable. These
    # two nudges ask for an early draft and then for a finalisation, so partial
    # work survives. Applied identically to every model, and recorded in the
    # transcript so a reader can see the harness intervened.
    parser.add_argument("--draft-after", type=int, default=6,
                        help="ask for a first recommendation.html after this many turns (0 disables)")
    parser.add_argument("--finalise-at", type=float, default=0.65,
                        help="fraction of --max-cost or --max-turns at which to demand a final write")
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
        keyfile = os.path.expanduser("~/.openrouter-key")
        if os.path.exists(keyfile):
            with open(keyfile) as handle:
                key = handle.read().strip()
    if not key:
        sys.exit("set OPENROUTER_API_KEY or put the key in ~/.openrouter-key")

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
    spend = 0.0
    in_rate, cache_rate, out_rate = RATES[args.model]

    drafted = finalised = False
    grace_turns = 0
    GRACE_LIMIT = 2          # turns allowed past the cap purely to land a write
    GRACE_COST_MULT = 1.25   # and never beyond this multiple of the cap
    stop_reason = None

    def deliverable():
        return os.path.exists(os.path.join(args.out, "recommendation.html"))

    def nudge(kind, text, **extra):
        """Queue a harness instruction for the model's next turn.

        Appended at the END of a loop iteration, after any tool results, because
        a user message may not interrupt a tool_calls/tool_result pair.
        """
        log({"type": "harness/nudge", "kind": kind, **extra})
        messages.append({"role": "user", "content": text})

    for turn in range(args.max_turns):
        log({"type": "turn/start", "turn": turn})
        try:
            message, usage, ttft = stream_turn(key, MODELS[args.model], messages, log)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            log({"type": "error", "http": exc.code, "detail": detail})
            print(f"HTTP {exc.code}: {detail}", file=sys.stderr)
            stop_reason = f"HTTP {exc.code}"
            break
        messages.append(message)

        if usage:
            cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
            uncached = max((usage.get("prompt_tokens") or 0) - cached, 0)
            spend += (uncached * in_rate + cached * cache_rate
                      + (usage.get("completion_tokens") or 0) * out_rate) / 1e6
        log({"type": "turn/end", "turn": turn, "spend_usd": round(spend, 6)})

        # Execute this turn's tools first, so the message history stays valid.
        for call in message.get("tool_calls") or []:
            name = call["function"]["name"]
            calls += 1
            try:
                tool_args = json.loads(call["function"]["arguments"] or "{}")
            except json.JSONDecodeError as exc:
                errors += 1
                log({"type": "tool/call", "name": name,
                     "args_raw": call["function"]["arguments"][:400]})
                log({"type": "tool/result", "name": name, "error": f"unparseable arguments: {exc}"})
                messages.append({"role": "tool", "tool_call_id": call["id"],
                                 "content": json.dumps({"error": f"unparseable arguments: {exc}"})})
                continue
            log({"type": "tool/call", "name": name,
                 "args": {k: str(v)[:300] for k, v in tool_args.items()}})
            result = call_tool(name, tool_args, args.tools_port, args.out)
            if isinstance(result, dict) and result.get("error"):
                errors += 1
            body = json.dumps(result)
            log({"type": "tool/result", "name": name, "bytes": len(body),
                 "result": body[:20000], "result_truncated": len(body) > 20000,
                 **({"error": result["error"]} if isinstance(result, dict) and result.get("error") else {})})
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": body})

        if not message.get("tool_calls"):
            stop_reason = "no more tool calls"
            break

        # Budget decisions come last, once spend for this turn is known and the
        # history is closed, so a queued nudge is guaranteed a turn to act on.
        if spend >= args.max_cost:
            if deliverable() or grace_turns >= GRACE_LIMIT or spend >= args.max_cost * GRACE_COST_MULT:
                stop_reason = "hit --max-cost"
                log({"type": "session/complete", "reason": stop_reason,
                     "spend_usd": round(spend, 6), "max_cost": args.max_cost,
                     "grace_turns_used": grace_turns, "produced_output": deliverable()})
                print(f"stopped: estimated spend ${spend:.4f} passed --max-cost "
                      f"${args.max_cost:.2f}"
                      + ("" if deliverable() else " with no deliverable"), file=sys.stderr)
                break
            grace_turns += 1
            nudge("grace",
                  "BUDGET EXHAUSTED. This is your last chance to produce output. Call "
                  "write_file with recommendation.html immediately, using only what you "
                  "have already confirmed and marking the rest unconfirmed. Do not call "
                  "any other tool.",
                  turn=turn, grace_turn=grace_turns, spend_usd=round(spend, 6))
            continue

        spent_frac = max(spend / args.max_cost if args.max_cost else 0,
                         (turn + 1) / args.max_turns if args.max_turns else 0)

        if not finalised and spent_frac >= args.finalise_at and not deliverable():
            finalised = True
            nudge("finalise",
                  "BUDGET NOTICE from the harness, not the diner. You are near the end "
                  "of this run's budget. Stop researching and call write_file now with "
                  "recommendation.html, using only what you have already confirmed. Mark "
                  "anything you could not verify as unconfirmed rather than dropping it "
                  "or guessing. An incomplete but honest write-up is worth far more than "
                  "no write-up at all.",
                  turn=turn, spent_frac=round(spent_frac, 3))
        elif not drafted and args.draft_after and (turn + 1) >= args.draft_after and not deliverable():
            drafted = True
            nudge("draft",
                  "PROGRESS NOTICE from the harness, not the diner. Write your best "
                  "recommendation.html now from what you have confirmed so far, then "
                  "carry on researching and call write_file again to improve it. Do not "
                  "wait until you are finished to produce a first version.",
                  turn=turn)
    else:
        stop_reason = f"hit --max-turns {args.max_turns}"

    if stop_reason and stop_reason != "hit --max-cost":
        log({"type": "session/complete", "reason": stop_reason})

    wrote = os.path.exists(os.path.join(args.out, "recommendation.html"))
    writes = sum(1 for m in messages if m.get("role") == "assistant"
                 for c in (m.get("tool_calls") or [])
                 if c["function"]["name"] == "write_file")
    log({"type": "session/end", "duration_s": round(time.time() - started, 3),
         "tool_calls": calls, "tool_errors": errors, "produced_output": wrote,
         "write_file_calls": writes, "nudged_draft": drafted,
         "nudged_finalise": finalised, "spend_usd": round(spend, 6)})
    transcript.close()

    print(f"model      {MODELS[args.model]}")
    print(f"target     {target} ({target.strftime('%A')})")
    print(f"duration   {time.time() - started:.1f}s")
    print(f"tool calls {calls} ({errors} errors)")
    print(f"est. spend ${spend:.4f}")
    print(f"revisions  {writes} write_file call(s)"
          + (f"  [nudged: {'draft' if drafted else ''}{' + ' if drafted and finalised else ''}"
             f"{'finalise' if finalised else ''}]" if (drafted or finalised) else ""))
    print(f"output     {'recommendation.html written' if wrote else 'NO OUTPUT PRODUCED'}")
    print(f"transcript {os.path.join(args.out, 'transcript.jsonl')}")
    return 0 if wrote else 1


if __name__ == "__main__":
    sys.exit(main())
