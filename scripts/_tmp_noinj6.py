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
        return "no-reference(url/program_html)"
    if isinstance(r, dict) and list(r) == ["fuzzy_match"] and r["fuzzy_match"] == "N/A":
        return "NA-lottery"
    if isinstance(r, dict) and "fuzzy_match" in r:
        return "fuzzy"
    return "exact/must_include"

for key, (run, site) in RUNS.items():
    cfg = load_config(["--wa.site", site, "--wa.task_filter", "readonly", "--wa.base_url", "http://x"])
    tk = {t["task_id"]: t for t in load_tasks(cfg)}
    ev = collections.defaultdict(list)
    for ln in open(f"runs/{run}/events.jsonl"):
        d = json.loads(ln)
        ev[d.get("kind")].append(d)
    inj = {d["task_id"] for d in ev["wa_episode_start"] if d["tag"] == "withmem" and d.get("mem_injected")}
    end = collections.defaultdict(dict)
    for d in ev["wa_episode_end"]:
        end[(d["tag"], d["task_id"])][d["rollout"]] = d
    ids = sorted({d["task_id"] for d in ev["wa_task"] if d["tag"] == "nomem"} &
                 {d["task_id"] for d in ev["wa_task"] if d["tag"] == "withmem"})
    rows = []
    for t in ids:
        a, b = end[("nomem", t)], end[("withmem", t)]
        sa = sum(bool(v["reward"]) for v in a.values()) / len(a)
        sb = sum(bool(v["reward"]) for v in b.values()) / len(b)
        rows.append(dict(t=t, d=sb - sa, sa=sa, sb=sb, noinj=t not in inj, cls=refclass(tk[t])))
    ni = [r for r in rows if r["noinj"]]
    print(f"=== {key}: no-inj n={len(ni)} delta={100*np.mean([r['d'] for r in ni]):+.2f}")
    byc = collections.defaultdict(list)
    for r in ni:
        byc[r["cls"]].append(r["d"])
    for c, v in sorted(byc.items(), key=lambda kv: np.sum(kv[1])):
        print(f"    {c:32s} n={len(v):3d} mean_d={100*np.mean(v):+7.2f}  contrib={100*np.sum(v)/len(ni):+6.2f} pts")
    clean = [r["d"] for r in ni if r["cls"] in ("exact/must_include",)]
    clean2 = [r["d"] for r in ni if r["cls"] in ("exact/must_include", "fuzzy")]
    print(f"    -> exact+must_include only:  n={len(clean):3d} delta={100*np.mean(clean):+.2f}")
    print(f"    -> excluding NA + no-ref:    n={len(clean2):3d} delta={100*np.mean(clean2):+.2f}")
    # same for all paired
    allc = collections.defaultdict(list)
    for r in rows:
        allc[r["cls"]].append(r["d"])
    print(f"    ALL paired n={len(rows)} delta={100*np.mean([r['d'] for r in rows]):+.2f}; "
          f"exact+must_include only n={sum(1 for r in rows if r['cls']=='exact/must_include')} "
          f"delta={100*np.mean([r['d'] for r in rows if r['cls']=='exact/must_include']):+.2f}")
    print()
