"""One WebArena rollout = one BrowserGym episode driven by an LLM agent.

Mirrors swe/rollout.py: memory is injected into the goal prompt (empty memory =
byte-identical to no-memory), the agent emits one action per turn until it sends a
message to the user (WebArena's task-complete signal) or hits the step cap.
BrowserGym returns the OFFICIAL task reward (0/1) at episode end, so unlike SWE there
is no separate evaluation harness — env.step's reward IS the ground truth.

API notes (verified against browsergym 0.14.x in .venv-wa):
  * obs page content lives in obs["axtree_object"] (raw CDP dict) -> render with
    flatten_axtree_to_str; there is no "axtree_txt" key.
  * actions must be mapped through a webarena HighLevelActionSet.to_python_code; the
    agent emits DSL like click('a12') / send_msg_to_user('answer'); bids must be quoted.
  * env.step never raises on a bad action — it stashes it in obs["last_action_error"],
    which we feed back to the agent so it can recover.
BrowserGym is imported lazily so importing this module never pulls it into the main env.
"""
from __future__ import annotations

import re
import urllib.parse


def _guard_host(action: str, origin: str) -> str:
    """Agents sometimes hallucinate an external host (gitlab.com, gitlab.local, github.com) inside
    a goto() when a project/branch isn't found on the dashboard/search — landing off the
    self-hosted env (login page or ERR_NAME_NOT_RESOLVED) and losing the episode. Rewrite any
    goto() whose host differs from the CURRENT page origin back onto that origin, so the agent's
    direct-navigation fallback lands on the real site instead of the public one."""
    if not origin or "goto(" not in action:
        return action
    m = re.search(r"""goto\(\s*(['"])(.*?)\1""", action)
    if not m:
        return action
    try:
        u = urllib.parse.urlparse(m.group(2))
        b = urllib.parse.urlparse(origin)
    except Exception:  # noqa: BLE001
        return action
    if u.scheme in ("http", "https") and u.netloc and u.netloc != b.netloc:
        fixed = urllib.parse.urlunparse(u._replace(scheme=b.scheme, netloc=b.netloc))
        return action[:m.start(2)] + fixed + action[m.end(2):]
    return action


def _action_set():
    from browsergym.core.action.highlevel import HighLevelActionSet

    return HighLevelActionSet(subsets=["webarena"], multiaction=False, strict=False)


class _StepTimeout(Exception):
    pass


def _call_with_timeout(fn, seconds: int):
    """Hard wall-clock cap via SIGALRM. browsergym/playwright's own per-action timeout
    doesn't cover every hang (a click that triggers a stuck navigation/download can wedge
    env.step indefinitely with the process idle on IO). Runs are single-threaded so the
    main-thread signal is safe. Raises _StepTimeout on expiry."""
    import signal

    def _handler(signum, frame):
        raise _StepTimeout(f"step exceeded {seconds}s")

    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        return fn()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def build_sys(action_set) -> str:
    return (
        "You are an autonomous web navigation agent. Each turn you see the accessibility "
        "tree of the current page and the history of what you already did.\n\n"
        + action_set.describe(with_long_description=False, with_examples=True) +
        "\n\nWork carefully: in your Thought, analyze the current page state, note which "
        "elements are relevant, recall what you already tried (avoid repeating a failed "
        "action), and decide the single best next action.\n"
        "Before you answer, VERIFY the answer against what is actually on the page — never "
        "answer from memory or a guess. Wait until the result rows you need are visible "
        "(after running a report/filter), then read them.\n"
        "Completeness rules: (1) if the task asks you to find or count things across a list "
        "(reviews, results, items), scroll/page through the WHOLE list before answering — a "
        "partial answer is wrong. (2) Copy the COMPLETE value shown for the entity: if a grid "
        "shows only a first name but a detail view shows the full name, open the detail and "
        "use the full name. (3) If a rank/most/Nth is asked and several entities TIE, list "
        "EVERY tied entity — re-sort or scroll to confirm you found them all. (4) Read ranked "
        "tables in order and don't confuse near-identical variants (e.g. 55 cm vs 65 cm).\n"
        "When the task asks for information, finish with send_msg_to_user containing ONLY the "
        "answer value — no sentence, no explanation, no units unless the task explicitly asks "
        "for them. Your message is compared against the exact expected answer, so any extra "
        "words make it wrong. If a single item is asked for, send exactly that item, e.g. "
        "send_msg_to_user(\"Quest Lumaflex Band\"), NOT \"The top product is Quest Lumaflex "
        "Band, with 5 sold.\" If a list is asked for, send just the items separated by commas, "
        "matching the wording the page uses. Copy names/labels verbatim from the page.\n"
        "When it asks to perform an action, finish once the change is confirmed on the page. "
        "Element ids (bids) MUST be quoted, e.g. click('a51').\n"
        "Stay on THIS server: everything the task needs is on the site you are already on. If a "
        "project isn't on the dashboard, navigate to it by path on the CURRENT host (or use "
        "Explore) — NEVER goto an external host such as gitlab.com, gitlab.local, or github.com.\n\n"
        "Respond in this format:\nThought: <your reasoning, as many sentences as needed>\n"
        "Action: <exactly one action call, e.g. click('a5') or send_msg_to_user(\"answer\")>\n"
        "The Action line MUST be a function call. To give your final answer, wrap it: "
        "send_msg_to_user(\"Sprite\") — never write the bare answer on its own line."
    )


