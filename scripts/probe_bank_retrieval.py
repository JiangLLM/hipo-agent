"""Does consolidation actually fix what it claims? An offline retrieval probe, no browser.

Replays the REAL injection path from hippo/wa/run.py — reasoning.topk_scored(intent, fetch_k,
scope=site:<site>, layer=L2) followed by brain.select_lesson's LLM gate — over every task of a
site, for two banks side by side. It answers the narrow mechanism question ("did the merge remove
the contradiction and the procedure-recording, without losing the lessons that worked?") without
pretending to be an end-to-end score: both banks were built FROM these tasks, so any success-rate
number here would be contaminated. What is legitimate is comparing WHICH lesson each task pulls.

    .venv-wa/bin/python scripts/probe_bank_retrieval.py shopping \
        runs/wa_shopping_.../memory.json runs/shopping_bank_clean.json \
        --focus 331,336,24,226

--focus tasks are printed in full (both banks' injected lesson text) — use the tasks whose
outcome memory actually changed, since those are the only ones the fix can be judged on.
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def probe(bank_path, tasks, site, cfg, brain, mk_store):
    """Return {task_id: (title, cosine, item)} using run.py's exact retrieval path."""
    store = mk_store(cfg)
    store.load(bank_path)
    scope = f"site:{site}"
    fetch = int(cfg.wa.get("retrieve_fetch_k", 5))
    thr = float(cfg.memory.get("relevance_threshold", 0.0))
    out = {}
    for t in tasks:
        cands = store.reasoning.topk_scored(t["intent"], fetch, thr, scope=scope, layer="L2")
        chosen = brain.select_lesson(t["intent"], [it for it, _ in cands])
        if chosen is None:
            out[t["task_id"]] = (None, None, None)
        else:
            cos = next((s for it, s in cands if it is chosen), None)
            out[t["task_id"]] = (chosen.title, cos, chosen)
    return out, len(store.reasoning.items)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("site")
    ap.add_argument("old_bank")
    ap.add_argument("new_bank")
    ap.add_argument("--focus", default="", help="comma task ids to print in full")
    ap.add_argument("--model", default="gpt-5.6-sol")
    ap.add_argument("--out", default="", help="write the full per-task table here (markdown)")
    args = ap.parse_args()

    sys.path.insert(0, "src")
    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    except Exception:
        pass
    from hippo.config import load_config
    from hippo.llm import LLMClient
    from hippo.memory.store import Memory
    from hippo.wa.brain import WaBrain
    from hippo.wa.data import load_tasks

    cfg = load_config(["--wa.site", args.site, "--wa.readonly_only", "true",
                       "--wa.base_url", "http://x", "--llm.model", args.model])
    tasks = load_tasks(cfg)
    llm = LLMClient(model=args.model, embed_model="local/BAAI/bge-small-en-v1.5",
                    max_tokens=8000, budget_usd=float(os.environ.get("BUDGET", "1000")))
    brain = WaBrain(llm, cfg)

    def mk(c):
        return Memory(llm.embed, c)

    print(f"site={args.site}  tasks={len(tasks)}  (retrieval path identical to run.py)")
    old, n_old = probe(args.old_bank, tasks, args.site, cfg, brain, mk)
    print(f"  OLD bank {args.old_bank}: {n_old} items loaded")
    new, n_new = probe(args.new_bank, tasks, args.site, cfg, brain, mk)
    print(f"  NEW bank {args.new_bank}: {n_new} items loaded")

    inj_old = sum(1 for v in old.values() if v[0])
    inj_new = sum(1 for v in new.values() if v[0])
    same = sum(1 for k in old if old[k][0] and new[k][0] and old[k][0] == new[k][0])
    changed = [k for k in old if (old[k][0] or "") != (new[k][0] or "")]
    print(f"\ninjection rate: OLD {inj_old}/{len(tasks)}  ->  NEW {inj_new}/{len(tasks)}"
          f"   (identical title on {same} tasks, changed on {len(changed)})")
    print(f"lost injection (old had, new none): "
          f"{[k for k in old if old[k][0] and not new[k][0]]}")
    print(f"gained injection (old none, new has): "
          f"{[k for k in old if not old[k][0] and new[k][0]]}")

    # distinct lessons actually used — the dead-weight measure
    used_old = {v[0] for v in old.values() if v[0]}
    used_new = {v[0] for v in new.values() if v[0]}
    print(f"distinct lessons ever injected: OLD {len(used_old)}/{n_old} "
          f"({n_old - len(used_old)} dead)  ->  NEW {len(used_new)}/{n_new} "
          f"({n_new - len(used_new)} dead)")

    focus = [int(x) for x in args.focus.split(",") if x.strip()]
    by_id = {t["task_id"]: t for t in tasks}
    for tid in focus:
        if tid not in by_id:
            print(f"\n!! t{tid} not in this site's task list")
            continue
        print("\n" + "=" * 78)
        print(f"TASK {tid}: {by_id[tid]['intent']}")
        print(f"REFERENCE: {by_id[tid].get('reference')}")
        for label, res in (("OLD", old[tid]), ("NEW", new[tid])):
            title, cos, it = res
            if not title:
                print(f"\n  [{label}] (gate injected NOTHING)")
                continue
            print(f"\n  [{label}] «{title}»  cos={cos}")
            print(f"        when: {it.description}")
            print(f"        rule: {it.content}")

    if args.out:
        rows = ["| task | OLD injected | NEW injected |", "|---|---|---|"]
        for t in tasks:
            k = t["task_id"]
            rows.append(f"| t{k} | {old[k][0] or '—'} | {new[k][0] or '—'} |")
        open(args.out, "w").write("\n".join(rows) + "\n")
        print(f"\nfull table -> {args.out}")
    print(f"\nprobe cost ${llm.spent_usd:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
