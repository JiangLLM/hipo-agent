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

def refclass(t):
    r = t.get("reference")
    if not r:
        return "no-ref"
    if isinstance(r, dict) and list(r) == ["fuzzy_match"] and r["fuzzy_match"] == "N/A":
        return "NA"
    if isinstance(r, dict) and "fuzzy_match" in r:
        return "fuzzy"
    return "exact"

def ts(x):
    return datetime.datetime.fromtimestamp(x).strftime("%m-%d %H:%M")

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
    nsteps = collections.defaultdict(int)
    for d in ev["wa_step"]:
        nsteps[(d["tag"], d["task_id"])] += 1
    print(f"===== {key} =====")
    # N/A lottery: per-step hit rate by arm
    for cls in ("NA",):
        for tag in ("nomem", "withmem"):
            hits = tot = 0
            tids = [t for t in tk if refclass(tk[t]) == cls and (tag, t) in end]
            for t in tids:
                for r, e in end[(tag, t)].items():
                    tot += e["n_steps"]
                    hits += bool(e["reward"])
            if tot:
                print(f"  NA-lottery {tag:8s}: tasks={len(tids):2d} rollouts_steps={tot:5d} wins={hits:3d} "
                      f"per-step hit rate={hits/tot:.4f}")
    # per-class paired delta (all tasks, not just no-inj)
    inj = {d["task_id"] for d in ev["wa_episode_start"] if d["tag"] == "withmem" and d.get("mem_injected")}
    ids = sorted({t for (tg, t) in end if tg == "nomem"} & {t for (tg, t) in end if tg == "withmem"})
    byc = collections.defaultdict(list)
    for t in ids:
        a, b = end[("nomem", t)], end[("withmem", t)]
        d = sum(bool(v["reward"]) for v in b.values())/len(b) - sum(bool(v["reward"]) for v in a.values())/len(a)
        byc[refclass(tk[t])].append((t, d, t not in inj))
    for c, v in byc.items():
        dd = [x[1] for x in v]
        ni = [x[1] for x in v if x[2]]
        print(f"  class {c:7s} n={len(v):3d} delta={100*np.mean(dd):+6.2f}  "
              f"contrib_to_overall={100*np.sum(dd)/len(ids):+6.2f}pts | no-inj n={len(ni):3d} "
              f"delta={100*np.mean(ni) if ni else 0:+6.2f} contrib={100*np.sum(ni)/max(sum(1 for x in v if x[2]) or 1,1) if ni else 0:+6.2f}")
    print()