def _obs_text(obs: dict) -> str:
    """Render the FULL accessibility tree, never truncated. WebArena pages run 20-40k+ chars
    and the task-relevant elements (products, forms, reviews) sit in the MIDDLE/END, so any
    truncation silently drops the very elements the agent must click. filter_visible_only=False
    to match the standard GenericAgent scaffold (fuller context)."""
    from browsergym.utils.obs import flatten_axtree_to_str

    try:
        return flatten_axtree_to_str(obs["axtree_object"],
                                     extra_properties=obs.get("extra_element_properties"),
                                     filter_visible_only=False)
    except Exception:  # noqa: BLE001 - fall back to bare render
        return flatten_axtree_to_str(obs["axtree_object"])


def _goal(obs: dict) -> str:
    if obs.get("goal"):
        return obs["goal"]
    msgs = obs.get("goal_object") or obs.get("chat_messages") or []
    for m in msgs:
        if m.get("role") in ("user", None) and m.get("message"):
            return m["message"]
    return ""


_ACTION_CALL = re.compile(r"^[a-zA-Z_]\w*\s*\(")


def _parse(resp: str) -> tuple[str, str]:
    resp = resp or ""
    # anchor on the Action: line (or end), NOT the first newline — otherwise a multi-line
    # Thought is truncated to its first line and the judge/L1/L2 never see the real reasoning
    # (which is exactly what verified/真会-vs-蒙对 gating depends on).
    th = re.search(r"Thought:\s*(.*?)(?:\n\s*Action:|\Z)", resp, re.S)
    am = re.search(r"Action:\s*(.+?)(?:\n|$)", resp, re.S)
    thought = th.group(1).strip() if th else ""
    lines = [x for x in resp.strip().splitlines() if x.strip()]
    action = (am.group(1).strip() if am else (lines[-1] if lines else "noop()")).strip()
    # Coerce a bare answer into a proper terminal action. Reasoning models often emit just
    # the answer value ("Sprite") instead of send_msg_to_user("Sprite"); a raw value is not
    # a valid action, so the episode would burn its whole step budget re-emitting it (seen
    # in 94% of episodes). Anything that isn't a verb(...) call is treated as the final
    # answer — the agent only produces bare text when it believes it is done answering.
    if not _ACTION_CALL.match(action):
        ans = re.sub(r"^(Thought|Action|Answer|Final Answer)\s*:\s*", "", action, flags=re.I)
        ans = ans.strip().strip('"').strip("'").replace('"', "'")
        action = f'send_msg_to_user("{ans}")'
    return thought, action


