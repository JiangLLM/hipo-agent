"""Task-level judging + two-layer extraction for WebArena.

  * judge_trajectory  — the env grader (reward) has ALREADY decided correct/incorrect; this
    only labels HOW a rollout got there: failure / genuine (really derived) / fluke (correct
    by luck, e.g. a shallow match).
  * reflect_trajectory (L1) — one reflection per genuine FAILURE (reward=0). Written answer-BLIND
    (no reference answer) so the lesson stays a general procedure.
  * contrast_rollouts (L2) — cross-rollout contrast by the genuine-success ratio; FLUKE rollouts
    are dropped upstream (no-op). Also written answer-BLIND.

The reference answer is used ONLY by judge_trajectory (to label success/genuine/fluke); the
experience WRITERS never see it, so lessons generalize instead of encoding one task's output.
The AGENT never sees the answer while solving (deployment-realistic).
"""
from __future__ import annotations

import json
import re

from ..schema import ReasoningItem

_JSON_KW = {"drop_params": True}
# Writer calls get their own output cap, decoupled from the client default the judge uses.
# gpt-5.6-sol is a reasoning model: thinking tokens count against max_tokens, and on long
# contrast inputs the 8000 shared cap ran dry mid-sentence — a truncated lesson entered the
# bank at "seemed relevant with" and poisoned three sibling tasks (gitlab t483-485).
_WRITE_KW = {"drop_params": True, "max_tokens": 16000}

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
    "An agent attempted a web task. The OFFICIAL grader has ALREADY scored this rollout against "
    "the reference answer — that CORRECT/INCORRECT verdict (given in the message) is GROUND "
    "TRUTH; do NOT re-judge whether the final answer matches.\n"
    "Your only job is to read the trace and label HOW the outcome came about.\n"
    'Respond JSON {"outcome": str, "reason": str}:\n'
    '- If the grader says INCORRECT -> outcome="failure"; reason = the concrete cause it went '
    "wrong and what it would have needed to do to reach the reference answer.\n"
    '- If the grader says CORRECT -> decide how the right answer was reached:\n'
    '    outcome="genuine" if the trace shows the agent actually navigated to and READ the '
    "value(s) that yield the reference answer;\n"
    '    outcome="fluke" if the correct answer was reached by luck — the agent dumped/listed a '
    "lot of content that merely happened to contain it, guessed, or never grounded the specific "
    "value. reason = why it is a fluke.\n"
    '- When the grader says CORRECT but you are unsure how, prefer "genuine".'
)

_L1_SYS = (
    "You are an expert web-navigation analyst distilling a lesson from ONE failed rollout. It "
    "{outcome_clause}\nExtract lessons that would prevent this failure on future tasks on this "
    "site.\n"
    # Blanket-prohibition guard (replay-validated): one trajectory cannot distinguish a bad
    # route from a good route walked badly. Without this line, 4/4 sampled L1s wrote blanket
    # prohibitions ("do not use the Yours tab") from a single failure — the class that zeroed
    # gitlab t169-172; with it, 1/4.
    "A single attempt cannot tell a bad route from a good route walked badly: do NOT write "
    "blanket prohibitions (\"never use X\", \"page Y is unreliable\") from one trajectory — state "
    "what to VERIFY on that route instead.\n" + _ITEM_FORMAT
)

_L2_SYS = (
    "An agent made N independent PARALLEL rollouts of the SAME web task. For each rollout you see "
    "its verdict (OK/WRONG, with the judge's reason) and EITHER the lesson distilled from it (its "
    "L1) OR, for a genuine success we want to learn from, its full TRACE.\n"
    "Look across ALL N outcomes and the success/failure ratio, then write ONE higher-level lesson:\n"
    "{direction}\n" + _ITEM_FORMAT
)

