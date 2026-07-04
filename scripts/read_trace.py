"""Read actual per-step traces: nomem vs withmem decision on the SAME step.
Shows the agent's thought, injected memory, chosen action, gold — so we can see
WHY memory did/didn't change the choice (not aggregate stats)."""
import json
import re
import sys

D = sys.argv[1]
ev = [json.loads(x) for x in open(f"{D}/events.jsonl")]


def by_task(tag):
    return {e["task"]: e for e in ev if e["kind"] == "test_episode" and e.get("tag") == tag}


nomem, withmem = by_task("nomem"), by_task("withmem")


def gold_label(s):
    g = s.get("act_repr") or s.get("gold") or ""
    left = g.split("->")[0]
    return re.sub(r"^\s*\[[^\]]*\]\s*", "", left).strip()


for task in withmem:
    a, b = nomem.get(task), withmem[task]
    if not a:
        continue
    print("\n" + "=" * 100)
    print(f"TASK: {task}")
    print(f"  nomem ss={a['step_success']} elem={a['element_acc']}   withmem ss={b['step_success']} elem={b['element_acc']}")
    sa, sb = a.get("steps", []), b.get("steps", [])
    for i, (x, y) in enumerate(zip(sa, sb)):
        ex, ey = x.get("elem", 0), y.get("elem", 0)
        flag = "  " if ex == ey else (">>FIXED" if ey > ex else ">>REGRESS")
        print(f"\n  [step {i}] gold={y.get('gold')}  ({gold_label(y)}) {flag}")
        print(f"     NOMEM   elem={ex} pred={x.get('pred')}")
        print(f"             thought: {x.get('thought','')}")
        print(f"     WITHMEM elem={ey} pred={y.get('pred')}")
        print(f"             thought: {y.get('thought','')}")
        facts = y.get("facts", [])
        if facts:
            print(f"             injected {len(facts)} facts:")
            for f in facts:
                print(f"                - {f}")