def _history(steps: list[dict], k: int = 15) -> str:
    """The AGENT's own live working history (thought + action + error per step) — its scratchpad,
    NOT the evidence the judge/L1/L2 read (that is compact_trace, kept FULL). Keep it BOUNDED:
    last k steps, thought clipped. Feeding the agent its entire full-reasoning history on a long
    task balloons the prompt and makes it lose the plot — the 16-page enumeration family went 8/8
    -> 0/8 when this was un-truncated. Truncation-freedom belongs on the learning/judging path;
    here (the agent's working memory) it hurts."""
    if not steps:
        return "(none yet)"
    out = []
    for i, s in enumerate(steps[-k:], start=max(1, len(steps) - k + 1)):
        line = f"{i}. thought: {s.get('thought','')[:200]}\n   action: {s['action']}"
        if s.get("err"):
            line += f"\n   -> ERROR: {s['err']}"
        out.append(line)
    return "\n".join(out)


def run_episode(task_id: int, memory_text: str, cfg, llm, logger=None, log_ctx: dict | None = None) -> dict:
    """Run one episode. Returns {reward(0/1), n_steps, steps[], stop_answer, error}.
    Never raises on agent-level failure; BudgetExceeded propagates (intentional stop).
    log_ctx (e.g. {tag, task_id, rollout}) tags every per-step event for post-hoc debug."""
    import browsergym.webarena  # noqa: F401 - registers tasks
    import gymnasium as gym

    from ..llm import BudgetExceeded

    ctx = log_ctx or {}

    def ev(kind, **f):
        if logger is not None:
            logger.event(kind, **ctx, **f)

    wa = cfg.get("wa", {}) or {}
    step_cap = int(wa.get("max_steps", 20))
    action_set = _action_set()
    sys = build_sys(action_set)
    # Optional, cost-aware framing: past lessons are HINTS, not mandates. Naive injection
    # made the agent follow a lesson's expensive procedure (hunt an attribute, open every
    # row) even when the answer was directly available, adding steps and new failure modes.
    mem_block = (
        "Optional hints from past tasks on this site — use one ONLY if it clearly fits the "
        "current task, and prefer the cheapest sufficient evidence. Do not add steps or chase "
        "a procedure a hint describes if you can already answer directly and correctly:\n"
        f"{memory_text}\n\n") if memory_text else ""
    env = None
    steps, reward = [], 0
    reset_to = int(wa.get("reset_timeout", 120))
    try:
        # make/reset are the browser setup path; wrap them in the same hard timeout as step
        # (a wedged Playwright teardown/setup otherwise busy-spins a greenlet at 100% CPU with
        # no timeout, hanging the whole run — seen mid-ablation). Best-effort: SIGALRM lands
        # when control returns to Python. On expiry the episode degrades to an error, not a hang.
        env = _call_with_timeout(lambda: gym.make(
            f"browsergym/webarena.{task_id}",
            action_mapping=action_set.to_python_code,
            timeout=int(wa.get("timeout", 10000)),
            disable_env_checker=True), reset_to)
        obs, info = _call_with_timeout(lambda: env.reset(), reset_to)
        goal = _goal(obs)
        n_preset = len(obs.get("chat_messages") or [])   # reset seeds a greeting; skip it
        ev("wa_episode_start", goal=goal, mem_injected=bool(memory_text),
           mem_chars=len(memory_text or ""))
        for si in range(step_cap):
            usr = (f"{mem_block}TASK: {goal}\n\nHISTORY:\n{_history(steps)}\n\n"
                   f"CURRENT PAGE (accessibility tree):\n{_obs_text(obs)}")
            resp = llm.chat([{"role": "system", "content": sys},
                             {"role": "user", "content": usr}],
                            temperature=cfg.llm.temperature)
            thought, action = _parse(resp)
            # off-host navigation guard: keep goto() on the current env origin (see _guard_host)
            _cur = obs.get("url") if isinstance(obs, dict) else None
            if _cur:
                _p = urllib.parse.urlparse(_cur)
                _g = _guard_host(action, f"{_p.scheme}://{_p.netloc}")
                if _g != action:
                    ev("wa_host_guard", step=si, was=action, now=_g)
                    action = _g
            try:
                obs, reward, terminated, truncated, info = _call_with_timeout(
                    lambda: env.step(action), int(wa.get("step_timeout", 90)))
            except _StepTimeout as exc:   # wedged browser op — env may be corrupt, end episode
                steps.append({"thought": thought, "action": action,
                              "err": str(exc), "url": "", "obs": ""})
                ev("wa_step", step=si, thought=thought, action=action, raw=resp,
                   url="", reward=int(reward or 0), action_error=str(exc), terminated=True)
                break
            err = obs.get("last_action_error") or ""
            # store the FULL observation snapshot per step so the judge/extractor can SEE
            # exactly what the page showed — verified-gating (real vs fluke) depends on this.
            steps.append({"thought": thought, "action": action, "err": err,
                          "url": obs.get("url", ""), "obs": _obs_text(obs)})
            ev("wa_step", step=si, thought=thought, action=action, raw=resp,
               url=obs.get("url", ""), reward=int(reward or 0),
               action_error=err, terminated=bool(terminated or truncated))
            if terminated or truncated:
                break
        stop_answer = ""
        chat = (obs.get("chat_messages") or [])[n_preset:]   # only agent-produced messages
        for m in reversed(chat):
            if m.get("role") == "assistant" and m.get("message"):
                stop_answer = m["message"]
                break
        ev("wa_episode_end", reward=int(reward or 0), n_steps=len(steps),
           stop_answer=stop_answer, n_action_errors=sum(1 for s in steps if s["err"]))
        return {"reward": int(reward or 0), "n_steps": len(steps), "steps": steps,
                "stop_answer": stop_answer, "error": ""}
    except BudgetExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 - env/setup failure -> degrade, don't halt
        ev("wa_episode_error", err=f"{type(exc).__name__}: {exc}", n_steps=len(steps))
        return {"reward": 0, "n_steps": len(steps), "steps": steps, "stop_answer": "",
                "error": f"{type(exc).__name__}: {exc}"}
    finally:
        if env is not None:
            try:
                _call_with_timeout(lambda: env.close(), 60)
            except Exception:  # noqa: BLE001 - wedged close must not hang the run
                pass


