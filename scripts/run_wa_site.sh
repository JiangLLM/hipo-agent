#!/bin/bash
# Run ONE WebArena site end-to-end: streaming No-Mem baseline + withmem (learn-as-you-go)
# over that site's readonly (string_match) tasks. pass@1, k=1 retrieval. Self-contained —
# safe to run alone or several in parallel (each gets its own browser + per-site memory).
#
#   MODEL=gpt-5.6-sol bash scripts/run_wa_site.sh gitlab
#
# Knobs:  MODEL (base model) · NTRAJ (1 = pass@1 / RB base; 3 or 5 = MaTTS L2 self-contrast)
# Output: runs/<run>/  (events.jsonl + summary.json + memory.json + metrics_*.csv)
#         runs/<run>.log  (full console log)
# Analyse: .venv-wa/bin/python scripts/analyze_wa.py runs/<run>
set -e
cd "$(dirname "$0")/.."
SITE="${1:-${SITE:-shopping_admin}}"
MODEL="${MODEL:-gpt-5.6-sol}"
NTRAJ="${NTRAJ:-1}"
ARMS="${ARMS:-nomem,withmem}"   # withmem = only re-run the learning arm (reuse prior nomem baseline)
EXTRA_ARGS="${EXTRA_ARGS:-}"    # extra CLI flags passed through verbatim (e.g. --wa.l1_fluke off)
BASE="${BASE:-http://10.44.12.29}"
RUN="${RUN_NAME:-wa_${SITE}_$(date +%Y%m%d_%H%M%S)}"
export LLM_TIMEOUT="${LLM_TIMEOUT:-180}"
LOG="runs/$(echo "$RUN" | tr '/' '_').log"
mkdir -p runs "runs/$(dirname "$RUN")" 2>/dev/null || true
echo "== [$SITE] model=$MODEL n_traj=$NTRAJ arms=$ARMS  readonly  -> runs/$RUN  (log: $LOG)"
caffeinate -i .venv-wa/bin/python -m hippo.wa.run \
  --llm.model "$MODEL" --llm.embed_model local/BAAI/bge-small-en-v1.5 \
  --wa.base_url "$BASE" --wa.site "$SITE" --wa.limit 0 \
  --wa.readonly_only true \
  --wa.arms "$ARMS" --agent.n_traj "$NTRAJ" \
  --memory.retrieve_k_reasoning 1 \
  --wa.max_steps 30 --wa.step_timeout 90 --wa.reset_timeout 120 \
  $EXTRA_ARGS \
  --run.budget_usd 500 --run.name "$RUN" 2>&1 | tee "$LOG"
echo "== [$SITE] DONE -> runs/$RUN"
echo "== analyse: .venv-wa/bin/python scripts/analyze_wa.py runs/$RUN"
