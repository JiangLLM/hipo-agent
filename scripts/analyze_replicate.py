#!/usr/bin/env python
"""Analyze a replicate run (nomem vs frozenmem, N rollouts/task).

Per (arm, task_id): MEAN official reward across the N rollouts = per-task success rate.
Reports (1) full-set net (mean-of-task-rates, both arms), (2) the decisive tasks from the
original single-rollout run — for each, nomem_rate vs frozen_rate — and whether the original
WIN/REGRESSION reproduces (frozen consistently better/worse) or washes out (was noise).

    .venv-wa/bin/python scripts/analyze_replicate.py runs/wa_rep_shopping_admin_YYYYMMDD_HHMMSS
"""
import json
import sys
import collections
from pathlib import Path


def load_episodes(run_dir):
    """(arm, task_id) -> list of final rewards, one per rollout."""
    ev = Path(run_dir) / "events.jsonl"
    rew = collections.defaultdict(dict)  # (arm,tid) -> {rollout: reward}
    for ln in ev.read_text().splitlines():
        if not ln.strip():
            continue
        try:
            e = json.loads(ln)
        except json.JSONDecodeError:
            continue
        # episode-end row: has stop_answer + reward + rollout + tag + task_id
        if "stop_answer" in e and "reward" in e and "rollout" in e and "tag" in e:
            rew[(e["tag"], e["task_id"])][e["rollout"]] = float(e["reward"])
    # collapse rollout dict -> list
    return {k: list(v.values()) for k, v in rew.items()}


def main():
    run_dir = sys.argv[1]
    site = Path(run_dir).name.split("_")[2] if "wa_rep_" in Path(run_dir).name else None
    ep = load_episodes(run_dir)
    arms = sorted({a for a, _ in ep})
    tasks = sorted({t for _, t in ep})
    if "nomem" not in arms:
        print("no nomem arm found; arms =", arms)
        return
    other = [a for a in arms if a != "nomem"]
    B = other[0] if other else None
    print(f"run: {run_dir}   arms={arms}   tasks={len(tasks)}")
    rollcount = {a: [len(ep.get((a, t), [])) for t in tasks] for a in arms}
    print(f"rollouts/task: " + ", ".join(f"{a}={min(rollcount[a])}-{max(rollcount[a])}" for a in arms))

    def rate(a, t):
        r = ep.get((a, t), [])
        return sum(r) / len(r) if r else None

    # ---- full-set net (mean of per-task rates) ----
    def net(a):
        vs = [rate(a, t) for t in tasks if rate(a, t) is not None and rate("nomem", t) is not None]
        return sum(vs) / len(vs) if vs else 0.0
    print(f"\n== 全集净值 (每任务均值率再平均, N 轮) ==")
    print(f"  nomem      {net('nomem'):.3f}")
    if B:
        print(f"  {B:<10} {net(B):.3f}    Δ = {net(B)-net('nomem'):+.3f}")

    # ---- decisive tasks ----
    dec_all = {}
    p = Path("runs/decisive_taskids.json")
    if p.exists():
        dec_all = json.load(open(p))
    dec = dec_all.get(site, []) if site else sorted({t for _, t in ep})
    if B and dec:
        print(f"\n== 决定性任务复现 (site={site}, N 轮均值) ==")
        print(f"{'task':<8}{'nomem':<9}{B:<11}{'Δ':<9}{'判定'}")
        rep_win = rep_reg = wash = 0
        for t in dec:
            rn, rb = rate("nomem", t), rate(B, t)
            if rn is None or rb is None:
                print(f"{t:<8}(缺 rollout,跳过)")
                continue
            d = rb - rn
            verdict = "记忆更好(胜利复现)" if d > 0.05 else ("记忆更差(退步复现)" if d < -0.05 else "打平(原判定是噪声)")
            if d > 0.05: rep_win += 1
            elif d < -0.05: rep_reg += 1
            else: wash += 1
            print(f"{t:<8}{rn:<9.2f}{rb:<11.2f}{d:<+9.2f}{verdict}")
        print(f"\n  胜利复现 {rep_win} · 退步复现 {rep_reg} · 洗成平局(噪声) {wash}")


if __name__ == "__main__":
    main()
