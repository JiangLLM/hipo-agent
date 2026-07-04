"""Is the INJECTED knowledge actually useful? Compare accuracy on steps where a fact
naming the gold element WAS injected vs where it wasn't, and vs the no-memory baseline."""
import json
import re
import sys

D = sys.argv[1]
ev = [json.loads(x) for x in open(f"{D}/events.jsonl")]


def gold_tokens(act_repr):
    # act_repr like "[button] Change Location -> CLICK" -> tokens of the label
    if not act_repr:
        return []
    left = act_repr.split("->")[0]
    left = re.sub(r"^\s*\[[^\]]*\]\s*", "", left)         # drop "[role] "
    return [w for w in re.findall(r"[a-z0-9]+", left.lower()) if len(w) >= 4]


def steps_by_task(tag):
    out = {}
    for e in ev:
        if e["kind"] == "test_episode" and e.get("tag") == tag:
            out[e["task"]] = e.get("steps", [])
    return out


nomem, withmem = steps_by_task("nomem"), steps_by_task("withmem")
common = set(nomem) & set(withmem)

# buckets
rel_n = rel_ok = 0           # a fact naming the gold element was injected
irr_n = irr_ok = 0           # facts injected but none named the gold element
base_rel_ok = base_irr_ok = 0  # same steps, nomem accuracy
fix_with_rel = fix_total = 0
reg_no_rel = reg_total = 0

for task in common:
    for sa, sb in zip(nomem[task], withmem[task]):
        toks = gold_tokens(sb.get("act_repr") or sb.get("gold"))
        if not toks:
            continue
        facts = " || ".join(sb.get("facts", [])).lower()
        relevant = any(t in facts for t in toks)
        eb = sb.get("elem", 0); ea = sa.get("elem", 0)
        if relevant:
            rel_n += 1; rel_ok += eb; base_rel_ok += ea
        else:
            irr_n += 1; irr_ok += eb; base_irr_ok += ea
        if ea == 0 and eb == 1:
            fix_total += 1; fix_with_rel += int(relevant)
        if ea == 1 and eb == 0:
            reg_total += 1; reg_no_rel += int(not relevant)

print(f"steps analyzed: {rel_n + irr_n}")
print(f"\n=== RELEVANCE HIT RATE ===")
print(f"  steps where an injected fact NAMES the gold element: {rel_n} ({100*rel_n//max(rel_n+irr_n,1)}%)")
print(f"  steps where NONE of the injected facts name it:       {irr_n} ({100*irr_n//max(rel_n+irr_n,1)}%)")

def pct(a, b):
    return f"{100*a/max(b,1):.1f}%"

print(f"\n=== IS THE KNOWLEDGE USEFUL? (element accuracy) ===")
print(f"  steps WITH a relevant fact injected:  withmem {pct(rel_ok, rel_n)}  vs  nomem {pct(base_rel_ok, rel_n)}   (n={rel_n})")
print(f"  steps WITHOUT a relevant fact:        withmem {pct(irr_ok, irr_n)}  vs  nomem {pct(base_irr_ok, irr_n)}   (n={irr_n})")
print(f"\n  -> if 'with relevant' withmem >> nomem, the knowledge helps when it's on-target")
print(f"  -> if relevance hit-rate is low, useful facts rarely reach the right step")

print(f"\n=== WHERE DID CHANGES COME FROM ===")
print(f"  fixes total={fix_total}, of which a relevant fact was present: {fix_with_rel}")
print(f"  regressions total={reg_total}, of which NO relevant fact present (pure noise): {reg_no_rel}")
