import json, sys, collections, datetime
import numpy as np
sys.path.insert(0, "src")
from hippo.config import load_config
from hippo.wa.data import load_tasks

RUN = "wa_fleet_shopping_admin_readonly_20260808_130520_20260808_130530"
GL_S = datetime.datetime(2026, 8, 8, 13, 22, 10).timestamp()
GL_E = datetime.datetime(2026, 8, 8, 15, 32, 0).timestamp()

def refclass(t):
    r = t.get("reference")
    if not r:
        return "no-ref"
    if isinstance(r, dict) and list(r) == ["fuzzy_match"] and r["fuzzy_match"] == "N/A":
        return "NA"
    if isinstance(r, dict) and "fuzzy_match" in r:
        return "fuzzy"
    return "exact"

cfg = load_config(["--wa.site", "shopping_admin", "--wa.task_filter", "readonly", "--wa.base_url", "http://x"])
tk = {t["task_id"]: t for t in load_tasks(cfg)}
ev = collections.defaultdict(list)
for ln in open(f"runs/{RUN}/events.jsonl"):
    d = json.loads(ln)
    ev[d.get("kind")].append(d)

end = collections.defaultdict(dict)
for d in ev["wa_episode_end"]:
    end[(d["tag"], d["task_id"])][d["rollout"]] = d
estart = {}
for d in ev["wa_episode_start"]:
    estart.setdefault((d["tag"], d["task_id"]), d["t"])
wt = {(d["tag"], d["task_id"]): d for d in ev["wa_task"]}
inj = {d["task_id"] for d in ev["wa_episode_start"] if d["tag"] == "withmem" and d.get("mem_injected")}
errs = collections.Counter()
for d in ev["wa_episode_error"]:
    errs[(d["tag"], d["task_id"])] += 1
run_t0 = ev["run_start"][0]["t"]

# exec window per (tag, task): from previous wa_task of same tag (or arm start) to episode_start
order = {}
for tag in ("nomem", "withmem"):
    seq = sorted([d for d in ev["wa_task"] if d["tag"] == tag], key=lambda d: d["t"])
    prev = run_t0 if tag == "nomem" else max(d["t"] for d in ev["wa_task"] if d["tag"] == "nomem")
    for i, d in enumerate(seq):
        order[(tag, d["task_id"])] = dict(idx=i, exec_start=prev, exec_end=estart[(tag, d["task_id"])])
        prev = d["t"]

rows = []
for t in sorted({tid for (tg, tid) in wt if tg == "nomem"}):
    a, b = end[("nomem", t)], end[("withmem", t)]
    rows.append(dict(
        t=t, cls=refclass(tk[t]), noinj=t not in inj,
        sa=sum(bool(v["reward"]) for v in a.values()) / len(a),
        sb=sum(bool(v["reward"]) for v in b.values()) / len(b),
        stepa=np.mean([v["n_steps"] for v in a.values()]),
        stepb=np.mean([v["n_steps"] for v in b.values()]),
        aea=np.mean([v["n_action_errors"] for v in a.values()]),
        aeb=np.mean([v["n_action_errors"] for v in b.values()]),
        dropa=8 - len(a), dropb=8 - len(b),
        erra=errs[("nomem", t)], errb=errs[("withmem", t)],
        exa=order[("nomem", t)]["exec_start"], exdur=order[("nomem", t)]["exec_end"] - order[("nomem", t)]["exec_start"],
        exdurb=order[("withmem", t)]["exec_end"] - order[("withmem", t)]["exec_start"]))
for r in rows:
    r["d"] = r["sb"] - r["sa"]

def bucket(r):
    return "pre" if r["exa"] < GL_S else ("overlap" if r["exa"] <= GL_E else "post")

print("nomem arm exec windows: first task starts", datetime.datetime.fromtimestamp(min(r['exa'] for r in rows)).strftime('%H:%M'),
      " last", datetime.datetime.fromtimestamp(max(r['exa'] for r in rows)).strftime('%H:%M'))
for name, sub in [("ALL", rows), ("no-inj", [r for r in rows if r["noinj"]]),
                  ("no-inj, drop NA+no-ref", [r for r in rows if r["noinj"] and r["cls"] in ("exact", "fuzzy")])]:
    print(f"\n### {name} (n={len(sub)})")
    print(f"{'bucket':9} {'n':>3} {'nomem':>6} {'withm':>6} {'delta':>7} | {'stp_n':>6} {'stp_w':>6} | {'aerr_n':>6} {'aerr_w':>6} | {'drop_n':>6} {'drop_w':>6} | {'sec/task_n':>10}")
    for bk in ("pre", "overlap", "post"):
        g = [r for r in sub if bucket(r) == bk]
        if not g:
            print(f"{bk:9} n=0"); continue
        print(f"{bk:9} {len(g):3d} {np.mean([r['sa'] for r in g]):6.3f} {np.mean([r['sb'] for r in g]):6.3f} "
              f"{100*np.mean([r['d'] for r in g]):+7.2f} | {np.mean([r['stepa'] for r in g]):6.2f} {np.mean([r['stepb'] for r in g]):6.2f} | "
              f"{np.mean([r['aea'] for r in g]):6.2f} {np.mean([r['aeb'] for r in g]):6.2f} | "
              f"{sum(r['dropa'] for r in g):6d} {sum(r['dropb'] for r in g):6d} | {np.mean([r['exdur'] for r in g]):10.1f}")

print("\n--- nomem-arm-only contention signature (per 20-task block, exec order) ---")
srt = sorted(rows, key=lambda r: r["exa"])
for i in range(0, len(srt), 15):
    g = srt[i:i+15]
    print(f"  tasks {i:3d}-{i+len(g)-1:3d} start {datetime.datetime.fromtimestamp(g[0]['exa']).strftime('%H:%M')}"
          f"-{datetime.datetime.fromtimestamp(g[-1]['exa']).strftime('%H:%M')} "
          f"sec/task={np.mean([r['exdur'] for r in g]):6.1f} steps={np.mean([r['stepa'] for r in g]):5.2f} "
          f"act_err={np.mean([r['aea'] for r in g]):5.2f} dropped={sum(r['dropa'] for r in g):2d} "
          f"nomem_sr={np.mean([r['sa'] for r in g]):.3f}")
print("  (withmem arm, same task order)")
for i in range(0, len(srt), 15):
    g = srt[i:i+15]
    print(f"  tasks {i:3d}-{i+len(g)-1:3d} sec/task={np.mean([r['exdurb'] for r in g]):6.1f} "
          f"steps={np.mean([r['stepb'] for r in g]):5.2f} act_err={np.mean([r['aeb'] for r in g]):5.2f} "
          f"dropped={sum(r['dropb'] for r in g):2d} withmem_sr={np.mean([r['sb'] for r in g]):.3f}")
