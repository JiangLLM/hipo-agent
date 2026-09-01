"""Is the 'hi baseline -> injection hurts / lo baseline -> injection helps' split a real
per-lesson process, or regression to the mean from bucketing on the noisy nomem arm?

Two nulls, both assuming memory has NO effect on any task:
  (A) arm-swap permutation: exchange the two arms' counts per task with prob 1/2, recompute the
      bucketing and the statistic. Exactly exchangeable, non-parametric.
  (B) binomial resample at the pooled p-hat with the observed per-arm n's.
"""
import sys, json
sys.path.insert(0, "scripts")
import numpy as np
from _verif_bucket import per_task, RUNS

rng = np.random.default_rng(0)
B = 4000


def stats(a_nc, a_n, b_nc, b_n, inj):
    """a=nomem-labelled arm, b=mem-labelled arm. returns (hi_mean, lo_mean, hi_n, lo_n, total)"""
    fa, fb = a_nc / a_n, b_nc / b_n
    d = 8 * (fb - fa)
    hi = (fa >= 0.75) & inj
    lo = (fa < 0.75) & inj
    return (d[hi].mean() if hi.any() else 0.0, d[lo].mean() if lo.any() else 0.0,
            hi.sum(), lo.sum(), d.sum())


out = {}
for name, run in RUNS.items():
    rows = [r for r in per_task(run).values() if r["channel"] == "string"]
    a_nc = np.array([r["nomem_nc"] for r in rows], float)
    a_n = np.array([r["nomem_n"] for r in rows], float)
    b_nc = np.array([r["mem_nc"] for r in rows], float)
    b_n = np.array([r["mem_n"] for r in rows], float)
    inj = np.array([r["inj"] for r in rows])
    obs = stats(a_nc, a_n, b_nc, b_n, inj)

    # (A) arm-swap permutation
    hiN, loN = [], []
    for _ in range(B):
        sw = rng.random(len(rows)) < 0.5
        A_nc = np.where(sw, b_nc, a_nc); A_n = np.where(sw, b_n, a_n)
        Bc = np.where(sw, a_nc, b_nc); Bn = np.where(sw, a_n, b_n)
        h, l, *_ = stats(A_nc, A_n, Bc, Bn, inj)
        hiN.append(h); loN.append(l)
    hiN, loN = np.array(hiN), np.array(loN)

    # (B) binomial null at pooled p
    p = (a_nc + b_nc) / (a_n + b_n)
    hiB, loB = [], []
    for _ in range(B):
        A = rng.binomial(a_n.astype(int), p).astype(float)
        Bb = rng.binomial(b_n.astype(int), p).astype(float)
        h, l, *_ = stats(A, a_n, Bb, b_n, inj)
        hiB.append(h); loB.append(l)
    hiB, loB = np.array(hiB), np.array(loB)

    out[name] = dict(obs=obs, hiN=hiN, loN=loN, hiB=hiB, loB=loB)
    print(f"== {name}  n={len(rows)} inj={inj.sum()}  total_delta={obs[4]:+.2f} rollouts")
    print(f"   hi/inj  obs {obs[0]:+.3f} (n={obs[2]})   swap-null mean {hiN.mean():+.3f} "
          f"[{np.percentile(hiN,2.5):+.2f},{np.percentile(hiN,97.5):+.2f}]  p={np.mean(hiN<=obs[0]):.3f}"
          f"   binom-null mean {hiB.mean():+.3f} p={np.mean(hiB<=obs[0]):.3f}")
    print(f"   lo/inj  obs {obs[1]:+.3f} (n={obs[3]})   swap-null mean {loN.mean():+.3f} "
          f"[{np.percentile(loN,2.5):+.2f},{np.percentile(loN,97.5):+.2f}]  p={np.mean(loN>=obs[1]):.3f}"
          f"   binom-null mean {loB.mean():+.3f} p={np.mean(loB>=obs[1]):.3f}")
