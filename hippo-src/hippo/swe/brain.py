"""Task-level judging + two-layer extraction for SWE-bench (label-free).

This is the SWE translation of the Mind2Web step-level design:
  * judge_attempt  — LLM verdict per attempt, with an EVIDENCE requirement: a
    "success" only counts as verified if the trace shows the fix observed working
    (repro/test run passing after the change). Judge noise is the failure mode that
    kills majority-direction extraction, and unverified successes are the poison
    memory amplifies — so verification is a first-class output, not a prompt aside.
  * reflect_attempt (L1) — one reflection per surprising attempt (failed, or
    succeeded-unverified). Repo-scoped, generalizable; file/module names are the
    reusable unit here (like visible UI labels were on Mind2Web).
  * contrast_attempts (L2) — cross-attempt contrast on divergence, direction picked
    by the majority: mostly-failed -> distill what made the successes work;
    mostly-succeeded -> distill the trap the failures fell into.

All calls go through hippo's LLMClient (budget guard + cache). `drop_params` keeps
temperature/etc. compatible with reasoning models (gpt-5 family rejects temp!=1).
"""
from __future__ import annotations

import json
import re

from ..schema import ReasoningItem

_JSON_KW = {"drop_params": True}

_ITEM_FORMAT = (  # NB: doubled braces — this string goes through str.format()
    'Respond JSON {{"items": [{{"title": str, "description": str, "content": str}}]}}.\n'
    "- title: short name for the strategy/fact.\n"
    "- description: WHEN this applies (and when it does not) — the retrieval condition.\n"
    "- content: 1-3 sentences of actionable insight.\n"
    "- Items must generalize to FUTURE issues on this repository: repo structure facts "
    "(which module/file owns a behavior), workflow strategies (how to locate, reproduce, "
    "verify), and pitfalls. File paths and module names are welcome; NEVER copy "
    "issue-specific literals (ticket numbers, exact error strings, variable values from "
    "this issue).\n"
    "- At most {max_items} items; no overlapping items; return [] if nothing genuinely "
    "reusable was learned."
)

_JUDGE_SYS = (
    "You are an expert reviewer judging whether a software agent RESOLVED a GitHub "
    "issue. You see the issue, a compact trace of the agent's shell session, and the "
    "final patch. There is NO ground truth; judge only from evidence in the trace.\n"
    "Check all three:\n"
    "1. Root cause: the patch changes non-test source code in a way that plausibly "
    "fixes the SPECIFIC issue (not a workaround that silences the symptom).\n"
    "2. Verified: the agent reproduced the problem (or ran a targeted test) and the "
    "trace SHOWS it passing AFTER the change.\n"
    "3. No regression signal: no test run in the trace still fails after the final "
    "change.\n"
    'Respond JSON {"success": bool, "verified": bool, "reason": str, "evidence": str}.\n'
    "- success: your best judgment that the issue is resolved.\n"
    "- verified: point 2 is literally visible in the trace; cite the step in evidence. "
    "If you believe success but nothing shows the fix working, success=true "
    "verified=false.\n"
    "- When uncertain, prefer success=false. A false success is more harmful than a "
    "false failure, because memory induction amplifies it into future behavior."
)

_L1_SYS = (
    "You are an expert software engineer distilling lessons from ONE agent attempt at "
    "fixing a repository issue. The attempt {outcome_clause}\n"
    "First reflect on WHY, then extract lessons that would prevent this failure mode "
    "(or turn this luck into a reliable procedure) on future issues in this repo.\n"
    + _ITEM_FORMAT
)

_L2_SYS = (
    "You are an expert software engineer. An agent made N independent attempts at the "
    "SAME repository issue, with mixed outcomes. You see each attempt's verdict, a "
    "short summary, and a per-attempt reflection.\n"
    "First contrast: what did the {minority} attempt(s) do differently from the "
    "{majority} majority?\n"
    "Then summarize: {direction}\n" + _ITEM_FORMAT
)


