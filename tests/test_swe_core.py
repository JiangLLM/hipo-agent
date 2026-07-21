"""Offline tests for the SWE module's pure logic (no docker, no network)."""
import hashlib
import random

from hippo.config import DotDict
from hippo.memory.store import Memory, ReasoningStore
from hippo.schema import ReasoningItem, Task
from hippo.swe.rollout import compact_trace
from hippo.swe.run import Dedup


def _hash_embed(texts):
    out = []
    for t in texts:
        rng = random.Random(int(hashlib.sha256(t.encode()).hexdigest()[:8], 16))
        out.append([rng.uniform(-1, 1) for _ in range(16)])
    return out


def _item(title, scope):
    return ReasoningItem(title=title, description="when fixing validators",
                         content="look in core/validators.py", scope=scope)


def test_reasoning_scope_filter():
    store = ReasoningStore(_hash_embed)
    store.add(_item("django lesson", "repo:django/django"))
    store.add(_item("sympy lesson", "repo:sympy/sympy"))
    # threshold=-1 so the random hash embeddings can't gate anything out
    assert len(store.topk("validators", k=5, threshold=-1)) == 2       # legacy: no scope
    got = store.topk("validators", k=5, threshold=-1, scope="repo:django/django")
    assert [it.title for it in got] == ["django lesson"]
    assert store.topk("validators", k=5, threshold=-1, scope="repo:nope/nope") == []


def test_memory_retrieve_respects_scope_flag():
    cfg = DotDict({"memory": {"mode": "reasoning_only", "retrieve_k_reasoning": 5,
                              "retrieve_k_fact": 0, "scope_reasoning": True,
                              "relevance_threshold": -1, "token_budget": 4000}})
    mem = Memory(_hash_embed, cfg)
    mem.write_reasoning(_item("django lesson", "repo:django/django"))
    task = Task(id="t", prompt="fix URLValidator", scope="repo:django/django")
    assert len(mem.retrieve(task)["reasoning"]) == 1
    other = Task(id="t2", prompt="fix URLValidator", scope="repo:sympy/sympy")
    assert mem.retrieve(other)["reasoning"] == []
    # rendered text keeps the applies-when condition (self-gating at injection time)
    text = mem.render(mem.retrieve(task))
    assert "applies when: when fixing validators" in text


def test_dedup_by_scope_and_title():
    d = Dedup()
    assert d.fresh(_item("Run  the repro First", "repo:django/django"))
    assert not d.fresh(_item("run the repro first", "repo:django/django"))   # case/space-insensitive
    assert d.fresh(_item("run the repro first", "repo:sympy/sympy"))         # other scope ok


def test_extraction_prompts_format_cleanly():
    from hippo.swe.brain import _L1_SYS, _L2_SYS
    s1 = _L1_SYS.format(outcome_clause="FAILED: x", max_items=2)
    s2 = _L2_SYS.format(minority="successful", majority="failing",
                        direction="the procedure.", max_items=2)
    assert '"items"' in s1 and '"items"' in s2 and "{max_items}" not in s1


def test_json_parser_survives_invalid_escapes():
    from hippo.swe.brain import SweBrain
    raw = '```json\n{"success": true, "reason": "replace `$` with `\\Z` and `\\A`"}\n```'
    out = SweBrain._json(raw)
    assert out.get("success") is True
    assert "\\Z" in out["reason"] or "Z" in out["reason"]
    assert SweBrain._json("no json here") == {}


def test_compact_trace_keeps_test_output_and_bounds_size():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "look around",
         "extra": {"actions": [{"command": "ls /testbed"}]}},
        {"role": "user", "content": "A" * 5000},
        {"role": "assistant", "content": "run the tests",
         "extra": {"actions": [{"command": "python -m pytest tests/test_x.py"}]}},
        {"role": "user", "content": "B" * 5000},
    ]
    trace = compact_trace(messages)
    assert "$ ls /testbed" in trace and "$ python -m pytest" in trace
    a_kept = trace.count("A")
    b_kept = trace.count("B")
    assert b_kept > a_kept                      # test-ish output keeps more
    assert len(compact_trace(messages * 60, max_chars=30_000)) < 40_000
