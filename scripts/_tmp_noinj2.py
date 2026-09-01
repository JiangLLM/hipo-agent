import json, collections, datetime
import numpy as np

RUNS = {
 "sa2": "wa_fleet_shopping_admin_readonly_20260808_130520_20260808_130530",
 "sa1": "wa_fleet_shopping_admin_readonly_20260807_225320_20260807_225403",
 "sh3": "wa_fleet_shopping_readonly_20260806_223937_20260806_224018",
}

def load(run):
    ev = collections.defaultdict(list)
    for ln in open(f"runs/{run}/events.jsonl"):
        try:
            d = json.loads(ln)
        except Exception:
            continue
        ev[d.get("kind")].append(d)
    return ev

for key, run in RUNS.items():
    ev = load(run)
    # denominator from wa_episode_end directly
    end = collections.defaultdict(dict)   # (tag,tid) -> {rollout: reward}
    for d in ev["wa_episode_end"]:
        end[(d["tag"], d["task_id"])][d["rollout"]] = d["reward"]
    wt = {(d["tag"], d["task_id"]): d for d in ev["wa_task"]}
    inj = set()
    for d in ev["wa_episode_start"]:
        if d["tag"] == "withmem" and d.get("mem_injected"):
            inj.add(d["task_id"])
    tids = sorted({t for (tg, t) in wt if tg == "nomem"} & {t for (tg, t) in wt if tg == "withmem"})
    rows = []
    mism = 0
    for t in tids:
        a = end[("nomem", t)]; b = end[("withmem", t)]
        na, nb = len(a), len(b)
        sa = sum(bool(v) for v in a.values()) / max(na, 1)
        sb = sum(bool(v) for v in b.values()) / max(nb, 1)
        wa_, wb_ = wt[("nomem", t)], wt[("withmem", t)]
        if (na, nb) != (wa_["n"], wb_["n"]):
            mism += 1
        rows.append(dict(t=t, na=na, nb=nb, sa=sa, sb=sb, d=sb - sa,
                         wsa=wa_["nc"] / wa_["n"], wsb=wb_["nc"] / wb_["n"], noinj=t not in inj))
    d_all = np.array([r["d"] for r in rows])
    d_ni = np.array([r["d"] for r in rows if r["noinj"]])
    print(f"=== {key}  paired={len(rows)}  episode_end-denominator")
    print(f"    nomem={np.mean([r['sa'] for r in rows]):.4f} withmem={np.mean([r['sb'] for r in rows]):.4f} "
          f"delta={100*d_all.mean():+.2f}   (mismatch vs wa_task n: {mism} tasks)")
    print(f"    no-inj n={len(d_ni)} delta={100*d_ni.mean():+.2f}   nonzero-delta tasks: {int((d_ni!=0).sum())}")
