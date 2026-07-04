"""The agent "brain": decision + judgment + extraction, behind one interface.

Two implementations share the loop in run.py:
  * MockBrain — deterministic, no API. Reads injected memory text and acts; lets us
    validate gating/routing/replay/eval logic for free.
  * LLMBrain  — real, via litellm.

The content of memory is always LLM-extracted (LLMBrain) / oracle-extracted (MockBrain,
a documented test shortcut). The *gate* (surprise) is computed elsewhere.
"""
from __future__ import annotations

import hashlib
import json
import random
import re

from .schema import FactItem, Outcome, ReasoningItem, Task, Trajectory

_LOGIC_MARKER = "RULE:parity"

_ABSTRACT_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have",
    "in", "into", "is", "it", "of", "on", "or", "that", "the", "this", "to",
    "with", "which", "who", "what", "when", "where", "why", "how",
    # Task boilerplate / common UI-domain words that should not by themselves reject a fact.
    "browse", "check", "find", "first", "get", "go", "page", "show", "shows",
    "site", "store", "stores", "ticket", "tickets",
}


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", text)]


def _task_literal_terms(prompt: str, gold_repr: str = "") -> set[str]:
    """Values that should not leak into AWM-style site facts.

    We keep this deterministic because the LLM often ignores soft "abstract it"
    instructions. UI labels are allowed; task values (places, dates, products,
    numbers, typed/selected values) are not.
    """
    terms: set[str] = set()
    text = f"{prompt} {gold_repr}"

    # Explicit typed/selected gold values are almost always task literals.
    for m in re.finditer(r"(?:TYPE|SELECT):\s*([^-\n]+)", gold_repr, flags=re.I):
        val = m.group(1).strip()
        if val:
            terms.add(val.lower())
            terms.update(t for t in _tokens(val) if len(t) > 1)

    # Dates, numbers, zip codes, sizes, and hyphenated product/location tokens.
    months = ("january february march april may june july august september october "
              "november december jan feb mar apr jun jul aug sep sept oct nov dec").split()
    toks = _tokens(text)
    for t in toks:
        if t in months or re.search(r"\d", t) or "-" in t:
            terms.add(t)

    # Capitalized proper-name spans from the goal, e.g. "New York", "Hamilton".
    for span in re.findall(r"\b[A-Z][A-Za-z0-9'-]*(?:\s+[A-Z][A-Za-z0-9'-]*)*", prompt):
        low = span.lower()
        if low not in _ABSTRACT_STOPWORDS:
            terms.add(low)
            terms.update(t for t in _tokens(span) if len(t) > 2)

    # Content n-grams catch lower-case task values such as "coffee makers" and
    # "brown plus size loungewear" without rejecting generic control names.
    content = [t for t in _tokens(prompt) if len(t) >= 4 and t not in _ABSTRACT_STOPWORDS]
    for n in (2, 3, 4):
        for i in range(len(content) - n + 1):
            terms.add(" ".join(content[i:i + n]))
    return {t for t in terms if t and t not in _ABSTRACT_STOPWORDS}


def _is_abstract_site_fact(statement: str, task: Task, gold_repr: str = "") -> bool:
    s = statement.lower()
    return not any(term in s for term in _task_literal_terms(task.prompt, gold_repr))


def _fmt_item(d: dict) -> str:
    """Render a RB-style memory item (title/description/content) into ONE statement string,
    keeping the WHEN-to-use condition visible so retrieval-time injection is self-gating."""
    title = (d.get("title") or "").strip()
    content = (d.get("content") or "").strip()
    desc = (d.get("description") or "").strip()
    head = f"{title}: " if title else ""
    body = content or title
    if not body:
        return ""
    return f"{head}{body}" + (f"  [Applies when: {desc}]" if desc else "")


def _parse_control(gold_repr: str) -> tuple[str, str, str]:
    """gold_repr like '[div]  Category -> CLICK' -> (role, label, op)."""
    m = re.match(r"\s*\[([^\]]*)\]\s*(.*?)\s*->\s*(\S+)", gold_repr or "")
    if not m:
        return ("", "", "")
    return (m.group(1).strip(), m.group(2).strip(), m.group(3).strip())


