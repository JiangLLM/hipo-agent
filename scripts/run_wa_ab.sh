#!/bin/bash
# Symmetric, low-noise A/B for the L2-only design.
# BOTH arms run 8 rollouts in ONE run (same network, same time):
#   nomem   — eval_rollouts=8, no learning     (the honest baseline, 8 draws not 1)
#   withmem — n_traj=8, learns, inject_only_l2 (only L2 lessons retrieved; L1 still written for debug)
# Compare the MEAN success rate (nc/8) per task — the only fair, noise-robust number.
#
#   bash scripts/run_wa_ab.sh gitlab
#   bash scripts/run_wa_ab.sh shopping_admin
#
# Knob: INJECT_ONLY_L2=off  -> retrieve L1+L2 (old behavior), for comparison.
set -e
cd "$(dirname "$0")/.."
SITE="${1:-gitlab}"
export LLM_TIMEOUT="${LLM_TIMEOUT:-180}"
EXTRA="--wa.eval_rollouts 8"
[ "${INJECT_ONLY_L2:-on}" = "off" ] && EXTRA="$EXTRA --wa.inject_only_l2 off"

ARMS=nomem,withmem NTRAJ=8 EXTRA_ARGS="$EXTRA" bash scripts/run_wa_site.sh "$SITE"

D=$(ls -dt runs/wa_${SITE}_*_*/ 2>/dev/null | head -1); D=${D%/}
echo
echo "== 对等 8 轨 A/B(均值口径,唯一可信): $D =="
.venv-wa/bin/python scripts/analyze_ab_mean.py "$D" 2>/dev/null \
  || echo "分析: .venv-wa/bin/python scripts/analyze_ab_mean.py $D"
