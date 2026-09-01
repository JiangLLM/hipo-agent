import json, collections, sys
RUN = sys.argv[2] if len(sys.argv) > 2 else "runs/wa_fleet_shopping_admin_readonly_20260808_130520_20260808_130530"
TID = int(sys.argv[1])
steps = collections.defaultdict(list)
ends = {}
for ln in open(f"{RUN}/events.jsonl"):
    d = json.loads(ln)
    if d.get("task_id") != TID:
        continue
    if d["kind"] == "wa_step":
        steps[(d["tag"], d["rollout"])].append(d)
    elif d["kind"] == "wa_episode_end":
        ends[(d["tag"], d["rollout"])] = d
for tag in ("nomem", "withmem"):
    print(f"--- {tag} ---")
    for r in range(8):
        k = (tag, r)
        if k not in ends:
            print(f"  r{r}: NO EPISODE_END")
            continue
        rw = [s["reward"] for s in steps[k]]
        errs = sum(1 for s in steps[k] if s["action_error"])
        e = ends[k]
        print(f"  r{r}: n_steps={e['n_steps']:2d} reward={e['reward']} act_err={errs:2d} "
              f"rewardtrace={''.join(str(x) for x in rw)}  ans={e['stop_answer'][:70]!r}")
