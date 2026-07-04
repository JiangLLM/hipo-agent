"""Environment contract.

v1 treats a task as single-step action prediction (fits the mock toy env and offline
Mind2Web-style action prediction). Multi-step ReAct can extend this later by making
`evaluate` consume a trajectory instead of a single action.
"""
from __future__ import annotations

from ..schema import Task


class BaseEnv:
    name: str = "base"

    def tasks(self) -> list[Task]:
        raise NotImplementedError

    def initial_obs(self, task: Task) -> str:
        return task.prompt

    def evaluate(self, task: Task, action: str) -> bool:
        """Ground-truth success of an action for this task (used to ground the judge)."""
        raise NotImplementedError