class SweBrain:
    def __init__(self, llm):
        self.llm = llm

    @staticmethod
    def _json(text: str) -> dict:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return {}
        blob = m.group(0)
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            # Models quoting code/regex emit invalid JSON escapes (e.g. `\A`, `\d`);
            # escape any backslash not starting a legal sequence and retry.
            try:
                return json.loads(re.sub(r'\\(?![\\/"bfnrtu])', r"\\\\", blob))
            except json.JSONDecodeError:
                return {}

    def _items(self, out: dict, scope: str, outcome: str, max_items: int) -> list[ReasoningItem]:
        items = []
        for d in out.get("items", [])[:max_items]:
            if not isinstance(d, dict) or not (d.get("title") and d.get("content")):
                continue
            items.append(ReasoningItem(title=str(d["title"]).strip(),
                                       description=str(d.get("description", "")).strip(),
                                       content=str(d["content"]).strip(),
                                       scope=scope, outcome=outcome))
        return items

    # ------------------------------------------------------------------ #
    def select_relevant(self, instance: dict, items: list) -> list:
        """Injection-side relevance gate: ONE cheap call picks the subset of retrieved
        items that genuinely applies to THIS issue (empty subset is a valid answer).
        Embedding similarity ranks candidates; this decides. The Mind2Web postmortem
        showed misleading injections were exactly items whose condition didn't match
        the current situation — this is that check, made explicit."""
        if not items:
            return []
        lines = [f"ISSUE:\n{instance['problem_statement'][:1500]}\n",
                 "CANDIDATE lessons from past tasks on this repo:"]
        for i, it in enumerate(items):
            lines.append(f"[{i}] {it.title} — applies when: {it.description[:150]}")
        sys = ("You gate which past lessons get shown to a coding agent. Select ONLY items "
               "whose applies-when condition matches the CURRENT issue; injecting off-topic "
               "lessons is worse than injecting nothing. Respond JSON "
               '{"keep": [indices]} — an empty list is a perfectly good answer.')
        out = self._json(self.llm.chat(
            [{"role": "system", "content": sys}, {"role": "user", "content": "\n".join(lines)}],
            temperature=0.0, **_JSON_KW))
        keep = out.get("keep", None)
        if not isinstance(keep, list):          # parse failure -> fail open (old behavior)
            return items
        return [items[i] for i in keep if isinstance(i, int) and 0 <= i < len(items)]

    def judge_attempt(self, instance: dict, attempt: dict) -> dict:
        """Verdict for one attempt. Deterministic pre-gate first: no submitted patch
        means failed, no LLM needed (and no chance for the judge to hallucinate)."""
        if attempt["exit_status"] != "Submitted" or not attempt["patch"].strip():
            return {"success": False, "verified": False, "evidence": "",
                    "reason": f"no submission ({attempt['exit_status'] or 'empty patch'})"}
        usr = (f"ISSUE:\n{instance['problem_statement'][:3000]}\n\n"
               f"AGENT TRACE:\n{attempt['trace']}\n\n"
               f"FINAL PATCH:\n{attempt['patch'][:6000]}")
        out = self._json(self.llm.chat(
            [{"role": "system", "content": _JUDGE_SYS}, {"role": "user", "content": usr}],
            temperature=0.0, **_JSON_KW))
        return {"success": bool(out.get("success", False)),
                "verified": bool(out.get("verified", False)),
                "reason": str(out.get("reason", "")).strip(),
                "evidence": str(out.get("evidence", "")).strip()}

    def reflect_attempt(self, instance: dict, attempt: dict, verdict: dict,
                        max_items: int = 2) -> list[ReasoningItem]:
        """LAYER 1: reflection on one surprising attempt."""
        if verdict["success"] and not verdict["verified"]:
            outcome_clause = ("produced a plausible patch but NEVER VERIFIED it — the "
                              "lesson space is how to verify fixes in this repo.")
            outcome = "unverified"
        else:
            outcome_clause = f"FAILED: {verdict['reason'] or attempt['exit_status']}"
            outcome = "failure"
        sys = _L1_SYS.format(outcome_clause=outcome_clause, max_items=max_items)
        usr = (f"REPO: {instance['repo']}\nISSUE:\n{instance['problem_statement'][:2000]}\n\n"
               f"ATTEMPT TRACE:\n{attempt['trace'][:15000]}\n\n"
               f"FINAL PATCH:\n{attempt['patch'][:3000] or '(none)'}")
        out = self._json(self.llm.chat(
            [{"role": "system", "content": sys}, {"role": "user", "content": usr}],
            temperature=0.0, **_JSON_KW))
        return self._items(out, f"repo:{instance['repo']}", outcome, max_items)

    def contrast_attempts(self, instance: dict, attempts: list[dict],
                          verdicts: list[dict], max_items: int = 2) -> list[ReasoningItem]:
        """LAYER 2: cross-attempt contrast. Caller enforces divergence + vote margin;
        this only phrases the majority-directed extraction."""
        n = len(attempts)
        nc = sum(1 for v in verdicts if v["success"] and v["verified"])
        if nc * 2 >= n:
            majority, minority = "successful", "failing"
            direction = ("the TRAP the failing attempt(s) fell into on this repo, and "
                         "how to recognize and avoid it.")
        else:
            majority, minority = "failing", "successful"
            direction = ("the reliable procedure the successful attempt(s) used — how "
                         "they located the right code, fixed it, and verified it.")
        sys = _L2_SYS.format(minority=minority, majority=majority,
                             direction=direction, max_items=max_items)
        lines = [f"REPO: {instance['repo']}", f"ISSUE:\n{instance['problem_statement'][:2000]}",
                 f"\n{n} attempts, {nc} verified-successful:"]
        for i, (a, v) in enumerate(zip(attempts, verdicts)):
            tag = "OK" if (v["success"] and v["verified"]) else "WRONG"
            lines.append(f"\n--- attempt {i + 1} [{tag}] "
                         f"({v['reason'][:120] or a['exit_status']})")
            lines.append(a["trace"][:6000])
            if a["patch"]:
                lines.append(f"patch: {a['patch'][:1500]}")
        out = self._json(self.llm.chat(
            [{"role": "system", "content": sys}, {"role": "user", "content": "\n".join(lines)}],
            temperature=0.0, **_JSON_KW))
        outcome = "success" if nc * 2 < n else "failure"   # what the MINORITY was
        return self._items(out, f"repo:{instance['repo']}", outcome, max_items)
