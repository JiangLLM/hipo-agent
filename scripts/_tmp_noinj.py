import json, sys, collections, datetime, statistics
import numpy as np

def load(run):
    ev = collections.defaultdict(list)
    for ln in open(f"runs/{run}/events.jsonl"):
        try:
            d = json.loads(ln)
        except Exception:
            continue
        ev[d.get("kind")].append(d)
    return ev

def tasks(ev):
    out = {}
    for d in ev["wa_task"]:
        out.setdefault(d["tag"], {})[d["task_id"]] = d
    return out

def noinj(ev):
    """tasks where the withmem arm injected nothing"""
    s = set()
    for d in ev["wa_episode_start"]:
        if d["tag"] == "withmem" and d.get("mem_injected"):
            s.add(d["task_id"])
    allt = {d["task_id"] for d in ev["wa_task"] if d["tag"] == "withmem"}
    return allt - s, allt

def ts(x):
    return datetime.datetime.fromtimestamp(x).strftime("%m-%d %H:%M:%S")

RUNS = {
 "sa2": "wa_fleet_shopping_admin_readonly_20260808_130520_20260808_130530",
 "sa1": "wa_fleet_shopping_admin_readonly_20260807_225320_20260807_225403",
 "sh3": "wa_fleet_shopping_readonly_20260806_223937_20260806_224018",
}

for key, run in RUNS.items():
    ev = load(run)
    T = tasks(ev)
    ni, allt = noinj(ev)
    paired = sorted(set(T["nomem"]) & set(T["withmem"]))
    def sr(tag, tid):
        d = T[tag][tid]; return d["nc"] / d["n"]
    d_all = [sr("withmem", t) - sr("nomem", t) for t in paired]
    d_ni = [sr("withmem", t) - sr("nomem", t) for t in paired if t in ni]
    d_inj = [sr("withmem", t) - sr("nomem", t) for t in paired if t not in ni]
    print(f"=== {key} {run}")
    print(f"  paired={len(paired)}  nomem={np.mean([sr('nomem',t) for t in paired]):.4f} "
          f"withmem={np.mean([sr('withmem',t) for t in paired]):.4f} delta={100*np.mean(d_all):+.2f}")
    print(f"  no-injection n={len(d_ni)} delta={100*np.mean(d_ni):+.2f}   injected n={len(d_inj)} delta={100*np.mean(d_inj):+.2f}")
    # bootstrap CI on no-injection delta
    rng = np.random.default_rng(0)
    arr = np.array(d_ni)
    bs = rng.choice(arr, size=(20000, len(arr)), replace=True).mean(axis=1)
    lo, hi = np.percentile(bs, [2.5, 97.5])
    print(f"  no-inj bootstrap 95% CI: [{100*lo:+.2f}, {100*hi:+.2f}]  p(<0)={np.mean(bs<0):.3f}")
    arr2 = np.array(d_all)
    bs2 = rng.choice(arr2, size=(20000, len(arr2)), replace=True).mean(axis=1)
    lo2, hi2 = np.percentile(bs2, [2.5, 97.5])
    print(f"  overall bootstrap 95% CI: [{100*lo2:+.2f}, {100*hi2:+.2f}]")
    print()