_L2_SELECT_SYS = (
    "Given the CURRENT web task and a numbered list of candidate past lessons, pick the ONE most "
    "APPLICABLE lesson. It must genuinely fit this task's goal and the controls/pages it needs — "
    "matching topic words is NOT enough (e.g. a task about the 'main' branch needs the branch-"
    "specific lesson, not a generic Contributors one). If NONE genuinely applies, return -1 — "
    "injecting nothing is better than a misleading lesson.\n"
    'Respond JSON {"idx": int} (the 0-based index, or -1).'
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

    def _items(self, out, scope, outcome, max_items, layer=""):
        items = []
        for d in out.get("items", [])[:max_items]:
            if isinstance(d, dict) and d.get("title") and d.get("content"):
                items.append(ReasoningItem(title=str(d["title"]).strip(),
                                           description=str(d.get("description", "")).strip(),
                                           content=str(d["content"]).strip(),
                                           scope=scope, outcome=outcome, layer=layer))
        return items

    def judge_trajectory(self, intent, trace, stop_answer, reward, reference=None):
        # The env grader already decided correct/incorrect (reward). We only label HOW:
        #   failure (incorrect) / genuine (correct, really derived) / fluke (correct by luck).
        correct = bool(reward)
        if not trace.strip():
            return {"outcome": "genuine" if correct else "failure", "reason": "empty trace"}
        ref = json.dumps(reference, ensure_ascii=False) if reference else "(not provided)"
        usr = (f"TASK: {intent}\n\nREFERENCE ANSWER (ground truth): {ref}\n"
               f"OFFICIAL GRADER VERDICT: {'CORRECT' if correct else 'INCORRECT'}\n\n"
               f"AGENT FINAL ANSWER: {stop_answer or '(none)'}\n\nTRACE:\n{trace}")
        out = self._json(self.llm.chat(
            [{"role": "system", "content": _JUDGE_SYS}, {"role": "user", "content": usr}],
            temperature=0.0, **_JSON_KW))
        outcome = str(out.get("outcome", "")).strip().lower()
        # Never contradict the grader: incorrect -> failure; correct -> genuine|fluke only.
        if not correct:
            outcome = "failure"
        elif outcome not in ("genuine", "fluke"):
            outcome = "genuine"
        return {"outcome": outcome, "reason": str(out.get("reason", "")).strip()}

    def reflect_trajectory(self, site, intent, trace, verdict, max_items=1):
        # L1 reflects a genuine FAILURE (env reward=0). The WRITER is deliberately answer-BLIND —
        # it never sees the reference answer — so the lesson stays a GENERAL procedure instead of
        # encoding this task's specific output (e.g. "answer N/A"). Genuine successes and flukes
        # never reach here. (The env grader still decides success/failure upstream; only the
        # experience TEXT is written blind.)
        clause = f"FAILED: {verdict.get('reason', '')}"
        sys = _L1_SYS.format(outcome_clause=clause, max_items=max_items)
        usr = f"SITE: {site}\nTASK: {intent}\n\nTRACE:\n{trace}"
        out = self._json(self.llm.chat(
            [{"role": "system", "content": sys}, {"role": "user", "content": usr}],
            temperature=0.0, **_WRITE_KW))
        return self._items(out, f"site:{site}", "failure", max_items, layer="L1")

    def contrast_rollouts(self, site, intent, rollouts, verdicts, l1_items, max_items=1, ok=None):
        # L2 = ONE cross-rollout lesson, chosen by the success/failure RATIO across the N rollouts:
        #   all wrong (nc==0)  -> summarize the COMMON cause; USE the judge verdicts — if they ran out
        #                         of the step budget / never answered, say the path is too long to
        #                         finish and advise a cheaper route or a best-effort partial answer
        #                         (NOT "be more exhaustive"); if they took a wrong path, name it to avoid.
        #   half (nc*2==n)     -> state BOTH what the successful did right AND the trap the failing hit.
        #   majority right     -> NOTE the specific mistake the failing minority made, as a caution.
        #   majority wrong     -> REMEMBER the reliable procedure the successful minority used.
        # Input per rollout: its L1 lesson (failure/蒙对), or — for a genuine success we must learn
        # FROM (half or majority-wrong) — its full TRACE. Items are tagged layer="L2".
        n = len(rollouts)
        if ok is None:
            ok = [v.get("outcome") == "genuine" for v in verdicts]
        nc = sum(ok)
        if nc == 0:
            # Two guard sentences, both replay-validated on real recorded inputs and red-teamed
            # (workflow wf_e9a9a91e, 2026-08-14):
            #  * no-distrust: t71 all-wrong used to yield "verify the mailing ZIP beyond map
            #    results", teaching t72 to override the map's CORRECT answer (3/4 -> 0/7). With
            #    the sentence, the same input yields "open the exact institution record" — the
            #    t141->t143 shipping-allocation save (same branch) survives verbatim.
            #  * no-invented-procedures: t615 all-wrong invented "upload via the file chooser"
            #    (no rollout ever completed it) and zeroed t616/618/619. Scope controls stay
            #    exempt (red team: t102's "select All" is load-bearing for three gitlab saves),
            #    and untried ideas go to a marked final clause, never the substance.
            direction = ("ALL rollouts FAILED. Summarize the common cause of failure. Read the "
                         "verdicts: if they ran out of the step budget or never produced a final "
                         "answer, say the approach is too long to finish in budget and advise a "
                         "cheaper route or giving a best-effort partial answer — do NOT advise being "
                         "more exhaustive. If they took a wrong path, name it so it is avoided. "
                         "If every rollout read the same on-page value and it was judged wrong, do "
                         "NOT conclude the site or its results are untrustworthy, and never advise "
                         "overriding a displayed value with outside knowledge — describe where the "
                         "correct value lives ON the site and how to read it. Recommend only "
                         "actions some rollout actually performed: a reading convention diagnosed "
                         "by the verdicts may be stated directly, and scope controls that only "
                         "change what is displayed (tabs, filters, sorting, page size) are safe to "
                         "include; but a UI mechanism no rollout ever completed must NOT become the "
                         "substance of the lesson — start the content with an executable "
                         "instruction, and mention an untried idea only in a final clause "
                         "explicitly marked as untried.")
            learn_from_success = False
        elif nc * 2 == n:
            direction = ("Half succeeded, half failed. State BOTH: the reliable thing the successful "
                         "rollouts did, AND the specific trap the failing ones fell into.")
            learn_from_success = True
        elif nc * 2 > n:
            # Answer-narrowing guard (replay-validated): t16 (7/8 right, 1 failed on format)
            # used to yield "preserve the requested output form", which stripped the
            # Walking/Driving labels from ALL 8 of t19's answers (8/8 -> 4/8). Same input with
            # the sentence yields "preserve answer labels". The look-alike-exclusion save
            # (t126 -> t226/228, same branch) survives.
            direction = ("Most rollouts SUCCEEDED; a few failed. NOTE the specific mistake the failing "
                         "minority made — phrase it as a caution to avoid. The caution may steer "
                         "navigation or verification, but must NEVER narrow the final answer: keep "
                         "every element, label and unit the task asks for — most rollouts answered "
                         "correctly, do not overcorrect their answer format.")
            learn_from_success = False
        else:  # nc*2 < n (and nc>0): majority wrong, minority right
            # Three guards, replay-validated + red-teamed:
            #  * decision-not-transcript: "REMEMBER the reliable procedure" transcribed the
            #    minority's clicks incl. incidental circumstances (t168's "view empty -> answer
            #    N/A" poison; t585's step-burn that zeroed t586). Asking WHY keeps it decision-level.
            #  * cheap-default + conditional-verification: t35 (3/8) used to write "bind and verify
            #    exact route endpoints" as an UNCONDITIONAL ritual — one lesson zeroed five easy
            #    routing tasks. CRITICAL red-team finding: the symptom condition goes in the
            #    CONTENT, never the description — retrieval embeds only title+description
            #    (store.py:36), and symptom clauses there pushed the t153 save from rank 1 to 13
            #    and t757 out of the fetch_k=5 pool. The description stays in the task family's
            #    own vocabulary.
            #  * enumeration exemption: without it the cost rule downgraded the broad-search
            #    saves (t158 -> t160/161, "open every plausible product") into conditional acts.
            direction = ("Most rollouts FAILED; a few succeeded. Explain WHY the successful "
                         "minority was right where the majority went wrong — the decision or check "
                         "that separated them — NOT a transcript of the minority's steps, and NOT "
                         "incidental page states they happened to see. The remedy must fit a tight "
                         "step budget: state the CHEAP default way first, and make any expensive "
                         "verification CONDITIONAL on the specific symptom that requires it — put "
                         "that symptom condition in the content, and keep the description written "
                         "in the task family's own vocabulary (the description is the retrieval "
                         "key; do not dilute it with symptom clauses). When the task itself asks "
                         "to enumerate or list everything, complete enumeration is NOT expensive "
                         "verification and must not be made conditional.")
            learn_from_success = True
        sys = _L2_SYS.format(direction=direction, max_items=max_items)
        l1_items = l1_items or [[] for _ in range(n)]
        # WRITER kept answer-BLIND (no reference answer) so the L2 stays a general procedure.
        lines = [f"SITE: {site}", f"TASK: {intent}", f"\n{n} rollouts, {nc} succeeded:"]
        for i, (r, v, is_ok, items) in enumerate(zip(rollouts, verdicts, ok, l1_items)):
            tag = "OK" if is_ok else "WRONG"
            if items:
                body = "L1 lesson: " + " | ".join(f"{it.title}: {it.content}" for it in items)
            elif is_ok and learn_from_success:
                body = "TRACE (genuine success — study why it worked):\n  " + (r.get("trace", "") or "")
            else:
                body = "(genuine success)" if is_ok else "(no usable trajectory)"
            lines.append(f"\n--- rollout {i+1} [{tag}] ({v['reason']})\n  {body}")
        out = self._json(self.llm.chat(
            [{"role": "system", "content": sys}, {"role": "user", "content": "\n".join(lines)}],
            temperature=0.0, **_WRITE_KW))
        outcome = "success" if learn_from_success else "failure"
        return self._items(out, f"site:{site}", outcome, max_items, layer="L2")

    def select_lesson(self, intent, items):
        """LLM injection gate: from cosine-recalled candidates, pick the ONE genuinely-applicable
        lesson (or None). Resolves generic-vs-specific ties raw cosine can't. Returns the chosen
        ReasoningItem or None (inject nothing)."""
        if not items:
            return None
        menu = "\n".join(f"[{i}] {it.title}: {it.content}" for i, it in enumerate(items))
        out = self._json(self.llm.chat(
            [{"role": "system", "content": _L2_SELECT_SYS},
             {"role": "user", "content": f"CURRENT TASK: {intent}\n\nCANDIDATE LESSONS:\n{menu}"}],
            temperature=0.0, **_JSON_KW))
        idx = out.get("idx", -1)
        return items[idx] if isinstance(idx, int) and 0 <= idx < len(items) else None
