#!/usr/bin/env python3
"""Exercise the runner loop against a stub OpenRouter, so no key is needed.

Proves: streaming parse, multi-turn tool calling, tool-argument accumulation
across chunks, the write_file guard, transcript shape, and that
extract_metrics.py reads the transcript it produces.

    ./test_runner.py
"""
import json
import os
import subprocess
import sys
import threading
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
turn = {"n": 0}


def sse(chunks):
    return "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"


USAGE = {"prompt_tokens": 12000, "completion_tokens": 800, "total_tokens": 12800,
         "prompt_tokens_details": {"cached_tokens": 9000},
         "completion_tokens_details": {"reasoning_tokens": 300}}


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        turn["n"] += 1
        n = turn["n"]
        if n == 1:
            # Tool call arguments deliberately split across chunks.
            chunks = [
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "fetch_url", "arguments": '{"url":"https://ex'}}]}}]},
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'ample.com/"}'}}]}}]},
                {"choices": [{"finish_reason": "tool_calls", "delta": {}}]},
                {"usage": USAGE, "choices": []},
            ]
        elif n == 2:
            # A rejected write, to prove the guard fires.
            chunks = [
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c2", "function": {"name": "write_file", "arguments": json.dumps({"filename": "evil.sh", "content": "x"})}}]}}]},
                {"choices": [{"finish_reason": "tool_calls", "delta": {}}]},
                {"usage": USAGE, "choices": []},
            ]
        elif n == 3:
            chunks = [
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c3", "function": {"name": "write_file", "arguments": json.dumps({"filename": "recommendation.html", "content": "<h1>ok</h1>"})}}]}}]},
                {"choices": [{"finish_reason": "tool_calls", "delta": {}}]},
                {"usage": USAGE, "choices": []},
            ]
        else:
            chunks = [
                {"choices": [{"delta": {"content": "Done."}}]},
                {"choices": [{"finish_reason": "stop", "delta": {}}]},
                {"usage": USAGE, "choices": []},
            ]
        payload = sse(chunks).encode()
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main():
    server = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    out = tempfile.mkdtemp(prefix="rpick-mock-")
    env = dict(os.environ, OPENROUTER_API_KEY="sk-or-v1-stub")
    # Point the runner at the stub, and at a tools port with nothing on it, so
    # the tool-server failure path is exercised too.
    patch = (f"import runner, sys; runner.API='http://127.0.0.1:{port}/v1/chat/completions'; "
             f"sys.argv=['runner','--model','glm','--out',{out!r},'--tools-port','1']; "
             f"sys.exit(runner.main())")
    result = subprocess.run([sys.executable, "-c", patch], cwd=HERE, env=env,
                            capture_output=True, text=True)
    print(result.stdout.strip())
    if result.stderr.strip():
        print("stderr:", result.stderr.strip()[:300])

    fails = []
    if not os.path.exists(os.path.join(out, "recommendation.html")):
        fails.append("recommendation.html was not written")
    events = [json.loads(l) for l in open(os.path.join(out, "transcript.jsonl"))]
    kinds = [e["type"] for e in events]
    for needed in ("session", "turn/start", "assistant/message", "tool/call",
                   "tool/result", "session/end"):
        if needed not in kinds:
            fails.append(f"transcript missing {needed}")
    # The tool-argument split across two chunks must reassemble.
    fetch = next((e for e in events if e["type"] == "tool/call" and e["name"] == "fetch_url"), None)
    if not fetch or "example.com" not in json.dumps(fetch.get("args", {})):
        fails.append("split tool arguments did not reassemble")
    # The write guard must have rejected evil.sh and recorded an error.
    if not any(e["type"] == "tool/result" and e.get("error") and "recommendation.html" in str(e.get("error"))
               for e in events):
        fails.append("write_file guard did not reject a non-deliverable filename")
    if os.path.exists(os.path.join(out, "evil.sh")):
        fails.append("write_file guard let evil.sh through")

    metrics = subprocess.run(
        [sys.executable, os.path.join(HERE, "..", "extract_metrics.py"), out, "--model", "glm"],
        capture_output=True, text=True)
    if metrics.returncode != 0:
        fails.append(f"extract_metrics failed: {metrics.stderr.strip()[:200]}")
    else:
        row = json.loads(metrics.stdout)
        print("\nextracted:", json.dumps({k: row[k] for k in (
            "input_tokens", "output_tokens", "reasoning_tokens",
            "cached_input_pct", "total_cost", "tool_calls", "tool_errors")}))
        if row["input_tokens"] != 12000 * 4:
            fails.append(f"input tokens {row['input_tokens']}, want 48000")
        if row["reasoning_tokens"] != 300 * 4:
            fails.append(f"reasoning {row['reasoning_tokens']}, want 1200")
        if row["cached_input_pct"] != 75.0:
            fails.append(f"cached % {row['cached_input_pct']}, want 75.0")
        if row["tool_errors"] < 1:
            fails.append("tool errors not counted")

    print()
    for f in fails:
        print("FAIL", f)
    print("all runner-loop checks passed" if not fails else f"{len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
