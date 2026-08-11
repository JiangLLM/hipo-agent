"""Classify every WebArena task as READ-ONLY or MUTATING, and freeze the result.

Why this exists: how a task is EVALUATED does not tell you whether it changes server state.
Our old filter kept only `eval_types == ["string_match"]`, which (a) threw away ~185 harmless
url_match / navigation-program_html tasks on sites we already run, and (b) still let 11 genuinely
state-changing tasks through (shopping 792-798 "Buy the...", gitlab 783/789, shopping_admin 790,
reddit 723). Statefulness is what actually matters, for two reasons:

  * reset discipline — a mutating task cannot be run as 8 concurrent rollouts against one shared
    deployment: rollout 1's purchase/post/edit is visible to rollouts 2-8, so both their rewards
    and the memory we distil from them are garbage. Mutating tasks must be serialised with a reset
    between rollouts (browsergym's full_reset, 200-500s each), or run at N=1.
  * honest coverage — "we run 230 of 812" should be a deliberate choice, not an artefact of a
    filter written around the eval field.

`require_reset` in test.raw.json is FALSE for all 812 tasks, so upstream gives us nothing to use.

The classification is therefore derived twice and reconciled:

  heuristic (deterministic, auditable):
    - any program_html checkpoint whose `url` is not "last"  -> MUTATING. Verified by hand: every
      such task edits something (concrete URLs like .../product/edit/id/1481, or `func:` helpers
      such as shopping_get_latest_order_url() which resolve an object the agent had to create).
    - any program_html `locator` starting with "func:"       -> MUTATING (e.g.
      shopping_get_sku_latest_review_rating, gitlab_get_project_memeber_role).
    - intent opening with an action verb                     -> MUTATING.
    - otherwise                                              -> READ-ONLY.

  llm (catches what regexes miss): judges the intent + eval, answering only "does completing this
    task write anything to the server".

Where they disagree the LLM wins but the disagreement is recorded in the output, so a human can
audit exactly the tasks whose classification was not mechanical. Run it once and commit the JSON;
the runner then reads a frozen manifest instead of re-deriving anything at run time.

    .venv-wa/bin/python scripts/classify_wa_tasks.py config/wa_task_class.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

# Verbs that open a mutating instruction. Deliberately generous: a false "mutating" only costs us
# throughput (the task gets serialised), a false "read-only" corrupts an entire task's rollouts.
VERBS = (
    r"^\s*(buy|add|create|post|submit|make|draft|purchase|order|set|update|change|edit|delete|"
    r"remove|cancel|assign|invite|fork|star|subscribe|upvote|downvote|reply|comment|like|disable|"
    r"enable|approve|reject|apply|increase|decrease|repost|publish|open an?|start an?|write|send|"
    r"fill|mark|move|rename|transfer|duplicate|archive|close|merge|re-?post|upload|"
    r"reorder|follow|unfollow|report|ban|lock|pin|tag|label|schedule|reserve|book|"
    r"register|sign up|rate|promote|notify|reduce|raise|adjust|configure|enroll|clone|push|"
    r"decline|refund|issue|grant|revoke|leave|unsubscribe|dismiss|resolve|reopen)\b"
)
# NOT in VERBS on purpose: "check out"/"checkout". In these intents it always means "go look at"
# (t44 "Check out my todos", t156 "Checkout merge requests assigned to me") — navigation, not a
# purchase. The real purchase tasks all open with "Buy".

# "Fill the form but do not save" tasks LOOK mutating and are not: the eval reads a form control's
# value on the page the agent ended on, so nothing was ever submitted. Had it been saved, the app
# would have redirected and the eval would have to check a concrete URL instead of "last". This
# covers the Draft-a-refund-message / Draft-a-price-rule / Create-a-report families (25 tasks).
_FORM_VALUE = re.compile(r"\.(value|selectedIndex|checked)\b")


def is_unsaved_form(task: dict) -> bool:
    checks = task["eval"].get("program_html") or []
    if not checks:
        return False
    return all(
        str(c.get("url", "")).startswith("last") and _FORM_VALUE.search(str(c.get("locator", "")))
        for c in checks
    )

CLASSIFY_SYS = """You classify WebArena web-agent tasks by whether completing them WRITES anything \
to the server.

MUTATING: the task cannot succeed unless server state changes — an order placed, a post or comment \
or review created, a setting/price/description edited, a member invited, an issue opened, an item \
added to a cart or wishlist, something deleted or cancelled.

READ_ONLY: the task only reads — answering a question, finding/comparing information, navigating to \
a page, computing a total from existing data, getting directions. Filtering, sorting, searching and \
generating an on-screen report are READ_ONLY: they change nothing server-side. Logging in is not a \
mutation (the harness logs in anyway).

You are given the intent and the evaluation spec. The evaluation is a strong hint: a check against \
a concrete page URL (e.g. a product-edit page, an order page, a members page) or against a helper \
function that resolves a newly created object usually means the agent had to create/change that \
object. A check against "last" (the page the agent ended on) with no locator usually means mere \
navigation.

