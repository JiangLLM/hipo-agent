#!/bin/bash
# Two-layer self-evolution run (final design): withmem arm only, n_traj=8 parallel rollouts.
# Reuses the earlier nomem baseline (rewards_nomem.json) — no need to re-run nomem.
#
#   bash scripts/run_wa_evolve.sh gitlab           # 43 tasks, quickest — run this first
#   bash scripts/run_wa_evolve.sh shopping_admin   # 88 tasks
#   bash scripts/run_wa_evolve.sh shopping
#   bash scripts/run_wa_evolve.sh reddit
#
# Per task: retrieve top-1 lesson -> 8 rollouts IN PARALLEL (8 worker processes) -> judge
# (verified = reasoning really derived the answer) -> L1 writes failures + 蒙对 flukes (one
# each, no cap) -> L2 contrasts the 8 L1s by majority/minority. No truncation anywhere.
# Turn off fluke capture with:  L1_FLUKE=off bash scripts/run_wa_evolve.sh gitlab
set -e
cd "$(dirname "$0")/.."
SITE="${1:-gitlab}"
export ARMS=withmem
export NTRAJ=8
EXTRA=""
[ "${L1_FLUKE:-on}" = "off" ] && EXTRA="--wa.l1_fluke off"

# run it (run_wa_site.sh carries the full, single-source-of-truth python invocation)
EXTRA_ARGS="$EXTRA" ARMS=withmem NTRAJ=8 bash scripts/run_wa_site.sh "$SITE"

# quick result peek from the newest run dir for this site
D=$(ls -dt runs/wa_${SITE}_*_*/ 2>/dev/null | head -1)
echo
echo "== 结果速览: $D =="
echo "  L1 写入: $(grep -c wa_write_l1 "$D/events.jsonl" 2>/dev/null || echo 0)"
echo "  L2 写入: $(grep -c wa_write_l2 "$D/events.jsonl" 2>/dev/null || echo 0)  (>0 = L2 真的在写)"
cat "$D/summary.json" 2>/dev/null
echo
echo "== 详细分析: .venv-wa/bin/python scripts/analyze_wa.py $D =="