def _dangerous_literals(prompt: str, gold_repr: str = "") -> set[str]:
    """Task-specific values that must NEVER survive into a reusable rule: multi-word
    proper-noun spans (New York, Six Flags White Water), months, digit-bearing tokens
    (dates/zips/sizes/quantities), and explicit gold typed/selected values. Deliberately
    NARROW — generic single words (city, events) are kept so generalized intents survive."""
    terms: set[str] = set()
    for sp in re.findall(r"\b[A-Z][A-Za-z0-9'&]*(?:\s+[A-Z][A-Za-z0-9'&]*)+", prompt):
        terms.add(sp.lower())
    for mth in ("january february march april may june july august september october "
                "november december").split():
        if re.search(r"\b" + mth + r"\b", prompt, re.I):
            terms.add(mth)
    for t in re.findall(r"\b\w*\d[\w:]*\b", prompt.lower()):
        terms.add(t)
    for m in re.finditer(r"(?:TYPE|SELECT):\s*([^-\n]+)", gold_repr, re.I):
        v = m.group(1).strip().lower()
        if v:
            terms.add(v)
    return {t for t in terms if len(t) >= 3}


def _delist(text: str, terms: set[str]) -> str:
    """Remove dangerous literals (longest first) and tidy leftover punctuation/space."""
    for t in sorted(terms, key=len, reverse=True):
        if t:
            text = re.sub(r"\b" + re.escape(t) + r"\b", "", text, flags=re.I)
    return re.sub(r"\s{2,}", " ", text).strip(" ,.;:-\u2013")


class Brain:
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def act(self, task: Task, obs: str, memory_text: str, salt: str = "") -> tuple[str, str, bool]:
        """Return (thought, action, can_derive). `salt` varies guesses across trajectories."""
        raise NotImplementedError

    def predict_solvable(self, task: Task, memory_text: str) -> bool:
        raise NotImplementedError

    def judge(self, task: Task, traj: Trajectory) -> Outcome:
        raise NotImplementedError

    def attribute(self, task, trajs, outcomes) -> tuple[bool, bool]:
        raise NotImplementedError

    def extract_reasoning(self, task, trajs, outcomes, env) -> ReasoningItem | None:
        raise NotImplementedError

    def extract_fact(self, task, trajs, outcomes, env) -> list[FactItem]:
        raise NotImplementedError

    def judge_step(self, task, step, thought, action, is_correct, gold_repr) -> dict:
        """Layer-1 surprise (single attempt, one step). Looks at the GOLD answer to decide
        whether a CORRECT step was genuinely reasoned or a lucky guess, and distills ONE
        high-quality site rule when the step is surprising. Returns
        {"genuine": bool, "lesson": FactItem | None}."""
        return {"genuine": bool(is_correct), "lesson": None}

    def extract_step_experiences(self, task, step, attempts, gold_repr, mode) -> list:
        """Layer-2 surprise (across the N attempts, one step). Contrastive distillation.
        Returns a FactItem list."""
        return []


# --------------------------------------------------------------------------- #
class MockBrain(Brain):
    def __init__(self, cfg):
        self.cfg = cfg

    # deterministic hashing "embedding" so similarity retrieval works offline
    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            seed = int(hashlib.sha256(t.encode()).hexdigest()[:8], 16)
            rng = random.Random(seed)
            out.append([rng.uniform(-1, 1) for _ in range(16)])
        return out

    def _knowledge_present(self, task: Task, memory_text: str) -> tuple[bool, str | None]:
        if task.task_type == "fact":
            k = task.meta.get("item")
            m = re.search(rf"item={k} -> action=(\w+)", memory_text)
            if m:
                return True, m.group(1)
            return False, None
        if task.task_type == "logic":
            if _LOGIC_MARKER in memory_text:
                nums = task.meta.get("nums", [])
                return True, ("even" if sum(nums) % 2 == 0 else "odd")
            return False, None
        return False, None

    def act(self, task: Task, obs: str, memory_text: str, salt: str = "") -> tuple[str, str, bool]:
        known, action = self._knowledge_present(task, memory_text)
        if known:
            return ("recalled from memory", action, True)
        # no knowledge -> guess; salt makes trajectories diverge (=> divergence signal)
        rng = random.Random(f"{task.id}:{task.task_type}:{salt}")
        space = ["even", "odd"] if task.task_type == "logic" else ["alpha", "beta", "gamma", "delta", "epsilon"]
        return ("no memory, guessing", rng.choice(space), False)

    def predict_solvable(self, task: Task, memory_text: str) -> bool:
        return self._knowledge_present(task, memory_text)[0]

    def judge(self, task: Task, traj: Trajectory) -> Outcome:
        # mock judge trusts the grounded env signal (a real judge approximates it)
        success = bool(traj.env_success)
        return Outcome(success=success, can_derive=bool(traj.meta.get("can_derive", True)),
                       confidence=1.0, reason="env-grounded")

    def attribute(self, task, trajs, outcomes) -> tuple[bool, bool]:
        # route by where the failure lives: logic->reasoning, fact->fact
        if task.task_type == "logic":
            return (False, True)
        if task.task_type == "fact":
            return (True, False)
        return (False, False)

    def extract_reasoning(self, task, trajs, outcomes, env) -> ReasoningItem | None:
        if task.task_type != "logic":
            return None
        return ReasoningItem(
            title="parity classification rule",
            description="how to solve logic-tasks of the form nums=[...]: classify",
            content=f"{_LOGIC_MARKER}: answer 'even' if sum(nums) is even else 'odd'.",
            certainty="high", outcome="success",
            source_traj_ids=[t.traj_id for t in trajs],
        )

    def extract_fact(self, task, trajs, outcomes, env) -> list[FactItem]:
        if task.task_type != "fact":
            return []
        k = task.meta.get("item")
        correct = env.oracle(task)            # mock shortcut: evidence from the env
        return [FactItem(
            scope=task.scope,
            statement=f"[{task.scope}] item={k} -> action={correct}",
            polarity="positive", confidence=1.0,
            evidence_traj_id=trajs[0].traj_id if trajs else None,
            key=f"item={k}",
        )]


