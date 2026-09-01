"""Replay contrast_rollouts (L2 writer) on REAL recorded inputs, old vs new direction prompts.

Fidelity notes, honestly:
  * all-wrong (nc==0) sources are HIGH fidelity — the L2 input there is judge reasons + L1 texts,
    both fully recorded (events.jsonl reasons; memory.json L1 content joined by title).
  * majority-wrong sources need the successful rollouts' TRACES, whose page observations were
    never persisted. We rebuild "thought -> action @ url" skeletons from wa_step events and label
    the result APPROXIMATE. The lesson's SHAPE (procedure transcript vs decision) is what the
    direction text controls, and that survives the approximation.

    .venv-wa/bin/python scripts/replay_l2_writer.py <run_dir> <task_id> [--old]
"""
from __future__ import annotations

import collections
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))

from dotenv import load_dotenv

load_dotenv(os.path.join(REPO, ".env"))
from hippo.llm import LLMClient                      # noqa: E402
from hippo.schema import ReasoningItem               # noqa: E402
from hippo.wa import brain as B                      # noqa: E402
from hippo.wa.data import _raw_config_text           # noqa: E402

# the direction strings as they were when the analyzed runs were produced (pre-2026-08-13)
OLD_DIRS = {
    "majority_wrong": ("Most rollouts FAILED; a few succeeded. REMEMBER the reliable procedure the "
                       "successful minority used to get it right."),
}
OLD_L1 = (
    "You are an expert web-navigation analyst distilling a lesson from ONE failed rollout. It "
    "{outcome_clause}\nExtract lessons that would prevent this failure on future tasks on this "
    "site.\n" + B._ITEM_FORMAT
)


def load_task_inputs(run_dir, task_id, tag="withmem"):
    verdicts = {}
    l1_titles = []
    steps = collections.defaultdict(list)
    for ln in open(os.path.join(run_dir, "events.jsonl")):
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if str(d.get("task_id")) != str(task_id) and str(d.get("task")) != str(task_id):
            continue
        k = d.get("kind")
        if k == "wa_judge" and d.get("tag") == tag:
            verdicts[d["rollout"]] = {"outcome": d["outcome"], "reason": d.get("reason", "")}
        elif k == "wa_write_l1":
            l1_titles.append(d["item"]["title"])
        elif k == "wa_step" and d.get("tag") == tag:
            steps[d["rollout"]].append(d)
    mem = {i["title"]: i for i in json.load(open(os.path.join(run_dir, "memory.json")))["reasoning"]
           if i["layer"] == "L1"}
    n = max(verdicts) + 1
    ordered = [verdicts[r] for r in range(n)]
    ok = [v["outcome"] == "genuine" for v in ordered]
    # join L1 items to failing rollouts in write order (one item per failure, same sequence)
    l1_items: list = [[] for _ in range(n)]
    fail_idx = [r for r in range(n) if ordered[r]["outcome"] == "failure"]
    for r, title in zip(fail_idx, l1_titles):
        it = mem.get(title)
        if it:
            l1_items[r] = [ReasoningItem(title=it["title"], description=it.get("description", ""),
                                         content=it["content"], scope=it["scope"],
                                         outcome=it.get("outcome", ""), layer="L1")]
    rollouts = []
    for r in range(n):
        tr = "\n".join(f"step {s['step']+1}: {s.get('raw','')} -> {s['action']} @ {s.get('url','')}"
                       for s in sorted(steps[r], key=lambda x: x["step"]))
        rollouts.append({"trace": tr + "\n[NOTE: page observations omitted in replay]"})
    return rollouts, ordered, ok, l1_items


def main():
    run_dir, task_id = sys.argv[1], sys.argv[2]
    use_old = "--old" in sys.argv
    RAW = {str(r["task_id"]): r for r in json.loads(_raw_config_text())}
    intent = RAW[str(task_id)]["intent"]
    rollouts, verdicts, ok, l1_items = load_task_inputs(run_dir, task_id)
    nc, n = sum(ok), len(ok)
    if use_old and nc > 0 and nc * 2 < n:
        # swap in the pre-edit direction by monkeypatching the branch string source
        orig = B.WaBrain.contrast_rollouts

        def patched(self, site, intent, rollouts, verdicts, l1_items, max_items=1, ok=None):
            import types
            src = orig.__func__ if isinstance(orig, types.MethodType) else orig
            return src(self, site, intent, rollouts, verdicts, l1_items, max_items, ok)
        # simpler: textual patch of the module constant is not possible (string is inline);
        # for the old variant we call the same function but overwrite the direction afterwards
        # via a shim system prompt. Implemented below by direct reconstruction instead.
    llm = LLMClient(model="gpt-5.6-sol", embed_model="local/BAAI/bge-small-en-v1.5",
                    max_tokens=2000, budget_usd=20, min_interval=1.0)
    br = B.WaBrain(llm)
    if use_old:
        # rebuild the exact old prompt path: only majority-wrong differs from HEAD
        assert nc > 0 and nc * 2 < n, "old variant only differs on the majority-wrong branch"
        direction = OLD_DIRS["majority_wrong"]
        sys_p = B._L2_SYS.format(direction=direction, max_items=1)
        lines = [f"SITE: shopping", f"TASK: {intent}", f"\n{n} rollouts, {nc} succeeded:"]
        for i, (r, v, is_ok, items) in enumerate(zip(rollouts, verdicts, ok, l1_items)):
            tag = "OK" if is_ok else "WRONG"
            if items:
                body = "L1 lesson: " + " | ".join(f"{it.title}: {it.content}" for it in items)
            elif is_ok:
                body = "TRACE (genuine success — study why it worked):\n  " + r["trace"]
            else:
                body = "(no usable trajectory)"
            lines.append(f"\n--- rollout {i+1} [{tag}] ({v['reason']})\n  {body}")
        out = br._json(llm.chat([{"role": "system", "content": sys_p},
                                 {"role": "user", "content": "\n".join(lines)}],
                                temperature=0.0, drop_params=True))
        items = br._items(out, "site:shopping", "success", 1, layer="L2")
    else:
        items = br.contrast_rollouts("shopping", intent, rollouts, verdicts, l1_items, ok=ok)
    print(f"== t{task_id} nc={nc}/{n} [{'OLD' if use_old else 'NEW'}] ==")
    for it in items:
        print(f"标题: {it.title}\n适用: {it.description}\n内容: {it.content}")
    print(f"(cost ${llm.spent_usd:.3f})")


if __name__ == "__main__":
    main()
