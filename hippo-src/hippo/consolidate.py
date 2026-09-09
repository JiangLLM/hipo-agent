"""Consolidation = prioritized replay of the hippocampal buffer into the slow stores.

Replays high-surprise entries first, extracts memory content (LLM/oracle), and writes
to the routed channel(s). Mirrors offline systems-consolidation in CLS.
"""
from __future__ import annotations

from .schema import BufferEntry


def consolidate(buffer: list[BufferEntry], memory, brain, env, logger) -> int:
    if not buffer:
        return 0
    if memory.cfg.replay.priority == "surprise":
        order = sorted(buffer, key=lambda e: e.surprise, reverse=True)
    else:
        order = list(buffer)

    written = 0
    for entry in order:
        if entry.route_reasoning and memory.use_reasoning:
            item = brain.extract_reasoning(entry.task, entry.trajs, entry.outcomes, env)
            if item is not None:
                item.surprise = entry.surprise
                memory.write_reasoning(item)
                written += 1
                logger.event("memory_write", channel="reasoning", task_id=entry.task.id,
                             surprise=entry.surprise, item=item)
        if entry.route_fact and memory.use_fact:
            items = brain.extract_fact(entry.task, entry.trajs, entry.outcomes, env) or []
            for item in items:
                memory.write_fact(item)
                written += 1
                logger.event("memory_write", channel="fact", task_id=entry.task.id,
                             surprise=entry.surprise, item=item)
    buffer.clear()
    return written
