#!/usr/bin/env python3
"""Check extract_metrics.py against the ten published hangar rows.

Every expected value is read off the published root index.html. Run from this
directory with no arguments and no dependencies:

    ./test_extract_metrics.py

Pinned: input tokens, output tokens, reasoning tokens, total tokens, cached
input %, and all four cost columns individually -- not just the total.

Not pinned: duration, TTFT and the tool counts. Those need a definition per
harness, the published column was counted by hand, and the extractor knowingly
differs on some Codex rows. README.md records exactly where.
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

FIELDS = ("input_tokens", "output_tokens", "reasoning_tokens", "total_tokens",
          "input_cost", "cache_read_cost", "output_cost", "total_cost",
          "cached_input_pct")

# run directory -> model key, then the published value of each field above.
# The Codex row labelled Luna 5.6 Max records gpt-5.6-sol in its transcript and
# is priced at the Sol rate, matching the note on the hangar table.
EXPECTED = {
    "hangar-codex-glm53flash-max": ("glm", 457685, 17458, 7694, 475143,
        0.005061, 0.005853, 0.004364, 0.015278, 85.26),
    "hangar-codex-luna56-max": ("sol", 1146755, 25512, 6879, 1172267,
        0.083075, 0.106368, 0.127560, 0.317003, 92.76),
    "hangar-codex-sol56-max": ("sol", 1069163, 28278, 7515, 1097441,
        0.057707, 0.101146, 0.141390, 0.300243, 94.60),
    "hangar-codex-astra60-max": ("astra", 1292366, 43129, 15271, 1335495,
        0.654860, 1.226880, 2.156450, 4.038190, 94.93),
    "hangar-omp-glm53-flash": ("glm", 1678509, 63405, None, 1741914,
        0.027013, 0.019775, 0.015851, 0.062639, 78.54),
    "hangar-omp-qwen3827b-xhigh": ("qwen", 3407451, 71935, 49131, 3479386,
        0.187257, 0.251736, 0.215805, 0.654798, 86.92),
    "hangar-opencode-glm5.7flash": ("glm", 4305447, 50468, 33414, 4355915,
        0.010045, 0.062573, 0.012617, 0.085234, 96.89),
    "hangar-opencode-qwen3827b-xhigh": ("qwen", 665490, 41817, 28788, 707307,
        0.012184, 0.054101, 0.125451, 0.191736, 95.64),
    "hangar-dsh-ptc-qwen3827b-xhigh": ("qwen", 1012499, 89894, None, 1102393,
        0.035355, 0.078907, 0.269682, 0.383944, 91.69),
    "hangar-dsh-qwen3827b-xhigh": ("qwen", 2654457, 78232, None, 2732689,
        0.050424, 0.215424, 0.234696, 0.500544, 95.48),
}

# Costs are compared to the last digit the table renders, so the tolerance is
# one unit of that digit. It has to be a shade over 1e-6 because of one genuine
# half-way tie: the Codex GLM output cost is exactly 17,458 x 0.250 / 1e6 =
# $0.0043645, which the published table renders down to $0.004364 and Python's
# round() takes up to $0.004365. That is a display tie, not a disagreement.
TOLERANCE = {"input_cost": 1.5e-6, "cache_read_cost": 1.5e-6,
             "output_cost": 1.5e-6, "total_cost": 1.5e-6,
             "cached_input_pct": 0.011}


def compare(got, want, tol):
    if got is None or want is None:
        return got is None and want is None
    return abs(got - want) <= tol


def main():
    failures = []
    for run, expected in EXPECTED.items():
        model, values = expected[0], expected[1:]
        run_dir = os.path.join(REPO, run)
        if not os.path.isdir(run_dir):
            # A missing directory must fail: silently skipping every run would
            # print success having tested nothing.
            print(f"FAIL  {run}: directory missing")
            failures.append(run)
            continue
        result = subprocess.run(
            [sys.executable, os.path.join(HERE, "extract_metrics.py"), run_dir,
             "--model", model],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"FAIL  {run}: extractor exited {result.returncode}")
            print(f"        {result.stderr.strip().splitlines()[-1:] or ''}")
            failures.append(run)
            continue
        got = json.loads(result.stdout)
        bad = [f"{field}: got {got[field]}, want {want}"
               for field, want in zip(FIELDS, values)
               if not compare(got[field], want, TOLERANCE.get(field, 0))]
        print(f"{'FAIL' if bad else 'pass'}  {run}")
        for line in bad:
            print(f"        {line}")
        if bad:
            failures.append(run)

    print()
    if failures:
        print(f"{len(failures)} of {len(EXPECTED)} runs do not match the published table")
        return 1
    print(f"all {len(EXPECTED)} runs reproduce the published token, reasoning "
          f"and cost columns")
    return 0


if __name__ == "__main__":
    sys.exit(main())
