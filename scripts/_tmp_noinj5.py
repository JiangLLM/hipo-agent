import json, sys, collections
sys.path.insert(0, "src")
from hippo.config import load_config
from hippo.wa.data import load_tasks

cfg = load_config(["--wa.site", "shopping_admin", "--wa.task_filter", "readonly",
                   "--wa.base_url", "http://x"])
tk = {t["task_id"]: t for t in load_tasks(cfg)}
man = json.load(open("config/wa_task_class.json"))
mrows = {r["task_id"]: r for r in man["tasks"]}
dis = {d if isinstance(d, int) else d.get("task_id"): d for d in man.get("disagreements", [])}

RUN = "runs/wa_fleet_shopping_admin_readonly_20260808_130520_20260808_130530"
ev = collections.defaultdict(list)
for ln in open(f"{RUN}/events.jsonl"):
    d = json.loads(ln)
    ev[d.get("kind")].append(d)
ids = sorted({d["task_id"] for d in ev["wa_task"] if d["tag"] == "nomem"})
print("n tasks:", len(ids), " all in manifest:", all(i in mrows for i in ids))
print("mutating flagged:", [i for i in ids if mrows[i]["mutating"]])
print("heuristic-vs-llm disagreement among the 109:",
      [i for i in ids if mrows[i].get("heuristic") != mrows[i].get("llm")])
print("disagreements list len:", len(man.get("disagreements", [])),
      " overlap with our 109:", [i for i in ids if i in dis])

MOV = [183, 706, 201, 1, 62, 193, 707, 289, 6, 112, 213]
for i in MOV:
    r = mrows[i]
    print(f"\nt{i} tmpl={tk[i]['template_id']} evals={tk[i]['eval_types']}")
    print("   intent:", tk[i]["intent"])
    print("   ref   :", tk[i]["reference"])
    print("   class :", r["mutating"], "|", r.get("why", "")[:150])
