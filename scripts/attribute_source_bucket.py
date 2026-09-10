#!/usr/bin/env python3
"""Attribute the per-task memory effect to the success-ratio bucket of the injected L2's SOURCE task.

For every paired WebArena fleet run (nomem + withmem arms, N rollouts each), this reads events.jsonl and
groups tasks by *where the lesson they received came from*:

  no-inject  : the gate injected nothing
  all-fail   : the L2 was written from a source task with nc == 0      (no verified success to anchor on)
  maj-wrong  : 0 < nc < n/2  (learn WHY the successful minority was right)
  half       : nc == n/2
  maj-right  : n/2 < nc < n  (a caution distilled against many verified successes)

and reports the mean per-task delta (withmem rate - nomem rate) with a 95% CI, split by whether the source
task shares the target's intent template. Finding (2026-09-01, 9 runs / 1258 pairs): only maj-right is
significantly positive (+5.7 [+2.7, +8.8]) and it transfers cross-template; all-fail is a zero-mean coin
flip with fat tails (19 big-ups / 13 big-downs) - the origin of the family-wipeout regressions.

Usage:
    python scripts/attribute_source_bucket.py runs/wa_fleet_shopping_all_2026* runs/wa_fleet_gitlab_all_2026*
    python scripts/attribute_source_bucket.py --all-fleet          # every runs/wa_fleet_* with both arms
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import math
import os
import statistics as st
import sys

BUCKETS = ["no-inject", "all-fail", "maj-wrong", "half", "maj-right"]


def bucket(nc: int, n: int) -> str:
    if nc == 0:
        return "all-fail"
    if nc * 2 == n:
        return "half"
    if nc * 2 < n:
        return "maj-wrong"
    if nc < n:
        return "maj-right"
    return "all-ok"  # never written by the L2 gate; kept for completeness


def load_run(run_dir: str):
    """Return per-task records: (delta, nomem_rate, bucket, same_template) or None if arms are incomplete."""
    src, inj, tpl = {}, {}, {}
    rates = {"nomem": {}, "withmem": {}}
    path = os.path.join(run_dir, "events.jsonl")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        for line in f:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            k = e.get("kind")
            if k == "wa_write_l2":
                src[e["item"]["title"]] = (e["nc"], e["n"], e["task"])
            elif k == "wa_task":
                tag = e.get("tag")
                tid = e["task_id"]
                tpl[tid] = e.get("template_id")
                if tag in rates and e.get("n", 0) > 0:  # n==0 -> every rollout crashed: drop from denominator
                    rates[tag][tid] = e["nc"] / e["n"]
                if tag == "withmem":
                    # ret_titles is the single gated injection (len 0/1; verified == mem_injected flag)
                    inj[tid] = e.get("ret_titles") or []
    keys = sorted(set(rates["nomem"]) & set(rates["withmem"]))
    if not keys:
        return None
    recs = []
    for k in keys:
        delta = rates["withmem"][k] - rates["nomem"][k]
        titles = inj.get(k, [])
        if not titles:
            recs.append((delta, rates["nomem"][k], "no-inject", None))
            continue
        t = titles[0]
        if t not in src:  # injected from a pre-loaded/frozen bank we cannot attribute
            recs.append((delta, rates["nomem"][k], "unknown-src", None))
            continue
        nc, n, stask = src[t]
        recs.append((delta, rates["nomem"][k], bucket(nc, n), tpl.get(stask) == tpl.get(k)))
    return recs


def ci(v):
    m = st.mean(v)
    if len(v) < 2:
        return m, float("nan"), float("nan")
    se = st.stdev(v) / math.sqrt(len(v))
    return m, m - 1.96 * se, m + 1.96 * se


def fmt_row(name, v, base=None):
    m, lo, hi = ci(v)
    up = sum(1 for x in v if x >= 0.5)
    dn = sum(1 for x in v if x <= -0.5)
    b = f"{100 * st.mean(base):6.1f}" if base else "     -"
    return f"{name:22s} n={len(v):4d} nomem={b} d={100 * m:+6.2f} CI=[{100 * lo:+6.1f},{100 * hi:+6.1f}] up={up:3d} dn={dn:3d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="*", help="run directories (each must hold events.jsonl with both arms)")
    ap.add_argument("--all-fleet", action="store_true", help="use every runs/wa_fleet_*/ directory")
    ap.add_argument("--per-run", action="store_true", help="also print one line per run per bucket")
    a = ap.parse_args()
    dirs = list(a.runs)
    if a.all_fleet:
        dirs += [d for d in sorted(glob.glob("runs/wa_fleet_*")) if os.path.isdir(d)]
    if not dirs:
        ap.error("give run dirs or --all-fleet")

    pooled = collections.defaultdict(list)
    pooled_base = collections.defaultdict(list)
    used = 0
    for d in dirs:
        recs = load_run(d)
        if not recs:
            continue
        used += 1
        per = collections.defaultdict(list)
        for delta, base, b, same in recs:
            per[b].append(delta)
            pooled[b].append(delta)
            pooled_base[b].append(base)
            if same is not None:
                key = f"{b}/{'same-tpl' if same else 'cross-tpl'}"
                pooled[key].append(delta)
                pooled_base[key].append(base)
        allv = [r[0] for r in recs]
        m, lo, hi = ci(allv)
        print(f"{os.path.basename(d)[:58]:58s} n={len(allv):4d} d={100 * m:+5.2f} CI=[{100 * lo:+5.1f},{100 * hi:+5.1f}]"
              + ("  " + " ".join(f"{b}:{len(per[b])}/{100 * st.mean(per[b]):+.1f}" for b in BUCKETS if per.get(b)) if a.per_run else ""))

    print(f"\n=== pooled over {used} runs, per-task delta = withmem rate - nomem rate, by SOURCE bucket ===")
    for b in BUCKETS + ["unknown-src"]:
        if pooled.get(b):
            print(fmt_row(b, pooled[b], pooled_base[b]))
    print("\n--- split by whether the source task shares the target's intent template ---")
    for b in BUCKETS[1:]:
        for s in ("same-tpl", "cross-tpl"):
            key = f"{b}/{s}"
            if len(pooled.get(key, [])) >= 2:
                print(fmt_row(key, pooled[key], pooled_base[key]))

    tot = sum(len(v) for b, v in pooled.items() if "/" not in b)
    if tot and pooled.get("no-inject"):
        cur = sum(sum(v) for b, v in pooled.items() if "/" not in b) / tot
        ctrl = st.mean(pooled["no-inject"])
        keep = ("maj-right", "maj-wrong", "no-inject", "unknown-src")
        alt = (sum(sum(v) for b, v in pooled.items() if "/" not in b and b in keep)
               + sum(len(v) for b, v in pooled.items() if "/" not in b and b not in keep) * ctrl) / tot
        removed = sum(sum(1 for x in v if x <= -0.5) for b, v in pooled.items() if "/" not in b and b not in keep)
        print(f"\npooled delta now {100 * cur:+.2f}; counterfactual 'never write from all-fail/half' "
              f"(those targets behave like no-inject) {100 * alt:+.2f}; big regressions removed: {removed}")


if __name__ == "__main__":
    sys.exit(main())
