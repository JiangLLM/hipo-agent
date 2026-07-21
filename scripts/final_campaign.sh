#!/bin/bash
# Verified 最终战役：三仓库回访率梯度 × 三记忆臂 × 3 seed，60 步紧预算主战场。
# 机器纪律：所有 rollout 严格串行、期间不跑任何评测；全部真值评测放在最后统一做。
# 预计 ~$350 / ~30h。产物 runs/fc_*。
set -e
cd "$(dirname "$0")/.."
M="--llm.model anthropic/claude-haiku-4-5 --llm.embed_model local/BAAI/bge-small-en-v1.5 --swe.agent_model anthropic/claude-haiku-4-5 --memory.retrieve_k_reasoning 4"
R=$(ls -dt runs/swe_big_django_2* | head -1)          # django bank@116 (243条)
SY=$(ls -dt runs/sym_stream_2* | head -1)             # sympy bank (82条) + 前40题preds

# ── 1. sphinx 攒库（前 30 题流式学习, N=5）──────────────────────────────
if ! ls runs/fc_sphinx_learn_2*/summary.json >/dev/null 2>&1; then   # summary = 真正跑完
  .venv/bin/python -m hippo.swe.run $M --swe.repos sphinx --swe.limit 30 \
    --swe.arms withmem --agent.n_traj 5 --run.budget_usd 45 --run.name fc_sphinx_learn
fi
SP=$(ls -dt runs/fc_sphinx_learn_2* | head -1)

# ── 2. 合并全局库（内容不变, 只合池）────────────────────────────────────
.venv/bin/python - <<PYEOF
import json, glob
banks = ["$R/memory.json", "$SY/memory.json", "$SP/memory.json"]
merged = {"reasoning": [], "fact": []}
for b in banks:
    merged["reasoning"] += json.load(open(b))["reasoning"]
json.dump(merged, open("runs/fc_global_bank.json", "w"))
print("global bank:", len(merged["reasoning"]), "items")
PYEOF

# ── 3. 计分臂：3 repos × {nomem, repo库, 全局库} × 3 seeds, 全部串行 ─────
run_arm () {  # repo skipfile arm seed extra_flags
  name="fc_${1}_${3}_s${4}"
  ls runs/${name}_2*/summary.json >/dev/null 2>&1 && return 0
  .venv/bin/python -m hippo.swe.run $M --swe.repos "$1" --swe.skip_done "$2" \
    --run.seed "$4" --run.budget_usd 40 --run.name "$name" $5
}
for seed in 1 2 3; do
  for spec in "django $R/preds_withmem.json" "sympy $SY/preds_withmem.json" "sphinx $SP/preds_withmem.json"; do
    repo=${spec%% *}; skip=${spec#* }
    case $repo in
      django) bank=$R/memory.json ;;
      sympy)  bank=$SY/memory.json ;;
      sphinx) bank=$SP/memory.json ;;
    esac
    run_arm "$repo" "$skip" nomem  "$seed" "--swe.arms nomem"
    run_arm "$repo" "$skip" repo   "$seed" "--swe.arms frozenmem --swe.memory_in $bank"
    run_arm "$repo" "$skip" global "$seed" "--swe.arms frozenmem --swe.memory_in runs/fc_global_bank.json --swe.memory_scope global"
  done
done

# ── 4. 真值评测统一收尾（rollout 全部结束后才开始）───────────────────────
.venv/bin/python scripts/eval_local.py "$SP/preds_withmem.json" --run-id fc_sphinx_learn_gt || true
for d in runs/fc_*_s[123]_2*; do
  p=$(ls "$d"/preds_*.json 2>/dev/null | head -1); [ -z "$p" ] && continue
  rid="gt_$(basename "$d" | sed 's/_2[0-9]*_[0-9]*$//')"
  ls "$d"/gt_*.json >/dev/null 2>&1 || .venv/bin/python scripts/eval_local.py "$p" --run-id "$rid" || true
done
echo FINAL_CAMPAIGN_COMPLETE
