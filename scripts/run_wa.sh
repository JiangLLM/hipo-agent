#!/bin/bash
# WebArena self-evolution experiment — one knob to swap base model.
#   MODEL=gpt-5.6-sol SITE=shopping bash scripts/run_wa.sh
# Runs nomem baseline + withmem streaming (learn-as-you-go, N rollouts/task).
# Everything logged to events.jsonl; analyse with scripts/analyze_wa.py.
set -e
cd "$(dirname "$0")/.."
MODEL="${MODEL:-gpt-5.6-sol}"
SITE="${SITE:-shopping_admin}"
LIMIT="${LIMIT:-40}"
NTRAJ="${NTRAJ:-5}"
READONLY="${READONLY:-true}"
export LLM_TIMEOUT="${LLM_TIMEOUT:-180}"
RUN="wa_${SITE}_$(echo $MODEL | tr '.' '_' | tr -d '-')"
caffeinate -i .venv-wa/bin/python -m hippo.wa.run \
  --llm.model "$MODEL" --llm.embed_model local/BAAI/bge-small-en-v1.5 \
  --wa.base_url http://10.44.12.29 --wa.site "$SITE" --wa.limit "$LIMIT" \
  --wa.readonly_only "$READONLY" \
  --wa.arms nomem,withmem --agent.n_traj "$NTRAJ" \
  --wa.max_steps 30 --wa.step_timeout 90 \
  --run.budget_usd 250 --run.name "$RUN"
echo "RUN_DONE: $RUN"
