"""Is the INJECTED knowledge useful? Pair nomem vs withmem at the SAME step and
classify memory's causal effect, then check whether the injected fact was even
relevant to the gold element. Usage: python scripts/debug_utility.py <run_dir>"""
import json
import re
import sys
from collections import Counter

D = sys.argv[1]
events = [json.loads(x) for x in open(f"{D}/events.jsonl")]
tep = [e for e in events if e.get("kind") == "test_episode"]
wm = {e["task"]: e for e in tep if e.get("tag") == "withmem"}
nm = {e["task"]: e for e in tep if e.get("tag") == "nomem"}
common = set(wm) & set(nm)


def label_of(act_repr: str) -> str:
    m = re.search(r"\]\s*(.*?)\s*->", act_repr or "")
    return (m.group(1) or "").strip().lower()


def fact_mentions_label(facts, label):
    if len(label) < 4:
        return None  # label too generic to judge
    return any(label in (f or "").lower() for f in facts)


helped = hurt = same_ok = same_bad = 0
relevant_present = relevant_judgeable = 0
hurt_examples, helped_examples = [], []
# when memory is injected, is the RIGHT fact (mentions gold element) present?
for t in common:
    ws, ns = wm[t].get("steps", []), nm[t].get("steps", [])
    for i in range(min(len(ws), len(ns))):
        w, n = ws[i], ns[i]
        if not w.get("solvable"):
            continue
        we, ne = w.get("elem", 0), n.get("elem", 0)
        facts = w.get("facts", [])
        label = label_of(w.get("act_repr", ""))
        rel = fact_mentions_label(facts, label)
        if rel is not None:
            relevant_judgeable += 1
            if rel:
                relevant_present += 1
        if we and not ne:
            helped += 1
            if rel:
                helped_examples.append((t, label, w))
        elif ne and not we:
            hurt += 1
            hurt_examples.append((t, label, rel, w))
        elif we and ne:
            same_ok += 1
        else:
            same_bad += 1

tot = helped + hurt + same_ok + same_bad
print(f"=== STEP-LEVEL CAUSAL EFFECT OF MEMORY (paired nomem vs withmem, {tot} solvable steps) ===")
print(f"  helped (wrong->right): {helped}")
print(f"  hurt   (right->wrong): {hurt}")
print(f"  same, both right:      {same_ok}")
print(f"  same, both wrong:      {same_bad}")
print(f"  NET element-acc steps from memory: {helped - hurt:+d}")

print(f"\n=== IS THE USEFUL FACT EVEN RETRIEVED? ===")
print(f"  steps where a judgeable gold-label exists: {relevant_judgeable}")
print(f"  ...of those, an injected fact MENTIONS the gold element: {relevant_present} "
      f"({100*relevant_present//max(relevant_judgeable,1)}%)")
print(f"  -> {relevant_judgeable - relevant_present} steps: gold element NOT covered by any injected fact (noise only)")

print(f"\n--- HURT steps: was the injected fact relevant to the gold element? ---")
hr = Counter(rel for _, _, rel, _ in hurt_examples)
print(f"  hurt with RELEVANT fact present: {hr.get(True,0)} | with only IRRELEVANT facts: {hr.get(False,0)} | label too generic: {hr.get(None,0)}")
for t, label, rel, w in hurt_examples[:5]:
    print(f"\n  [{t[:55]}] gold='{label}' pred={w.get('pred')}  (relevant_fact_present={rel})")
    for f in w.get("facts", [])[:3]:
        print(f"     injected: {f[:110]}")

print(f"\n--- HELPED steps (memory fixed it): sample ---")
for t, label, w in helped_examples[:3]:
    print(f"  [{t[:55]}] gold='{label}' -> pred={w.get('pred')} OK")
    for f in w.get("facts", [])[:2]:
        print(f"     injected: {f[:110]}")
