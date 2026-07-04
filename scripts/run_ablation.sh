#!/usr/bin/env bash
# Run the core A/B matrix and print a comparison table.
# Usage: bash scripts/run_ablation.sh [extra args, e.g. --agent.n_traj 3]
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"
EXTRA="${*:-}"
COMMON="--mock $EXTRA"

run () {  # name, args...
  local name="$1"; shift
  "$PY" -m hippo.run $COMMON --run.name "$name" "$@" >/dev/null 2>&1
  local f
  f=$(ls -dt runs/${name}_* | head -1)/summary.json
  "$PY" - "$name" "$f" <<'PY'
import json, sys
name, f = sys.argv[1], sys.argv[2]
d = json.load(open(f))
print(f"{name:14s} sr_pass1={d['sr_pass1']:.3f} sr_passk={d['sr_passk']:.3f} "
      f"writes={d['writes']:>3} delta={d['learning_delta']:+.3f} by_type={d['sr_by_type']}")
PY
}

echo "=== hippo-agent ablation (mock) ==="
run nomem      --memory.mode off
run reason     --memory.mode reasoning_only --surprise.source traj_divergence
run fact       --memory.mode fact_only      --surprise.source traj_divergence
run storeall   --memory.mode both           --surprise.source store_all
run mempred    --memory.mode both           --surprise.source memory_pred
run trajdiv    --memory.mode both           --surprise.source traj_divergence