# --------------------------------------------------------------------------- #
class RandomBrain(Brain):
    """Picks a random candidate id from the prompt. No network — a pipeline floor."""

    def __init__(self, cfg):
        self.cfg = cfg

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            seed = int(hashlib.sha256(t.encode()).hexdigest()[:8], 16)
            rng = random.Random(seed)
            out.append([rng.uniform(-1, 1) for _ in range(16)])
        return out

    def act(self, task: Task, obs: str, memory_text: str, salt: str = "") -> tuple[str, str, bool]:
        ids = re.findall(r"\b(c\d+):", obs)
        if not ids:
            return ("no candidates", "", False)
        rng = random.Random(f"{task.id}:{salt}")
        return ("random pick", rng.choice(ids), False)

    def predict_solvable(self, task, memory_text) -> bool:
        return False

    def judge(self, task, traj) -> Outcome:
        return Outcome(success=bool(traj.env_success), reason="env")

    def attribute(self, task, trajs, outcomes) -> tuple[bool, bool]:
        return (False, False)

    def extract_reasoning(self, task, trajs, outcomes, env):
        return None

    def extract_fact(self, task, trajs, outcomes, env):
        return None


# --------------------------------------------------------------------------- #
class LLMBrain(Brain):
    def __init__(self, llm, cfg, judge_llm=None):
        self.llm = llm
        self.cfg = cfg
        self.judge_llm = judge_llm or llm

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.llm.embed(texts)

    @staticmethod
    def _json(text: str) -> dict:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return {}
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return {}

    def act(self, task: Task, obs: str, memory_text: str, salt: str = "") -> tuple[str, str, bool]:
        sys = ("You are an agent solving a task using ONLY the provided memory and the task. "
               "If memory does not let you derive the answer, set can_derive=false. "
               'Respond as JSON: {"thought": str, "answer": str, "can_derive": bool}. '
               'The "answer" must be EXACTLY the single token the task asks for (e.g. a '
               'candidate id like c3) — no operation names, no extra words.')
        usr = f"MEMORY:\n{memory_text or '(empty)'}\n\nTASK:\n{obs}"
        raw = self.llm.chat([{"role": "system", "content": sys},
                             {"role": "user", "content": usr}])
        out = self._json(raw)
        ans = str(out.get("answer", "")).strip()
        # Robustness: the model often ignores the JSON schema and replies in prose
        # (the task itself says "answer with only the id"), which would lose a correct
        # pick to a format mismatch. Fall back to the last candidate token in the text.
        if not re.fullmatch(r"c\d+", ans):
            ids = re.findall(r"\bc\d+\b", raw)
            if ids:
                ans = ids[-1]
        return (out.get("thought", ""), ans, bool(out.get("can_derive", True)))

    def predict_solvable(self, task: Task, memory_text: str) -> bool:
        sys = 'Can the TASK be solved from MEMORY alone? Respond JSON {"solvable": bool}.'
        usr = f"MEMORY:\n{memory_text or '(empty)'}\n\nTASK:\n{task.prompt}"
        out = self._json(self.llm.chat([{"role": "system", "content": sys},
                                        {"role": "user", "content": usr}], temperature=0.0))
        return bool(out.get("solvable", False))

    def judge(self, task: Task, traj: Trajectory) -> Outcome:
        if traj.env_success is not None:        # grounded signal available
            return Outcome(success=bool(traj.env_success),
                           can_derive=bool(traj.meta.get("can_derive", True)), reason="env")
        sys = ('Judge whether the agent solved the task (label-free, from the trajectory). '
               'Respond JSON {"success": bool, "reason": str}.')
        usr = f"TASK:\n{task.prompt}\n\nACTION:\n{traj.final_answer}"
        out = self._json(self.judge_llm.chat([{"role": "system", "content": sys},
                                              {"role": "user", "content": usr}], temperature=0.0))
        return Outcome(success=bool(out.get("success", False)),
                       can_derive=bool(traj.meta.get("can_derive", True)),
                       reason=out.get("reason", ""))

    def attribute(self, task, trajs, outcomes) -> tuple[bool, bool]:
        sys = ('Attribute the failure: is it a FACT problem (missing/incorrect knowledge) '
               'or a LOGIC problem (flawed reasoning)? Respond JSON {"fact": bool, "logic": bool}.')
        usr = f"TASK:\n{task.prompt}\n\nANSWERS:\n" + "\n".join(t.final_answer or "" for t in trajs)
        out = self._json(self.judge_llm.chat([{"role": "system", "content": sys},
                                              {"role": "user", "content": usr}], temperature=0.0))
        return (bool(out.get("fact", False)), bool(out.get("logic", False)))

    def extract_reasoning(self, task, trajs, outcomes, env) -> ReasoningItem | None:
        # Distill a CONCRETE, reusable procedure: keep the real UI element labels and
        # their order from the gold path (these are the reusable signal); also note the
        # typical mistake from failed attempts. Abstracting these away yields useless
        # platitudes, so we deliberately KEEP the specifics here.
        sys = ('You are an expert web agent. You get a task, the agent\'s attempts (with '
               'per-step correctness), and the GOLD CORRECT PATH (the actually-correct '
               'steps, with element labels). Distill ONE reusable, CONCRETE procedure for '
               'this KIND of task on this site. KEEP the real element labels and their '
               'order from the gold path (e.g. "click \'Filter by\' -> \'Next month\' -> '
               '\'Apply\'"). Also state the typical mistake to avoid (from failed attempts). '
               'Respond JSON {"title": str, "description": str (WHEN to use: the site + the '
               'kind of task this applies to), "content": str (the concrete step-by-step '
               'procedure with element labels, + the pitfall to avoid)}.')
        usr = self._attempts_blob(task, trajs, outcomes)
        out = self._json(self.judge_llm.chat([{"role": "system", "content": sys},
                                              {"role": "user", "content": usr}], temperature=0.0))
        if not out.get("content"):
            return None
        any_success = any(o.success for o in outcomes)
        return ReasoningItem(title=out.get("title", "strategy"),
                             description=out.get("description", ""),
                             content=out["content"],
                             outcome="success" if any_success else "failure",
                             source_traj_ids=[t.traj_id for t in trajs])

    def extract_fact(self, task, trajs, outcomes, env) -> list[FactItem]:
        # Mine MULTIPLE site-general UI facts from the gold path — the reusable unit that
        # transfers across DIFFERENT tasks on the same site (search box, nav, filters...).
        sys = ('From the GOLD CORRECT PATH, extract reusable UI facts about THIS website '
               'that would help ANY task on this site: which labeled element does what '
               '(e.g. search box label, category navigation, filter/sort controls, date '
               'picker, apply/continue buttons). Each fact MUST be site-general and '
               'described by visible element text/label — NOT tied to this task\'s specific '
               'query, and NEVER use per-page ids. Respond JSON '
               '{"facts": [{"statement": str, "key": str (short slug for upsert)}]} (up to 6).')
    def judge_step(self, task, step, thought, action, is_correct, gold_repr) -> dict:
        # LAYER 1 surprise: ONE judge call per (attempt, step). The CORRECT control is parsed
        # from the gold action and handed to the model as ground truth, so the model CANNOT
        # re-derive (and get wrong) which control is correct — it only explains WHEN the control
        # is needed (intent), how to recognize it (cue), and the look-alike trap. The statement
        # is then assembled from a template and de-literalized in code, so task-specific values
        # can't leak and the correct control is always the gold one.
        #   * WRONG or CORRECT-but-lucky -> emit a rule.  CORRECT-and-genuine -> nothing new.
        role, label, _op = _parse_control(gold_repr)
        verdict = "CORRECT" if is_correct else "WRONG"
        sys = (
            "You label ONE web-navigation step into a reusable DECISION RULE. The CORRECT control "
            "is ALREADY GIVEN (parsed from gold). Do NOT decide correctness; only describe how to "
            "recognize it and the trap.\n"
            "Given: sub-goal, page candidates, agent REASONING and chosen ACTION, verdict, and "
            "CORRECT_CONTROL={role,label}.\n"
            "Return JSON {\"genuine\":bool,\"reason\":str,\"intent\":str,\"cue\":str,\"trap\":str}.\n"
            "- genuine: WRONG -> false. CORRECT -> true only if the reasoning names the real "
            "discriminative cue for CORRECT_CONTROL (else false = lucky guess).\n"
            "- reason: one short clause on why the step failed or was lucky.\n"
            "- intent: the GENERIC user sub-goal this control serves, 3-6 word verb phrase. If the "
            "sub-goal names a specific place/product/show/date/number, GENERALIZE it: say 'find "
            "events in a city' NOT 'in New York City'; 'search for a vehicle' NOT 'for Honda'. BAD "
            "(never output): a control name; the words button/filter/link/element; 'page-state'/'sub-goal'.\n"
            "- cue: how to recognize CORRECT_CONTROL by its visible text/role/position, <=15 words; "
            "same generalization rule.\n"
            "- trap: ONLY the visible label of the WRONG control the agent picked, <=5 words, and it "
            "MUST differ from CORRECT_CONTROL.label; if the pick equals the correct control or no "
            "distinct wrong control is identifiable, set trap to \"\".\n"
            "- HARD: CORRECT_CONTROL.label is ground truth; NEVER name a different control as correct. "
            "intent and cue MUST be non-empty. NEVER copy any product name, place, date, number, "
            "color, or size into intent or cue."
        )
        usr = (f"SUB-GOAL: {task.prompt}\nPAGE candidates: {step.obs[:600]}\n"
               f"AGENT reasoning: {thought}\nAGENT chose: {action}\n"
               f"CORRECT_CONTROL: role={role} label={label!r}\nVerdict: {verdict}")
        out = self._json(self.judge_llm.chat([{"role": "system", "content": sys},
                                              {"role": "user", "content": usr}], temperature=0.0))
        genuine = bool(out.get("genuine", False)) if is_correct else False
        reason = (out.get("reason") or "").strip()
        if (is_correct and genuine) or not label:
            return {"genuine": genuine, "reason": reason, "lesson": None}
        # deterministic post-filter: strip dangerous literals, drop degenerate/echoed traps
        lit = _dangerous_literals(task.prompt, gold_repr)
        intent = _delist(str(out.get("intent", "")).strip(), lit)
        cue = _delist(str(out.get("cue", "")).strip(), lit)
        trap = str(out.get("trap", "")).strip()
        if (not trap) or trap.lower() == label.lower() or re.match(r"(CLICK|TYPE|SELECT|HOVER)\b", trap, re.I):
            trap = ""
        if not intent:                                   # no usable condition -> not reusable
            return {"genuine": genuine, "reason": reason, "lesson": None}
        stmt = f"When {intent}: use '{label}' ({role})"
        if trap:
            stmt += f", not '{trap}'"
        if cue:
            stmt += f". {cue}"
        key = re.sub(r"[^a-z0-9]+", "-", f"{role}:{label}:{intent}".lower()).strip("-")[:80]
        lesson = FactItem(scope=task.scope, statement=stmt, polarity="positive",
                          key=key, condition=intent)
        return {"genuine": genuine, "reason": reason, "lesson": lesson}

    def extract_step_experiences(self, task, step, attempts, gold_repr, mode) -> list[FactItem]:
        # LAYER 2 surprise: contrastive distillation ACROSS the N attempts for one step.
        # SITE-SPECIFIC step knowledge (stored as scoped facts, retrieved by site). The debug
        # showed errors are "doesn't know THIS site's required element/sequence" -> generic
        # rules don't help; concrete site rules do.
        n = len(attempts)
        nc = sum(1 for a in attempts if a["correct"])
        majority = "correct" if nc * 2 >= n else "wrong"
        direction = (
            "MOST attempts FAILED and a few succeeded -> summarize HOW to do this step "
            "CORRECTLY: the reliable way the correct attempt(s) / the GOLD action used."
            if majority == "wrong" else
            "MOST attempts SUCCEEDED and a few failed -> summarize HOW to AVOID the trap the "
            "failing attempt(s) fell into (the look-alike control they wrongly picked)."
        )
        sys = (
            "You are an expert in web navigation. For ONE step of a task, an agent made N parallel "
            "attempts. You are given the goal, the page candidates, the GOLD correct action, and "
            "for each attempt: its REASONING, chosen ACTION, whether it was CORRECT, and a short "
            "per-attempt reflection on why it went wrong.\n\n"
            "## Think first (self-contrast)\n"
            "Reflect on WHY some attempts succeeded and others failed - what distinguishes the "
            "correct control from the look-alike(s) the wrong attempts picked. Use the GOLD action "
            "as ground truth and the per-attempt reflections.\n\n"
            "## Then summarize\n"
            f"  - {direction}\n\n"
            "## Item format (each): title / description / content\n"
            "      title:       short name for the control / decision.\n"
            "      description: WHEN to use and WHEN NOT to use this item (the condition).\n"
            "      content:     1-3 sentences of insight to AVOID such failures and pick the right control.\n\n"
            "## Hard rules\n"
            "  - Describe controls by GENERAL FUNCTION + visible text/role, NEVER by numeric id.\n"
            "  - State what the control DOES, NOT how it serves THIS task.\n"
            "  - NEVER include any value taken from the goal (product names, places, dates, numbers).\n"
            "  - Do NOT output overlapping or duplicate items. At most 3 items.\n\n"
            'Respond JSON: {"facts":[{"title":str,"description":str,"content":str,"key":str}]}'
        )
        lines = [f"GOAL: {task.prompt}", f"PAGE candidates: {step.obs[:600]}",
                 f"GOLD correct action (abstract it, do NOT copy literal values): {gold_repr}",
                 f"{n} attempts, {nc} correct:"]
        for i, a in enumerate(attempts):
            lines.append(f"  attempt{i+1} [{'ok' if a['correct'] else 'wrong'}]: "
                         f"reasoning: {a['thought'][:160]} -> chose {a['chosen']}")
            if a.get("reason"):
                lines.append(f"      why-wrong (layer1): {a['reason'][:160]}")
        out = self._json(self.judge_llm.chat([{"role": "system", "content": sys},
                                              {"role": "user", "content": "\n".join(lines)}],
                                             temperature=0.0))
        items = []
        for f in out.get("facts", []):
            if not isinstance(f, dict):
                continue
            stmt = _fmt_item(f)
            if not stmt or not _is_abstract_site_fact(stmt, task, gold_repr):
                continue
            items.append(FactItem(scope=task.scope, statement=stmt, key=f.get("key")))
        return items

    @staticmethod
    def _attempts_blob(task, trajs, outcomes) -> str:
        # Feed the FULL self-experience (reasoning + choice + correctness), like
        # ReasoningBank — NOT the gold answer (stay faithful to learning from
        # self-judged experience; gold would be cheating vs real deployment).
        lines = [f"TASK:\n{task.prompt}", "",
                 "ATTEMPTS (the agent's own reasoning and chosen answer, with the "
                 "self-judged correctness signal):"]
        for i, (t, o) in enumerate(zip(trajs, outcomes)):
            verdict = "CORRECT" if o.success else "INCORRECT"
            lines.append(f"\n[attempt {i + 1} — overall {verdict}]")
            if len(t.steps) <= 1:
                th = t.steps[0].thought if t.steps else ""
                lines.append(f"reasoning: {th}")
                lines.append(f"chosen answer: {t.final_answer}")
            else:  # multi-step trajectory (e.g. Mind2Web episode)
                for k, st in enumerate(t.steps):
                    mark = {True: "ok", False: "wrong"}.get(st.correct, "?")
                    lines.append(f"  step {k+1} [{mark}]: {st.thought} -> {st.action}")
        # learning phase may supply the gold correct path (with element labels)
        gold = trajs[0].meta.get("gold_path") if trajs else None
        if gold:
            lines.append("\nGOLD CORRECT PATH (the actually-correct steps for this task):")
            lines.extend(f"  {g}" for g in gold)
        return "\n".join(lines)
