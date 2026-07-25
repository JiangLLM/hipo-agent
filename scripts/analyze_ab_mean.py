#!/usr/bin/env python
"""Symmetric A/B analysis — the ONLY fair, low-noise measure for hippo WebArena.

Reads ONE run that ran BOTH arms at N rollouts (nomem eval_rollouts=8, withmem n_traj=8) and
compares the MEAN success rate (nc/n) per arm. Single-rollout pass@1 (rollout[0]) is shown too,
but the mean is what to trust — it averages out the sampling noise that made every prior number
untrustworthy. Wins/regressions are counted by nc margin (>=3 of 8), which is robust to noise.

    .venv-wa/bin/python scripts/analyze_ab_mean.py runs/<dir>
"""
import json
import sys

BAD = {783}  # known bad-eval tasks (state-change slipped into readonly -> false-positive reward)


def main():
    d = sys.argv[1]
    rows = [json.loads(l) for l in open(f"{d}/events.jsonl") if l.strip()]
    T = {}  # (arm, task_id) -> (rollout0 reward, nc, n)
    for r in rows:
        if r.get("kind") == "wa_task":
            T[(r["tag"], r["task_id"])] = (r["reward"], r["nc"], r["n"])
    arms = sorted({a for a, _ in T})
    tasks = sorted({t for _, t in T})
    common = [t for t in tasks if all((a, t) in T for a in arms) and t not in BAD]
    print(f"arms={arms}  tasks={len(tasks)}  comparable (excl {BAD}) = {len(common)}")
    if not common:
        return
    for a in arms:
        r0 = sum(T[(a, t)][0] for t in common) / len(common)
        mean = sum(T[(a, t)][1] / T[(a, t)][2] for t in common) / len(common)
        print(f"  {a:<9} rollout[0] pass@1 = {r0:.3f}    8-rollout MEAN = {mean:.3f}")
    if "nomem" in arms and "withmem" in arms:
        def nc(a, t):
            return T[(a, t)][1] / T[(a, t)][2]
        dmean = sum(nc("withmem", t) - nc("nomem", t) for t in common) / len(common)
        print(f"  Δ MEAN (withmem - nomem) = {dmean:+.3f}   ← the number to trust")
        win = [t for t in common if T[("withmem", t)][1] - T[("nomem", t)][1] >= 3]
        loss = [t for t in common if T[("nomem", t)][1] - T[("withmem", t)][1] >= 3]
        print(f"\n  真改善 (withmem nc 高 ≥3/8): {len(win)}  {sorted(win)}")
        print(f"  真回退 (nomem nc 高 ≥3/8):   {len(loss)}  {sorted(loss)}")
        for t in sorted(set(win) | set(loss)):
            print(f"    t{t}: nomem {T[('nomem', t)][1]}/8   withmem {T[('withmem', t)][1]}/8")


if __name__ == "__main__":
    main()
