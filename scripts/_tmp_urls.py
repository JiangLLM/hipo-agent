import json, collections, sys
RUN = "runs/wa_fleet_shopping_admin_readonly_20260808_130520_20260808_130530"
TID = int(sys.argv[1])
NR = int(sys.argv[2]) if len(sys.argv) > 2 else 2
steps = collections.defaultdict(list)
for ln in open(f"{RUN}/events.jsonl"):
    d = json.loads(ln)
    if d.get("task_id") == TID and d["kind"] == "wa_step":
        steps[(d["tag"], d["rollout"])].append(d)
for tag in ("nomem", "withmem"):
    for r in range(NR):
        print(f"--- {tag} r{r}")
        for s in steps[(tag, r)]:
            print(f"  [{s['step']:2d}] rw={s['reward']} act={s['action'][:90]!r}")
            print(f"        url={s['url'][:150]}")
