"""4-site CORRECTED pass@1 (primary), merging both re-grade batches.
Usage: .venv-wa/bin/python scripts/analyze_corrected4.py runs/regrade_output.json runs/regrade_admin_output.json
"""
import json
import sys
import importlib.resources as ir


RUNS = {
    "reddit": "runs/wa_reddit_20260719_151957_20260719_151959",
    "gitlab": "runs/wa_gitlab_20260719_161841_20260719_161843",
    "shopping": "runs/wa_shopping_20260719_161803_20260719_161805",
    "shopping_admin": "runs/wa_shopping_admin_20260719_182647_20260719_182649",
}


def etype(raw, t):
    k = list((raw[t]["eval"].get("reference_answers") or {}).keys())
    return "fuzzy" if "fuzzy_match" in k else ("exact" if "exact_match" in k else "must")


def load_flips(input_path, output_path):
    recs = json.load(open(input_path))
    out = {o["i"]: bool(o.get("corrected")) for o in json.load(open(output_path))}
    flip = {}
    for i, r in enumerate(recs):
        flip[(r["site"], r["arm"], r["task_id"])] = out.get(i, False)
    return flip


def main():
    raw = {x["task_id"]: x for x in json.loads(ir.files("webarena").joinpath("test.raw.json").read_text())}
    flip = {}
    flip.update(load_flips("runs/regrade_input.json", sys.argv[1]))
    flip.update(load_flips("runs/regrade_admin_input.json", sys.argv[2]))

    print("== 4-SITE CORRECTED pass@1 (primary exact+must) ==\n")
    G = {"nm_raw": 0, "wm_raw": 0, "nm_c": 0, "wm_c": 0, "n": 0, "win": 0, "reg": 0}
    for site, D in RUNS.items():
        rew = {}
        for l in open(f"{D}/events.jsonl"):
            d = json.loads(l)
            if d.get("kind") == "wa_task":
                rew[(d["tag"], d["task_id"])] = d["reward"]
        tids = sorted({t for (tg, t) in rew if etype(raw, t) != "fuzzy"})

        def corr(arm, t):
            return True if rew.get((arm, t), 0) == 1 else flip.get((site, arm, t), False)

        n = len(tids)
        nm_raw = sum(rew.get(("nomem", t), 0) for t in tids)
        wm_raw = sum(rew.get(("withmem", t), 0) for t in tids)
        nm_c = sum(corr("nomem", t) for t in tids)
        wm_c = sum(corr("withmem", t) for t in tids)
        wins = [t for t in tids if not corr("nomem", t) and corr("withmem", t)]
        regs = [t for t in tids if corr("nomem", t) and not corr("withmem", t)]
        print(f"[{site:14}] n={n:3}  nomem {nm_raw}->{nm_c} ({nm_c/n:.0%})  withmem {wm_raw}->{wm_c} ({wm_c/n:.0%})  "
              f"Δ{(wm_c-nm_c)/n:+.0%}  wins {len(wins)}{wins} regs {len(regs)}{regs}")
        for kk, vv in (("nm_raw", nm_raw), ("wm_raw", wm_raw), ("nm_c", nm_c), ("wm_c", wm_c), ("n", n),
                       ("win", len(wins)), ("reg", len(regs))):
            G[kk] += vv

    print(f"\n== GRAND TOTAL (4 sites, corrected primary) ==")
    print(f"  nomem   raw {G['nm_raw']}/{G['n']}={G['nm_raw']/G['n']:.1%}  -> corrected {G['nm_c']}/{G['n']}={G['nm_c']/G['n']:.1%}")
    print(f"  withmem raw {G['wm_raw']}/{G['n']}={G['wm_raw']/G['n']:.1%}  -> corrected {G['wm_c']}/{G['n']}={G['wm_c']/G['n']:.1%}")
    print(f"  corrected Δ(withmem-nomem) = {(G['wm_c']-G['nm_c'])/G['n']:+.1%}")
    print(f"  memory wins {G['win']}, regressions {G['reg']}, net {G['win']-G['reg']}")


if __name__ == "__main__":
    main()
