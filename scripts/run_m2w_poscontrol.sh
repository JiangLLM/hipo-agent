#!/usr/bin/env bash
# POSITIVE CONTROL: learn on a task set, then test on THE SAME tasks (memory holds their
# exact procedure). This isolates "is the memory mechanism even capable of helping?"
#   - withmem >> nomem here  => mechanism works; the field failure is COVERAGE (tasks too diverse)
#   - withmem ~ nomem here    => mechanism is broken (retrieval/injection/following)
#
# Usage: bash scripts/run_m2w_poscontrol.sh
# Overrides: MODEL=openai/gpt-4o LLIM=40 NTRAJ=3 BUDGET=12 SPLIT=test_task
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"
SPLIT="${SPLIT:-test_task}"; LLIM="${LLIM:-40}"; NTRAJ="${NTRAJ:-3}"
MODEL="${MODEL:-openai/gpt-4o}"; BUDGET="${BUDGET:-12}"

echo "POSITIVE CONTROL  model=$MODEL learn=test=$LLIM tasks n_traj=$NTRAJ"
"$PY" -m hippo.m2w.run --brain llm --llm.model "$MODEL" \
  --m2w.test_split "$SPLIT" --m2w.holdout 0.5 \
  --m2w.learn_limit "$LLIM" --m2w.test_on_learn true --m2w.test_limit "$LLIM" \
  --agent.n_traj "$NTRAJ" --memory.mode both --surprise.source traj_divergence \
  --memory.token_budget 20000 --logging.trace true \
  --run.budget_usd "$BUDGET" --run.name m2w_poscontrol 2>&1 | grep -E "A/B|halted|Error:" || true
echo "=== if withmem >> nomem: mechanism OK, real problem is coverage; else: mechanism broken ==="
