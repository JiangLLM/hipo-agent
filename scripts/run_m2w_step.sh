#!/usr/bin/env bash
# Step-evolve on Mind2Web with PER-STEP retrieval (now default in step mode) + larger k.
# Reports withmem vs no-memory on held-out same-site tasks (per-website holdout).
#
# Usage: bash scripts/run_m2w_step.sh            # medium scale (60/60), trustworthy-ish
#        LLIM=0 TLIM=0 BUDGET=60 bash scripts/run_m2w_step.sh   # FULL cross-task (expensive)
# Overrides: SPLIT MODE(record) KFACT NTRAJ MODEL SEED FACTGATE
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"
SPLIT="${SPLIT:-test_task}"; HOLDOUT="${HOLDOUT:-0.5}"
LLIM="${LLIM:-60}"; TLIM="${TLIM:-60}"; NTRAJ="${NTRAJ:-3}"
MODE="${MODE:-aggregate}"; KFACT="${KFACT:-8}"; FACTGATE="${FACTGATE:-surprise}"
MODEL="${MODEL:-openai/gpt-4o}"; BUDGET="${BUDGET:-30}"; SEED="${SEED:-0}"

echo "split=$SPLIT holdout=$HOLDOUT learn=$LLIM test=$TLIM n_traj=$NTRAJ record=$MODE k_fact=$KFACT fact_gate=$FACTGATE seed=$SEED model=$MODEL"
"$PY" -m hippo.m2w.run --brain llm --llm.model "$MODEL" \
  --m2w.protocol step_evolve --m2w.record_mode "$MODE" --m2w.fact_gate "$FACTGATE" \
  --m2w.test_split "$SPLIT" --m2w.holdout "$HOLDOUT" \
  --m2w.learn_limit "$LLIM" --m2w.test_limit "$TLIM" \
  --memory.mode both --memory.retrieve_k_fact "$KFACT" --surprise.source traj_divergence \
  --agent.n_traj "$NTRAJ" --run.seed "$SEED" --run.budget_usd "$BUDGET" \
  --run.name "m2w_step_${SPLIT}_L${LLIM}_s${SEED}" 2>&1 | grep -E "A/B|halted|Error:|run_id" || true
echo "=== artifacts in runs/m2w_step_*/ (summary.json, metrics_nomem.csv, metrics_withmem.csv) ==="
