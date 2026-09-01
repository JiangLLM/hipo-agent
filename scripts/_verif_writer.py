"""Competing predictor: is the damage predicted by the READER's baseline (the claim), or by the
WRITER of the injected lesson (same intent template + writer was all-wrong / had a different
reference-answer convention)?"""
import sys, json, collections
sys.path.insert(0, "scripts")
import numpy as np
import importlib.resources as ir
from _verif_bucket import per_task, RUNS

raw = {int(t["task_id"]): t for t in json.loads(ir.files("webarena").joinpath("test.raw.json").read_text())}


def writers(run):
    w = {}
    for ln in open(f"{run}/events.jsonl"):
        d = json.loads(ln)
        if d.get("kind") in ("wa_write_l1", "wa_write_l2"):
            w.setdefault(d["item"]["title"], (d.get("task"), d["kind"], d.get("nc"), d.get("n")))
    return w


rowsall = []
for name, run in RUNS.items():
    W = writers(run)
    for tid, r in per_task(run).items():
        if r["channel"] != "string" or not r["inj"]:
            continue
        t0 = (r["titles"] or [None])[0]
        w = W.get(t0, (None, None, None, None))
        wt = w[0]
        same_tmpl = (wt is not None and raw.get(wt, {}).get("intent_template_id") == r["template"])
        wnc, wn = w[2], w[3]
        allwrong = (wnc == 0) if wnc is not None else None
        d = 8 * (r["mem_nc"] / r["mem_n"] - r["nomem_nc"] / r["nomem_n"])
        hi = r["nomem_nc"] / r["nomem_n"] >= 0.75
        rowsall.append(dict(run=name, site="admin" if "admin" in name else "shop", tid=tid, d=d, hi=hi,
                            same=same_tmpl, layer=w[1], wnc=wnc, wn=wn, allwrong=allwrong, wt=wt))

R = rowsall
def summ(sub, lab):
    if not sub:
        print(f"  {lab:34s} n=  0"); return
    d = np.array([x["d"] for x in sub])
    print(f"  {lab:34s} n={len(d):3d} sum={d.sum():+7.2f} mean={d.mean():+.3f}  "
          f"n(<=-3)={(d<=-3).sum()} n(>=+3)={(d>=3).sum()}")

print("ALL injected string tasks, by writer provenance")
for site in ("admin", "shop"):
    S = [x for x in R if x["site"] == site]
    print(f"== {site}  (n_inj={len(S)}, total {sum(x['d'] for x in S):+.2f})")
    summ([x for x in S if x["same"]], "writer = SAME template")
    summ([x for x in S if not x["same"]], "writer = different template")
    summ([x for x in S if x["same"] and x["allwrong"]], "SAME tmpl & writer all-wrong (0/n)")
    summ([x for x in S if x["same"] and x["allwrong"] is False], "SAME tmpl & writer had a success")
    summ([x for x in S if not x["same"] and x["allwrong"]], "diff tmpl & writer all-wrong")
    summ([x for x in S if not x["same"] and x["allwrong"] is False], "diff tmpl & writer had a success")

print("\nCross-tab: reader baseline x same-template writer (mean delta)")
for site in ("admin", "shop"):
    S = [x for x in R if x["site"] == site]
    print(f"== {site}")
    for hi in (True, False):
        for same in (True, False):
            summ([x for x in S if x["hi"] == hi and x["same"] == same], f"hi={hi} same_tmpl={same}")

print("\nSame-template share of injections, by site/run")
for name in RUNS:
    S = [x for x in R if x["run"] == name]
    if not S: continue
    print(f"  {name:8s} inj={len(S):3d} same_tmpl={sum(x['same'] for x in S):3d} "
          f"({100*sum(x['same'] for x in S)/len(S):.0f}%)  "
          f"same&allwrong={sum(1 for x in S if x['same'] and x['allwrong']):2d}  "
          f"delta_from_same&allwrong={sum(x['d'] for x in S if x['same'] and x['allwrong']):+.2f}  "
          f"delta_rest={sum(x['d'] for x in S if not (x['same'] and x['allwrong'])):+.2f}")
