"""For each step where memory HURT (nomem right -> withmem wrong), show what the
agent picked with/without memory and what was injected, to classify:
  (a) NOT-REUSABLE / not-retrieved : no injected fact is about the gold element
  (b) MISDIRECTED                  : an injected fact pointed at a wrong control
Usage: python scripts/debug_misdirect.py <run_dir>"""
import json
import re
import sys

D = sys.argv[1]
ev = [json.loads(x) for x in open(f"{D}/events.jsonl")]
tep = [e for e in ev if e.get("kind") == "test_episode"]
wm = {e["task"]: e for e in tep if e.get("tag") == "withmem"}
nm = {e["task"]: e for e in tep if e.get("tag") == "nomem"}


def label(ar):
    m = re.search(r"\]\s*(.*?)\s*->", ar or "")
    return (m.group(1) or "").strip().lower()


print("=== PER-TASK per-step element-correct (nomem vs withmem): is it really 'all wrong'? ===")
for t in set(wm) & set(nm):
    ws, ns = wm[t]["steps"], nm[t]["steps"]
    ne = [s.get("elem") for s in ns if s.get("solvable")]
    we = [s.get("elem") for s in ws if s.get("solvable")]
    print(f"\n[{t[:60]}]")
    print(f"  nomem   elem/step: {ne}  ({sum(ne)}/{len(ne)})")
    print(f"  withmem elem/step: {we}  ({sum(we)}/{len(we)})")

print("\n\n=== HURT steps (nomem RIGHT -> withmem WRONG): (a) not-reusable or (b) misdirected? ===")
for t in set(wm) & set(nm):
    ws, ns = wm[t]["steps"], nm[t]["steps"]
    for i in range(min(len(ws), len(ns))):
        w, n = ws[i], ns[i]
        if not w.get("solvable"):
            continue
        if n.get("elem") and not w.get("elem"):
            gl = label(w.get("act_repr", ""))
            facts = w.get("facts", [])
            rel = gl and len(gl) >= 4 and any(gl in (f or "").lower() for f in facts)
            verdict = "(b) MISDIRECTED: a fact names the gold control yet agent went elsewhere" if rel \
                else "(a) NOT-REUSABLE: no injected fact is about the gold control (noise crowded it out)"
            print(f"\n[{t[:55]}]  gold='{gl}'")
            print(f"   nomem chose : {n.get('pred')}   (correct)")
            print(f"   withmem chose: {w.get('pred')}   (wrong)")
            print(f"   injected facts ({len(facts)}):")
            for f in facts[:8]:
                print(f"      - {f[:110]}")
            print(f"   => {verdict}")
