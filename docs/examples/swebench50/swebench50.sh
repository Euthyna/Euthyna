#!/bin/zsh
# Run the 50-instance SWE-bench Verified subset through mini-swe-agent, with every call
# passing through the euthyna gateway.
#
# The subset is the one already selected in the research repo
# (harness/pruning_ab/configs/swe_agent_run_batch.config.yaml) — 50 of SWE-bench
# Verified across 10 repositories. It is NOT a random sample; whatever selected it
# selected it, and any resolve rate from here describes that subset, not Verified.
#
# Pass 1 of a sequential design: one rep over all 50, to learn three things before
# committing to more — the quantized resolve rate, the real action vocabulary, and
# whether repeated ritual n-grams exist in trajectories long enough to have them.
#
#   ./swebench50.sh                       # preflight, then run
#   ./swebench50.sh --preflight-only
#   MODEL=openai/... WORKERS=2 ./swebench50.sh
set -e
cd "$(dirname "$0")"

MODEL="${MODEL:-openai/SWE-Lego-Qwen3-8B-MLX-4bit}"
WORKERS="${WORKERS:-1}"
OUT="${OUT:-$HOME/swebench50-run1}"
STEP_LIMIT="${STEP_LIMIT:-50}"
PY=/Users/loki/Desktop/euthyna/.venv/bin/python
MINI=$HOME/.venv-mini-swe/bin/mini-extra

echo "=============== preflight ==============="
$PY swebench50-preflight.py || { echo "\npreflight failed — fix the blockers above"; exit 1; }
[[ "$1" == "--preflight-only" ]] && exit 0

# Anchored alternation over the exact 50 ids, so a substring can never pull in a
# neighbour (django-14539 must not match django-145390).
FILTER="^($(paste -sd'|' - < swebench50.txt))$"

echo "\n=============== run ==============="
echo "model    : $MODEL"
echo "workers  : $WORKERS   (>1 runs several containers; they queue at the model anyway)"
echo "output   : $OUT"
echo "instances: 50 (verified/test, research-repo subset)"

# Serial runs give disjoint [started_at, ended_at] windows, which is what window-based
# cost attribution needs. With WORKERS>1 that breaks and only prefix-chaining separates
# sessions — which it does, but per-run cost attribution then has to come from the
# session id rather than the clock.
[[ "$WORKERS" -gt 1 ]] && echo "  ! parallel: use session-keyed cost attribution, not --window-costs"

$MINI swebench \
  --subset verified --split test \
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
