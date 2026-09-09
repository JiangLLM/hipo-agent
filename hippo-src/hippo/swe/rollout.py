"""One rollout attempt = one fresh Docker container + a mini-swe-agent DefaultAgent.

mini-swe-agent is used strictly as the environment/agent shell (container exec,
bash-tool loop, patch submission protocol); everything hippo-specific — memory
injection, judging, extraction — lives outside it. Memory is injected by prefixing
the instance template with a `{{memory}}` block, so an empty memory renders to
nothing and the nomem arm is byte-identical to stock mini-swe-agent.

Each attempt gets its OWN container from the same per-instance image, which is what
makes N parallel attempts on one task state-isolated for free (the WebArena version
of this design has to fight cross-rollout pollution; here Docker gives it to us).
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .data import image_name

_MEMORY_BLOCK = """{% if memory %}<memory>
Lessons your past attempts learned on THIS repository. Each item says when it
applies; use an item only if it is relevant to the current issue.

{{memory}}
</memory>

{% endif %}"""

# "attend" variant: one-time forced attention. Cheaper than ReasoningBank's
# discuss-every-step, but guarantees the memory is actually read once.
_MEMORY_BLOCK_ATTEND = """{% if memory %}<memory>
Lessons your past attempts learned on THIS repository:

{{memory}}
</memory>

IMPORTANT: in your FIRST response, before any command, state in one or two
sentences which memory items (if any) apply to this issue and how you will use
them; then proceed.

{% endif %}"""


def load_sb_config() -> dict:
    """Start from mini-swe-agent's stock swebench config so agent behavior (prompts,
    submission protocol, observation formatting) matches the community baseline."""
    from minisweagent.config import builtin_config_dir

    with open(builtin_config_dir / "benchmarks" / "swebench.yaml") as fh:
        return yaml.safe_load(fh)


class _NotesDockerEnvironment:
    """Wraps a DockerEnvironment so that the first time a command touches a file we
    have notes for, those notes are appended to that command's observation — the v2
    'inject at the moment of engagement' mechanism. Pure delegation otherwise."""

    def __init__(self, env, injector):
        self._env = env
        self._injector = injector

    def execute(self, action: dict, *args, **kwargs) -> dict:
        out = self._env.execute(action, *args, **kwargs)
        extra = self._injector.peek(action.get("command", ""))
        if extra and isinstance(out.get("output"), str):
            out["output"] = out["output"] + "\n\n" + extra
        return out

    def __getattr__(self, name):
        return getattr(self._env, name)


def run_attempt(instance: dict, memory_text: str, cfg, traj_path: Path) -> dict:
    """Run ONE attempt. Returns a plain dict (never raises on agent-level failure):
    {exit_status, patch, n_steps, cost, trace, error}."""
    from minisweagent.agents.default import DefaultAgent
    from minisweagent.environments.docker import DockerEnvironment
    from minisweagent.models import get_model

    swe = cfg.get("swe", {}) or {}
    base = load_sb_config()
    agent_cfg = base.get("agent", {})
    block = _MEMORY_BLOCK_ATTEND if swe.get("injection_style") == "attend" else _MEMORY_BLOCK
    agent_cfg["instance_template"] = block + agent_cfg["instance_template"]
    agent_cfg["step_limit"] = int(swe.get("step_limit", 60))
    agent_cfg["cost_limit"] = float(swe.get("attempt_cost_limit", 0.5))

    model_cfg = {**base.get("model", {}), "model_name": swe.get("agent_model", cfg.llm.model)}
    env_cfg = {**base.get("environment", {}),
               "image": image_name(instance, swe.get("arch", "arm64")),
               "pull_timeout": 1800}

    env = None
    try:
        model = get_model(config=model_cfg)
        env = DockerEnvironment(**env_cfg)
        run_env = env
        if swe.get("notes_in"):                 # v2 file-triggered notes (opt-in)
            from .notes import FileNotes, NotesInjector

            run_env = _NotesDockerEnvironment(env, NotesInjector(FileNotes(swe["notes_in"])))
        agent = DefaultAgent(model, run_env, output_path=traj_path, **agent_cfg)
        try:
            info = agent.run(instance["problem_statement"], memory=memory_text or "")
        except Exception as exc:  # noqa: BLE001 - DefaultAgent re-raises after logging
            info = {"exit_status": type(exc).__name__, "submission": ""}
        return {"exit_status": info.get("exit_status", ""),
                "patch": info.get("submission", "") or "",
                "n_steps": agent.n_calls, "cost": agent.cost,
                "trace": compact_trace(agent.messages), "error": ""}
    except Exception as exc:  # noqa: BLE001 - container/model setup failed
        return {"exit_status": "SetupError", "patch": "", "n_steps": 0, "cost": 0.0,
                "trace": "", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        if env is not None:
            env.cleanup()


# --------------------------------------------------------------------------- #
_TESTISH = re.compile(r"\b(pytest|runtests?|test_|tests\.|manage\.py test|tox|repro)", re.I)


def _actions(msg: dict) -> list[str]:
    return [a.get("command", "") for a in msg.get("extra", {}).get("actions", [])]


def _clip(text: str, head: int, tail: int = 0) -> str:
    text = text or ""
    if len(text) <= head + tail + 40:
        return text
    cut = f"\n...[{len(text) - head - tail} chars elided]...\n"
    return text[:head] + cut + (text[-tail:] if tail else "")


def compact_trace(messages: list[dict], max_chars: int = 30_000) -> str:
    """Compress a full transcript into a judge/extractor-readable trace.

    Test-ish command outputs keep much more text than ordinary ones — verification
    evidence ("ran the repro, saw it pass") is exactly what the judge must find, and
    it lives in those outputs. The final steps keep more, early steps less.
    """
    steps: list[str] = []
    step_no = 0
    for i, msg in enumerate(messages):
        role = msg.get("role", "")
        if role == "assistant":
            step_no += 1
            thought = _clip(str(msg.get("content", "")).strip(), 400)
            cmds = _actions(msg)
            block = [f"### step {step_no}", f"THOUGHT: {thought}"]
            block += [f"$ {_clip(c, 300)}" for c in cmds]
            steps.append("\n".join(block))
        elif role in ("user", "tool") and step_no > 0:
            out = str(msg.get("content", ""))
            prev_cmds = " ".join(_actions(messages[i - 1])) if i else ""
            keep = 1600 if _TESTISH.search(prev_cmds) else 400
            steps.append(f"OUTPUT: {_clip(out, keep, tail=200 if keep > 400 else 0)}")
    trace = "\n".join(steps)
    if len(trace) > max_chars:  # drop from the middle; the ending carries the verdict
        trace = trace[: max_chars // 3] + "\n...[trace elided]...\n" + trace[-2 * max_chars // 3:]
    return trace
