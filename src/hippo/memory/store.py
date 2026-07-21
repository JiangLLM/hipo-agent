"""Self-built dual memory: ReasoningStore (similarity) + FactStore (scope+similarity).

Not Honcho's DB — just its split-of-concerns style. v1 keeps items in-memory with
numpy vectors and can snapshot to JSON. Reasoning is append-only (v1); facts upsert
by key so corrected/negative facts overwrite stale ones.
"""
from __future__ import annotations

import os
import threading
from typing import Callable

import numpy as np

from ..schema import FactItem, ReasoningItem

EmbedFn = Callable[[list[str]], list[list[float]]]


def _cos(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    if b.ndim == 1:
        b = b[None, :]
    an = a / (np.linalg.norm(a) + 1e-9)
    bn = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-9)
    return bn @ an


class ReasoningStore:
    def __init__(self, embed_fn: EmbedFn):
        self._embed = embed_fn
        self.items: list[ReasoningItem] = []
        self._lock = threading.Lock()   # thread-safe under task-parallel learn

    def add(self, item: ReasoningItem) -> None:
        if item.embedding is None:                      # embed OUTSIDE the lock (network)
            item.embedding = self._embed([f"{item.title}. {item.description}"])[0]
        with self._lock:
            self.items.append(item)

    def topk(self, query: str, k: int, threshold: float = 0.0,
             scope: str | None = None) -> list[ReasoningItem]:
        """`scope=None` searches everything (legacy); a scope string restricts the pool
        to items written under that scope (e.g. one repo / one website)."""
        if k <= 0:
            return []
        with self._lock:
            items = list(self.items)                            # snapshot under lock
        if scope is not None:
            items = [it for it in items if getattr(it, "scope", "") == scope]
        if not items:
            return []                                           # skip embedding when empty
        q = np.asarray(self._embed([query])[0], dtype=float)   # embed outside lock
        mat = np.asarray([it.embedding for it in items], dtype=float)
        sims = _cos(q, mat)
        order = np.argsort(-sims)
        # threshold gate: only return items relevant enough (can return nothing)
        return [items[i] for i in order if sims[i] >= threshold][:k]

    def topk_scored(self, query: str, k: int, threshold: float = 0.0,
                    scope: str | None = None) -> list[tuple[ReasoningItem, float]]:
        """Like topk but returns (item, cosine) pairs — for retrieval-quality logging
        and downstream relevance gating."""
        items = self.topk(query, k, threshold, scope)
        if not items:
            return []
        q = np.asarray(self._embed([query])[0], dtype=float)
        mat = np.asarray([it.embedding for it in items], dtype=float)
        sims = _cos(q, mat)
        return list(zip(items, [float(s) for s in sims]))


class FactStore:
    def __init__(self, embed_fn: EmbedFn):
        self._embed = embed_fn
        self.items: list[FactItem] = []
        self._lock = threading.Lock()   # thread-safe under task-parallel learn

    def upsert(self, item: FactItem) -> None:
        if item.embedding is None:                      # embed OUTSIDE the lock (network)
            item.embedding = self._embed([item.statement])[0]
        with self._lock:
            if item.key is not None:
                for i, ex in enumerate(self.items):
                    if ex.key == item.key and ex.scope == item.scope:
                        self.items[i] = item   # overwrite stale value
                        return
            self.items.append(item)

    def query(self, scope: str, query: str, k: int, threshold: float = 0.0) -> list[FactItem]:
        if k <= 0:
            return []
        with self._lock:
            pool = [it for it in self.items if it.scope == scope]   # snapshot under lock
        if not pool:
            return []
        q = np.asarray(self._embed([query])[0], dtype=float)        # embed outside lock
        mat = np.asarray([it.embedding for it in pool], dtype=float)
        sims = _cos(q, mat)
        order = np.argsort(-sims)
        return [pool[i] for i in order if sims[i] >= threshold][:k]


class Memory:
    """Manager honoring the ablation switches (memory.mode, k, token budget)."""

    def __init__(self, embed_fn: EmbedFn, cfg):
        self.cfg = cfg
        self.mode = cfg.memory.mode               # off | fact_only | reasoning_only | both
        self.reasoning = ReasoningStore(embed_fn)
        self.fact = FactStore(embed_fn)

    @property
    def use_reasoning(self) -> bool:
        return self.mode in ("reasoning_only", "both")

    @property
    def use_fact(self) -> bool:
        return self.mode in ("fact_only", "both")

    def retrieve(self, task) -> dict:
        thr = float(self.cfg.memory.get("relevance_threshold", 0.0))
        r_scope = task.scope if bool(self.cfg.memory.get("scope_reasoning", False)) else None
        r = (self.reasoning.topk(task.prompt, self.cfg.memory.retrieve_k_reasoning, thr, scope=r_scope)
             if self.use_reasoning else [])
        f = self.fact.query(task.scope, task.prompt, self.cfg.memory.retrieve_k_fact, thr) if self.use_fact else []
        return {"reasoning": r, "fact": f}

    def write_reasoning(self, item: ReasoningItem) -> None:
        if self.use_reasoning:
            self.reasoning.add(item)

    def write_fact(self, item: FactItem) -> None:
        if self.use_fact:
            self.fact.upsert(item)

    def render(self, retrieved: dict) -> str:
        budget_chars = self.cfg.memory.token_budget * 4  # ~4 chars/token
        candidates = []
        for it in retrieved.get("fact", []):
            sign = "NOT " if it.polarity == "negative" else ""
            candidates.append(f"[fact] {sign}{it.statement}")
        for it in retrieved.get("reasoning", []):
            when = f" (applies when: {it.description})" if it.description else ""
            candidates.append(f"[strategy] {it.title}: {it.content}{when}")
        # cap by whole items (never cut an item mid-text)
        lines, total = [], 0
        for line in candidates:
            if total + len(line) + 1 > budget_chars:
                break
            lines.append(line)
            total += len(line) + 1
        return "\n".join(lines)

    def stats(self) -> dict:
        return {"n_reasoning": len(self.reasoning.items), "n_fact": len(self.fact.items)}

    def save(self, path: str) -> None:
        import json
        from dataclasses import asdict

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        blob = {"reasoning": [asdict(it) for it in self.reasoning.items],
                "fact": [asdict(it) for it in self.fact.items]}
        with open(path, "w") as fh:
            json.dump(blob, fh)

    def load(self, path: str) -> None:
        import json

        with open(path) as fh:
            blob = json.load(fh)
        self.reasoning.items = [ReasoningItem(**d) for d in blob.get("reasoning", [])]
        self.fact.items = [FactItem(**d) for d in blob.get("fact", [])]
        self._reembed_if_dim_mismatch()

    def _reembed_if_dim_mismatch(self) -> None:
        """Guard: saved embeddings may be from a different embed model than the current
        brain (e.g. loading an LLM-built store under a hashing brain). Re-embed if so."""
        probe = len(self.reasoning._embed(["probe"])[0])
        def bad(it):
            return not it.embedding or len(it.embedding) != probe
        for it in self.reasoning.items:
            if bad(it):
                it.embedding = self.reasoning._embed([f"{it.title}. {it.description}"])[0]
        for it in self.fact.items:
            if bad(it):
                it.embedding = self.fact._embed([it.statement])[0]
