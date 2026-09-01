import json, sys, collections, datetime
import numpy as np
sys.path.insert(0, "src")
from hippo.config import load_config
from hippo.wa.data import load_tasks

GL_S = datetime.datetime(2026, 8, 8, 13, 22, 10).timestamp()
GL_E = datetime.datetime(2026, 8, 8, 15, 32, 0).timestamp()
RUNS = {
 "sa2": ("wa_fleet_shopping_admin_readonly_20260808_130520_20260808_130530", "shopping_admin"),
 "sa1": ("wa_fleet_shopping_admin_readonly_20260807_225320_20260807_225403", "shopping_admin"),
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
    estart = {}
    for d in ev["wa_episode_start"]:
        estart.setdefault((d["tag"], d["task_id"]), d["t"])
    inj = {d["task_id"] for d in ev["wa_episode_start"] if d["tag"] == "withmem" and d.get("mem_injected")}
    run_t0 = ev["run_start"][0]["t"]
    ex = {}
    for tag in ("nomem", "withmem"):
        seq = sorted([d for d in ev["wa_task"] if d["tag"] == tag], key=lambda d: d["t"])
        prev = run_t0 if tag == "nomem" else max(d["t"] for d in ev["wa_task"] if d["tag"] == "nomem")
        for d in seq:
            ex[(tag, d["task_id"])] = (prev, estart[(tag, d["task_id"])] - prev)
            prev = d["t"]
    ids = sorted({t for (tg, t) in end if tg == "nomem"} & {t for (tg, t) in end if tg == "withmem"})
    ni = [t for t in ids if t not in inj]

    def delta(S):
        return 100 * np.mean([sum(bool(v['reward']) for v in end[('withmem', t)].values()) / len(end[('withmem', t)])
                              - sum(bool(v['reward']) for v in end[('nomem', t)].values()) / len(end[('nomem', t)])
                              for t in S]) if S else 0.0
    dropped = {t for t in ids if len(end[("nomem", t)]) < 8 or len(end[("withmem", t)]) < 8}
    print(f"===== {key}: nested removal on the no-injection control =====")
    S = list(ni); print(f"  all no-injection                        n={len(S):3d}  {delta(S):+6.2f}")
    S = [t for t in S if rc(tk[t]) != "NA"]; print(f"  - drop fuzzy_match:'N/A' lottery tasks  n={len(S):3d}  {delta(S):+6.2f}")
    S = [t for t in S if rc(tk[t]) != "no-ref"]; print(f"  - also drop url_match/program_html      n={len(S):3d}  {delta(S):+6.2f}")
    S = [t for t in S if t not in dropped]; print(f"  - also drop tasks with a crashed rollout n={len(S):3d}  {delta(S):+6.2f}")

    if key == "sa2":
        print("  time buckets (nomem exec start vs gitlab 13:22-15:32):")
        for bk, pred in [("pre", lambda t: ex[("nomem", t)][0] < GL_S),
                         ("overlap", lambda t: GL_S <= ex[("nomem", t)][0] <= GL_E),
                         ("post", lambda t: ex[("nomem", t)][0] > GL_E)]:
            g = [t for t in ni if pred(t)]
            gc = [t for t in g if rc(tk[t]) in ("exact", "fuzzy")]
            wn = np.mean([ex[("nomem", t)][1] for t in g]) if g else 0
            ww = np.mean([ex[("withmem", t)][1] for t in g]) if g else 0
            sn = np.mean([np.mean([v["n_steps"] for v in end[("nomem", t)].values()]) for t in g]) if g else 0
            sw = np.mean([np.mean([v["n_steps"] for v in end[("withmem", t)].values()]) for t in g]) if g else 0
            print(f"    {bk:8s} n={len(g):3d} d={delta(g):+6.2f} | clean n={len(gc):3d} d={delta(gc):+6.2f} | "
                  f"sec/task nomem={wn:6.1f} withmem={ww:6.1f} | steps nomem={sn:5.2f} withmem={sw:5.2f} | "
                  f"crashes nomem={sum(8-len(end[('nomem',t)]) for t in g)} withmem={sum(8-len(end[('withmem',t)]) for t in g)}")
    else:
        seqn = sorted(ni, key=lambda t: ex[("nomem", t)][0])
        third = len(seqn) // 3
        for i, lbl in enumerate(("first", "middle", "last")):
            g = seqn[i * third:(i + 1) * third if i < 2 else len(seqn)]
            gc = [t for t in g if rc(tk[t]) in ("exact", "fuzzy")]
            print(f"    {lbl:8s} n={len(g):3d} d={delta(g):+6.2f} | clean n={len(gc):3d} d={delta(gc):+6.2f} | "
                  f"sec/task nomem={np.mean([ex[('nomem',t)][1] for t in g]):6.1f} "
                  f"withmem={np.mean([ex[('withmem',t)][1] for t in g]):6.1f} | "
                  f"crashes nomem={sum(8-len(end[('nomem',t)]) for t in g)} withmem={sum(8-len(end[('withmem',t)]) for t in g)}")
    # paired wall time nomem vs withmem, all tasks
    print(f"  paired sec/task over all {len(ids)} tasks: nomem={np.mean([ex[('nomem',t)][1] for t in ids]):.1f} "
          f"withmem={np.mean([ex[('withmem',t)][1] for t in ids]):.1f}")
    print()
