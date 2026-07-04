#!/usr/bin/env bash
# Real LLM ablation on Mind2Web. Reads keys from .env automatically.
# Usage:
#   bash scripts/run_mind2web.sh
# Optional env overrides:
#   MODEL=openai/gpt-4o-mini  NTRAJ=3  DATA=data/mind2web.jsonl  BUDGET=2  PY=.venv/bin/python
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PY:-.venv/bin/python}"
MODEL="${MODEL:-openai/gpt-4o-mini}"
DATA="${DATA:-data/mind2web.jsonl}"
NTRAJ="${NTRAJ:-3}"
BUDGET="${BUDGET:-2}"
COMMON="--env jsonl --data.path $DATA --data.match exact --brain llm --llm.model $MODEL --run.budget_usd $BUDGET"

echo "model=$MODEL data=$DATA n_traj=$NTRAJ budget=\$$BUDGET"
echo

run () {  # name  extra-args...
  local name="$1"; shift
  echo ">>> running $name ..."
  $PY -m hippo.run $COMMON --run.name "$name" "$@" 2>&1 | grep -E "SUMMARY|halted|run halted|Error:" || true
  echo
}

# baseline: no memory, single trajectory (cheapest)
run m2w_nomem    --memory.mode off            --agent.n_traj 1

# store-everything (no surprise gate) — the ablation upper bound on writes
run m2w_storeall --memory.mode both --surprise.source store_all       --agent.n_traj "$NTRAJ"

# surprise source #1: memory-prediction error
run m2w_mempred  --memory.mode both --surprise.source memory_pred     --agent.n_traj "$NTRAJ"

# surprise source #2 (ours): N-trajectory divergence + memory-pred
run m2w_trajdiv  --memory.mode both --surprise.source traj_divergence --agent.n_traj "$NTRAJ"

echo "=== done. per-run artifacts in runs/<name>_*/ (summary.json, metrics.csv, events.jsonl) ==="
