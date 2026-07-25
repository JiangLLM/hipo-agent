"""Deterministic per-task dossier for WebArena gitlab debug.

Usage: .venv-wa/bin/python scripts/dump_task_dossier.py <task_id> [run_dir] [nomem_json]

Prints, for ONE task, straight from the recorded run (no guessing):
  - intent + reference answer
  - every rollout's RAW stop_answer (untruncated) + reward + judge outcome + judge reason
  - the injected experience(s): title/layer/description/content (full) + the LOGGED cosine
  - the RECONSTRUCTED cosine candidate pool (what cosine saw at THIS task's retrieval moment:
    the L2 items written before it, scored against the task intent) — logged pool isn't stored,
    so this is reconstructed; the chosen item's reconstructed cosine should match the logged one
  - per-rollout step traces (thought/action/url/action_error), untruncated thought
"""
import sys, json, collections
import numpy as np

TID = int(sys.argv[1])
RUN = sys.argv[2] if len(sys.argv) > 2 else "runs/wa_gitlab_20260721_220729_20260721_220731"
NMF = sys.argv[3] if len(sys.argv) > 3 else "runs/wa_gitlab_20260720_020100_20260720_020102/rewards_nomem.json"
E = f"{RUN}/events.jsonl"
MF = f"{RUN}/memory.json"


def norm(s):
    return " ".join(str(s).split()).lower()


items = {x["title"]: x for x in json.load(open(MF)).get("reasoning", [])}
by_title = {norm(k): v for k, v in items.items()}
try:
    nm = json.load(open(NMF))
except Exception:
    nm = {}

steps = collections.defaultdict(list)
ans, rew, out, rea = {}, {}, {}, {}
retr_titles, retr_scores = None, None
written_before = []          # wa_write titles logged BEFORE this task's wa_retrieve
seen_retrieve = False
for ln in open(E):
    try:
        d = json.loads(ln)
    except Exception:
        continue
    k = d.get("kind")
    if k in ("wa_write_l1", "wa_write_l2") and not seen_retrieve:
        written_before.append((d["item"]["title"], d.get("task"), "L2" if k == "wa_write_l2" else "L1"))
    if k == "wa_retrieve" and d.get("task_id") == TID:
        seen_retrieve = True
        retr_titles, retr_scores = d.get("titles"), d.get("scores")
    if d.get("task_id") != TID:
        continue
    if k == "wa_step":
        steps[d["rollout"]].append(d)
    elif k == "wa_episode_end":
        ans[d["rollout"]] = d.get("stop_answer", "")
        rew[d["rollout"]] = d.get("reward")
    elif k == "wa_judge":
        out[d["rollout"]] = d.get("outcome")
        rea[d["rollout"]] = d.get("reason", "")

sys.path.insert(0, "src")
from hippo.config import load_config
from hippo.wa.data import load_tasks
import re as _re
_m = _re.search(r"wa_([a-z_]+?)_\d{8}", RUN)   # infer site from the run dir name
SITE = _m.group(1) if _m else "gitlab"
cfg = load_config(["--wa.site", SITE, "--wa.readonly_only", "true", "--wa.base_url", "http://x"])
tk = {t["task_id"]: t for t in load_tasks(cfg)}
intent = tk[TID]["intent"]
reference = tk[TID].get("reference")

print("=" * 80)
print(f"TASK {TID}   reward {sum(bool(v) for v in rew.values())}/{len(rew)}")
print("=" * 80)
print("INTENT   :", intent)
print("REFERENCE:", reference)
print("NOMEM(single-rollout 0/1):", nm.get(str(TID)))

print("\n----- RAW ANSWERS (untruncated) -----")
for r in sorted(ans):
    print(f"  rollout {r}: reward={rew.get(r)} outcome={out.get(r)}")
    print(f"     answer: {ans[r]!r}")
    print(f"     judge : {rea.get(r, '')}")

print("\n----- INJECTED EXPERIENCE (logged) -----")
if not retr_titles:
    print("  (none injected)")
for t, sc in zip(retr_titles or [], retr_scores or []):
    it = by_title.get(norm(t))
    print(f"  «{t}»  [logged cosine={sc}]")
    if it:
        print(f"     layer      : {it.get('layer')}")
        print(f"     description: {it.get('description')}")
        print(f"     content    : {it.get('content')}")

# reconstruct candidate pool: L2 items in the bank BEFORE this task, scored vs intent
print("\n----- COSINE CANDIDATE POOL (reconstructed; pool not logged) -----")
seen = set()
L2 = []
for t, wtk, ly in written_before:
    if t in seen:
        continue
    seen.add(t)
    if ly == "L2":
        L2.append((t, wtk))
if not L2:
    print("  (no L2 in bank yet at this task)")
else:
    from hippo.llm import LLMClient
    llm = LLMClient(model=cfg.llm.model, embed_model="local/BAAI/bge-small-en-v1.5")
    q = np.asarray(llm.embed([intent])[0], float)
    q /= np.linalg.norm(q) + 1e-9
    rows = []
    for title, wtk in L2:
        it = by_title.get(norm(title))
        if not it or it.get("embedding") is None:
            continue
        v = np.asarray(it["embedding"], float)
        v /= np.linalg.norm(v) + 1e-9
        rows.append((float(q @ v), title, wtk))
    rows.sort(reverse=True)
    chosen = set(norm(t) for t in (retr_titles or []))
    for i, (c, title, wtk) in enumerate(rows):
        mark = "  <== LLM-gate CHOSE this" if norm(title) in chosen else ""
        pool = " [in top-5 pool]" if i < 5 else ""
        print(f"  #{i+1} cos={c:.3f}  «{title}» (written by t{wtk}){pool}{mark}")

print("\n----- STEP TRACES (thought/action/url, untruncated thought) -----")
for r in sorted(steps):
    print(f"  ### rollout {r} (reward={rew.get(r)}, outcome={out.get(r)})")
    for d in steps[r]:
        print(f"    step{d.get('step')} url={d.get('url','')}")
        print(f"       thought: {d.get('thought')!r}")
        print(f"       action : {d.get('action')!r}")
        if d.get("action_error"):
            print(f"       action_error: {d.get('action_error')[:120]}")
        if d.get("raw") is not None:
            print(f"       raw: {d.get('raw')!r}")
