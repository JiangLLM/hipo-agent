"""Task-level judging + two-layer extraction for WebArena (label-free).

Direct translation of swe/brain.py to the web-navigation domain:
  * judge_trajectory  — label-free verdict from the trace, evidence-gated (an
    info-seeking task's answer must be traceable to something the agent actually saw;
    a state-change task must show the change happened). Same "verified vs claimed"
    split that guards against memory-amplified false successes.
  * reflect_trajectory (L1) — one reflection per surprising rollout (failed, or
    succeeded-unverified). Site-scoped, generalizable UI/procedure knowledge.
  * contrast_rollouts (L2) — cross-rollout contrast on divergence, majority-directed,
    vote-margin gated.

Native reward (from env.step) is NEVER passed in here — judging stays label-free like
deployment; native reward is only used downstream to score, never to learn.
"""
from __future__ import annotations

import json
import re

from ..schema import ReasoningItem

_JSON_KW = {"drop_params": True}

_ITEM_FORMAT = (  # doubled braces: goes through str.format()
    'Respond JSON {{"items": [{{"title": str, "description": str, "content": str}}]}}.\n'
    "- title: short name for the control/decision.\n"
    "- description: WHEN this applies (and when not) — the retrieval condition.\n"
    "- content: 1-3 sentences of actionable insight.\n"
    "- Items must generalize to FUTURE tasks on this SITE. Cover BOTH: (a) navigation — where "
    "a control/report lives, what a labeled element does, the reliable sequence, the look-alike "
    "trap (e.g. a report that cannot filter by status); AND (b) answer extraction — how to read "
    "the result COMPLETELY once you reach it: copy the full displayed value (open a detail view "
    "if the grid abbreviates a name), enumerate EVERY tied/qualifying row, verify the answer is "
    "visible rather than guessed, don't confuse near-identical variants. "
    "Describe controls by visible text/role, NEVER by numeric bid. NEVER copy task-specific "
    "values (product names, search terms, dates, numbers).\n"
    "- Return at most {max_items} item — the single most important, reusable lesson; "
    "[] only if nothing reusable was learned."
)

_JUDGE_SYS = (
    "You judge whether a web agent COMPLETED its task, label-free, from the trace only. "
    "There is no ground truth.\n"
    "Task types: (1) information-seeking — the final answer the agent sent to the user must "
    "contain the asked info and it must be traceable to a page the agent actually observed; (2) navigation — "
    "the agent must have reached the target page; (3) content-modification — the trace must "
    "show the change was submitted and confirmed.\n"
    "Before calling it success, verify ALL of:\n"
    "- Completeness: if the task implies an EXHAUSTIVE result (\"list ALL reviewers who...\", "
    "\"how many...\", a range/aggregate), the agent must have inspected the FULL source "
    "(scrolled through every review / all pages), not stopped after the first few. A partial "
    "list is a FAILURE even if the items it names are correct.\n"
    "- Grounding: every value/name the agent reports is visible in an observation in the "
    "trace; anything inferred or guessed without a visible source is a failure.\n"
    "- Right target: the agent acted on the exact entity the task named, not an adjacent one.\n"
    'Respond JSON {"success": bool, "verified": bool, "reason": str, "evidence": str}.\n'
    "- verified: TRUE only if the answer is both visible in the trace AND the agent's REASONING "
    "actually derived it from what it observed — not guessed, not a coincidental right answer. "
    "Read the full reasoning: if the agent landed on the correct answer without sound, grounded "
    "reasoning (a lucky/蒙对 hit), set success=true verified=false. Cite the step.\n"
    "- When uncertain prefer success=false. A false success is more harmful than a false "
    "failure, because memory amplifies it."
)

_L1_SYS = (
    "You are an expert web-navigation analyst distilling lessons from ONE rollout. It "
    "{outcome_clause}\nReflect on WHY, then extract lessons that prevent this failure (or "
    "turn luck into a reliable procedure) on future tasks on this site.\n" + _ITEM_FORMAT
)

_L2_SYS = (
    "An agent made N independent PARALLEL rollouts of the SAME web task, with mixed outcomes. "
    "For each rollout you see its verdict (OK/WRONG) and EITHER the lesson distilled from it (its "
    "L1 — written only for failures and lucky/蒙对 hits) OR, for a genuine success (which has no "
    "L1), its full TRACE so you can inspect WHY it worked.\n"
    "Contrast the {minority} rollout(s) against the {majority}: if most were WRONG, study the "
    "successful rollout(s)' TRACES and work out the reliable procedure that made them succeed; if "
    "most were RIGHT, study the failing rollout(s)' lessons and name the trap to avoid.\n"
    "Then write it as higher-level guidance: {direction}\n" + _ITEM_FORMAT
)


