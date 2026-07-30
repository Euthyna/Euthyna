#!/bin/zsh
# Run the arm64-available SWE-bench Verified instances through mini-swe-agent, with every
# call passing through the euthyna gateway.
#
# 500 (Verified) -> 50 (the research programme's own subset) -> 28 (arm64 image published).
# Both filters are non-random and the second is an accident of what SWE-bench chose to
# publish for Apple Silicon, so ANY resolve rate here describes this doubly-filtered set
# and nothing else. That is acceptable because the goal is harvesting successful
# trajectories for distillation, not estimating capability.
#
# Why arm64 and not the default x86_64 images: measured 17.6x emulation overhead on this
# host (0.07s native vs 1.23s emulated, CPU-bound Python). At that rate the run is ~100
# hours. mini-swe-agent honours instance["image_name"] before its x86_64 default, so a
# local dataset carrying arm64 names fixes it with no fork.
#
#   ./swebench-arm64.sh                    # preflight, then run
#   ./swebench-arm64.sh --preflight-only
#   WORKERS=2 STEP_LIMIT=40 ./swebench-arm64.sh
#   FILTER='^astropy__astropy-12907$' ./swebench-arm64.sh    # single instance
set -e
cd "$(dirname "$0")"

MODEL="${MODEL:-openai/SWE-Lego-Qwen3-8B-MLX-4bit}"
WORKERS="${WORKERS:-1}"
OUT="${OUT:-$HOME/swebench-arm64-run1}"
STEP_LIMIT="${STEP_LIMIT:-40}"
DATASET="${DATASET:-$HOME/swebench28-arm64}"
PY=/Users/loki/Desktop/euthyna/.venv/bin/python
MINI=$HOME/.venv-mini-swe/bin/mini-extra

echo "=============== preflight ==============="
$PY swebench50-preflight.py || { echo "\npreflight failed — fix the blockers above"; exit 1; }
[[ "$1" == "--preflight-only" ]] && exit 0

# Anchored alternation so a substring cannot pull in a neighbour
# (django-14539 must not match django-145390).
FILTER="${FILTER:-^($(paste -sd'|' - < swebench28-arm64.txt))$}"

echo "\n=============== run ==============="
echo "model     : $MODEL"
echo "dataset   : $DATASET  (arm64 image_name per row)"
echo "workers   : $WORKERS"
echo "step limit: $STEP_LIMIT"
echo "output    : $OUT"

# Serial runs give disjoint [started_at, ended_at] windows, which window-based cost
# attribution requires. With WORKERS>1 the windows interleave and window_costs leaves
# those runs unpriced by design — use session-keyed costs instead.
[[ "$WORKERS" -gt 1 ]] && echo "  ! parallel: window cost attribution will report UNPRICED; use session keys"

$MINI swebench \
  --subset "$DATASET" --split test \
  --filter "$FILTER" \
  --workers "$WORKERS" \
  --model "$MODEL" \
  --environment-class docker \
  --output "$OUT" \
  -c swebench.yaml \
  -c model.model_kwargs.temperature=0 \
  -c agent.step_limit=$STEP_LIMIT \
  -c 'model.model_kwargs.max_tokens=2048' \
  -c agent.max_observation_length=20000

echo "\n=============== what the gateway saw ==============="
cd /Users/loki/Desktop/euthyna
$PY -m euthyna.cli.main report || true
$PY -m euthyna.cli.main skills || true
