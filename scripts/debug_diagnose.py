"""Discriminate the failure mode: extraction vs injection vs generalization vs coverage/length.

For each solvable TEST step we ask three yes/no questions:
  A. learn_seen  : did this step's gold element appear in the LEARN phase (same site)?
  B. memory_has  : does the FULL site fact-store contain a fact naming this gold element?
  C. injected    : was such a fact actually injected at this step (in the retrieved top-k)?

Buckets:
  - NOT learn_seen                  -> COVERAGE/GENERALIZATION gap (test needs elements never learned)
  - learn_seen & NOT memory_has     -> EXTRACTION problem (saw it, but distilled no usable fact)
  - memory_has & NOT injected        -> INJECTION/RETRIEVAL problem (fact exists, not retrieved)
  - injected                         -> delivered; compare accuracy to see if the fact actually helps
Also reports site recurrence + steps/task to test the 'tasks too short / site doesn't recur' idea.
"""
import json
import re
import sys
from collections import defaultdict

D = sys.argv[1]
ev = [json.loads(x) for x in open(f"{D}/events.jsonl")]


def tokens(act_repr_or_gold):
    if not act_repr_or_gold:
        return []
    left = act_repr_or_gold.split("->")[0]
    left = re.sub(r"^\s*\[[^\]]*\]\s*", "", left)
    left = re.sub(r"^\s*(CLICK|TYPE|SELECT)\s*\[\d+\]", "", left)
    return [w for w in re.findall(r"[a-z0-9]+", left.lower()) if len(w) >= 4]


# ---- reconstruct the learned memory + the elements seen during LEARN, per site ----
mem_store = defaultdict(list)           # site -> [fact statements]
learn_label_text = defaultdict(str)     # site -> concatenated gold element labels seen in learn
for e in ev:
    if e["kind"] == "step_write_l1":
        site = e["item"]["scope"]
        mem_store[site].append(e["item"]["statement"].lower())
        learn_label_text[site] += " " + (e.get("gold") or "").lower()
    elif e["kind"] == "step_write_l2":
        for it in e["items"]:
            mem_store[it["scope"]].append(it["statement"].lower())
        # gold label of the diverging step belongs to the task's site(s)
        for it in e["items"]:
            learn_label_text[it["scope"]] += " " + (e.get("gold") or "").lower()


def site_of(ep_event):
    return ep_event.get("scope", "")


# ---- walk withmem test steps ----
cov_gap = extraction = injection = delivered = 0
delivered_ok = delivered_n = 0
injected_but_irrel = 0
steps_total = 0
site_test_tasks = defaultdict(int)
steps_per_task = []

for e in ev:
    if e["kind"] != "test_episode" or e.get("tag") != "withmem":
        continue
    site = site_of(e)
    site_test_tasks[site] += 1
    steps = e.get("steps", [])
    steps_per_task.append(len(steps))
    for s in steps:
        toks = tokens(s.get("act_repr") or s.get("gold"))
        if not toks:
            continue
        steps_total += 1
        injected_facts = " || ".join(s.get("facts", [])).lower()
        store = " || ".join(mem_store.get(site, []))
        learn_seen = any(t in learn_label_text.get(site, "") for t in toks)
        memory_has = any(t in store for t in toks)
        injected = any(t in injected_facts for t in toks)
        elem = s.get("elem", 0)
        if injected:
            delivered += 1
            delivered_ok += elem
            delivered_n += 1
        elif memory_has:
            injection += 1
        elif learn_seen:
            extraction += 1
        else:
            cov_gap += 1

print(f"=== TEST step diagnosis (n={steps_total} solvable steps) ===\n")
def line(name, c):
    return f"  {name:42s} {c:4d}  ({100*c//max(steps_total,1)}%)"
print(line("COVERAGE/GENERALIZATION gap (elem never learned)", cov_gap))
print(line("EXTRACTION problem (learned, no usable fact)", extraction))
print(line("INJECTION problem (fact in store, not retrieved)", injection))
print(line("DELIVERED (relevant fact actually injected)", delivered))
print(f"\n  among DELIVERED: element acc = {100*delivered_ok/max(delivered_n,1):.1f}%  "
      f"(if low, the delivered facts are wrong/contradictory = EXTRACTION-quality)")

print(f"\n=== site recurrence / task length (the 'too short / no recurrence' idea) ===")
sites = len(site_test_tasks)
import statistics
print(f"  test sites={sites}  test tasks/site: "
      f"min={min(site_test_tasks.values())} median={statistics.median(site_test_tasks.values())} max={max(site_test_tasks.values())}")
print(f"  steps/test task: min={min(steps_per_task)} median={statistics.median(steps_per_task)} max={max(steps_per_task)}")
print(f"  sites with ANY learned facts: {len(mem_store)}")
