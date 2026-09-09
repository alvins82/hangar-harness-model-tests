#!/usr/bin/env python3
"""Check extract_metrics.py against the ten published hangar rows.

The token and cost columns are the ones worth trusting, so they are the ones
pinned here: every expected value below is read off the published index.html.
Run from this directory with no arguments and no dependencies:

    ./test_extract_metrics.py
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# run directory -> (model key, input tokens, output tokens, total cost, cached input %)
EXPECTED = {
    "hangar-codex-glm53flash-max": ("glm", 457685, 17458, 0.015278, 85.26),
    "hangar-codex-luna56-max": ("sol", 1146755, 25512, 0.317003, 92.76),
    "hangar-codex-sol56-max": ("sol", 1069163, 28278, 0.300243, 94.60),
    "hangar-codex-astra60-max": ("astra", 1292366, 43129, 4.038190, 94.93),
    "hangar-omp-glm53-flash": ("glm", 1678509, 63405, 0.062639, 78.54),
    "hangar-omp-qwen3827b-xhigh": ("qwen", 3407451, 71935, 0.654798, 86.92),
    "hangar-opencode-glm5.7flash": ("glm", 4305447, 50468, 0.085234, 96.89),
    "hangar-opencode-qwen3827b-xhigh": ("qwen", 665490, 41817, 0.191736, 95.64),
    "hangar-dsh-ptc-qwen3827b-xhigh": ("qwen", 1012499, 89894, 0.383944, 91.69),
    "hangar-dsh-qwen3827b-xhigh": ("qwen", 2654457, 78232, 0.500544, 95.48),
}

# The Codex row labelled Luna 5.6 Max records gpt-5.6-sol in its transcript and is
# therefore priced at the Sol rate, matching the note on the hangar table.


def main():
    failures = []
    for run, (model, want_in, want_out, want_cost, want_cached) in EXPECTED.items():
        run_dir = os.path.join(REPO, run)
        if not os.path.isdir(run_dir):
            print(f"skip {run}: directory missing")
            continue
        result = subprocess.run(
            [sys.executable, os.path.join(HERE, "extract_metrics.py"), run_dir, "--model", model],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            failures.append(f"{run}: extractor failed\n{result.stderr}")
            continue
        got = json.loads(result.stdout)
        checks = [
            ("input tokens", got["input_tokens"], want_in, 0),
            ("output tokens", got["output_tokens"], want_out, 0),
            ("total cost", got["total_cost"], want_cost, 1e-6),
            ("cached input %", got["cached_input_pct"], want_cached, 0.011),
        ]
        bad = [f"{name}: got {g}, want {w}" for name, g, w, tol in checks if abs(g - w) > tol]
        print(f"{'FAIL' if bad else 'pass'}  {run}")
        for line in bad:
            print(f"        {line}")
        if bad:
            failures.append(run)

    print()
    if failures:
        print(f"{len(failures)} run(s) do not match the published table")
        return 1
    print("all runs reproduce the published token and cost columns")
    return 0


if __name__ == "__main__":
    sys.exit(main())
