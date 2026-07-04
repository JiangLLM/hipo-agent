"""Deterministic, API-free check of the two-layer step surprise + TASK-level concurrency.

Stubs predict()/brain so we control correctness & divergence, then assert:
  * Layer 1 fires per surprising attempt (wrong OR correct-but-lucky)
  * Layer 2 fires once per DIVERGENT step (mixed correct/wrong)
  * TASKS run concurrently (wall time << serial)
  * no writes are lost under concurrency
  * a transient error in one sample is skipped, not fatal
"""
import sys
import threading
import time

sys.path.insert(0, "src")

from hippo.config import DotDict
from hippo.m2w import run as R
from hippo.m2w.env import Episode, M2WStep
from hippo.schema import FactItem


class StubBrain:
    def __init__(self):
        self._n = 0
        self._lock = threading.Lock()

    def judge_step(self, task, step, thought, action, is_correct, gold_repr):
        with self._lock:
            self._n += 1
        # CORRECT here is treated as "lucky" (genuine=False) -> still surprising -> lesson
        return {"genuine": False, "lesson": FactItem(scope=task.scope,
                statement=f"rule for {gold_repr} (correct={is_correct})", key=None)}

    def extract_step_experiences(self, task, step, attempts, gold_repr, mode):
        return [FactItem(scope=task.scope, statement=f"L2 contrast {gold_repr}", key=None)]


class StubMemory:
    def __init__(self):
        self.facts = []
        self._lock = threading.Lock()
        self.cfg = DotDict({"memory": {"mode": "both"}})

    def retrieve(self, task):
        return {"reasoning": [], "fact": []}

    def render(self, retrieved):
        return ""

    def write_fact(self, item):
        with self._lock:
            self.facts.append(item)

    def stats(self):
        return {"n_reasoning": 0, "n_fact": len(self.facts)}


class StubLogger:
    def __init__(self):
        self.events = []
        self._lock = threading.Lock()

    def event(self, kind, **kw):
        with self._lock:
            self.events.append((kind, kw))


def make_step(pos_id):
    return M2WStep(obs=f"id={pos_id} ...", target_act=f"CLICK [{pos_id}]",
                   target_obs="gold", act_repr="[link] X -> CLICK",
                   pos_ids=[pos_id], solvable=True)


def make_episode(tid, pos_ids):
    ep = Episode(task_id=tid, task=f"goal {tid}", website="w", domain="d", subdomain="s")
    ep.steps = [make_step(p) for p in pos_ids]
    return ep


def base_cfg():
    return DotDict({
        "run": {"seed": 0, "concurrency": 8},
        "brain": "llm",
        "llm": {"temperature": 0.7},
        "m2w": {"layer1": "on", "layer2": "on"},
    })


def predict_divergent(cfg, brain, task_str, history, obs, mem_text, temperature, step, rng):
    """r==0 -> correct (gold id); r>0 -> wrong. Sleep so concurrency would overlap."""
    time.sleep(0.05)
    r = int(round((temperature - cfg.llm.temperature) / 0.0001))
    pid = step.pos_ids[0] if r == 0 else "999"
    return (f"thought r={r}", f"CLICK [{pid}]", True)


def test_task_level_concurrency_and_counts():
    cfg = base_cfg()
    eps = [make_episode(f"t{i}", ["100", "200"]) for i in range(4)]  # 4 tasks x 2 steps
    R.predict = predict_divergent
    brain, mem, log = StubBrain(), StubMemory(), StubLogger()
    t0 = time.time()
    R.step_learn_phase(cfg, brain, mem, eps, log, 3, "aggregate")
    dt = time.time() - t0

    kinds = [k for k, _ in log.events]
    l1 = kinds.count("step_write_l1")
    l2 = kinds.count("step_write_l2")
    done = [kw for k, kw in log.events if k == "step_learn_done"][0]

    # 4 tasks x 2 steps x 3 attempts, every attempt surprising -> 24 L1 writes
    assert l1 == 24, f"expected 24 layer-1 writes, got {l1}"
    # each step diverges (1 correct, 2 wrong) -> 1 layer-2 item; 4x2=8 steps
    assert l2 == 8, f"expected 8 layer-2 events, got {l2}"
    assert done["layer1_writes"] == 24 and done["layer2_writes"] == 8, done
    # no writes lost under concurrency: 24 + 8 = 32 facts
    assert len(mem.facts) == 32, f"expected 32 facts, got {len(mem.facts)}"
    # concurrency: per task ~2*3*0.05=0.30s; 4 tasks in parallel ~0.30s; serial ~1.2s
    assert dt < 0.7, f"tasks not concurrent: {dt:.3f}s (serial would be ~1.2s)"
    print(f"OK task-concurrency: L1={l1} L2={l2} facts={len(mem.facts)} wall={dt:.3f}s (serial~1.2s)")


def test_step_level_parallelism_switch():
    cfg = base_cfg()
    cfg["m2w"]["parallelism"] = "step"
    # One task, one step, four samples. With step parallelism, the four 50ms predict
    # calls overlap; sequential would be ~0.20s plus judge/write overhead.
    ep = make_episode("t_step", ["100"])
    R.predict = predict_divergent
    brain, mem, log = StubBrain(), StubMemory(), StubLogger()
    t0 = time.time()
    R.step_learn_phase(cfg, brain, mem, [ep], log, 4, "aggregate")
    dt = time.time() - t0

    kinds = [k for k, _ in log.events]
    assert kinds.count("step_write_l1") == 4, kinds
    assert kinds.count("step_write_l2") == 1, kinds
    assert len(mem.facts) == 5, f"expected 5 facts, got {len(mem.facts)}"
    assert dt < 0.16, f"step samples not concurrent: {dt:.3f}s (serial would be ~0.20s)"
    print(f"OK step-parallelism: facts={len(mem.facts)} wall={dt:.3f}s (serial~0.20s)")


def test_transient_error_is_skipped_not_fatal():
    cfg = base_cfg()
    ep = make_episode("t_err", ["100"])  # 1 task, 1 step

    def predict_raise(cfg_, brain_, task_str, history, obs, mem_text, temperature, step, rng):
        r = int(round((temperature - cfg_.llm.temperature) / 0.0001))
        if r == 1:
            raise RuntimeError("simulated transient 500")
        pid = step.pos_ids[0] if r == 0 else "999"
        return (f"thought r={r}", f"CLICK [{pid}]", True)
    R.predict = predict_raise
    brain, mem, log = StubBrain(), StubMemory(), StubLogger()
    R.step_learn_phase(cfg, brain, mem, [ep], log, 3, "aggregate")

    kinds = [k for k, _ in log.events]
    assert "step_error" in kinds, "transient error not logged as step_error"
    # 3 samples, 1 errored -> 2 survive (r0 correct-lucky, r2 wrong) -> 2 L1 writes
    assert kinds.count("step_write_l1") == 2, kinds
    # survivors: 1 correct, 1 wrong -> divergent -> 1 L2 event
    assert kinds.count("step_write_l2") == 1, kinds
    print("OK resilience: 1/3 sample failed -> skipped, run continued, L1=2 L2=1")


if __name__ == "__main__":
    test_task_level_concurrency_and_counts()
    test_step_level_parallelism_switch()
    test_transient_error_is_skipped_not_fatal()
    print("ALL PASS")
