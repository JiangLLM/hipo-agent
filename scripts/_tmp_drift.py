import json, sys, collections, datetime
import numpy as np
sys.path.insert(0, "src")
from hippo.config import load_config
from hippo.wa.data import load_tasks

RUN = "wa_fleet_shopping_admin_readonly_20260808_130520_20260808_130530"
cfg = load_config(["--wa.site", "shopping_admin", "--wa.task_filter", "readonly", "--wa.base_url", "http://x"])
tk = {t["task_id"]: t for t in load_tasks(cfg)}
man = {r["task_id"]: r for r in json.load(open("config/wa_task_class.json"))["tasks"]}
ev = collections.defaultdict(list)
for ln in open(f"runs/{RUN}/events.jsonl"):
    d = json.loads(ln)
    ev[d.get("kind")].append(d)
end = collections.defaultdict(dict)
for d in ev["wa_episode_end"]:
    end[(d["tag"], d["task_id"])][d["rollout"]] = d
inj = {d["task_id"] for d in ev["wa_episode_start"] if d["tag"] == "withmem" and d.get("mem_injected")}
ids = sorted({t for (tg, t) in end if tg == "nomem"})

def norm(s):
    return " ".join(str(s).split()).lower().strip(" .!?")

print("--- consensus-answer drift scan (no-injection tasks only) ---")
print("  a task is flagged when each arm has a >=6/8 majority answer and the two majorities differ")
flag = 0
for t in ids:
    if t in inj:
        continue
    ca = collections.Counter(norm(v["stop_answer"]) for v in end[("nomem", t)].values() if v["stop_answer"])
    cb = collections.Counter(norm(v["stop_answer"]) for v in end[("withmem", t)].values() if v["stop_answer"])
    if not ca or not cb:
        continue
    (ma, na_), (mb, nb_) = ca.most_common(1)[0], cb.most_common(1)[0]
    if na_ >= 6 and nb_ >= 6 and ma != mb:
        flag += 1
        print(f"  t{t}: nomem {na_}x {ma[:60]!r}   withmem {nb_}x {mb[:60]!r}")
print(f"  flagged: {flag}")

print("\n--- read-only classification of the 109 ---")
print("  mutating flagged:", [t for t in ids if man[t]["mutating"]])
dis = [t for t in ids if man[t].get("heuristic") != man[t].get("llm")]
print("  heuristic/llm disagreement:", dis)
for t in dis:
    a, b = end[("nomem", t)], end[("withmem", t)]
    sa = sum(bool(v["reward"]) for v in a.values()) / len(a)
    sb = sum(bool(v["reward"]) for v in b.values()) / len(b)
    print(f"    t{t} tmpl={tk[t]['template_id']} noinj={t not in inj} d={100*(sb-sa):+6.1f}  "
          f"{tk[t]['intent'][:70]}")

print("\n--- effect of dropped (crashed) rollouts on the delta ---")
for name, S in [("ALL", ids), ("no-inj", [t for t in ids if t not in inj])]:
    d_corr, d_zero = [], []
    for t in S:
        a, b = end[("nomem", t)], end[("withmem", t)]
        na, nb = len(a), len(b)
        ka = sum(bool(v["reward"]) for v in a.values())
        kb = sum(bool(v["reward"]) for v in b.values())
        d_corr.append(kb / nb - ka / na)
        d_zero.append(kb / 8 - ka / 8)
    print(f"  {name:8s} n={len(S):3d} corrected(drop)={100*np.mean(d_corr):+6.2f}  "
          f"old(err=0)={100*np.mean(d_zero):+6.2f}  shift={100*(np.mean(d_corr)-np.mean(d_zero)):+.2f}")
