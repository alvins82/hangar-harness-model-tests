#!/bin/bash
# Wait for the GLM run to finish, then run the remaining three sequentially.
cd "$(dirname "$0")"
while pgrep -f "runner.py --model glm" > /dev/null; do sleep 20; done
echo "=== glm finished, starting the rest ==="
for m in qwen luna sol; do
  case $m in
    qwen) out=rpick-openrouter-qwen3827b ;;
    luna) out=rpick-openrouter-luna56 ;;
    sol)  out=rpick-openrouter-sol56 ;;
  esac
  echo; echo "########## $m -> $out ##########"
  timeout 2400 python3 runner.py --model $m --out "../../$out" --tools-port 8791 --max-cost 1.00 2>&1 | tail -12
  echo "exit=$?"
done
echo; echo "=== all three done ==="
