"""Attribute the failure to Layer-1 / Layer-2 / downstream (retrieval-injection).
Usage: python scripts/attribute_layers.py <run_dir>"""
import json
import re
import sys

D = sys.argv[1]
ev = [json.loads(x) for x in open(f"{D}/events.jsonl")]


def of(k):
    return [e for e in ev if e.get("kind") == k]


NEG = re.compile(r"instead of|rather than|avoid|not the right|do not|don't", re.I)
LEAK = re.compile(r"coffee|maker|loungewear|swimsuit|drone|playstation|spider|prometheus", re.I)


def quality(facts, name):
    n = len(facts) or 1
    neg = sum(1 for f in facts if NEG.search(f))
    leak = sum(1 for f in facts if LEAK.search(f))
    print(f"\n[{name}]  n={len(facts)}")
    print(f"  negative/avoidance rules : {neg} ({100*neg//n}%)")
    print(f"  literal task-value leak  : {leak} ({100*leak//n}%)")
    for f in facts[:4]:
        print(f"    • {f[:150]}")
    return set(f[:80] for f in facts)


# --- per-layer extracted content ---
l1 = [e["item"]["statement"] for e in of("step_write_l1") if e.get("item")]
l2 = [it["statement"] for e in of("step_write_l2") for it in e.get("items", [])]
print("=== EXTRACTION QUALITY BY LAYER ===")
l1set = quality(l1, "LAYER 1  (per-attempt judge_step)")
l2set = quality(l2, "LAYER 2  (cross-N extract_step_experiences)")

# --- downstream: what got injected, and on the HURT steps which layer's facts? ---
tep = of("test_episode")
wm = {e["task"]: e for e in tep if e.get("tag") == "withmem"}
nm = {e["task"]: e for e in tep if e.get("tag") == "nomem"}


def src(stmt):
    p = stmt[:80]
    if p in l1set and p in l2set: return "both"
    if p in l1set: return "L1"
    if p in l2set: return "L2"
    return "?"


inj_total = inj_l1 = inj_l2 = inj_unk = 0
hurt_steps = []
for t in set(wm) & set(nm):
    ws, ns = wm[t]["steps"], nm[t]["steps"]
    for i in range(min(len(ws), len(ns))):
        w, n = ws[i], ns[i]
        if not w.get("solvable"):
            continue
        for f in w.get("facts", []):
            inj_total += 1
            s = src(f)
            inj_l1 += s in ("L1", "both")
            inj_l2 += s in ("L2", "both")
            inj_unk += s == "?"
        if n.get("elem") and not w.get("elem"):   # memory turned a right step wrong
            hurt_steps.append((t, w))

print("\n=== DOWNSTREAM: injected facts provenance ===")
print(f"  injected fact instances at test: {inj_total}")
print(f"  from L1: {inj_l1} | from L2: {inj_l2} | unmatched: {inj_unk}")

print("\n=== ON HURT STEPS: which layer's facts were present? ===")
for t, w in hurt_steps[:6]:
    tags = [src(f) for f in w.get("facts", [])]
    from collections import Counter
    print(f"  gold='{(w.get('act_repr') or '')[:40]}' pred={w.get('pred')}  injected-from={dict(Counter(tags))}")
