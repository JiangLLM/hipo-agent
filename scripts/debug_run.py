"""Post-hoc debug of a step_evolve run: what was extracted, what was injected,
and where withmem lost vs nomem. Usage: python scripts/debug_run.py <run_dir>"""
import json
import sys
from collections import Counter, defaultdict

D = sys.argv[1]
events = [json.loads(x) for x in open(f"{D}/events.jsonl")]


def of(kind):
    return [e for e in events if e.get("kind") == kind]


# ---------- 1. EXTRACTION: what went into memory ----------
l1 = of("step_write_l1")
l2 = of("step_write_l2")
print(f"=== EXTRACTION ===  L1 writes={len(l1)}  L2 writes(events)={len(l2)}")
done = of("step_learn_done")
if done:
    print("learn_done:", {k: done[-1][k] for k in ("layer1_writes", "layer2_writes", "n_fact")})

# facts per scope (site)
scope_facts = defaultdict(list)
for e in l1:
    it = e.get("item", {})
    scope_facts[it.get("scope")].append(it.get("statement", ""))
for e in l2:
    for it in e.get("items", []):
        scope_facts[it.get("scope")].append(it.get("statement", ""))
print(f"sites with facts: {len(scope_facts)} | facts/site: "
      f"min={min(len(v) for v in scope_facts.values())} "
      f"max={max(len(v) for v in scope_facts.values())} "
      f"mean={sum(len(v) for v in scope_facts.values())/len(scope_facts):.1f}")

print("\n--- 15 sample extracted facts (quality / value-leak check) ---")
allf = [(s, st) for s, sts in scope_facts.items() for st in sts]
for s, st in allf[:15]:
    print(f"  [{s}] {st[:150]}")

# crude leak heuristic: fact contains a long literal token likely from the task query
print("\n--- facts that look OVER-SPECIFIC (contain quoted literal / TYPE value) ---")
import re
leaky = [(s, st) for s, st in allf if re.search(r"TYPE '?[A-Z0-9]", st) or st.count("'") >= 4]
print(f"  count={len(leaky)} / {len(allf)}")
for s, st in leaky[:6]:
    print(f"  [{s}] {st[:150]}")


# ---------- 2. INJECTION: what test-time retrieval pulled ----------
tw = [e for e in of("test_episode") if e.get("tag") == "withmem"]
tn = [e for e in of("test_episode") if e.get("tag") == "nomem"]
print(f"\n=== INJECTION (withmem test) ===  episodes={len(tw)}")
steps_with_facts = total_steps = fact_counts = 0
for e in tw:
    for st in e.get("steps", []):
        total_steps += 1
        nf = len(st.get("facts", []))
        fact_counts += nf
        if nf > 0:
            steps_with_facts += 1
print(f"solvable test steps={total_steps} | steps with >=1 injected fact={steps_with_facts} "
      f"({100*steps_with_facts//max(total_steps,1)}%) | avg facts/step={fact_counts/max(total_steps,1):.2f}")
# scope coverage: test episodes whose site had ANY learned fact
covered = sum(1 for e in tw if e.get("scope", "").replace("site:", "") and
              any(sf for sc, sf in scope_facts.items() if sc == e.get("scope")))
print(f"test episodes whose SITE has learned facts: {covered}/{len(tw)} "
      f"(rest get nothing -> withmem==nomem there)")


# ---------- 3. WHERE DID IT CHANGE? per-episode A/B ----------
def by_id(evs):
    d = {}
    for e in evs:
        d[e.get("task")] = e
    return d

wm, nm = by_id(tw), by_id(tn)
common = set(wm) & set(nm)
better = worse = same = 0
worse_cases = []
for t in common:
    dw = wm[t].get("step_success", 0)
    dn = nm[t].get("step_success", 0)
    if dw > dn: better += 1
    elif dw < dn: worse += 1; worse_cases.append((t, dn, dw, wm[t]))
    else: same += 1
print(f"\n=== PER-EPISODE A/B (n={len(common)}) ===  withmem better={better}  worse={worse}  same={same}")

print("\n--- up to 4 episodes where memory HURT (with the injected facts on the flipped step) ---")
for t, dn, dw, e in worse_cases[:4]:
    print(f"\n[{e.get('scope')}] ss {dn:.2f} -> {dw:.2f}  task: {t[:80]}")
    for st in e.get("steps", []):
        if not st.get("step"):  # a step that failed under withmem
            print(f"   FAILED step: gold={st.get('gold')}  pred={st.get('pred')}")
            for f in st.get("facts", [])[:4]:
                print(f"      injected: {f}")
            break
