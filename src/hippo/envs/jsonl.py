"""Generic JSONL env — the drop-in contract for real datasets.

Export any dataset to a JSONL file where each line is one single-step task:

    {"id": "...", "prompt": "...", "scope": "site:shopping",
     "task_type": "fact|logic|generic", "gold": "<answer or action>"}

then run:  python -m hippo.run --env jsonl --data.path data/your.jsonl

Scoring is exact-match by default (override `data.match` = "exact" | "contains").
Use this to wire Mind2Web/WebArena exports without touching the core loop. A real
LLM agent answers via LLMBrain; `evaluate` grounds the judge against `gold`.
"""
from __future__ import annotations

import json

from ..schema import Task
from .base import BaseEnv


class JsonlEnv(BaseEnv):
    name = "jsonl"

    def __init__(self, cfg):
        self.cfg = cfg
        data = cfg.get("data", {}) or {}
        self.path = data.get("path") if isinstance(data, dict) else None
        if not self.path:
            raise ValueError("env=jsonl requires --data.path <file.jsonl>")
        self.match = (data.get("match", "exact") if isinstance(data, dict) else "exact")
        limit = int(data.get("limit", 0)) if isinstance(data, dict) else 0
        self._tasks: list[Task] = []
        with open(self.path) as fh:
            for i, line in enumerate(fh):
                line = line.strip()
                if not line:
                    continue
                if limit and i >= limit:
                    break
                rec = json.loads(line)
                self._tasks.append(Task(
                    id=str(rec.get("id", i)),
                    prompt=rec["prompt"],
                    scope=rec.get("scope", "default"),
                    task_type=rec.get("task_type", "generic"),
                    gold=rec.get("gold"),
                    meta=rec.get("meta", {}),
                ))

    def tasks(self) -> list[Task]:
        return self._tasks

    def evaluate(self, task: Task, action: str) -> bool:
        if task.gold is None:
            return False
        a, g = str(action).strip().lower(), str(task.gold).strip().lower()
        if self.match == "contains":
            return g in a or a in g
        return a == g
