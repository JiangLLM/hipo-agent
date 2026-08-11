"""Measure — instead of asking an LLM to guess — where the N rollouts of a task diverged.

WHY. L2 today is one LLM call that reads all N rollouts and writes a sentence about what
separated the successes from the failures. The only ground truth it gets is a terminal 0/1
per rollout; nothing tells it WHICH STEP went wrong. Honest Lying (arXiv 2605.29463) measured
what happens in exactly that setup: on ALFWorld, 0 of 121 reflections named the correct
target object, because binary feedback leaves an information vacuum the reflector fills with
plausible-sounding but causally wrong diagnoses.

The escape is that an LLM agent's history is fully observable text, so "what separated them"
is a MEASUREMENT, not an estimate. This script does the zero-extra-rollout version: it takes
the rollouts we already paid for, aligns them into a prefix tree over states, and reads off
the earliest node where the outcome distribution splits. That node is the measured divergence
point, and the gap between its children is a measured delta in success rate — the step-level
signal the 0/1 reward does not carry.

STATE ABSTRACTION. Raw actions cannot be compared across rollouts: WebArena bids are assigned
per page load, so the same Reviews tab shows up as click('1676') in one rollout and
click('1576') in another. We key each step on (url, action_type, payload) instead, where the
url is the one logged by wa_step, i.e. the page REACHED by that action, and the payload is the
literal text for fill / select_option / send_msg_to_user, dropped for click / hover. Two
rollouts clicking different controls that land on the same page therefore look identical at
that step, so the reported depth is an UPPER bound on how early the divergence really was.

    python3 scripts/wa_divergence_probe.py runs/wa_shopping_*/events.jsonl \
        --out runs/shopping_divergence.md
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import re
import sys
from urllib.parse import urlsplit

SUCCESS = "genuine"  # judge outcome that counts as a real success (fluke is not)
OPAQUE = ("click", "hover")  # bid-only actions: the argument is not comparable across rollouts


def norm_url(url: str) -> str:
    """Drop scheme+host (port identifies the site), keep path and sorted query."""
    if not url:
        return ""
    p = urlsplit(url)
    q = "&".join(sorted(p.query.split("&"))) if p.query else ""
    return f"{p.path}?{q}" if q else p.path


def norm_action(action: str) -> str:
    """(action_type, payload) with the payload kept only when it is stable across rollouts."""
    if not action:
        return "?"
    m = re.match(r"^(\w+)\((.*)\)\s*$", action.strip(), re.S)
    if not m:
        return action.strip()[:40]
    kind, args = m.group(1), m.group(2)
    if kind in OPAQUE:
        return kind
    texts = re.findall(r"""['"](.*?)['"]""", args, re.S)
    payload = texts[-1] if texts else ""
    payload = re.sub(r"\s+", " ", payload).strip().lower()[:60]
    return f"{kind}({payload})" if payload else kind


def load(paths):
    """-> {task_id: {"goal", "rollouts": {rid: {"steps": [...], "ok": bool, ...}}, "l2", "l1"}}"""
    tasks = collections.defaultdict(
        lambda: {"goal": "", "rollouts": collections.defaultdict(
            lambda: {"steps": [], "ok": None, "reward": None, "reason": "", "answer": ""}), "l2": [], "l1": []})
    for path in paths:
        with open(path) as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = e.get("kind")
                if kind == "wa_episode_start":
                    t = tasks[e["task_id"]]
                    t["goal"] = t["goal"] or e.get("goal", "")
                elif kind == "wa_step":
                    tasks[e["task_id"]]["rollouts"][e["rollout"]]["steps"].append(
                        (e.get("step", 0), norm_url(e.get("url", "")), norm_action(e.get("action", "")),
                         e.get("thought", ""), e.get("action", "")))
                elif kind == "wa_episode_end":
                    r = tasks[e["task_id"]]["rollouts"][e["rollout"]]
                    r["reward"] = e.get("reward")
                    r["answer"] = e.get("stop_answer") or ""
                elif kind == "wa_judge":
                    r = tasks[e["task_id"]]["rollouts"][e["rollout"]]
                    r["ok"] = e.get("outcome") == SUCCESS
                    r["outcome"] = e.get("outcome")
                    r["reason"] = e.get("reason", "")
                elif kind == "wa_write_l2":
                    tasks[e.get("task", e.get("task_id"))]["l2"].append(e)
                elif kind == "wa_write_l1":
                    tasks[e.get("task", e.get("task_id"))]["l1"].append(e)
    for t in tasks.values():
        for r in t["rollouts"].values():
            r["steps"].sort(key=lambda s: s[0])
    return tasks


