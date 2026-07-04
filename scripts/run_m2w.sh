#!/usr/bin/env bash
# Train-then-test on Mind2Web, OUR memory.
#   LEARN: per-website holdout (first half of each site's tasks), N rollouts, gold-graded,
#          contrastive distillation -> dual fact/reasoning memory.
#   TEST:  the held-out tasks of the SAME sites, memory FROZEN, single pass.
#   Reports A/B: no-memory vs learned-memory (gold only ever used for scoring).
#
# Usage: bash scripts/run_m2w.sh
# Overrides: SPLIT=test_task HOLDOUT=0.5 LLIM=40 TLIM=40 NTRAJ=3 MODEL=openai/gpt-4o-mini BUDGET=8
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"
SPLIT="${SPLIT:-test_task}"
HOLDOUT="${HOLDOUT:-0.5}"
LLIM="${LLIM:-40}"
TLIM="${TLIM:-40}"
NTRAJ="${NTRAJ:-3}"
MODEL="${MODEL:-openai/gpt-4o-mini}"
BUDGET="${BUDGET:-8}"
THRESH="${THRESH:-0.3}"

echo "split=$SPLIT holdout=$HOLDOUT learn_limit=$LLIM test_limit=$TLIM n_traj=$NTRAJ thresh=$THRESH model=$MODEL budget=\$$BUDGET"
"$PY" -m hippo.m2w.run --brain llm --llm.model "$MODEL" \
  --m2w.test_split "$SPLIT" --m2w.holdout "$HOLDOUT" \
  --m2w.learn_limit "$LLIM" --m2w.test_limit "$TLIM" \
  --m2w.memory_out "runs/learned_memory_${SPLIT}.json" \
  --agent.n_traj "$NTRAJ" --memory.mode both --surprise.source traj_divergence \
  --memory.relevance_threshold "$THRESH" \
  --run.budget_usd "$BUDGET" --run.name m2w_protocol 2>&1 | grep -E "A/B|SUMMARY|halted|Error:|run_id" || true
echo "=== artifacts in runs/m2w_protocol_*/ (summary.json, metrics_nomem.csv, metrics_withmem.csv) ==="
