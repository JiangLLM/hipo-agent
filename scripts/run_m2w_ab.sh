#!/usr/bin/env bash
# A/B of RETRIEVAL policy, holding the learned memory FIXED.
#   run1 (thresh): learn once + save memory + test with topk + threshold 0.3
#   run2 (all):    load same memory, inject ALL relevant-scope items (k huge, no threshold)
#   run3 (topk):   load same memory, top-k but NO threshold (the pre-fix behavior)
# Every arm prints its own no-memory baseline too (cached, ~free).
#
# Usage: bash scripts/run_m2w_ab.sh
# Overrides: SPLIT=test_task HOLDOUT=0.5 LLIM=40 TLIM=40 NTRAJ=3 MODEL=openai/gpt-4o-mini BUDGET=10
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"
SPLIT="${SPLIT:-test_task}"; HOLDOUT="${HOLDOUT:-0.5}"
LLIM="${LLIM:-40}"; TLIM="${TLIM:-40}"; NTRAJ="${NTRAJ:-3}"
MODEL="${MODEL:-openai/gpt-4o-mini}"; BUDGET="${BUDGET:-10}"
MEM="runs/m2w_ab_mem_${SPLIT}.json"

base () {  # name + extra retrieval args...
  local name="$1"; shift
  echo "===== arm: $name ====="
  "$PY" -m hippo.m2w.run --brain llm --llm.model "$MODEL" \
    --m2w.test_split "$SPLIT" --m2w.holdout "$HOLDOUT" \
    --m2w.learn_limit "$LLIM" --m2w.test_limit "$TLIM" \
    --agent.n_traj "$NTRAJ" --memory.mode both --surprise.source traj_divergence \
    --run.budget_usd "$BUDGET" --run.name "m2w_ab_${name}" "$@" 2>&1 \
    | grep -E "A/B|halted|Error:" | sed "s/^/[$name] /" || true
}

echo "split=$SPLIT holdout=$HOLDOUT learn=$LLIM test=$TLIM n_traj=$NTRAJ model=$MODEL"
# arm 3 (threshold): learns + saves the shared memory
base thresh --m2w.memory_out "$MEM" --memory.retrieve_k_reasoning 2 --memory.retrieve_k_fact 4 --memory.relevance_threshold 0.3
# arm 1 (all): same memory, inject everything in-scope, no threshold, big token budget (true all)
base all    --m2w.memory_in  "$MEM" --memory.retrieve_k_reasoning 999 --memory.retrieve_k_fact 999 --memory.relevance_threshold 0.0 --memory.token_budget 20000
# arm 2 (topk, no threshold): same memory, top-k only
base topk   --m2w.memory_in  "$MEM" --memory.retrieve_k_reasoning 2 --memory.retrieve_k_fact 4 --memory.relevance_threshold 0.0
echo "=== done. compare the three [arm] A/B lines (nomem is the same baseline for all) ==="
