"""Decisive check: is the low injection-relevance due to (a) extraction/retrieval, or
(b) the benchmark simply not repeating controls across same-site tasks (coverage ceiling)?

This computes, with NO LLM calls, the UPPER BOUND on coverage: for each solvable step,
was its gold control label already the gold control of some EARLIER task on the same site?
If even this upper bound is ~5-10%, then no prompt/retrieval fix can help most steps —
the relevant memory literally cannot exist. Trust the numbers after '=== RECURRENCE ==='.
"""
import json, os, re, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))

def gold_label(repr_str):
    m = re.match(r"\s*\[([^\]]*)\]\s*(.*?)\s*->\s*(\S+)", repr_str or "")
    return m.group(2).strip().lower() if m else ""

def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    tasks = json.load(open(os.path.join(HERE, "data", "eval_tasks_49.json")))
    if limit:
        tasks = tasks[:limit]
    seen_by_site = defaultdict(set)     # controls seen in PRIOR tasks (same site)
    seen_by_site_task = defaultdict(set)  # controls seen in prior OR current task
    total = recur_prior_task = recur_incl_same_task = 0
    per_site_tasks = defaultdict(int)
    for t in tasks:
        site = t["site"]; per_site_tasks[site] += 1
        this_task_labels = set()
        for st in t["steps"]:
            if not st["solvable"]:
                continue
            gl = gold_label(st["act_repr"])
            if not gl:
                continue
            total += 1
            if gl in seen_by_site[site]:            # appeared in an EARLIER task, same site
                recur_prior_task += 1
            if gl in seen_by_site_task[site]:        # appeared earlier OR earlier-in-this-task
                recur_incl_same_task += 1
            this_task_labels.add(gl)
            seen_by_site_task[site].add(gl)
        seen_by_site[site] |= this_task_labels
    nsite = len(per_site_tasks)
    print(f"=== RECURRENCE (upper bound on memory coverage), {len(tasks)} tasks ===")
    print(f"sites: {nsite}, tasks/site avg: {len(tasks)/max(nsite,1):.1f}")
    print(f"solvable steps: {total}")
    print(f"\n[cross-task, same-site] gold control seen in an EARLIER task on same site:")
    print(f"   {recur_prior_task}/{total} = {100*recur_prior_task/max(total,1):.1f}%  <-- UPPER BOUND for cross-task memory")
    print(f"\n[incl. earlier-in-same-task] control seen earlier at all (same site):")
    print(f"   {recur_incl_same_task}/{total} = {100*recur_incl_same_task/max(total,1):.1f}%")
    # per-site breakdown of how many tasks each site has (recurrence needs >1 task/site)
    multi = sum(1 for s, c in per_site_tasks.items() if c > 1)
    print(f"\nsites with >1 task (any recurrence possible at all): {multi}/{nsite}")
    print("=== END ===")

if __name__ == "__main__":
    main()
