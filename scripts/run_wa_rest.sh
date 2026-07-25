#!/bin/bash
# Run the remaining WebArena sites end-to-end, SEQUENTIALLY (each is 8 headless browsers;
# running sites in parallel would oversubscribe CPU and invite the Playwright wedge).
# Uses the current code (answer-blind experience writing + off-host guard + browsergym infra
# patches) and the withmem self-evolution arm (n_traj=8), reusing run_wa_evolve.sh.
#
#   bash scripts/run_wa_rest.sh                       # shopping_admin shopping reddit
#   bash scripts/run_wa_rest.sh shopping_admin reddit # only these
#
# Each site: reachability pre-check on its port; skip (loudly) if the container is down.
# Per-site memory is fresh/empty (self-evolution from scratch); results in runs/wa_<site>_*.
set -e
cd "$(dirname "$0")/.."
BASE="${BASE:-http://10.44.12.29}"
SITES=("$@"); [ ${#SITES[@]} -eq 0 ] && SITES=(shopping_admin shopping reddit)

echo "== will run (sequential): ${SITES[*]}  base=$BASE =="
for S in "${SITES[@]}"; do
  # macOS ships bash 3.2 (no associative arrays) — plain case, works everywhere
  case "$S" in
    shopping)        P=7770 ;;
    shopping_admin)  P=7780 ;;
    reddit)          P=9999 ;;
    gitlab)          P=8023 ;;
    *)               P="" ;;
  esac
  if [ -z "$P" ]; then echo "!! unknown site '$S' (skip)"; continue; fi
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 6 "$BASE:$P" 2>/dev/null || echo 000)
  if [ "$code" = "000" ]; then
    echo "!! [$S] $BASE:$P unreachable (HTTP 000) — container down / off VPN? SKIPPING."
    continue
  fi
  echo "== [$S] reachable (HTTP $code) — starting withmem n=8 =="
  bash scripts/run_wa_evolve.sh "$S" || echo "!! [$S] run exited non-zero (continuing to next site)"
  echo "== [$S] done =="
done
echo "== all requested sites finished =="
echo "== analyse each: .venv-wa/bin/python scripts/analyze_wa.py <run目录> =="
