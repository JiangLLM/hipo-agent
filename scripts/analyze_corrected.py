"""Combine the strict re-grade (workflow output) with the raw runs to produce:
  1. CORRECTED pass@1 scores per site per arm (raw-1 kept; raw-0 flipped only if the
     re-grade verified it as correct — lenient on format, strict on data).
  2. The KEY table: tasks where nomem is WRONG (corrected) and withmem is RIGHT (corrected)
     = genuine memory wins; plus regressions (nomem right, withmem wrong).

Usage: .venv-wa/bin/python scripts/analyze_corrected.py runs/regrade_output.json
  where regrade_output.json is the workflow's returned list of {i, corrected, ...}.
"""
import json
import sys
import importlib.resources as ir


def etype(raw, t):
    k = list((raw[t]["eval"].get("reference_answers") or {}).keys())
    return "fuzzy" if "fuzzy_match" in k else ("exact" if "exact_match" in k else "must")


RUNS = {
    "reddit": "runs/wa_reddit_20260719_151957_20260719_151959",
    "gitlab": "runs/wa_gitlab_20260719_161841_20260719_161843",
    "shopping": "runs/wa_shopping_20260719_161803_20260719_161805",
}


def main():
    raw = {x["task_id"]: x for x in json.loads(ir.files("webarena").joinpath("test.raw.json").read_text())}
    recs = json.load(open("runs/regrade_input.json"))          # index -> record (site,arm,task_id,etype)
    out = json.load(open(sys.argv[1]))                          # workflow output: [{i, corrected, ...}]
    corr_by_i = {o["i"]: bool(o.get("corrected")) for o in out}
    # corrected status of each raw-0 (site,arm,task_id)
    flip = {}
    for i, r in enumerate(recs):
        flip[(r["site"], r["arm"], r["task_id"])] = corr_by_i.get(i, False)

    print("== CORRECTED pass@1 (primary: exact+must), per site ==\n")
    grand = {"nomem": [0, 0], "withmem": [0, 0]}
    winlist = {}
    for site, D in RUNS.items():
        rew = {}
        for l in open(f"{D}/events.jsonl"):
            d = json.loads(l)
            if d.get("kind") == "wa_task":
                rew[(d["tag"], d["task_id"])] = d["reward"]
        tids = sorted({t for (tag, t) in rew if etype(raw, t) != "fuzzy"})

        def corrected(arm, t):
            r = rew.get((arm, t), 0)
            return True if r == 1 else flip.get((site, arm, t), False)

        nm_raw = sum(rew.get(("nomem", t), 0) for t in tids)
        wm_raw = sum(rew.get(("withmem", t), 0) for t in tids)
        nm_c = sum(corrected("nomem", t) for t in tids)
        wm_c = sum(corrected("withmem", t) for t in tids)
        n = len(tids)
        print(f"[{site}]  n={n}")
        print(f"  nomem   raw {nm_raw}/{n}={nm_raw/n:.0%}  -> corrected {nm_c}/{n}={nm_c/n:.0%}")
        print(f"  withmem raw {wm_raw}/{n}={wm_raw/n:.0%}  -> corrected {wm_c}/{n}={wm_c/n:.0%}")
        print(f"  corrected Δ(withmem-nomem) = {(wm_c-nm_c)/n:+.0%}")
        # memory wins / regressions on CORRECTED grades
        wins = [t for t in tids if not corrected("nomem", t) and corrected("withmem", t)]
        regs = [t for t in tids if corrected("nomem", t) and not corrected("withmem", t)]
        print(f"  >> memory WINS (nomem✗ -> withmem✓): {len(wins)} {wins}")
        print(f"  >> regressions (nomem✓ -> withmem✗): {len(regs)} {regs}")
        for t in wins:
            print(f"       WIN t{t}: {raw[t]['intent'][:64]}")
        print()
        grand["nomem"][0] += nm_c; grand["nomem"][1] += n
        grand["withmem"][0] += wm_c; grand["withmem"][1] += n
        winlist[site] = (wins, regs)

    gn, gt = grand["nomem"]; gw = grand["withmem"][0]
    print("== GRAND TOTAL (3 sites, corrected primary) ==")
    print(f"  nomem   {gn}/{gt} = {gn/gt:.1%}")
    print(f"  withmem {gw}/{gt} = {gw/gt:.1%}   Δ = {(gw-gn)/gt:+.1%}")
    tot_win = sum(len(w) for w, _ in winlist.values())
    tot_reg = sum(len(r) for _, r in winlist.values())
    print(f"  memory wins {tot_win}, regressions {tot_reg}, net {tot_win-tot_reg}")


if __name__ == "__main__":
    main()
