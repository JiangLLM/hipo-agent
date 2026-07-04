#!/usr/bin/env bash
# Channel ablation on Mind2Web, holding the learned memory FIXED:
#   run1 (both):     learn once + save memory, test with BOTH channels
#   run2 (fact):     same memory, test with FACT channel only
#   run3 (reason):   same memory, test with REASONING channel only
# Each arm also prints its no-memory baseline (cached). Goal: is site-general FACT the
# transferable unit on Mind2Web's diverse-per-site tasks?
#
# Usage: bash scripts/run_m2w_channels.sh
# Overrides: SPLIT=test_task HOLDOUT=0.5 LLIM=40 TLIM=40 NTRAJ=3 MODEL=openai/gpt-4o-mini BUDGET=10
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"
SPLIT="${SPLIT:-test_task}"; HOLDOUT="${HOLDOUT:-0.5}"
LLIM="${LLIM:-40}"; TLIM="${TLIM:-40}"; NTRAJ="${NTRAJ:-3}"
MODEL="${MODEL:-openai/gpt-4o-mini}"; BUDGET="${BUDGET:-10}"
MEM="runs/m2w_ch_mem_${SPLIT}.json"

arm () {  # name + extra args...
  local name="$1"; shift
  echo "===== arm: $name ====="
  "$PY" -m hippo.m2w.run --brain llm --llm.model "$MODEL" \
    --m2w.test_split "$SPLIT" --m2w.holdout "$HOLDOUT" \
    --m2w.learn_limit "$LLIM" --m2w.test_limit "$TLIM" \
    --agent.n_traj "$NTRAJ" --surprise.source traj_divergence \
    --run.budget_usd "$BUDGET" --run.name "m2w_ch_${name}" "$@" 2>&1 \
    | grep -E "A/B|halted|Error:" | sed "s/^/[$name] /" || true
}

echo "split=$SPLIT holdout=$HOLDOUT learn=$LLIM test=$TLIM n_traj=$NTRAJ model=$MODEL"
# learn once (both) + save, test both channels
arm both  --memory.mode both --m2w.memory_out "$MEM"
# same memory, fact-only retrieval
arm fact  --memory.mode fact_only      --m2w.memory_in "$MEM"
# same memory, reasoning-only retrieval
arm reason --memory.mode reasoning_only --m2w.memory_in "$MEM"
echo "=== done. compare withmem across both / fact / reason (nomem baseline is shared) ==="
