#!/bin/bash
# SYMMETRIC WebArena A/B — the only apples-to-apples measure. BOTH arms get N=8 rollouts
# (nomem via wa.eval_rollouts, withmem via agent.n_traj), so the comparison is mean success
# rate (nc/n) vs mean success rate: no voting bonus, no 8-vs-1 shape mismatch, and per-task
# wins/regressions are counted by nc margin instead of a single noisy draw.
#
#   bash scripts/run_wa_sym.sh reddit                 # 11 tasks — the remaining site
#   N=8 bash scripts/run_wa_sym.sh reddit
#   ARMS=nomem,frozenmem MEM=runs/<x>/memory_clean.json bash scripts/run_wa_sym.sh shopping
#
# The last form is how we will validate the consolidation fix (frozen clean bank vs nomem).
# Analysis is automatic at the end (analyze_ab_mean.py = mean-based, noise-robust).
set -e
cd "$(dirname "$0")/.."
SITE="${1:-reddit}"
N="${N:-8}"
ARMS="${ARMS:-nomem,withmem}"
MEM="${MEM:-}"                       # memory.json for a frozenmem arm
BASE="${BASE:-http://10.44.12.29}"
# macOS ships bash 3.2 (no associative arrays) — plain case, works everywhere
case "$SITE" in
  shopping)        P=7770 ;;
  shopping_admin)  P=7780 ;;
  reddit)          P=9999 ;;
  gitlab)          P=8023 ;;
  *)               P="" ;;
esac
[ -z "$P" ] && { echo "!! unknown site '$SITE'"; exit 1; }
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 6 "$BASE:$P" 2>/dev/null || echo 000)
[ "$code" = "000" ] && { echo "!! [$SITE] $BASE:$P unreachable — container down / off VPN?"; exit 1; }
echo "== [$SITE] reachable (HTTP $code)"

EXTRA=""
[ -n "$MEM" ] && EXTRA="--wa.memory_in $MEM"
RUN="${RUN_NAME:-wa_sym_${SITE}_$(date +%Y%m%d_%H%M%S)}"
export LLM_TIMEOUT="${LLM_TIMEOUT:-180}"
LOG="runs/${RUN}.log"
mkdir -p runs
echo "== [$SITE] SYMMETRIC A/B  arms=$ARMS  N=$N per arm (both!)  -> runs/$RUN"

caffeinate -i .venv-wa/bin/python -m hippo.wa.run \
  --llm.model "${MODEL:-gpt-5.6-sol}" --llm.embed_model local/BAAI/bge-small-en-v1.5 \
  --wa.base_url "$BASE" --wa.site "$SITE" --wa.limit 0 \
  --wa.readonly_only true \
  --wa.arms "$ARMS" \
  --agent.n_traj "$N" --wa.eval_rollouts "$N" \
  --memory.retrieve_k_reasoning 1 \
  --wa.max_steps 30 --wa.step_timeout 90 --wa.reset_timeout 120 \
  $EXTRA \
  --run.budget_usd "${BUDGET:-1000000}" --run.name "$RUN" 2>&1 | tee "$LOG"

D=$(ls -dt runs/${RUN}_*/ 2>/dev/null | head -1)
echo
echo "== [$SITE] DONE -> $D"
echo "  L1 写入: $(grep -c wa_write_l1 "$D/events.jsonl" 2>/dev/null || echo 0)"
echo "  L2 写入: $(grep -c wa_write_l2 "$D/events.jsonl" 2>/dev/null || echo 0)"
echo
echo "===== 对称 A/B（均值口径，可信） ====="
.venv-wa/bin/python scripts/analyze_ab_mean.py "$D" || true
