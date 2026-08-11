#!/bin/bash
# Run one WebArena site across the 8-box fleet: rollout r goes to deployment r, so a task's N
# rollouts are genuinely independent even when the task writes to the server.
#
#   bash scripts/run_wa_fleet.sh shopping                  # readonly tasks (139), 8 rollouts each
#   FILTER=all bash scripts/run_wa_fleet.sh reddit         # every reddit task incl. mutating (106)
#   NTRAJ=8 ARMS=nomem,withmem bash scripts/run_wa_fleet.sh gitlab
#
# Refuses to start unless every box in the fleet is serving ITS OWN urls. That check is not
# ceremony: a box whose Magento base_url was not re-patched answers 302 to the host baked into the
# upstream image, which silently funnels its rollout onto a foreign deployment and re-creates the
# shared-state contamination the fleet exists to remove. It has already happened once.
#
# RESET DISCIPLINE. Mutating tasks dirty their box as the stream advances, and nothing here resets
# between tasks — cross-task drift is the ~1-2% effect upstream tolerates, whereas within-task
# contamination (which the fleet fixes) is fatal. For a clean second pass, run
# `bash scripts/wa_fleet.sh reset` between runs; it recreates every site from its pristine image on
# all 8 boxes in parallel.
set -euo pipefail
cd "$(dirname "$0")/.."

SITE="${1:-shopping}"
FILTER="${FILTER:-readonly}"        # readonly | all | string_match (legacy 230-task set)
NTRAJ="${NTRAJ:-8}"
# Both arms by default. A withmem-only run cannot be compared with anything: the cross-run
# baselines it forces you back onto are the exact thing that invalidated every number we produced
# before the fleet existed. One such run has already been wasted by this default being withmem.
ARMS="${ARMS:-nomem,withmem}"

# One experiment at a time. The 8 boxes serve whichever run asks, so a second run started while
# one is in flight silently shares them: both slow down and both sets of numbers pick up the
# contention. That happened once already and it is invisible in the output.
if pgrep -f "hippo\.wa\.run" >/dev/null 2>&1; then
  echo "!! a WebArena run is already using the fleet:"
  pgrep -fl "hippo\.wa\.run" | head -2 | cut -c1-150
  echo "   Wait for it, or stop it deliberately. Two runs on 8 boxes contaminate each other."
  exit 1
fi
MODEL="${MODEL:-gpt-5.6-sol}"
RUN="${RUN_NAME:-wa_fleet_${SITE}_${FILTER}_$(date +%Y%m%d_%H%M%S)}"
export LLM_TIMEOUT="${LLM_TIMEOUT:-180}"

URLS=$(bash scripts/wa_fleet.sh urls)
N_BOX=$(echo "$URLS" | tr ',' '\n' | wc -l | tr -d ' ')
if [ "$N_BOX" -lt "$NTRAJ" ]; then
  echo "!! fleet has $N_BOX boxes but NTRAJ=$NTRAJ — every rollout needs its own box"; exit 1
fi

# A site nobody deployed does not fail loudly: set_site_env points WA_MAP/WA_WIKIPEDIA at ports
# 3000/8888 regardless, ui_login() then dies per episode with ERR_CONNECTION_REFUSED, and the run
# completes as a tidy 0% arm. Refuse instead of producing that number.
case "$SITE" in
  map|wikipedia)
    echo "!! site '$SITE' is not deployed on this fleet (ports 3000/8888 are dead)."
    echo "   Running it would score 0 on every task and look like a legitimate result."
    exit 1 ;;
esac

echo "== preflight: all $N_BOX boxes must serve their own urls"
bash scripts/wa_fleet.sh check || { echo "!! fleet not ready — fix the boxes before running"; exit 1; }

LOG="runs/${RUN}.log"
mkdir -p runs
echo "== [$SITE] filter=$FILTER n_traj=$NTRAJ arms=$ARMS -> runs/$RUN  (log: $LOG)"

caffeinate -i .venv-wa/bin/python -m hippo.wa.run \
  --llm.model "$MODEL" --llm.embed_model local/BAAI/bge-small-en-v1.5 \
  --wa.base_url "$(echo "$URLS" | cut -d, -f1)" \
  --wa.base_urls "$URLS" \
  --wa.site "$SITE" --wa.limit 0 \
  --wa.task_filter "$FILTER" \
  --wa.fleet_reset "${FLEET_RESET:-$([ "$FILTER" = all ] && echo on || echo off)}" \
  --wa.arms "$ARMS" --agent.n_traj "$NTRAJ" --wa.eval_rollouts "$NTRAJ" \
  --memory.retrieve_k_reasoning 1 \
  --wa.max_steps 30 --wa.step_timeout 90 --wa.reset_timeout 120 \
  --run.budget_usd "${BUDGET:-1000000}" --run.name "$RUN" 2>&1 | tee "$LOG"

D=$(ls -dt runs/${RUN}_*/ 2>/dev/null | head -1)
echo
echo "== [$SITE] DONE -> $D"
echo "  L1 writes: $(grep -c wa_write_l1 "$D/events.jsonl" 2>/dev/null || echo 0)"
echo "  L2 writes: $(grep -c wa_write_l2 "$D/events.jsonl" 2>/dev/null || echo 0)"
.venv-wa/bin/python scripts/analyze_ab_mean.py "$D" 2>/dev/null || true
