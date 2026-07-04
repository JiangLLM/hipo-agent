"""Dump raw extracted facts + per-step injected facts (nomem vs withmem) for a run."""
import json
import sys
from collections import defaultdict

D = sys.argv[1]
ev = [json.loads(x) for x in open(f"{D}/events.jsonl")]

# ---- 1. extracted facts per site (FULL text) ----
facts = defaultdict(list)
for e in ev:
    if e["kind"] == "step_write_l1":
        facts[e["item"]["scope"]].append(("L1", e["item"]["statement"]))
    elif e["kind"] == "step_write_l2":
        for it in e["items"]:
            facts[it["scope"]].append(("L2", it["statement"]))

print("=" * 80)
print("EXTRACTED FACTS BY SITE")
for site, fs in facts.items():
    print(f"\n## {site}  ({len(fs)} facts)")
    for tag, s in fs:
        print(f"  [{tag}] {s}")

# ---- 2. per test episode: nomem vs withmem, step by step ----
def by_task(tag):
    return {e["task"]: e for e in ev if e["kind"] == "test_episode" and e.get("tag") == tag}

nm, wm = by_task("nomem"), by_task("withmem")
print("\n" + "=" * 80)
print("TEST EPISODES — nomem vs withmem (per step, with injected facts)")
for task, we in wm.items():
    ne = nm.get(task, {})
    nsteps, osteps = we.get("steps", []), ne.get("steps", [])
    wss = we.get("step_success"); nss = ne.get("step_success")
    print(f"\n===== [{we['scope']}]  ss {nss} -> {wss}")
    print(f"      task: {task[:100]}")
    for i, s in enumerate(nsteps):
        if not s.get("solvable", True):
            continue
        o = osteps[i] if i < len(osteps) else {}
        flag = ""
        if o.get("elem") == 1 and s.get("elem") == 0:
            flag = "  <-- REGRESSED (nomem right, withmem wrong)"
        elif o.get("elem") == 0 and s.get("elem") == 1:
            flag = "  <-- fixed"
        print(f"  step{i}: gold={s.get('gold')}{flag}")
        print(f"     nomem  : pred={o.get('pred')} elem={o.get('elem')}")
        print(f"     withmem: pred={s.get('pred')} elem={s.get('elem')}")
        for fct in s.get("facts", []):
            print(f"       inj: {fct}")
