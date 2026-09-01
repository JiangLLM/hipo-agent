"""Adversarial recheck of the 'composition effect' claim.

Per run: per task, nc/n for nomem and withmem arms (n = rollouts with episode_end),
injection flag from the withmem wa_retrieve/wa_task, grading channel from the raw
webarena config. Then bucket by nomem baseline and print sums of (withmem_nc - nomem_nc).
"""
import json, sys, collections
import importlib.resources as ir

RUNS = {
    "admin#1": "runs/wa_fleet_shopping_admin_readonly_20260807_225320_20260807_225403",
    "admin#2": "runs/wa_fleet_shopping_admin_readonly_20260808_130520_20260808_130530",
    "shop#1": "runs/wa_fleet_shopping_readonly_20260803_192709_20260803_192720",
    "shop#2": "runs/wa_fleet_shopping_readonly_20260805_182840_20260805_182907",
    "shop#3": "runs/wa_fleet_shopping_readonly_20260806_223937_20260806_224018",
}

raw = json.loads(ir.files("webarena").joinpath("test.raw.json").read_text())
META = {}
for t in raw:
    tid = int(t["task_id"])
    ev = t["eval"]
    ra = ev.get("reference_answers") or {}
    ets = set(ev["eval_types"])
    if "exact_match" in ra or "must_include" in ra:
        ch = "string"
    elif "fuzzy_match" in ra:
        vals = ra["fuzzy_match"]
        vals = vals if isinstance(vals, list) else [vals]
        ch = "NA" if all(str(v).strip().upper() == "N/A" for v in vals) else "fuzzy_other"
    elif ets & {"program_html", "url_match"}:
        ch = "urlprog"
    else:
        ch = "other"
    META[tid] = dict(channel=ch, template=t.get("intent_template_id"), intent=t["intent"],
                     sites=tuple(t["sites"]), ref=ra)


def load(run):
    end = collections.defaultdict(lambda: collections.defaultdict(dict))  # tag->tid->rollout->reward
    inj = {}
    ret = {}
    for ln in open(f"{run}/events.jsonl"):
        d = json.loads(ln)
        k = d.get("kind")
        if k == "wa_episode_end":
            end[d["tag"]][d["task_id"]][d["rollout"]] = 1 if d.get("reward") else 0
        elif k == "wa_retrieve":
            ret[d["task_id"]] = d.get("titles") or []
            inj[d["task_id"]] = bool(d.get("n_retrieved"))
    return end, inj, ret


def per_task(run):
    end, inj, ret = load(run)
    rows = {}
    tids = set(end["nomem"]) | set(end["withmem"])
    for tid in sorted(tids):
        a = end["nomem"].get(tid, {})
        b = end["withmem"].get(tid, {})
        if not a or not b:
            continue
        rows[tid] = dict(
            nomem_nc=sum(a.values()), nomem_n=len(a),
            mem_nc=sum(b.values()), mem_n=len(b),
            inj=inj.get(tid, False), titles=ret.get(tid, []),
            **META[tid],
        )
    return rows


if __name__ == "__main__":
    for name, run in RUNS.items():
        rows = per_task(run)
        chc = collections.Counter(r["channel"] for r in rows.values())
        s = {tid: r for tid, r in rows.items() if r["channel"] == "string"}
        # paired delta in fraction, matching the reported table
        def mdelta(d):
            return 100 * sum(r["mem_nc"] / r["mem_n"] - r["nomem_nc"] / r["nomem_n"] for r in d.values()) / max(len(d), 1)
        print(f"== {name}  n_paired={len(rows)} channels={dict(chc)}")
        print(f"   all delta {mdelta(rows):+.1f} (n={len(rows)}) | string {mdelta(s):+.1f} (n={len(s)})",
              f"| urlprog {mdelta({k:v for k,v in rows.items() if v['channel']=='urlprog'}):+.1f}",
              f"| NA {mdelta({k:v for k,v in rows.items() if v['channel']=='NA'}):+.1f}")
        # bucket by nomem baseline, restricted to string channel
        for lab, pred in (("hi(>=0.75)", lambda r: r["nomem_nc"] / r["nomem_n"] >= 0.75),
                          ("lo(<0.75)", lambda r: r["nomem_nc"] / r["nomem_n"] < 0.75)):
            for ilab, ipred in (("inj", lambda r: r["inj"]), ("non", lambda r: not r["inj"])):
                sub = [r for r in s.values() if pred(r) and ipred(r)]
                tot = sum(r["mem_nc"] - r["nomem_nc"] for r in sub)
                print(f"   {lab:11s} {ilab}: n={len(sub):3d} sum_rollouts={tot:+6.1f} per_task={tot/max(len(sub),1):+.2f}")
        base = sum(r["nomem_nc"] / r["nomem_n"] for r in s.values()) / max(len(s), 1)
        hi = sum(1 for r in s.values() if r["nomem_nc"] / r["nomem_n"] >= 0.75) / max(len(s), 1)
        ninj = sum(1 for r in s.values() if r["inj"])
        print(f"   nomem SR(string)={base:.3f}  frac>=0.75={hi:.2f}  injected={ninj}/{len(s)}")
