"""Deterministic toy env to exercise the full pipeline with zero API cost.

Two task families, designed so the two memory channels matter:

* ``fact`` tasks  — the correct action is a per-site secret (``scope`` + item id).
  Only learnable by *remembering* it → exercises the FactStore.
* ``logic`` tasks — the correct action is derivable by a fixed rule that transfers
  across sites (parity of a number list) → exercises the ReasoningStore.

A memoryless agent guesses (~chance). Once a surprise is consolidated, the relevant
knowledge is injected next time and the agent succeeds → cumulative SR should climb.
"""
from __future__ import annotations

import random

from ..schema import Task
from .base import BaseEnv

FACT_ACTIONS = ["alpha", "beta", "gamma", "delta", "epsilon"]
LOGIC_ACTIONS = ["even", "odd"]


class MockEnv(BaseEnv):
    name = "mock"

    def __init__(self, cfg):
        self.cfg = cfg
        seed = cfg.run.seed
        self.rng = random.Random(seed)
        self.n_sites = int(cfg.get("mock", {}).get("n_sites", 3)) if isinstance(cfg.get("mock", {}), dict) else 3
        self.n_tasks = int(cfg.get("mock", {}).get("n_tasks", 60)) if isinstance(cfg.get("mock", {}), dict) else 60
        self.n_fact_items = 4
        # per-site secret: item_id -> action
        self._secrets: dict[str, dict[int, str]] = {}
        for s in range(self.n_sites):
            scope = f"site:{s}"
            self._secrets[scope] = {
                k: self.rng.choice(FACT_ACTIONS) for k in range(self.n_fact_items)
            }

    def tasks(self) -> list[Task]:
        out: list[Task] = []
        rng = random.Random(self.cfg.run.seed + 1)
        for i in range(self.n_tasks):
            scope = f"site:{rng.randrange(self.n_sites)}"
            if rng.random() < 0.5:
                k = rng.randrange(self.n_fact_items)
                prompt = f"[{scope}] fact-task item={k}: which action applies here?"
                out.append(Task(id=f"t{i}", prompt=prompt, scope=scope,
                                task_type="fact", gold=self._secrets[scope][k],
                                meta={"item": k}))
            else:
                nums = [rng.randrange(1, 9) for _ in range(rng.randrange(2, 5))]
                gold = "even" if sum(nums) % 2 == 0 else "odd"
                prompt = f"[{scope}] logic-task nums={nums}: classify."
                out.append(Task(id=f"t{i}", prompt=prompt, scope=scope,
                                task_type="logic", gold=gold, meta={"nums": nums}))
        return out

    def evaluate(self, task: Task, action: str) -> bool:
        return str(action).strip().lower() == str(task.gold).strip().lower()

    # -- helpers used by the mock brain (a real env would not expose this) ----
    def oracle(self, task: Task) -> str:
        return str(task.gold)
