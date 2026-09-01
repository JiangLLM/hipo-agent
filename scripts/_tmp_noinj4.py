import json, collections, datetime
import numpy as np

RUN = "wa_fleet_shopping_admin_readonly_20260808_130520_20260808_130530"
GL_START = datetime.datetime(2026, 8, 8, 13, 22, 10).timestamp()
GL_END = datetime.datetime(2026, 8, 8, 15, 32, 0).timestamp()

def load(run):
    ev = collections.defaultdict(list)
    for ln in open(f"runs/{run}/events.jsonl"):
        try:
            d = json.loads(ln)
        except Exception:
            continue
        ev[d.get("kind")].append(d)
    return ev

def ts(x):
    return datetime.datetime.fromtimestamp(x).strftime("%H:%M:%S")

ev = load(RUN)
inj = {d["task_id"] for d in ev["wa_episode_start"] if d["tag"] == "withmem" and d.get("mem_injected")}
end = collections.defaultdict(dict)
for d in ev["wa_episode_end"]:
    end[(d["tag"], d["task_id"])][d["rollout"]] = d
start = {}
for d in ev["wa_episode_start"]:
    start.setdefault((d["tag"], d["task_id"]), d["t"])
wtask = {(d["tag"], d["task_id"]): d for d in ev["wa_task"]}
errs = collections.Counter()
for d in ev["wa_episode_error"]:
    errs[(d["tag"], d["task_id"])] += 1
steps = collections.Counter()
for d in ev["wa_step"]:
    steps[(d["tag"], d["task_id"])] += 1

rows = []
for t in sorted({tid for (tg, tid) in wtask if tg == "nomem"}):
    a, b = end[("nomem", t)], end[("withmem", t)]
    sa = sum(bool(v["reward"]) for v in a.values()) / len(a)
    sb = sum(bool(v["reward"]) for v in b.values()) / len(b)
    t0a, t0b = start[("nomem", t)], start[("withmem", t)]
    wall_a = wtask[("nomem", t)]["t"] - t0a
    wall_b = wtask[("withmem", t)]["t"] - t0b
    rows.append(dict(t=t, sa=sa, sb=sb, d=sb - sa, na=len(a), nb=len(b),
                     t0a=t0a, t0b=t0b, wa=wall_a, wb=wall_b,
                     stepsa=steps[("nomem", t)] / max(len(a), 1),
                     stepsb=steps[("withmem", t)] / max(len(b), 1),
                     erra=errs[("nomem", t)], errb=errs[("withmem", t)],
                     noinj=t not in inj,
                     tmpl=wtask[("nomem", t)]["template_id"]))

ni = [r for r in rows if r["noinj"]]
print(f"no-injection tasks: {len(ni)}  delta={100*np.mean([r['d'] for r in ni]):+.2f}")
print(f"  tasks with d<0: {sum(1 for r in ni if r['d']<0)}  d>0: {sum(1 for r in ni if r['d']>0)} d==0: {sum(1 for r in ni if r['d']==0)}")
print("\nBIGGEST MOVERS (no-injection, |d|>0), sorted by d:")
print(f"{'task':>5} {'tmpl':>5} {'nomem':>10} {'withmem':>10} {'d':>7}  {'nomem_start':>11} {'overlap?':>9} {'wall_n':>7} {'wall_w':>7} {'stp_n':>6} {'stp_w':>6} {'err_n':>5} {'err_w':>5}")
for r in sorted(ni, key=lambda r: r["d"]):
    if r["d"] == 0:
        continue
    ov = "OVERLAP" if GL_START <= r["t0a"] <= GL_END else ("pre" if r["t0a"] < GL_START else "post")
    print(f"{r['t']:>5} {r['tmpl']:>5} {r['sa']*r['na']:.0f}/{r['na']:<8} {r['sb']*r['nb']:.0f}/{r['nb']:<8} "
          f"{100*r['d']:+7.1f}  {ts(r['t0a']):>11} {ov:>9} {r['wa']:7.0f} {r['wb']:7.0f} {r['stepsa']:6.1f} {r['stepsb']:6.1f} {r['erra']:5d} {r['errb']:5d}")

# cumulative contribution
srt = sorted(ni, key=lambda r: r["d"])
tot = sum(r["d"] for r in ni)
run = 0
for i, r in enumerate(srt):
    run += r["d"]
    if r["d"] < 0:
        print(f"  cum after {i+1} worst tasks: {100*run/len(ni):+.2f} pts of {100*tot/len(ni):+.2f}")

print("\n--- BUCKET BY NOMEM WALL CLOCK vs gitlab window ---")
for label, pred in [("pre  (<13:22)", lambda r: r["t0a"] < GL_START),
                    ("OVERLAP 13:22-15:32", lambda r: GL_START <= r["t0a"] <= GL_END),
                    ("post (>15:32)", lambda r: r["t0a"] > GL_END)]:
    for sub, name in [(ni, "no-inj"), (rows, "all")]:
        g = [r for r in sub if pred(r)]
        if not g:
            print(f"  {label:22} {name:7} n=0")
            continue
        print(f"  {label:22} {name:7} n={len(g):3d}  nomem={np.mean([r['sa'] for r in g]):.3f} "
              f"withmem={np.mean([r['sb'] for r in g]):.3f} delta={100*np.mean([r['d'] for r in g]):+6.2f}  "
              f"wall_n={np.mean([r['wa'] for r in g]):6.1f}s wall_w={np.mean([r['wb'] for r in g]):6.1f}s "
              f"steps_n={np.mean([r['stepsa'] for r in g]):5.2f} steps_w={np.mean([r['stepsb'] for r in g]):5.2f} "
              f"err_n={sum(r['erra'] for r in g):3d} err_w={sum(r['errb'] for r in g):3d} "
              f"drop_n={sum(8-r['na'] for r in g):3d} drop_w={sum(8-r['nb'] for r in g):3d}")
    print()
