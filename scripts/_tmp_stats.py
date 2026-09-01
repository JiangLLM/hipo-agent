import json, sys, collections, datetime
import numpy as np
sys.path.insert(0, "src")
from hippo.config import load_config
from hippo.wa.data import load_tasks

RUNS = {
 "sa2": ("wa_fleet_shopping_admin_readonly_20260808_130520_20260808_130530", "shopping_admin"),
 "sa1": ("wa_fleet_shopping_admin_readonly_20260807_225320_20260807_225403", "shopping_admin"),
 "sh3": ("wa_fleet_shopping_readonly_20260806_223937_20260806_224018", "shopping"),
}

def rc(t):
    r = t.get("reference")
    if not r:
        return "no-ref"
    if isinstance(r, dict) and list(r) == ["fuzzy_match"] and r["fuzzy_match"] == "N/A":
        return "NA"
    if isinstance(r, dict) and "fuzzy_match" in r:
        return "fuzzy"
    return "exact"

rng = np.random.default_rng(7)

def boot(ds, B=40000):
    a = np.array(ds)
    if len(a) == 0:
        return (0, 0, 1.0)
    bs = rng.choice(a, size=(B, len(a)), replace=True).mean(axis=1)
    return np.percentile(bs, 2.5), np.percentile(bs, 97.5), min(np.mean(bs <= 0), np.mean(bs >= 0)) * 2

def perm(pairs, B=40000):
    """rollout-level permutation: for each task shuffle the pooled 0/1 rollouts between arms"""
    obs = np.mean([np.mean(b) - np.mean(a) for a, b in pairs])
    cnt = 0
    for _ in range(B // 100):
        pass
    stats = np.empty(B)
    pooled = [(np.array(a + b), len(a), len(b)) for a, b in pairs]
    for i in range(B):
        s = 0.0
        for p, na, nb in pooled:
            q = rng.permutation(p)
            s += q[na:].mean() - q[:na].mean()
        stats[i] = s / len(pooled)
    return obs, np.mean(np.abs(stats) >= abs(obs) - 1e-12)

for key, (run, site) in RUNS.items():
    cfg = load_config(["--wa.site", site, "--wa.task_filter", "readonly", "--wa.base_url", "http://x"])
    tk = {t["task_id"]: t for t in load_tasks(cfg)}
    ev = collections.defaultdict(list)
    for ln in open(f"runs/{run}/events.jsonl"):
        d = json.loads(ln)
        ev[d.get("kind")].append(d)
    end = collections.defaultdict(dict)
    for d in ev["wa_episode_end"]:
        end[(d["tag"], d["task_id"])][d["rollout"]] = d
    inj = {d["task_id"] for d in ev["wa_episode_start"] if d["tag"] == "withmem" and d.get("mem_injected")}
    ids = sorted({t for (tg, t) in end if tg == "nomem"} & {t for (tg, t) in end if tg == "withmem"})
    sets = {
        "no-inj ALL": [t for t in ids if t not in inj],
        "no-inj exact+fuzzy": [t for t in ids if t not in inj and rc(tk[t]) in ("exact", "fuzzy")],
        "no-inj exact only": [t for t in ids if t not in inj and rc(tk[t]) == "exact"],
        "INJECTED ALL": [t for t in ids if t in inj],
        "INJECTED exact+fuzzy": [t for t in ids if t in inj and rc(tk[t]) in ("exact", "fuzzy")],
        "ALL paired": ids,
        "ALL exact+fuzzy": [t for t in ids if rc(tk[t]) in ("exact", "fuzzy")],
    }
    print(f"===== {key} =====")
    for name, S in sets.items():
        pairs = []
        for t in S:
            a = [int(bool(v["reward"])) for v in end[("nomem", t)].values()]
            b = [int(bool(v["reward"])) for v in end[("withmem", t)].values()]
            pairs.append((a, b))
        ds = [np.mean(b) - np.mean(a) for a, b in pairs]
        lo, hi, p = boot(ds)
        o, pp = perm(pairs, 20000) if S else (0, 1)
        print(f"  {name:22s} n={len(S):3d} delta={100*np.mean(ds):+6.2f}  boot95=[{100*lo:+6.2f},{100*hi:+6.2f}] "
              f" perm_p={pp:.4f}")
    print()
