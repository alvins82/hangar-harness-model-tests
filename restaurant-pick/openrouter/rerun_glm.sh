#!/bin/bash
# GLM's first attempt was killed by a 1500s timeout four seconds short, mid-run.
# Wait for the qwen/luna/sol queue to drain, then give it 90 minutes.
cd "$(dirname "$0")"
while pgrep -f "run_rest.sh|runner.py --model" > /dev/null; do sleep 30; done
echo "=== queue drained, re-running glm with a 90 min limit ==="
rm -f ../../rpick-openrouter-glm53-flash/transcript.jsonl
timeout 5400 python3 runner.py --model glm --out ../../rpick-openrouter-glm53-flash \
  --tools-port 8791 --max-cost 1.00 2>&1 | tail -12
echo "glm rerun exit=$?"