class WaBrain:
    def __init__(self, llm):
        self.llm = llm

    @staticmethod
    def _json(text: str) -> dict:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return {}
        for c in (m.group(0), re.sub(r'\\(?![\\/"bfnrtu])', r"\\\\", m.group(0))):
            try:
                return json.loads(c)
            except json.JSONDecodeError:
                continue
        return {}

    def _items(self, out, scope, outcome, max_items):
        items = []
        for d in out.get("items", [])[:max_items]:
            if isinstance(d, dict) and d.get("title") and d.get("content"):
                items.append(ReasoningItem(title=str(d["title"]).strip(),
                                           description=str(d.get("description", "")).strip(),
                                           content=str(d["content"]).strip(),
                                           scope=scope, outcome=outcome))
        return items

    def judge_trajectory(self, intent: str, trace: str, stop_answer: str) -> dict:
        if not trace.strip():
            return {"success": False, "verified": False, "reason": "empty trace", "evidence": ""}
        usr = f"TASK: {intent}\n\nTRACE:\n{trace}\n\nFINAL ANSWER: {stop_answer or '(none)'}"
        out = self._json(self.llm.chat(
            [{"role": "system", "content": _JUDGE_SYS}, {"role": "user", "content": usr}],
            temperature=0.0, **_JSON_KW))
        return {"success": bool(out.get("success", False)),
                "verified": bool(out.get("verified", False)),
                "reason": str(out.get("reason", "")).strip(),
                "evidence": str(out.get("evidence", "")).strip()}

    def reflect_trajectory(self, site, intent, trace, verdict, outcome_hint=None, max_items=1):
        # L1 only reflects the two "surprising" outcomes (the caller skips genuine successes):
        #   outcome_hint="fluke": got the right answer but the judge found the REASONING did not
        #     actually establish it (a lucky/蒙对 hit) -> record as a CAUTION, not a procedure.
        #   otherwise (reward=0 failure) -> what went wrong / how to avoid it.
        if outcome_hint == "fluke":
            clause = ("reached the correct answer but the REASONING did not actually establish it — "
                      "the judge found it a lucky/guessed (蒙对) hit, not truly derived. Record a "
                      "CAUTION: what looked right but was not really known, so future tasks do not "
                      "trust this shortcut and instead verify the answer properly.")
            outcome = "unverified"
        else:
            clause = f"FAILED: {verdict['reason']}"
            outcome = "failure"
        sys = _L1_SYS.format(outcome_clause=clause, max_items=max_items)
        usr = f"SITE: {site}\nTASK: {intent}\n\nTRACE:\n{trace}"
        out = self._json(self.llm.chat(
            [{"role": "system", "content": sys}, {"role": "user", "content": usr}],
            temperature=0.0, **_JSON_KW))
        return self._items(out, f"site:{site}", outcome, max_items)

    def contrast_rollouts(self, site, intent, rollouts, verdicts, l1_items, max_items=1, ok=None):
        # L2 operates OVER the per-rollout L1 lessons (`l1_items[i]` = list of L1 items distilled
        # from rollout i), NOT the raw traces: read the N distilled lessons + their OK/WRONG labels,
        # contrast minority vs majority, promote to higher-level guidance. `ok` is the per-rollout
        # success label that triggered L2 (reward- or judge-based); direction/tags MUST use it.
        n = len(rollouts)
        if ok is None:
            ok = [bool(v["success"] and v["verified"]) for v in verdicts]
        nc = sum(ok)
        if nc * 2 >= n:
            majority, minority = "successful", "failing"
            direction = "the TRAP the failing rollout(s) fell into, and how to avoid it."
        else:
            majority, minority = "failing", "successful"
            direction = "the reliable procedure the successful rollout(s) used."
        sys = _L2_SYS.format(minority=minority, majority=majority,
                             direction=direction, max_items=max_items)
        l1_items = l1_items or [[] for _ in range(n)]
        # Only attach a genuine success's full TRACE when success is the MINORITY (most rollouts
        # failed) — that's the only direction where L2 needs to distill "how it succeeded". In the
        # majority-succeeded direction L2 learns "avoid the trap" from the failing minority's L1s,
        # so dumping every winner's trace would just bloat the prompt and distract it.
        success_minority = nc * 2 < n
        lines = [f"SITE: {site}", f"TASK: {intent}",
                 f"\n{n} rollouts, {nc} succeeded. Per rollout: its L1 lesson (failure / 蒙对), or — "
                 f"only for a minority genuine success — its full trace to inspect why it worked:"]
        for i, (r, v, is_ok, items) in enumerate(zip(rollouts, verdicts, ok, l1_items)):
            tag = "OK" if is_ok else "WRONG"
            if items:
                body = "L1 lesson: " + " | ".join(f"{it.title}: {it.content}" for it in items)
            elif is_ok and success_minority:
                body = "no L1 (a MINORITY genuine success) — TRACE, study why it worked:\n  " + (r.get("trace", "") or "")
            else:
                body = "(genuine success — no lesson needed for this direction)" if is_ok else "(no usable trajectory)"
            lines.append(f"\n--- rollout {i+1} [{tag}] ({v['reason']})\n  {body}")
        out = self._json(self.llm.chat(
            [{"role": "system", "content": sys}, {"role": "user", "content": "\n".join(lines)}],
            temperature=0.0, **_JSON_KW))
        outcome = "success" if nc * 2 < n else "failure"
        return self._items(out, f"site:{site}", outcome, max_items)
