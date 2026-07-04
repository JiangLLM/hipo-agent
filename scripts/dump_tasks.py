"""Look at the QUESTION (task) + ANSWER (gold action path) for sites that have
multiple tasks, so we can reason about what reusable experience to extract.
Usage: python scripts/dump_tasks.py [site_substr ...]"""
import glob
import json
import sys
from collections import defaultdict

want = [s.lower() for s in sys.argv[1:]] or ["seatgeek", "kohls", "budget"]

samples = []
for f in sorted(glob.glob("data/mind2web/test_task/*.json")):
    samples.extend(json.load(open(f)))

by_site = defaultdict(list)
for s in samples:
    by_site[s.get("website", "?")].append(s)

for site, tasks in by_site.items():
    if not any(w in site.lower() for w in want):
        continue
    print(f"\n{'='*70}\nSITE: {site}   ({len(tasks)} tasks)\n{'='*70}")
    for t in tasks:
        print(f"\n  QUESTION: {t['confirmed_task']}")
        print(f"  ANSWER (gold path, {len(t.get('action_reprs', []))} steps):")
        for i, ar in enumerate(t.get("action_reprs", [])):
            print(f"     {i+1}. {ar}")
