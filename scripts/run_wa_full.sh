#!/bin/bash
# Run ALL 4 hosted WebArena sites IN PARALLEL — each is one run_wa_site.sh with its own
# browser + per-site memory, so a crash/hang in one site does NOT affect the others.
# Covers the 230 readonly (string_match) tasks: reddit 11, gitlab 43, shopping_admin 88,
# shopping 88. ReasoningBank protocol: streaming No-Mem vs withmem, pass@1, k=1.
#
#   MODEL=gpt-5.6-sol bash scripts/run_wa_full.sh
#
# Sites are ordered small->big so failures surface fast. ~3-4h wall-clock (bounded by the
# 88-task sites). One knob: MODEL. NTRAJ=1 default (pass@1); NTRAJ=3/5 = MaTTS.
#
# Monitor:  tail -f runs/full_<stamp>_*.log
# Stop all: pkill -f hippo.wa.run
# Analyse:  for d in runs/full_<stamp>/*/; do .venv-wa/bin/python scripts/analyze_wa.py "$d"; done
set -e
cd "$(dirname "$0")/.."
MODEL="${MODEL:-gpt-5.6-sol}"
SITES="${SITES:-reddit gitlab shopping_admin shopping}"
STAMP=$(date +%Y%m%d_%H%M%S)
export MODEL NTRAJ BASE LLM_TIMEOUT
echo "== full readonly WebArena run  stamp=$STAMP  model=$MODEL  sites: $SITES"
for SITE in $SITES; do
  RUN_NAME="full_${STAMP}/${SITE}" bash scripts/run_wa_site.sh "$SITE" &
  echo "  launched $SITE (pid $!)  -> runs/full_${STAMP}/${SITE}"
  sleep 3                       # stagger browser starts
done
echo "== all 4 sites launched. monitor: tail -f runs/full_${STAMP}_*.log"
wait
echo "== ALL SITES DONE: runs/full_${STAMP}/"
echo "== analyse: for d in runs/full_${STAMP}/*/; do .venv-wa/bin/python scripts/analyze_wa.py \"\$d\"; done"
