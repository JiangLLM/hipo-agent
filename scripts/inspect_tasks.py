"""Look at the QUESTION (task) and the ANSWER (gold action path) for multiple
DIFFERENT tasks on the SAME site, so we can design what experience to extract.
Usage: python scripts/inspect_tasks.py [n_sites]"""
import glob
import json
import sys
from collections import defaultdict

n_sites = int(sys.argv[1]) if len(sys.argv) > 1 else 4

samples = []
for f in sorted(glob.glob("data/mind2web/test_task/*.json")):
    samples.extend(json.load(open(f)))

by_site = defaultdict(list)
for s in samples:
    by_site[s.get("website", "?")].append(s)

# sites with the most tasks first (best for seeing cross-task commonality)
sites = sorted(by_site, key=lambda w: -len(by_site[w]))

for site in sites[:n_sites]:
    tasks = by_site[site]
    print(f"\n{'='*78}\nSITE: {site}   ({len(tasks)} tasks)\n{'='*78}")
    for s in tasks[:5]:
        print(f"\n  QUESTION: {s['confirmed_task']}")
        print(f"  ANSWER (gold path):")
        for rep in s.get("action_reprs", []):
            print(f"      {rep}")
