"""Separate the 4 hypotheses for WHY memory doesn't help, from logs + data:

  H1 EXTRACTION  : the element WAS exercised in learn, but no stored fact captures it.
  H2 INJECTION   : a stored fact names it, but it was NOT retrieved/injected at test.
  H3 GENERALIZE  : the test step's element NEVER appeared in learn (same site) -> nothing to learn.
  H4 TASK LENGTH : tasks short / elements rarely recur across learn<->test -> little to reuse.

Decision tree per FAILED test step (element wrong, solvable):
  not seen_in_learn            -> H3
  seen_in_learn, not in store  -> H1 (extraction missed it)
  in store, not injected       -> H2 (retrieval)
  injected, still failed       -> H1b (fact present but useless content/format)
"""
import json
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, "src")
from hippo.m2w.run import _holdout_split, _load_eps

D = sys.argv[1]
DATA = "data/mind2web"

# --- reconstruct the SAME learn/test split the run used ---
eps = _load_eps(DATA, "test_task", 5)
learn_eps, test_eps = _holdout_split(eps, 0.5, 0)
learn_eps, test_eps = learn_eps[:40], test_eps[:40]


def toks(act_repr):
    if not act_repr:
        return set()
    left = act_repr.split("->")[0]
    left = re.sub(r"^\s*\[[^\]]*\]\s*", "", left)
    return {w for w in re.findall(r"[a-z0-9]+", left.lower()) if len(w) >= 4}


# elements exercised in LEARN, per site
learn_site_tokens = defaultdict(set)
learn_lens, test_lens = [], []
for ep in learn_eps:
    n = 0
    for st in ep.steps:
        if st.solvable:
            n += 1
            learn_site_tokens[ep.scope] |= toks(st.act_repr)
    learn_lens.append(n)
for ep in test_eps:
    test_lens.append(sum(1 for st in ep.steps if st.solvable))

# --- stored facts per site (from learn write events) ---
ev = [json.loads(x) for x in open(f"{D}/events.jsonl")]
store = defaultdict(list)
for e in ev:
    if e["kind"] == "step_write_l1":
        store[e["item"]["scope"]].append(e["item"]["statement"].lower())
    elif e["kind"] == "step_write_l2":
        for it in e["items"]:
            store[it["scope"]].append(it["statement"].lower())


def store_has(site, tk):
    return any(any(t in f for t in tk) for f in store.get(site, []))


# --- H4 context: lengths + recurrence ---
def med(xs):
    return sorted(xs)[len(xs) // 2] if xs else 0
print("=== H4 context: task length & element recurrence ===")
print(f"  learn steps/task: median={med(learn_lens)} mean={sum(learn_lens)/max(len(learn_lens),1):.1f}")
print(f"  test  steps/task: median={med(test_lens)} mean={sum(test_lens)/max(len(test_lens),1):.1f}")
# recurrence: of all solvable test steps, how many have their element seen in learn (same site)?
seen = tot = 0
for ep in test_eps:
    for st in ep.steps:
        if not st.solvable:
            continue
        tot += 1
        if toks(st.act_repr) & learn_site_tokens.get(ep.scope, set()):
            seen += 1
print(f"  test steps whose element was SEEN in learn (same site): {seen}/{tot} ({100*seen//max(tot,1)}%)")
print(f"  -> if this is low, H3/H4 dominate (little to reuse no matter how good extraction is)")

# --- decision tree over FAILED test steps (from withmem events) ---
wm = [e for e in ev if e["kind"] == "test_episode" and e.get("tag") == "withmem"]
buckets = Counter()
failed = 0
for e in wm:
    site = e["scope"]
    for s in e.get("steps", []):
        if not s.get("solvable", True):
            continue
        if s.get("elem", 0) == 1:
            continue
        failed += 1
        tk = toks(s.get("act_repr") or s.get("gold"))
        if not tk:
            buckets["(no parseable element)"] += 1
            continue
        seen_learn = bool(tk & learn_site_tokens.get(site, set()))
        in_store = store_has(site, tk)
        injected = any(any(t in f.lower() for t in tk) for f in s.get("facts", []))
        if not seen_learn:
            buckets["H3 never seen in learn (generalization/coverage)"] += 1
        elif not in_store:
            buckets["H1 seen in learn but NOT extracted (extraction miss)"] += 1
        elif not injected:
            buckets["H2 in store but NOT injected (retrieval)"] += 1
        else:
            buckets["H1b injected but still wrong (fact useless content)"] += 1

print(f"\n=== WHY each FAILED test step failed (n={failed}) ===")
for k, v in buckets.most_common():
    print(f"  {v:4d}  {v*100//max(failed,1):3d}%   {k}")
