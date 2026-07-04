#!/usr/bin/env bash
# Clean A/B of PER-STEP vs WHOLE-TASK retrieval, holding the learned memory FIXED:
#   run1 (perstep): learn once + save memory + test with per-step retrieval
#   run2 (wholetask): load same memory, test with whole-task retrieval (retrieve once by goal)
# Same memory, same test tasks -> isolates the contribution of per-step retrieval.
#
# Usage: bash scripts/run_m2w_perstep_ab.sh
# Overrides: LLIM TLIM NTRAJ KFACT MODEL BUDGET SPLIT
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"
SPLIT="${SPLIT:-test_task}"; LLIM="${LLIM:-60}"; TLIM="${TLIM:-60}"; NTRAJ="${NTRAJ:-3}"
KFACT="${KFACT:-8}"; MODEL="${MODEL:-openai/gpt-4o}"; BUDGET="${BUDGET:-30}"
MEM="runs/m2w_ps_mem_${SPLIT}.json"
COMMON="--brain llm --llm.model $MODEL --m2w.protocol step_evolve --m2w.record_mode aggregate \
  --m2w.test_split $SPLIT --m2w.holdout 0.5 --m2w.learn_limit $LLIM --m2w.test_limit $TLIM \
  --memory.mode both --memory.retrieve_k_fact $KFACT --surprise.source traj_divergence \
  --agent.n_traj $NTRAJ --run.budget_usd $BUDGET"

echo "learn=$LLIM test=$TLIM k_fact=$KFACT model=$MODEL"
echo "===== arm: perstep (learns + saves memory) ====="
$PY -m hippo.m2w.run $COMMON --m2w.per_step_retrieval on --m2w.memory_out "$MEM" \
  --run.name m2w_ps_on 2>&1 | grep -E "A/B|halted|Error:" | sed 's/^/[perstep] /' || true
echo "===== arm: wholetask (same memory) ====="
$PY -m hippo.m2w.run $COMMON --m2w.per_step_retrieval off --m2w.memory_in "$MEM" \
  --run.name m2w_ps_off 2>&1 | grep -E "A/B|halted|Error:" | sed 's/^/[wholetask] /' || true
echo "=== compare the two withmem: difference = per-step retrieval's contribution ==="