Answer JSON only: {"mutating": true|false, "why": "<one short clause>"}"""


def heuristic(task: dict) -> tuple[bool, list[str]]:
    """Return (mutating, reasons)."""
    reasons = []
    for chk in task["eval"].get("program_html") or []:
        url = str(chk.get("url", ""))
        if not url.startswith("last"):
            reasons.append(f"program_html url={url[:48]}")
        if str(chk.get("locator", "")).startswith("func:"):
            reasons.append("program_html locator=func:")
    if re.match(VERBS, task.get("intent", ""), re.I):
        reasons.append("intent opens with an action verb")
    return bool(reasons), reasons


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--model", default="gpt-5.6-sol")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--skip-llm", action="store_true", help="heuristic only (no cost, less accurate)")
    args = ap.parse_args()

    sys.path.insert(0, "src")
    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    except Exception:
        pass
    from hippo.wa.data import _raw_config_text

    tasks = json.loads(_raw_config_text())
    print(f"{len(tasks)} tasks")

    heur = {}
    for t in tasks:
        m, why = heuristic(t)
        heur[t["task_id"]] = (m, why)
    n_h = sum(1 for m, _ in heur.values() if m)
    print(f"heuristic: {n_h} mutating / {len(tasks) - n_h} read-only")

    llm_verdict = {}
    if not args.skip_llm:
        from concurrent.futures import ThreadPoolExecutor

        from hippo.llm import LLMClient

        llm = LLMClient(model=args.model, embed_model="local/BAAI/bge-small-en-v1.5",
                        max_tokens=2000, budget_usd=float(os.environ.get("BUDGET", "1000")))

        def judge(t):
            ev = {k: v for k, v in t["eval"].items() if v}
            usr = (f"SITES: {t['sites']}\nINTENT: {t['intent']}\n"
                   f"EVAL: {json.dumps(ev, ensure_ascii=False)[:1500]}")
            try:
                raw = llm.chat([{"role": "system", "content": CLASSIFY_SYS},
                                {"role": "user", "content": usr}], temperature=0.0)
                m = re.search(r"\{.*\}", raw or "", re.S)
                d = json.loads(m.group(0)) if m else {}
                return t["task_id"], bool(d.get("mutating")), str(d.get("why", ""))[:160]
            except Exception as exc:  # noqa: BLE001 - fall back to the heuristic for this task
                return t["task_id"], None, f"llm error: {type(exc).__name__}"

        with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
            for i, (tid, m, why) in enumerate(ex.map(judge, tasks)):
                llm_verdict[tid] = (m, why)
                if (i + 1) % 100 == 0:
                    print(f"  judged {i + 1}/{len(tasks)}  (${llm.spent_usd:.2f})")
        print(f"llm done, cost ${llm.spent_usd:.2f}")

    rows, disagree = [], []
    for t in tasks:
        tid = t["task_id"]
        hm, why = heur[tid]
        lm, lwhy = llm_verdict.get(tid, (None, ""))
        # Decision rule: the UNION of both signals, then one evidence-based exemption.
        #
        # Union, not "LLM wins": the two error directions are not symmetric. Calling a read-only
        # task mutating only costs throughput (it gets serialised); calling a mutating task
        # read-only corrupts every rollout of that task. The LLM specifically fails on tasks whose
        # reference answer is "N/A" — it reads "nothing needs to change" and answers read-only,
        # but the agent still goes and upvotes / edits the address / adds the maintainer, so the
        # server is dirty either way (t723, t783, t791, t794-798). What we need to know is whether
        # the agent might WRITE, not whether the task requires a write.
        final = bool(hm or lm)
        if final and is_unsaved_form(t):
            final = False
            lwhy = "fill-the-form-only: eval reads a form control value on the final page"
        if lm is not None and lm != hm:
            disagree.append({"task_id": tid, "sites": t["sites"], "intent": t["intent"][:150],
                             "heuristic": hm, "heuristic_why": why, "llm": lm, "llm_why": lwhy,
                             "final_mutating": final})
        rows.append({
            "task_id": tid,
            "sites": t["sites"],
            "template_id": t.get("intent_template_id", -1),
            "eval_types": t["eval"]["eval_types"],
            "mutating": final,
            "heuristic": hm,
            "llm": lm,
            "why": (lwhy if lm is not None else "; ".join(why)) or "no mutation signal",
        })

    n_m = sum(1 for r in rows if r["mutating"])
    out = {
        "n_tasks": len(rows),
        "n_mutating": n_m,
        "n_readonly": len(rows) - n_m,
        "model": None if args.skip_llm else args.model,
        "note": "mutating tasks must not be run as concurrent rollouts against one deployment; "
                "serialise them with a reset between rollouts, or run them at n_traj=1",
        "disagreements": disagree,
        "tasks": rows,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=1)

    print(f"\nfinal: {n_m} mutating / {len(rows) - n_m} read-only  "
          f"({len(disagree)} heuristic/llm disagreements)")
    import collections
    ro = collections.Counter()
    for r in rows:
        if not r["mutating"] and len(r["sites"]) == 1:
            ro[r["sites"][0]] += 1
    print("single-site READ-ONLY per site:", dict(ro), "total", sum(ro.values()))
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
