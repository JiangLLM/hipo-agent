#!/bin/bash
# Calibration: is the base model's SR in the 30-60% divergence sweet spot on django?
# Single attempt, no memory. Judge SR prints inline; ground truth via sb-cli afterwards:
#   sb-cli submit swe-bench_verified test --predictions_path runs/<run>/preds_nomem.json --run_id calib
set -e
cd "$(dirname "$0")/.."
MODEL="${MODEL:-anthropic/claude-haiku-4-5}"
.venv/bin/python -m hippo.swe.run \
  --llm.model "$MODEL" \
  --llm.embed_model local/BAAI/bge-small-en-v1.5 \
  --swe.agent_model "$MODEL" \
  --swe.repos django --swe.limit 25 \
  --swe.arms nomem \
  --run.budget_usd 15 --run.name swe_calib "$@"
