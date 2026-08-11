"""Does the reworded inject gate refuse the lessons that hurt, and keep the ones that help?

The gate picks at most one lesson per task, or none. On shopping_admin it accepted a lesson on 22
tasks the baseline already answered 8/8, and those injections cost 12 rollouts; the reworded
prompt is supposed to say "no lesson" more often on exactly those. This replays the decision
offline, on runs we already have, so we learn that before paying for another 109-task run.

It reconstructs each task's candidate pool the way the runner would (the L2 items written earlier
in the stream, cosine top-5 over "title. description"), then asks the OLD and the NEW prompt the
same question. Judge the result by the two columns that matter: does NEW refuse on the tasks where
injection lost rollouts, and does it still accept on the tasks where injection won them.

    .venv-wa/bin/python scripts/gate_prompt_ab.py                    # the 8 decisive tasks
    .venv-wa/bin/python scripts/gate_prompt_ab.py --all              # every task in the run
    .venv-wa/bin/python scripts/gate_prompt_ab.py --run <run_dir>
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))

# The prompt as it was when the runs under analysis were produced.
OLD_PROMPT = (
    "Given the CURRENT web task and a numbered list of candidate past lessons, pick the ONE most "
    "APPLICABLE lesson. It must genuinely fit this task's goal and the controls/pages it needs — "
    "matching topic words is NOT enough (e.g. a task about the 'main' branch needs the branch-"
    "specific lesson, not a generic Contributors one). If NONE genuinely applies, return -1 — "
    "injecting nothing is better than a misleading lesson.\n"
    'Respond JSON {"idx": int} (the 0-based index, or -1).'
)

# --- candidate rewordings, tested side by side ------------------------------------------------
# A: calibration. The gate has no idea how strong the agent is, so it treats every apt-sounding
#    lesson as useful. Tell it the measured baseline.
V_CALIB = (
    "A web agent is about to attempt the task below. This agent is strong: on this site it already "
    "solves about 6 in 10 tasks perfectly with no help at all, reading pages carefully, following "
    "menus, filtering grids and copying values exactly. Handing it a lesson OVERRIDES its own "
    "judgement, so on a task it would have got right, a lesson can only do harm.\n"
    "From the candidates, pick one ONLY if this task is likely to defeat that agent and the lesson "
    "speaks to the reason. Otherwise return -1.\n"
    'Respond JSON {"idx": int} (the 0-based index, or -1).'
)

# B: name the failure. If the gate cannot say what concrete mistake the lesson prevents HERE, it
#    is matching on topic, which is the failure mode we measured.
V_NAME = (
    "Given the CURRENT web task and candidate past lessons, decide whether to hand the agent one.\n"
    "Pick a lesson only if you can name the specific mistake it prevents ON THIS TASK — the wrong "
    "page it stops you opening, the row it stops you missing, the value it stops you misreading. "
    "If you cannot name that mistake, the lesson is only topically related and you must return -1.\n"
    'Respond JSON {"idx": int, "prevents": str} — "prevents" is that mistake, or "" when idx is -1.'
)

# C: default no. Make refusal the resting state and require the lesson to earn its place.
V_DEFAULT_NO = (
    "Default: hand the agent NOTHING. Most tasks are done better without advice, because a lesson "
    "written for an earlier task overrides the agent's own reading of this one.\n"
    "Override the default only when a candidate lesson is clearly about the same difficulty this "
    "task presents, and the task is one a careful agent could plausibly get wrong. Otherwise -1.\n"
    'Respond JSON {"idx": int} (the 0-based index, or -1).'
)

DEFAULT_RUN = "runs/wa_fleet_shopping_admin_readonly_20260807_225320_20260807_225403"
# tasks whose outcome injection actually changed, worst first, then the clear wins
DECISIVE = [113, 217, 216, 203, 185, 116, 120, 5, 123, 121]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=DEFAULT_RUN)
    ap.add_argument("--all", action="store_true", help="every task, not just the decisive ones")
    ap.add_argument("--model", default="gpt-5.6-sol")
    ap.add_argument("--interval", type=float, default=1.5, help="seconds between LLM calls")
    args = ap.parse_args()

    from dotenv import load_dotenv

    load_dotenv(os.path.join(REPO, ".env"))          # explicit: a bare load_dotenv() depends on cwd
    from hippo.llm import LLMClient
    from hippo.wa import brain as B
    from hippo.wa.data import _raw_config_text

    llm = LLMClient(model=args.model, embed_model="local/BAAI/bge-small-en-v1.5",
                    max_tokens=8000, budget_usd=float(os.environ.get("BUDGET", "50")),
                    min_interval=args.interval)
    # Fail loudly instead of silently falling through to api.openai.com on a key that is not
    # funded: litellm reports that as a RateLimitError, which reads like throttling and sent an
    # earlier debugging session chasing the wrong problem for an hour.
    if not llm.api_base:
        raise SystemExit("LLM_API_BASE is not set — refusing to run, calls would go to OpenAI")
    print(f"gateway: {llm.api_base}")

    run = args.run if os.path.isabs(args.run) else os.path.join(REPO, args.run)
    RAW = {int(r["task_id"]): r for r in json.loads(_raw_config_text())}
    order, writes = [], []
    ends = collections.defaultdict(list)
    for ln in open(os.path.join(run, "events.jsonl")):
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            continue
        k = d.get("kind")
        if k == "wa_task" and d.get("tag") == "withmem":
            order.append(d["task_id"])
        elif k == "wa_write_l2":
            writes.append((len(order), d["item"]["title"]))       # stream position of the write
        elif k == "wa_episode_end":
            ends[(d.get("tag"), d["task_id"])].append(1 if d.get("reward") else 0)
    mem = {i["title"]: i for i in json.load(open(os.path.join(run, "memory.json")))["reasoning"]
           if i.get("layer") == "L2"}
    score = lambda arm, t: sum(ends[(arm, t)]) / len(ends[(arm, t)])

    def ask(prompt, intent, items):
        menu = "\n".join(f"[{i}] {it['title']}: {it['content']}" for i, it in enumerate(items))
        out = B.WaBrain._json(llm.chat(
            [{"role": "system", "content": prompt},
             {"role": "user", "content": f"CURRENT TASK: {intent}\n\nCANDIDATE LESSONS:\n{menu}"}],
            temperature=0.0, drop_params=True))
        i = out.get("idx", -1)
        return i if isinstance(i, int) and 0 <= i < len(items) else -1

    wanted = [t for t in order if ("nomem", t) in ends] if args.all \
        else [t for t in DECISIVE if t in order and ("nomem", t) in ends]
    print(f"run: {os.path.basename(run)}   tasks: {len(wanted)}\n")
    PROMPTS = [("OLD", OLD_PROMPT), ("NEW", B._L2_SELECT_SYS),
               ("CALIB", V_CALIB), ("NAME", V_NAME), ("NO-BY-DEF", V_DEFAULT_NO)]
    print(f"{'task':>6} {'nomem':>6} {'withmem':>8} {'cost':>7}  " +
          "  ".join(f"{n:<15}" for n, _ in PROMPTS))

    rows = []
    for t in wanted:
        pos = order.index(t)
        pool, seen = [], set()
        for p, title in writes:                       # only lessons that existed by then
            if p <= pos and title in mem and title not in seen:
                seen.add(title)
                pool.append(mem[title])
        if not pool:
            continue
        q = np.asarray(llm.embed([RAW[t]["intent"]])[0], float)
        q /= np.linalg.norm(q) + 1e-9
        scored = []
        for it in pool:
            v = np.asarray(llm.embed([f"{it['title']}. {it['description']}"])[0], float)
            v /= np.linalg.norm(v) + 1e-9
            scored.append((float(q @ v), it))
        scored.sort(key=lambda x: -x[0])
        top = [it for _, it in scored[:5]]

        picks = {n: ask(p, RAW[t]["intent"], top) for n, p in PROMPTS}
        nm, wm = score("nomem", t), score("withmem", t)
        cell = lambda i: "none" if i < 0 else top[i]["title"][:14]
        print(f"  t{t:<5d} {nm*8:5.0f}/8 {wm*8:7.0f}/8 {(wm-nm)*8:+7.0f}  " +
              "  ".join(f"{cell(picks[n]):<15}" for n, _ in PROMPTS))
        rows.append((t, nm, wm, picks))

    hurt = [r for r in rows if r[2] < r[1]]
    helped = [r for r in rows if r[2] > r[1]]
    print(f"\n{'prompt':<12} {'refuses on HURT':>16} {'refuses on HELPED':>18} {'net rollouts':>13}")
    for n, _ in PROMPTS:
        rh = [r for r in hurt if r[3]["OLD"] >= 0 and r[3][n] < 0]
        rp = [r for r in helped if r[3]["OLD"] >= 0 and r[3][n] < 0]
        net = (sum(r[1] - r[2] for r in rh) - sum(r[2] - r[1] for r in rp)) * 8
        print(f"{n:<12} {len(rh):>10}/{len(hurt):<5} {len(rp):>12}/{len(helped):<5} {net:>+13.0f}")
    print(f"\ncost ${llm.spent_usd:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
