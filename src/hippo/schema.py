"""Core data structures shared across the pipeline."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@dataclass
class Task:
    id: str
    prompt: str
    scope: str                      # environment id (e.g. "site:shopping", "repo:x@sha")
    task_type: str = "generic"      # used by mock env + routing analysis
    gold: Any = None                # offline metric only; never shown to the agent
    meta: dict = field(default_factory=dict)


@dataclass
class Step:
    thought: str
    action: str
    obs: str
    predicted_obs: str | None = None   # for observation-level surprise (fact routing)
    correct: bool | None = None        # self-judged correctness of this step (no gold leak)


@dataclass
class Trajectory:
    task_id: str
    traj_id: str
    steps: list[Step] = field(default_factory=list)
    final_answer: str | None = None
    env_success: bool | None = None    # ground-truth success from env (if available)
    meta: dict = field(default_factory=dict)


@dataclass
class Outcome:
    """Label-free judgment of a trajectory (grounded on the execution result)."""
    success: bool
    can_derive: bool = True            # did the agent claim it could solve from memory?
    confidence: float = 1.0
    reason: str = ""


@dataclass
class ReasoningItem:
    title: str
    description: str
    content: str
    scope: str = ""                    # optional env id (e.g. "repo:django/django"); "" = global
    certainty: str = "medium"          # Honcho-style tag: low | medium | high
    outcome: str = "unknown"           # success | failure
    source_traj_ids: list[str] = field(default_factory=list)
    surprise: float = 0.0
    id: str = field(default_factory=lambda: _uid("rsn"))
    created_at: float = field(default_factory=time.time)
    embedding: list[float] | None = None


@dataclass
class FactItem:
    scope: str
    statement: str
    polarity: str = "positive"         # positive | negative (confirmed failure)
    confidence: float = 1.0
    evidence_traj_id: str | None = None
    key: str | None = None             # for upsert/dedup (e.g. scope+task_type)
    condition: str = ""                # generic sub-goal this fact applies to (for intent-based retrieval)
    id: str = field(default_factory=lambda: _uid("fact"))
    created_at: float = field(default_factory=time.time)
    embedding: list[float] | None = None


@dataclass
class BufferEntry:
    """One hippocampal-buffer record awaiting consolidation."""
    task: Task
    trajs: list[Trajectory]
    outcomes: list[Outcome]
    surprise: float
    route_fact: bool = False
    route_reasoning: bool = False
    signals: dict = field(default_factory=dict)   # raw surprise signals, for logging
