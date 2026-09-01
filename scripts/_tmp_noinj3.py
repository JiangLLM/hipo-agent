import json, collections, datetime
import numpy as np

RUN = "wa_fleet_shopping_admin_readonly_20260808_130520_20260808_130530"
GL = "wa_fleet_gitlab_readonly_20260808_132155_20260808_132210"

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
    return datetime.datetime.fromtimestamp(x).strftime("%m-%d %H:%M:%S")

ev = load(RUN)
gl = load(GL)
gl_t = [d["t"] for k in gl for d in gl[k] if "t" in d]
print("gitlab run window:", ts(min(gl_t)), "->", ts(max(gl_t)))
sa_t = [d["t"] for k in ev for d in ev[k] if "t" in d]
print("sa2 run window   :", ts(min(sa_t)), "->", ts(max(sa_t)))

# arm windows
for tag in ("nomem", "withmem"):
    tt = [d["t"] for d in ev["wa_task"] if d["tag"] == tag]
    print(f"  {tag}: wa_task from {ts(min(tt))} to {ts(max(tt))}  ({len(tt)} tasks)")
