#!/bin/bash
# Sequentially serve each 1B-class candidate on :8001 and run the benchmark.
set -u
cd "$(dirname "$0")"
VLLM=~/.venv-vllm-metal/bin/vllm
PY=../../.venv/bin/python
LOG=/tmp/serving-b-candidate.log

run_one () {
  local model="$1"; local tag="$2"; shift 2
  echo "=== $tag ($model)"
  pkill -f "vllm serve.*port 8001" 2>/dev/null; sleep 3
  VLLM_METAL_USE_PAGED_ATTENTION=1 VLLM_METAL_MEMORY_FRACTION=0.15 caffeinate -i \
    "$VLLM" serve "$model" --host 127.0.0.1 --port 8001 --seed 1234 \
    --max-model-len 8192 --max-num-seqs 2 --disable-log-stats "$@" > "$LOG" 2>&1 &
  for i in $(seq 1 90); do
    curl -s -m 2 http://127.0.0.1:8001/health >/dev/null 2>&1 && break; sleep 2
  done
  if ! curl -s -m 2 http://127.0.0.1:8001/health >/dev/null 2>&1; then
    echo "!!! $tag failed to start"; tail -5 "$LOG"; return 1
  fi
  "$PY" bench.py --endpoint http://127.0.0.1:8001 --tag "$tag"
}

run_one mlx-community/Qwen3-1.7B-4bit qwen3-1.7b \
  --default-chat-template-kwargs '{"enable_thinking": false}'
run_one mlx-community/gemma-3-1b-it-qat-4bit gemma3-1b
run_one mlx-community/LFM2.5-1.2B-Instruct-4bit lfm2.5-1.2b
run_one mlx-community/Qwen3-0.6B-4bit qwen3-0.6b \
  --default-chat-template-kwargs '{"enable_thinking": false}'
echo "CANDIDATES_DONE"
