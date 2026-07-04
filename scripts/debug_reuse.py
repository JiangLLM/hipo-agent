"""Is memory MISLEADING the agent (带偏) or just NOT REUSABLE? Align nomem vs withmem
per solvable step and bucket the outcomes."""
import json
import re
import sys
import glob
from collections import Counter

D = sys.argv[1]
ev = [json.loads(x) for x in open(glob.glob(f"{D}/events.jsonl")[0])]


def toks(ar):
    if not ar:
        return set()
    left = ar.split("->")[0]
    left = re.sub(r"^\s*\[[^\]]*\]\s*", "", left)
    return {w for w in re.findall(r"[a-z0-9]+", left.lower()) if len(w) >= 4}


def by_task(tag):
    return {e["task"]: e for e in ev if e["kind"] == "test_episode" and e.get("tag") == tag}


nm, wm = by_task("nomem"), by_task("withmem")
b = Counter()
for task in set(nm) & set(wm):
    for sa, sb in zip(nm[task].get("steps", []), wm[task].get("steps", [])):
        if not sb.get("solvable", True):
            continue
        na, wa = sa.get("elem", 0), sb.get("elem", 0)
        tk = toks(sb.get("act_repr") or sb.get("gold"))
        facts = " ".join(sb.get("facts", [])).lower()
        rel = bool(tk) and any(t in facts for t in tk)
        if na == 1 and wa == 0:
            b["MISLED  本来对 -> 被记忆搞错 (带偏)"] += 1
        elif na == 0 and wa == 1:
            b["REUSED  本来错 -> 被记忆修对 (复用成功)"] += 1
        elif na == 1 and wa == 1:
            b["both right (记忆没影响)"] += 1
        elif rel:
            b["both wrong + 有相关fact (经验在场但没复用上/无效)"] += 1
        else:
            b["both wrong + 无相关fact (没有可复用的经验)"] += 1

tot = sum(b.values())
print(f"aligned solvable steps: {tot}\n")
for k, v in b.most_common():
    print(f"  {v:4d}  {v*100//max(tot,1):3d}%   {k}")

misled = b["MISLED  本来对 -> 被记忆搞错 (带偏)"]
reused = b["REUSED  本来错 -> 被记忆修对 (复用成功)"]
print(f"\n净效果 (复用成功 - 带偏) = {reused} - {misled} = {reused - misled}")
