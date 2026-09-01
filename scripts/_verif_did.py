"""Two RTM-free views:
 (1) unconditional delta split by injected / not-injected (no selection on the noisy arm at all);
 (2) difference-in-differences inside the hi-baseline stratum (inj minus non), with the arm-swap
     null so RTM that is common to both groups cancels and any residual is measured.
Also: concentration of the admin hi/inj loss over tasks.
"""
import sys
sys.path.insert(0, "scripts")
import numpy as np
from _verif_bucket import per_task, RUNS

rng = np.random.default_rng(1)
B = 4000

print("--- (1) unconditional per-task delta (rollouts /8), split ONLY by injection ---")
for name, run in RUNS.items():
    rows = [r for r in per_task(run).values() if r["channel"] == "string"]
    d = np.array([8 * (r["mem_nc"] / r["mem_n"] - r["nomem_nc"] / r["nomem_n"]) for r in rows])
    inj = np.array([r["inj"] for r in rows])
    # bootstrap CI over tasks
    def ci(x):
        if len(x) == 0:
            return (0, 0)
        bs = [rng.choice(x, len(x), replace=True).mean() for _ in range(2000)]
        return np.percentile(bs, 2.5), np.percentile(bs, 97.5)
    a, b = d[inj], d[~inj]
    print(f"{name:8s} inj n={inj.sum():3d} mean={a.mean():+.3f} CI[{ci(a)[0]:+.2f},{ci(a)[1]:+.2f}]"
          f"   non n={(~inj).sum():3d} mean={b.mean() if len(b) else 0:+.3f}"
          f"   all mean={d.mean():+.3f}")

print("\n--- (2) DiD inside hi-baseline stratum, vs arm-swap null ---")
for name, run in RUNS.items():
    rows = [r for r in per_task(run).values() if r["channel"] == "string"]
    a_nc = np.array([r["nomem_nc"] for r in rows], float); a_n = np.array([r["nomem_n"] for r in rows], float)
    b_nc = np.array([r["mem_nc"] for r in rows], float); b_n = np.array([r["mem_n"] for r in rows], float)
    inj = np.array([r["inj"] for r in rows])

    def did(A_nc, A_n, Bc, Bn):
        fa, fb = A_nc / A_n, Bc / Bn
        dd = 8 * (fb - fa)
        hi = fa >= 0.75
        g1, g0 = dd[hi & inj], dd[hi & ~inj]
        if len(g1) == 0 or len(g0) == 0:
            return None, (g1.mean() if len(g1) else np.nan), np.nan
        return g1.mean() - g0.mean(), g1.mean(), g0.mean()

    obs, o1, o0 = did(a_nc, a_n, b_nc, b_n)
    if obs is None:
        print(f"{name:8s} hi/non group EMPTY (n=0) -> DiD not computable; hi/inj obs {o1:+.3f}")
        continue
    null = []
    for _ in range(B):
        sw = rng.random(len(rows)) < 0.5
        v, _, _ = did(np.where(sw, b_nc, a_nc), np.where(sw, b_n, a_n),
                      np.where(sw, a_nc, b_nc), np.where(sw, a_n, b_n))
        if v is not None:
            null.append(v)
    null = np.array(null)
    print(f"{name:8s} hi/inj {o1:+.3f}  hi/non {o0:+.3f}  DiD {obs:+.3f}"
          f"   swap-null mean {null.mean():+.3f} [{np.percentile(null,2.5):+.2f},{np.percentile(null,97.5):+.2f}]"
          f"  p(one-sided)={np.mean(null <= obs):.3f}")

print("\n--- (3) concentration of admin hi/inj loss ---")
for name in ["admin#1", "admin#2", "shop#3"]:
    rows = [r for r in per_task(RUNS[name]).values() if r["channel"] == "string"]
    sub = [(8 * (r["mem_nc"] / r["mem_n"] - r["nomem_nc"] / r["nomem_n"]), r)
           for r in rows if r["inj"] and r["nomem_nc"] / r["nomem_n"] >= 0.75]
    sub.sort(key=lambda x: x[0])
    tot = sum(x[0] for x in sub)
    neg = [x for x in sub if x[0] < 0]
    print(f"{name}: hi/inj n={len(sub)} total={tot:+.2f}; {len(neg)} tasks negative, "
          f"top-3 worst sum={sum(x[0] for x in sub[:3]):+.2f} ({100*sum(x[0] for x in sub[:3])/tot:.0f}% of total)")
    for dv, r in sub[:6]:
        print(f"    t{list(r.keys()) and ''}{dv:+5.2f}  nomem {r['nomem_nc']}/{r['nomem_n']} -> mem {r['mem_nc']}/{r['mem_n']}  «{(r['titles'] or ['-'])[0][:70]}»")
