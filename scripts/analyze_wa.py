"""Analyze a WebArena run with the correct scoring discipline.

Splits results by eval type: the PRIMARY metric is exact_match + must_include
(deterministic string ops, grader-model-independent, sensitive to answer quality);
fuzzy_match is reported SEPARATELY with a noise caveat (WebArena grades multi-element
fuzzy refs element-by-element, so correct answers often score 0 regardless of the model
under test). Never fold fuzzy into the headline A/B.

    .venv-wa/bin/python scripts/analyze_wa.py runs/wa_shopping_admin_gpt5_6sol_<ts>
"""
import json
import sys
from collections import Counter


def eval_type_map():
    """task_id -> 'exact_match' | 'must_include' | 'fuzzy_match' (the dominant ref key)."""
    import importlib.resources as ir
    raw = json.loads(ir.files("webarena").joinpath("test.raw.json").read_text())
    out = {}
    for r in raw:
        refs = r.get("eval", {}).get("reference_answers") or {}
        keys = list(refs.keys())
        # a task is "clean" (primary) unless it has any fuzzy_match ref
        out[int(r["task_id"])] = "fuzzy_match" if "fuzzy_match" in keys else (
            "exact_match" if "exact_match" in keys else "must_include" if "must_include" in keys else "other")
    return out


def load(run_dir):
    tasks = {"nomem": [], "withmem": [], "frozenmem": []}
    retr = {}          # task_id -> retrieval event (withmem)
    for line in open(f"{run_dir}/events.jsonl"):
        d = json.loads(line)
        k = d.get("kind")
        if k == "wa_task":
            tasks.setdefault(d["tag"], []).append(d)
        elif k == "wa_retrieve" and d.get("tag") == "withmem":
            retr[d["task_id"]] = d
    return tasks, retr


def sr(rows):
    return (sum(d["reward"] for d in rows), len(rows))


def by_type(rows, etype):
    prim = [d for d in rows if etype.get(d["task_id"]) in ("exact_match", "must_include")]
    fuzz = [d for d in rows if etype.get(d["task_id"]) == "fuzzy_match"]
    return prim, fuzz


def line(name, rows):
    w, n = sr(rows)
    return f"{name:9s} {w:>3}/{n:<3} = {w/max(n,1):.1%}" if n else f"{name:9s}  (none)"


def main():
    run_dir = sys.argv[1].rstrip("/")
    etype = eval_type_map()
    t, retr = load(run_dir)
    nm, wm = t.get("nomem", []), t.get("withmem", [])
    print(f"== {run_dir}\n")

    for tag, rows in (("nomem", nm), ("withmem", wm), ("frozenmem", t.get("frozenmem", []))):
        if not rows:
            continue
        prim, fuzz = by_type(rows, etype)
        print(f"[{tag}]")
        print("  overall :", line("", rows).strip())
        print("  PRIMARY :", line("exact+must", prim).strip(), " <- headline")
        print("  fuzzy   :", line("(noisy)", fuzz).strip(), " <- report-only")
        if tag == "withmem":
            last = rows[-1]
            print(f"  memory  : L1={last.get('l1_total')} L2={last.get('l2_total')} bank={last.get('n_mem')}")
        print()

    if not (nm and wm):
        return
    # paired A/B on PRIMARY subset (same task_ids, both arms)
    nmap = {d["task_id"]: d["reward"] for d in nm}
    prim_wm, _ = by_type(wm, etype)
    pairs = [(d["task_id"], d["reward"], nmap[d["task_id"]]) for d in prim_wm if d["task_id"] in nmap]
    pw = [tid for tid, a, b in pairs if a > b]
    pl = [tid for tid, a, b in pairs if b > a]
    print(f"PAIRED (primary subset, n={len(pairs)}): withmem wins {len(pw)} {pw}, "
          f"nomem wins {len(pl)} {pl}, tie {len(pairs)-len(pw)-len(pl)}")

    # LOW-VARIANCE metric: mean success rate per task = nc/n (fraction of rollouts that
    # succeeded). rollout[0] is a single noisy draw; nc/n averages over all rollouts of the
    # task and is the fair A/B when arms run the same rollout count (wa.eval_rollouts).
    def mean_rate(rows):
        prim = [d for d in rows if etype.get(d["task_id"]) in ("exact_match", "must_include")
                and d.get("n")]
        return (sum(d["nc"] / d["n"] for d in prim) / len(prim), len(prim)) if prim else (0, 0)
    all_arms = [("nomem", nm), ("withmem", wm), ("frozenmem", t.get("frozenmem", []))]
    print("\nMEAN SUCCESS RATE (nc/n, primary) — the low-variance ablation metric:")
    for tag, rows in all_arms:
        if rows:
            mr, k = mean_rate(rows)
            print(f"  {tag:9s} mean-rate {mr:.1%}  (n={k} tasks, {rows[-1].get('n','?')} rollouts each)")
    # paired mean-rate: withmem vs nomem per task
    ncmap = {d["task_id"]: (d["nc"], d["n"]) for d in nm if d.get("n")}
    dd = [(d["task_id"], d["nc"]/d["n"] - ncmap[d["task_id"]][0]/ncmap[d["task_id"]][1])
          for d in prim_wm if d["task_id"] in ncmap and d.get("n")]
    if dd:
        up = [tid for tid, x in dd if x > 0.001]; down = [tid for tid, x in dd if x < -0.001]
        print(f"  paired Δ(withmem-nomem) mean-rate: avg {sum(x for _,x in dd)/len(dd):+.1%}; "
              f"rate-up {len(up)} {up}, rate-down {len(down)} {down}")

    # self-evolution curve on PRIMARY, stream order
    print("\nself-evolution (withmem PRIMARY, stream order):")
    prwd, run_w = [], 0
    for d in prim_wm:
        prwd.append(d["reward"]); run_w += d["reward"]
        cum = run_w / len(prwd); win = sum(prwd[-10:]) / len(prwd[-10:])
        bar = "#" * int(win * 30)
        r = retr.get(d["task_id"], {})
        hit = f"ret={r.get('n_retrieved',0)}" if r else ""
        print(f"  t{d['task_id']:>3} tmpl{d.get('template_id','?'):>4} r={d['reward']} "
              f"nc={d.get('nc','?')}/{d.get('n','?')} cum={cum:.2f} win10={win:.2f} "
              f"bank={d.get('n_mem',0):>2} {hit} |{bar}")
    half = len(prwd) // 2
    if half:
        fh = sum(prwd[:half]) / half; sh = sum(prwd[half:]) / (len(prwd) - half)
        print(f"  first-half {fh:.2f} -> second-half {sh:.2f} (Δ{sh-fh:+.2f})")

    # memory diagnosis: on flips, was a lesson retrieved?
    print("\nflip diagnosis (primary tasks where arms differ):")
    for tid, a, b in pairs:
        if a == b:
            continue
        r = retr.get(tid, {})
        who = "withmem↑" if a > b else "nomem↑"
        print(f"  t{tid} {who}: retrieved {r.get('n_retrieved',0)} items "
              f"scores={r.get('scores',[])} titles={r.get('titles',[])[:2]}")


if __name__ == "__main__":
    main()
