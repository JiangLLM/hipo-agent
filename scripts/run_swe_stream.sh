#!/bin/bash
# Small stream A/B: nomem baseline + withmem self-evolution (N=5) over 25 django tasks.
# Produces preds_nomem.json / preds_withmem.json for sb-cli ground-truth scoring.
set -e
cd "$(dirname "$0")/.."
MODEL="${MODEL:-anthropic/claude-haiku-4-5}"
.venv/bin/python -m hippo.swe.run \
  --llm.model "$MODEL" \
  --llm.embed_model local/BAAI/bge-small-en-v1.5 \
  --swe.agent_model "$MODEL" \
  --swe.repos django --swe.limit 25 \
  --agent.n_traj 5 \
  --memory.retrieve_k_reasoning 4 \
  --run.budget_usd 60 --run.name swe_stream25 "$@"
