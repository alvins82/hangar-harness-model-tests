#!/usr/bin/env python3
"""Prove the progressive-output nudges fire, reach the model, and rescue a run.

The plain test_runner.py can't cover this: it never reaches a nudge threshold.
Two stubs here:

  A. a model that researches forever and only writes when told the budget is
     exhausted -- proves the grace turn is what saves the run
  B. a model that writes as soon as it is asked to draft -- proves progressive
     output arrives mid-run rather than only at the end

    ./test_nudges.py
"""
import json, os, subprocess, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
USAGE = {"prompt_tokens": 9000, "completion_tokens": 600, "total_tokens": 9600,
         "prompt_tokens_details": {"cached_tokens": 6000},
         "completion_tokens_details": {"reasoning_tokens": 200}}
MARKS = {"draft": "PROGRESS NOTICE", "finalise": "BUDGET NOTICE", "grace": "BUDGET EXHAUSTED"}


def sse(chunks):
    return "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"


def make_stub(writes_on):
    """writes_on: which nudge kind makes this stub finally write."""
    state = {"seen": [], "n": 0}

    class Stub(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            for msg in body["messages"]:
                text = msg.get("content")
                if msg.get("role") == "user" and isinstance(text, str):
                    for kind, mark in MARKS.items():
                        if mark in text and kind not in state["seen"]:
                            state["seen"].append(kind)
            state["n"] += 1
            told = MARKS[writes_on] in json.dumps(body["messages"])
            if told:
                fn = {"name": "write_file", "arguments": json.dumps(
                    {"filename": "recommendation.html", "content": "<h1>output</h1>"})}
            else:
                fn = {"name": "maps_lookup", "arguments": '{"query":"x"}'}
            chunks = [
                {"choices": [{"delta": {"tool_calls": [
                    {"index": 0, "id": f"c{state['n']}", "function": fn}]}}]},
                {"choices": [{"finish_reason": "tool_calls", "delta": {}}]},
                {"usage": USAGE, "choices": []},
            ]
            payload = sse(chunks).encode()
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return Stub, state


def run_case(name, writes_on, max_cost, draft_after, expect_kind):
    Stub, state = make_stub(writes_on)
    srv = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    out = tempfile.mkdtemp(prefix="nudge-")
    code = (f"import runner,sys; runner.API='http://127.0.0.1:{srv.server_address[1]}/v1';"
            f"sys.argv=['r','--model','glm','--out',{out!r},'--tools-port','1',"
            f"'--max-turns','14','--draft-after','{draft_after}','--finalise-at','0.6',"
            f"'--max-cost','{max_cost}']; sys.exit(runner.main())")
    subprocess.run([sys.executable, "-c", code], cwd=HERE,
                   env=dict(os.environ, OPENROUTER_API_KEY="stub"),
                   capture_output=True, text=True)
    events = [json.loads(l) for l in open(os.path.join(out, "transcript.jsonl"))]
    kinds = [e.get("kind") for e in events if e["type"] == "harness/nudge"]
    wrote = os.path.exists(os.path.join(out, "recommendation.html"))
    fails = []
    if expect_kind not in kinds:
        fails.append(f"{expect_kind} nudge never logged (got {kinds})")
    if expect_kind not in state["seen"]:
        fails.append(f"model never received the {expect_kind} nudge")
    if not wrote:
        fails.append("no deliverable produced")
    print(f"{'FAIL' if fails else 'pass'}  {name}")
    print(f"        nudges logged={kinds} received={state['seen']} deliverable={wrote}")
    for f in fails:
        print(f"        {f}")
    return fails


def main():
    fails = []
    # A model that will not stop researching is rescued only by the grace turn
    # past the hard cap.
    fails += run_case("grace turn rescues a run that never volunteers a write",
                      writes_on="grace", max_cost="0.002", draft_after="99",
                      expect_kind="grace")
    # A cooperative model produces output mid-run, not at the end.
    fails += run_case("draft nudge produces output mid-run",
                      writes_on="draft", max_cost="10", draft_after="2",
                      expect_kind="draft")
    print()
    print("all nudge checks passed" if not fails else f"{len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