def compact_trace(steps: list[dict], obs_budget: int = 200000) -> str:
    """Judge/extractor-readable trace with FULL page evidence — the verified check (real vs
    fluked correct) and L1/L2 read this trace. Normal traces are un-truncated. ONLY when the
    concatenated page obs would overflow the judge model's context (huge Magento grids x many
    steps -> ContextWindowExceeded, which hard-fails the whole task) do we bound it: spend the
    obs budget on the LATEST steps first (the answer is read there — the evidence the verified
    label needs most) and OMIT the oldest steps' pages once the budget is spent."""
    obs_keep: dict = {}
    used = 0
    for i in range(len(steps) - 1, -1, -1):        # newest -> oldest: give recent steps the budget
        obs = steps[i].get("obs", "") or ""
        if not obs:
            continue
        if used >= obs_budget:
            obs_keep[i] = None                     # omit this old page entirely
        elif used + len(obs) <= obs_budget:
            obs_keep[i] = obs; used += len(obs)
        else:
            obs_keep[i] = obs[: obs_budget - used] + "…[clipped]"; used = obs_budget
    lines = []
    for i, s in enumerate(steps):
        head = (f"step {i+1}: {s['thought']} -> {s['action']}"
                + (f"  [ERR: {s['err']}]" if s.get("err") else "")
                + (f"  @ {s.get('url','')}" if s.get("url") else ""))
        if s.get("obs"):
            kept = obs_keep.get(i, "")
            head += f"\n  page: {kept}" if kept else "\n  page: [omitted — trace too long for the judge]"
        lines.append(head)
    return "\n".join(lines)
