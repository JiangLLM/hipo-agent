#!/bin/bash
# Low-variance causal A/B: is memory's per-task effect REAL or single-rollout noise?
# For one site, run the readonly set N times under two FIXED conditions and compare
# MEAN success rate per task:
#   nomem      — no memory
#   frozenmem  — that site's FINAL memory bank, frozen (deployment condition: full bank,
#                top-k retrieval, no learning). Isolates memory's causal effect per task
#                WITHOUT the streaming-order confound of the original withmem run.
# Decisive tasks (nomem/withmem differed on the single-rollout run) are inside the readonly
# set; analyze_replicate.py subsets them AND reports the full-set net.
#
#   bash scripts/run_wa_replicate.sh shopping_admin
#   ROLLOUTS=5 bash scripts/run_wa_replicate.sh gitlab
set -e
cd "$(dirname "$0")/.."
SITE="${1:-shopping_admin}"
ROLLOUTS="${ROLLOUTS:-5}"
MODEL="${MODEL:-gpt-5.6-sol}"
BASE="${BASE:-http://10.44.12.29}"
export LLM_TIMEOUT="${LLM_TIMEOUT:-180}"

# each site's FINAL withmem bank (the clean 4-site run)
case "$SITE" in
  reddit)         BANK="runs/wa_reddit_20260719_151957_20260719_151959/memory.json";;
  gitlab)         BANK="runs/wa_gitlab_20260719_161841_20260719_161843/memory.json";;
  shopping)       BANK="runs/wa_shopping_20260719_161803_20260719_161805/memory.json";;
  shopping_admin) BANK="runs/wa_shopping_admin_20260719_182647_20260719_182649/memory.json";;
  *) echo "unknown site $SITE"; exit 1;;
esac
[ -f "$BANK" ] || { echo "bank not found: $BANK"; exit 1; }

RUN="${RUN_NAME:-wa_rep_${SITE}_$(date +%Y%m%d_%H%M%S)}"
LOG="runs/$(echo "$RUN" | tr '/' '_').log"
mkdir -p runs
echo "== [replicate:$SITE] nomem vs frozenmem  rollouts=$ROLLOUTS  bank=$BANK  -> runs/$RUN"
caffeinate -i .venv-wa/bin/python -m hippo.wa.run \
  --llm.model "$MODEL" --llm.embed_model local/BAAI/bge-small-en-v1.5 \
  --wa.base_url "$BASE" --wa.site "$SITE" --wa.limit 0 \
  --wa.readonly_only true \
  --wa.arms nomem,frozenmem --wa.memory_in "$BANK" \
  --wa.eval_rollouts "$ROLLOUTS" \
  --memory.retrieve_k_reasoning 1 \
  --wa.max_steps 30 --wa.step_timeout 90 --wa.reset_timeout 120 \
  --run.budget_usd "${BUDGET:-1000000}" --run.name "$RUN" 2>&1 | tee "$LOG"
echo "== [replicate:$SITE] DONE -> runs/$RUN"
echo "== analyse: .venv-wa/bin/python scripts/analyze_replicate.py runs/$RUN"
