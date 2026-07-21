"""Build the v2 file-keyed mechanism-notes bank OFFLINE from existing trajectories.

No rollouts needed: the big run saved every attempt of the 116 learn tasks. For each
task we take the best trace (a verified-success attempt if the judge found one, else
attempt 0) and ask the model for the VERIFIED facts the attempt established about
specific files — contracts, gotchas, data flow — each anchored to a class/method.
Behavior advice ("write a test first") is explicitly out of scope: the postmortem
showed failures are decided by subsystem understanding, not workflow discipline.

    .venv/bin/python scripts/build_notes.py runs/swe_big_django_*/ notes_v2.json
"""
from __future__ import annotations

import glob
import json
import re
import sys

SYS = (
    "You are building a REPOSITORY NOTEBOOK from one debugging session. Extract facts "
    "the agent VERIFIED about how specific source files work — by reading the code or "
    "observing execution. These notes will be shown to a future agent the moment it "
    "opens the same file while fixing a DIFFERENT issue.\n"
    'Respond JSON {"notes": [{"file": str (repo-relative path, e.g. '
    '"django/db/models/sql/query.py"), "anchor": str (the class/method the fact is '
    'about, e.g. "Query.split_exclude"), "note": str (ONE sentence: a mechanism fact — '
    "a contract, a gotcha, where data flows, what a method silently does or fails to "
    "do)}]}.\n"
    "Rules: only facts VERIFIED in this session (visible in code the agent read or "
    "output it saw) — no speculation; no workflow/testing advice; no issue-specific "
    "values (ticket numbers, literal user inputs); at most 4 notes, fewer is fine; "
    "skip facts any developer would already know — keep only what took work to learn."
)


def main() -> None:
    run_dir = sys.argv[1].rstrip("/")
    out_path = sys.argv[2]
    model = sys.argv[3] if len(sys.argv) > 3 else "anthropic/claude-haiku-4-5"
    from dotenv import load_dotenv

    load_dotenv("/Users/yutongs/Projects/hipo-agent/.env")
    from hippo.llm import LLMClient
    from hippo.swe.notes import FileNotes
    from hippo.swe.rollout import compact_trace

    # which attempt was a verified success, per task (from the run's events)
    best_attempt: dict[str, int] = {}
    for line in open(f"{run_dir}/events.jsonl"):
        if '"kind": "swe_task"' not in line:
            continue
        d = json.loads(line)
        if d.get("tag") != "withmem":
            continue
        for r, v in enumerate(d.get("judge", [])):
            if v.get("success") and v.get("verified"):
                best_attempt[d["instance"]] = r
                break

    llm = LLMClient(model=model, embed_model="local/BAAI/bge-small-en-v1.5",
                    max_tokens=8000, budget_usd=80)
    notes = FileNotes()
    tasks = sorted({p.split("/")[-1].split(".")[0]
                    for p in glob.glob(f"{run_dir}/trajs/*.withmem.a0.traj.json")})
    n_calls = 0
    for iid in tasks:
        a = best_attempt.get(iid, 0)
        try:
            d = json.load(open(f"{run_dir}/trajs/{iid}.withmem.a{a}.traj.json"))
        except FileNotFoundError:
            continue
        trace = compact_trace(d["messages"], max_chars=14000)
        raw = llm.chat([{"role": "system", "content": SYS},
                        {"role": "user", "content": f"SESSION TRACE ({iid}):\n{trace}"}],
                       temperature=0.0, drop_params=True)
        m = re.search(r"\{.*\}", raw, re.S)
        try:
            out = json.loads(re.sub(r'\\(?![\\/"bfnrtu])', r"\\\\", m.group(0))) if m else {}
        except json.JSONDecodeError:
            out = {}
        n_calls += 1
        for n in out.get("notes", [])[:4]:
            if isinstance(n, dict) and n.get("file", "").endswith(".py") and n.get("note"):
                notes.add(n["file"].lstrip("/").removeprefix("testbed/"),
                          str(n.get("anchor", "")).strip(), str(n["note"]).strip())
        if n_calls % 20 == 0:
            print(f"{n_calls}/{len(tasks)} tasks, {notes.stats()}")
    notes.save(out_path)
    print(f"done: {notes.stats()}, cost ${llm.spent_usd:.2f}, saved {out_path}")


if __name__ == "__main__":
    main()