def divergence(rollouts):
    """Walk the shared prefix; return the first depth where the outcome distribution splits.

    At each depth the rollouts still travelling together are bucketed by their state token.
    A bucket is a branch. The node is a DIVERGENCE if two branches differ in success rate;
    we return it with delta = best branch SR - worst branch SR. If every branch has the same
    SR we descend into the largest one (the others carry no contrast to explain).
    """
    alive = [r for r in rollouts if r["ok"] is not None]
    depth = 0
    while len(alive) > 1:
        buckets = collections.defaultdict(list)
        for r in alive:
            key = (r["steps"][depth][1], r["steps"][depth][2]) if depth < len(r["steps"]) else ("<END>", "<END>")
            buckets[key].append(r)
        rates = {k: sum(x["ok"] for x in v) / len(v) for k, v in buckets.items()}
        if len(buckets) > 1 and max(rates.values()) > min(rates.values()):
            best = max(rates, key=lambda k: (rates[k], len(buckets[k])))
            worst = min(rates, key=lambda k: (rates[k], -len(buckets[k])))
            return {"depth": depth, "delta": rates[best] - rates[worst],
                    "branches": [(k, len(buckets[k]), rates[k]) for k in
                                 sorted(buckets, key=lambda k: -rates[k])],
                    "best": best, "worst": worst,
                    "best_rollouts": buckets[best], "worst_rollouts": buckets[worst]}
        if all(k == ("<END>", "<END>") for k in buckets):
            break
        alive = max(buckets.values(), key=len)
        depth += 1
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("events", nargs="+", help="events.jsonl (globs ok)")
    ap.add_argument("--out", default="", help="write a markdown report here")
    args = ap.parse_args()

    paths = [p for pat in args.events for p in sorted(glob.glob(pat))]
    if not paths:
        print("no events.jsonl matched", file=sys.stderr)
        return 1
    tasks = load(paths)

    contrast = collections.Counter()   # (n, n_success) -> tasks
    l2_by_contrast = collections.Counter()
    found, missing, deltas, depths = [], [], [], []
    for tid, t in sorted(tasks.items()):
        rs = [r for r in t["rollouts"].values() if r["ok"] is not None]
        if not rs:
            continue
        n, nc = len(rs), sum(r["ok"] for r in rs)
        contrast[(n, nc)] += 1
        if t["l2"]:
            l2_by_contrast["all-fail (nc=0)" if nc == 0 else
                           "all-success (nc=n)" if nc == n else "mixed"] += len(t["l2"])
        if not (0 < nc < n):
            continue
        d = divergence(rs)
        (found if d else missing).append((tid, t, n, nc, d))
        if d:
            deltas.append(d["delta"])
            depths.append(d["depth"])

    n_tasks = sum(contrast.values())
    n_mixed = sum(c for (n, nc), c in contrast.items() if 0 < nc < n)
    out = []
    w = out.append
    w("# WebArena rollout divergence probe\n")
    w(f"Source: {', '.join(paths)}\n")
    w("## Is there any contrast to learn from?\n")
    w(f"- tasks judged: **{n_tasks}**")
    w(f"- all rollouts failed: **{sum(c for (n, nc), c in contrast.items() if nc == 0)}**")
    w(f"- all rollouts succeeded: **{sum(c for (n, nc), c in contrast.items() if nc == n)}**")
    w(f"- mixed (the only groups with within-task contrast): **{n_mixed}** "
      f"({n_mixed / max(n_tasks, 1):.0%})\n")
    if l2_by_contrast:
        w("L2 lessons written, by how much contrast the group actually had:\n")
        for k in ("mixed", "all-fail (nc=0)", "all-success (nc=n)"):
            if l2_by_contrast[k]:
                w(f"- {k}: **{l2_by_contrast[k]}**")
        w("")
    w("## Can the divergence be localized from the rollouts we already have?\n")
    w(f"- mixed tasks with a measurable split point: **{len(found)}/{n_mixed}**")
    if deltas:
        deltas_s, depths_s = sorted(deltas), sorted(depths)
        w(f"- measured delta in success rate at the split (median): **{deltas_s[len(deltas_s)//2]:.2f}**")
        w(f"- split depth in steps (median): **{depths_s[len(depths_s)//2]}**, "
          f"min {min(depths)}, max {max(depths)}")
    w("")
    w("## Per-task detail\n")
    for tid, t, n, nc, d in found:
        w(f"### task {tid} — {nc}/{n} genuine")
        w(f"*{t['goal'][:160]}*\n")
        w(f"Split at step **{d['depth']}**, measured delta **{d['delta']:.2f}**:\n")
        for (url, act), cnt, rate in d["branches"]:
            w(f"- `{act}` on `{url[:80] or '/'}` — {cnt} rollouts, success {rate:.2f}")
        for label, key in (("winning", "best_rollouts"), ("losing", "worst_rollouts")):
            r = d[key][0]
            if d["depth"] < len(r["steps"]):
                st = r["steps"][d["depth"]]
                w(f"\n{label} branch, rollout thought: *{st[3][:200]}*")
                w(f"  raw action: `{st[4][:90]}`")
        if t["l2"]:
            w("\nL2 actually written for this task:")
            for e in t["l2"]:
                it = e.get("item", {})
                w(f"- **{it.get('title', '')}** (nc={e.get('nc')}/{e.get('n')})")
        else:
            w("\nL2 written for this task: none")
        w("")
    if missing:
        w("## Mixed tasks with no measurable split\n")
        for tid, t, n, nc, _ in missing:
            w(f"- task {tid} ({nc}/{n}): {t['goal'][:100]}")
        w("")

    text = "\n".join(out)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text)
        print(f"wrote {args.out}")
    print("\n".join(out[:40]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
