#!/usr/bin/env bash
# A/B/C on Mind2Web (each arm learns its own memory, then tests; vs its no-mem baseline):
#   A  task-level (existing): whole-task experience, our dual memory
#   B  step-evolve, record_mode=all      : per-wrong 'avoid' + aggregate 'do' (your full version)
#   C  step-evolve, record_mode=aggregate: only the majority-direction summary (lean version)
#
# Usage: bash scripts/run_m2w_abc.sh
# Overrides: SPLIT=test_task HOLDOUT=0.5 LLIM=30 TLIM=30 NTRAJ=3 MODEL=openai/gpt-4o BUDGET=15
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"
SPLIT="${SPLIT:-test_task}"; HOLDOUT="${HOLDOUT:-0.5}"
LLIM="${LLIM:-30}"; TLIM="${TLIM:-30}"; NTRAJ="${NTRAJ:-3}"
MODEL="${MODEL:-openai/gpt-4o}"; BUDGET="${BUDGET:-15}"
COMMON="--brain llm --llm.model $MODEL --m2w.test_split $SPLIT --m2w.holdout $HOLDOUT \
  --m2w.learn_limit $LLIM --m2w.test_limit $TLIM --agent.n_traj $NTRAJ \
  --memory.mode both --surprise.source traj_divergence --run.budget_usd $BUDGET"

arm () { local name="$1"; shift; echo "===== arm: $name ====="
  $PY -m hippo.m2w.run $COMMON --run.name "m2w_abc_${name}" "$@" 2>&1 \
    | grep -E "A/B|halted|Error:" | sed "s/^/[$name] /" || true; }

echo "split=$SPLIT holdout=$HOLDOUT learn=$LLIM test=$TLIM n_traj=$NTRAJ model=$MODEL"
arm A_task                                                            # existing task-level
arm B_step_all  --m2w.protocol step_evolve --m2w.record_mode all
arm C_step_agg  --m2w.protocol step_evolve --m2w.record_mode aggregate
echo "=== compare the three withmem vs their nomem (nomem ~ same: empty memory) ==="
