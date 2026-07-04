"""Mind2Web streaming self-evolution loop — OUR memory on the AWM/MindAct testbed.

Experience unit = a whole multi-step task (episode). We stream over the task split
cold-start; after each batch we consolidate (our prioritized replay) into the dual
fact/reasoning store, gated by surprise. Standard metrics: element acc, action F1,
step SR, task SR.

    python -m hippo.m2w.run --brain llm --m2w.split test_website --m2w.limit 40 \
        --memory.mode both --surprise.source traj_divergence --agent.n_traj 1
    python -m hippo.m2w.run --brain random --m2w.split test_website   # API-free floor
    python -m hippo.m2w.run --brain oracle --m2w.split test_website   # ceiling
"""
from __future__ import annotations

import os
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from dotenv import load_dotenv

from ..config import load_config
from ..consolidate import consolidate
from ..eval import write_csv
from ..llm import BudgetExceeded
from ..logging_utils import RunLogger
from ..memory import Memory
from ..schema import BufferEntry, Outcome, Step, Task, Trajectory
from ..surprise import compute_surprise
from ._dom import calculate_f1, construct_act_str, parse_act_str
from .data import add_scores, load_split
from .env import build_episodes

SYS_M2W = (
    "You are an agent navigating the web. Given the task, the trajectory so far, and "
    "the current page elements, first reason briefly about which element advances the "
    "task and why, then output the next action. Action space:\n"
    "1. CLICK [id]\n2. TYPE [id] [value]\n3. SELECT [id] [value]\n"
    "Respond in EXACTLY this format:\n"
    "Thought: <one concise sentence on why this element>\n"
    "Action: `CLICK [123]`"
)


def _candidate_ids(obs: str) -> list[str]:
    return re.findall(r"id=(\d+)", obs)


def _hash_embed(texts):
    import hashlib

    out = []
    for t in texts:
        seed = int(hashlib.sha256(t.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        out.append([rng.uniform(-1, 1) for _ in range(16)])
    return out


def predict(cfg, brain, ep_task, history_str, obs, mem_text, temperature, step, rng):
    sel = cfg.brain
    if sel == "oracle":
        return "recall", step.target_act, True
    if sel == "random":
        ids = _candidate_ids(obs)
        act = f"CLICK [{rng.choice(ids)}]" if ids else "CLICK []"
        return "random", act, False
    # llm
    msgs = [{"role": "system", "content": SYS_M2W}]
    if mem_text:
        msgs.append({"role": "user", "content": "Lessons from past tasks:\n" + mem_text})
    content = f"Task: {ep_task}\nTrajectory:\n{history_str}Observation: `{obs}`"
    msgs.append({"role": "user", "content": content})
    resp = brain.llm.chat(msgs, temperature=temperature, stop=["Task:", "Observation:"])
    tm = re.search(r"Thought:\s*(.+?)(?:\n|Action:)", resp, re.S)
    thought = tm.group(1).strip() if tm else ""
    am = re.search(r"Action:\s*`([^`]+)`", resp) or re.search(r"`([^`]+)`", resp)
    act = (am.group(1) if am else resp.splitlines()[-1]).strip()
    return thought, act, True


def run_episode(cfg, brain, ep, mem_text, temperature, rng):
    """Run one episode (teacher-forced multi-step). Returns (Trajectory, per-step metrics)."""
    history = ""
    steps_out: list[Step] = []
    el_acc, act_f1, step_succ = [], [], []
    detail: list[dict] = []   # per-step trace for debugging
    trace = bool((cfg.get("logging", {}) or {}).get("trace", False))
    for st in ep.steps:
        if not st.solvable:
            el_acc.append(0); act_f1.append(0); step_succ.append(0)
            history += f"Observation: `{st.target_obs[:400]}`\nAction: `{st.target_act}` ({st.act_repr})\n"
            steps_out.append(Step(thought="(gold not in top-k)", action="", obs="", correct=False))
            detail.append({"solvable": False, "gold": st.target_act, "pred": None, "elem": 0, "step": 0})
            continue
        thought, pred_act, _ = predict(cfg, brain, ep.task, history, st.obs, mem_text, temperature, st, rng)
        pred_op, pred_id, pred_val = parse_act_str(pred_act)
        tgt_op, _, tgt_val = parse_act_str(st.target_act)
        elem_ok = pred_id in st.pos_ids
        f1 = calculate_f1(construct_act_str(pred_op, pred_val), construct_act_str(tgt_op, tgt_val))
        ss = 1 if pred_act.strip() == st.target_act.strip() else 0
        el_acc.append(1 if elem_ok else 0); act_f1.append(f1); step_succ.append(ss)
        steps_out.append(Step(thought=thought, action=pred_act, obs="", correct=bool(ss)))
        detail.append({"solvable": True, "thought": thought if trace else thought[:140],
                       "pred": pred_act, "gold": st.target_act, "act_repr": st.act_repr,
                       "elem": int(elem_ok), "step": ss})
        # teacher forcing: append GOLD action to history
        history += f"Observation: `{st.target_obs[:400]}`\nAction: `{st.target_act}` ({st.act_repr})\n"

    n = len(ep.steps)
    task_success = 1 if (n > 0 and sum(step_succ) == n) else 0
    traj = Trajectory(task_id=ep.task_id, traj_id=f"{ep.task_id}:{temperature}",
                      steps=steps_out, final_answer=f"task_success={task_success}",
                      env_success=bool(task_success),
                      meta={"gold_path": [st.act_repr for st in ep.steps if st.act_repr]})
    metrics = {"element_acc": el_acc, "action_f1": act_f1, "step_success": step_succ,
               "task_success": task_success, "n_steps": n, "steps": detail}
    return traj, metrics


def _load_eps(data_dir, split, top_k):
    samples = load_split(data_dir, split)
    samples = add_scores(samples, os.path.join(data_dir, "scores_all_data.pkl"))
    return build_episodes(samples, top_k_elements=top_k)


def _holdout_split(eps, frac, seed):
    """Per-website split: first `frac` of each site's tasks -> learn, rest -> test.

    Guarantees the same websites appear in both, so learned site facts can transfer.
    """
    from collections import defaultdict
    by = defaultdict(list)
    for e in eps:
        by[e.website].append(e)
    learn, test = [], []
    for site, es in by.items():
        k = max(1, int(len(es) * frac)) if len(es) > 1 else 0
        learn.extend(es[:k]); test.extend(es[k:])
    return learn, test


def learn_phase(cfg, brain, memory, eps, logger, n_traj):
    buffer: list[BufferEntry] = []
    rng = random.Random(cfg.run.seed)
    is_llm = cfg.brain == "llm"
    temp = cfg.llm.temperature if is_llm else 0.0
    pool = ThreadPoolExecutor(max_workers=max(1, cfg.run.concurrency))
    try:
        for idx, ep in enumerate(eps):
            task_obj = Task(id=ep.task_id, prompt=ep.task, scope=ep.scope)
            mem_text = memory.render(memory.retrieve(task_obj))
            predicted_solvable = brain.predict_solvable(task_obj, mem_text) if is_llm else False

            def worker(r, ep=ep, mem_text=mem_text):   # the N rollouts run CONCURRENTLY
                return run_episode(cfg, brain, ep, mem_text, temp + 0.0001 * r, rng)
            if is_llm and n_traj > 1:
                rollouts = list(pool.map(worker, range(n_traj)))
            else:
                rollouts = [worker(r) for r in range(n_traj)]
            trajs = [t for t, _ in rollouts]
            outcomes = [Outcome(success=bool(t.env_success)) for t in trajs]
            sr = compute_surprise(cfg, trajs, outcomes, predicted_solvable)
            # populate BOTH stores (attribute() is blind here; the fact-vs-reasoning
            # comparison is done at test time via --memory.mode).
            rf = rr = bool(sr.write)
            buffer.append(BufferEntry(task=task_obj, trajs=trajs, outcomes=outcomes, surprise=sr.score,
                                      route_fact=rf, route_reasoning=rr, signals=sr.signals))
            if (idx + 1) % cfg.replay.batch_size == 0:
                consolidate(buffer, memory, brain, None, logger)
    finally:
        pool.shutdown(wait=True)
    if buffer:
        consolidate(buffer, memory, brain, None, logger)
    logger.event("learn_done", **memory.stats())


def step_learn_phase(cfg, brain, memory, eps, logger, n_traj, record_mode):
    """Two-layer step-level surprise-gated learning.

    LAYER 1 (single attempt, per step): judge EACH attempt's step against the gold via a
      judge call (looks at the answer). Surprise = the step is WRONG, or it is CORRECT but a
      lucky guess (not genuinely reasoned). Either case distills ONE high-quality site rule.
    LAYER 2 (across the N attempts, per step): on DIVERGENCE (mixed correct/wrong), contrast
      the attempts — majority-wrong -> how to do it right; majority-correct -> the pitfall.

    Both layers write site-scoped facts. Switch off via m2w.layer1/layer2 = off.
    Parallelism is controlled by m2w.parallelism:
      * task (default): tasks run concurrently; within a task, steps and N samples are sequential.
      * step: tasks run sequentially; within each step, the N samples run concurrently.
    Memory is thread-safe (lock-guarded stores), the logger is thread-safe, and a transient
    API error skips just that sample instead of killing the run; the budget stop still propagates."""
    rng = random.Random(cfg.run.seed)
    is_llm = cfg.brain == "llm"
    m2w = cfg.get("m2w", {}) or {}
    layer1 = m2w.get("layer1", "on") != "off"
    layer2 = m2w.get("layer2", "on") != "off"
    parallelism = m2w.get("parallelism", "task")
    if parallelism not in ("task", "step"):
        raise ValueError(f"unknown m2w.parallelism: {parallelism!r} (expected 'task' or 'step')")
    temp = cfg.llm.temperature if is_llm else 0.0
    workers = max(1, cfg.run.concurrency)

    def one_sample(r, st, history, mem_text, task_obj, task_str):
        """One of the N samples for THIS step: predict + Layer-1 judge. Transient
        API/parse errors return errored=True (skip the sample); budget stop propagates."""
        try:
            thought, act, _ = predict(cfg, brain, task_str, history, st.obs, mem_text,
                                      temp + 0.0001 * r, st, rng)
            pid = parse_act_str(act)[1]
            correct = pid in st.pos_ids
            genuine, lesson, reason = correct, None, ""
            if layer1 and is_llm:                   # LAYER 1: per-attempt judge (looks at gold)
                v = brain.judge_step(task_obj, st, thought, act, correct, st.act_repr)
                genuine = bool(v.get("genuine", correct))
                lesson = v.get("lesson")
                reason = v.get("reason", "")
        except BudgetExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - degrade on transient error, don't halt
            err = type(exc).__name__
            last = getattr(exc, "last_attempt", None)   # unwrap tenacity RetryError -> real cause
            if last is not None:
                try:
                    err = type(last.exception()).__name__
                except Exception:  # noqa: BLE001
                    pass
            return {"errored": True, "err": err}
        surprised = (not correct) or (not genuine)
        return {"errored": False, "thought": thought, "chosen": act, "correct": correct,
                "genuine": genuine, "surprised": surprised, "lesson": lesson, "reason": reason}

    def learn_one_task(ep):
        """Process ALL steps of ONE task (teacher-forced). Runs as one parallel job."""
        task_obj = Task(id=ep.task_id, prompt=ep.task, scope=ep.scope)
        history = ""
        w1 = w2 = 0
        for st in ep.steps:
            if not st.solvable:
                history += f"Observation: `{st.target_obs[:300]}`\nAction: `{st.target_act}` ({st.act_repr})\n"
                continue
            # per-step retrieval: query by THIS step's situation (goal + current page)
            q_obj = Task(id=ep.task_id, prompt=f"{ep.task}\n{st.obs[:400]}", scope=ep.scope)
            mem_text = memory.render(memory.retrieve(q_obj))
            if is_llm and n_traj > 1 and parallelism == "step":
                worker = partial(one_sample, st=st, history=history, mem_text=mem_text,
                                 task_obj=task_obj, task_str=ep.task)
                results = list(pool.map(worker, range(n_traj)))   # N samples concurrent
            else:
                results = [one_sample(r, st, history, mem_text, task_obj, ep.task) for r in range(n_traj)]
            n_err = sum(1 for res in results if res.get("errored"))
            if n_err:
                logger.event("step_error", task=ep.task_id, n_err=n_err,
                             errs=[res.get("err") for res in results if res.get("errored")])
            results = [res for res in results if not res.get("errored")]
            if not results:                          # all N failed -> skip step, keep going
                history += f"Observation: `{st.target_obs[:300]}`\nAction: `{st.target_act}` ({st.act_repr})\n"
                continue
            attempts = []
            for res in results:
                attempts.append({k: res[k] for k in
                                 ("thought", "chosen", "correct", "genuine", "surprised", "reason")})
                if layer1 and res["surprised"] and res["lesson"] is not None:
                    lesson = res["lesson"]
                    memory.write_fact(lesson)        # thread-safe store
                    w1 += 1
                    logger.event("step_write_l1", task=ep.task_id, gold=st.act_repr,
                                 correct=res["correct"], genuine=res["genuine"], chose=res["chosen"],
                                 item={"statement": lesson.statement[:200], "key": lesson.key,
                                       "scope": lesson.scope})
            nc = sum(a["correct"] for a in attempts)
            # LAYER 2: contrastive distillation, only when the surviving attempts DIVERGE
            if layer2 and is_llm and 0 < nc < len(attempts):
                items = brain.extract_step_experiences(task_obj, st, attempts, st.act_repr, record_mode)
                for it in items:
                    memory.write_fact(it)            # site-scoped -> retrieved by site
                w2 += len(items)
                logger.event("step_write_l2", task=ep.task_id, n=len(attempts), n_correct=nc,
                             wrote=len(items), gold=st.act_repr,
                             items=[{"statement": it.statement[:200], "scope": it.scope,
                                     "key": it.key} for it in items])
            history += f"Observation: `{st.target_obs[:300]}`\nAction: `{st.target_act}` ({st.act_repr})\n"
        return w1, w2

    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        if is_llm and len(eps) > 1 and parallelism == "task":
            counts = list(pool.map(learn_one_task, eps))   # TASKS run concurrently
        else:
            counts = [learn_one_task(ep) for ep in eps]
    finally:
        pool.shutdown(wait=True)
    w1 = sum(c[0] for c in counts)
    w2 = sum(c[1] for c in counts)
    logger.event("step_learn_done", layer1_writes=w1, layer2_writes=w2, **memory.stats())


def step_test_phase(cfg, brain, memory, eps, logger, tag):
    """Test for step mode: PER-STEP retrieval (query by the current step situation),
    memory frozen. Mirrors test_phase metrics."""
    rng = random.Random(cfg.run.seed + 7)
    trace = bool((cfg.get("logging", {}) or {}).get("trace", False))
    per_step = (cfg.get("m2w", {}) or {}).get("per_step_retrieval", "on") != "off"
    is_llm = cfg.brain == "llm"
    workers = max(1, cfg.run.concurrency)

    def test_one(pair):
        """Evaluate ONE episode (memory frozen -> safe to run concurrently)."""
        idx, ep = pair
        history, el, f1, sf, detail = "", [], [], [], []
        n_steps = len(ep.steps)
        # whole-task retrieval (per_step=off): retrieve once by the goal, reuse for all steps
        goal_ret = None if per_step else memory.retrieve(Task(id=ep.task_id, prompt=ep.task, scope=ep.scope))
        for st in ep.steps:
            if not st.solvable:
                el.append(0); f1.append(0); sf.append(0)
                history += f"Observation: `{st.target_obs[:300]}`\nAction: `{st.target_act}` ({st.act_repr})\n"
                continue
            if per_step:
                retrieved = memory.retrieve(Task(id=ep.task_id, prompt=f"{ep.task}\n{st.obs[:400]}", scope=ep.scope))
            else:
                retrieved = goal_ret
            mem_text = memory.render(retrieved)
            th, act, _ = predict(cfg, brain, ep.task, history, st.obs, mem_text, 0.0, st, rng)
            po, pid, pv = parse_act_str(act)
            to, _, tv = parse_act_str(st.target_act)
            ok = 1 if pid in st.pos_ids else 0
            el.append(ok); f1.append(calculate_f1(construct_act_str(po, pv), construct_act_str(to, tv)))
            sf.append(1 if act.strip() == st.target_act.strip() else 0)
            detail.append({"solvable": True, "thought": th if trace else th[:140], "pred": act,
                           "gold": st.target_act, "act_repr": st.act_repr, "elem": ok, "step": sf[-1],
                           "n_ret": {k: len(v) for k, v in retrieved.items()},
                           "facts": [f.statement[:90] for f in retrieved.get("fact", [])]})
            history += f"Observation: `{st.target_obs[:300]}`\nAction: `{st.target_act}` ({st.act_repr})\n"
        row = {"idx": idx, "task_id": ep.task_id, "website": ep.website,
               "element_acc": _mean(el), "action_f1": _mean(f1), "step_success": _mean(sf),
               "task_success": 1 if (n_steps > 0 and sum(sf) == n_steps) else 0,
               "n_steps": n_steps, "wrote": 0}
        logger.event("test_episode", tag=tag, idx=idx, scope=ep.scope, task=ep.task,
                     step_success=row["step_success"], element_acc=row["element_acc"], steps=detail)
        return row

    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        if is_llm and len(eps) > 1:
            rows = list(pool.map(test_one, enumerate(eps)))   # EPISODES concurrent (memory frozen)
        else:
            rows = [test_one((idx, ep)) for idx, ep in enumerate(eps)]
    finally:
        pool.shutdown(wait=True)
    s = _summarize(rows)
    write_csv(os.path.join(logger.dir, f"metrics_{tag}.csv"), rows)
    return s


def test_phase(cfg, brain, memory, eps, logger, tag):
    """One pass, memory frozen (no writes). Returns summary + writes rows."""
    rows = []
    rng = random.Random(cfg.run.seed + 7)
    trace = bool((cfg.get("logging", {}) or {}).get("trace", False))
    for idx, ep in enumerate(eps):
        task_obj = Task(id=ep.task_id, prompt=ep.task, scope=ep.scope)
        retrieved = memory.retrieve(task_obj)
        mem_text = memory.render(retrieved)
        traj, mt = run_episode(cfg, brain, ep, mem_text, 0.0, rng)
        rows.append({"idx": idx, "task_id": ep.task_id, "website": ep.website,
                     "element_acc": _mean(mt["element_acc"]), "action_f1": _mean(mt["action_f1"]),
                     "step_success": _mean(mt["step_success"]), "task_success": mt["task_success"],
                     "n_steps": mt["n_steps"], "wrote": 0})
        logger.event("test_episode", tag=tag, idx=idx, scope=ep.scope, task=ep.task,
                     step_success=rows[-1]["step_success"], element_acc=rows[-1]["element_acc"],
                     n_retrieved={k: len(v) for k, v in retrieved.items()},
                     mem_text=mem_text if trace else mem_text[:1800],
                     retrieved={"fact": [f.statement[:80] for f in retrieved.get("fact", [])],
                                "reasoning": [{"title": r.title, "desc": r.description[:80]}
                                              for r in retrieved.get("reasoning", [])]},
                     steps=mt["steps"])
    s = _summarize(rows)
    write_csv(os.path.join(logger.dir, f"metrics_{tag}.csv"), rows)
    return s


def stream_phase(cfg, brain, memory, eps, logger, n_traj, record_mode, learn=True, tag="stream"):
    """边学边升级 — ONE streaming pass, NO holdout, NO separate frozen test.

    Tasks are processed IN ORDER (memory persists across steps AND tasks). For each step:
      * retrieve the CURRENT memory,
      * run N rollouts (rollout 0 = greedy temp=0 = the SCORED prediction; rest temp>0),
      * SCORE the greedy vs gold,
      * LEARN inline from all N (two-layer surprise) -> write back to memory,
      * the next step / next task sees what was just written.
    learn=False = cold no-memory baseline over the same stream (only the greedy score).
    Per-step / per-task scores are logged IN ORDER so the self-evolution curve is visible."""
    rng = random.Random(cfg.run.seed)
    is_llm = cfg.brain == "llm"
    m2w = cfg.get("m2w", {}) or {}
    layer1 = m2w.get("layer1", "on") != "off"
    layer2 = m2w.get("layer2", "on") != "off"
    temp = cfg.llm.temperature if is_llm else 0.0
    workers = max(1, cfg.run.concurrency)
    n_eff = n_traj if (learn and is_llm) else 1     # baseline only needs the greedy score
    rows, w1, w2 = [], 0, 0

    def one(r, st, history, mem_text, task_obj, task_str):
        t = 0.0 if r == 0 else temp + 0.0001 * r    # rollout 0 = greedy = the scored one
        try:
            thought, act, _ = predict(cfg, brain, task_str, history, st.obs, mem_text, t, st, rng)
            pid = parse_act_str(act)[1]
            correct = pid in st.pos_ids
            genuine, lesson = correct, None
            if learn and layer1 and is_llm:
                v = brain.judge_step(task_obj, st, thought, act, correct, st.act_repr)
                genuine = bool(v.get("genuine", correct))
                lesson = v.get("lesson")
        except BudgetExceeded:
            raise
        except Exception:  # noqa: BLE001 - degrade on transient error, don't halt
            return {"errored": True, "r": r}
        return {"errored": False, "r": r, "thought": thought, "chosen": act, "correct": correct,
                "genuine": genuine, "surprised": (not correct) or (not genuine), "lesson": lesson}

    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        for ti, ep in enumerate(eps):
            task_obj = Task(id=ep.task_id, prompt=ep.task, scope=ep.scope)
            history, el, f1, sf = "", [], [], []
            for si, st in enumerate(ep.steps):
                if not st.solvable:
                    el.append(0); f1.append(0); sf.append(0)
                    history += f"Observation: `{st.target_obs[:300]}`\nAction: `{st.target_act}` ({st.act_repr})\n"
                    continue
                q_obj = Task(id=ep.task_id, prompt=f"{ep.task}\n{st.obs[:400]}", scope=ep.scope)
                try:                                               # transient retrieve/embed error -> treat as no memory, don't halt
                    mem_text = memory.render(memory.retrieve(q_obj))
                except BudgetExceeded:
                    raise
                except Exception as exc:  # noqa: BLE001
                    mem_text = ""
                    logger.event("retrieve_error", task=ep.task_id, step_idx=si, err=type(exc).__name__)
                worker = partial(one, st=st, history=history, mem_text=mem_text,
                                 task_obj=task_obj, task_str=ep.task)
                if is_llm and n_eff > 1:
                    results = list(pool.map(worker, range(n_eff)))   # N rollouts CONCURRENT
                else:
                    results = [worker(r) for r in range(n_eff)]
                ok = [x for x in results if not x.get("errored")]
                greedy = next((x for x in results if x["r"] == 0 and not x.get("errored")), None)
                if greedy is None:
                    greedy = ok[0] if ok else None
                # SCORE with the greedy rollout
                if greedy is None:
                    el.append(0); f1.append(0); sf.append(0)
                else:
                    po, pid, pv = parse_act_str(greedy["chosen"])
                    to, _, tv = parse_act_str(st.target_act)
                    el.append(1 if pid in st.pos_ids else 0)
                    f1.append(calculate_f1(construct_act_str(po, pv), construct_act_str(to, tv)))
                    sf.append(1 if greedy["chosen"].strip() == st.target_act.strip() else 0)
                # LEARN inline (memory grows for the next step / task)
                if learn:
                    for res in ok:
                        if layer1 and res["surprised"] and res["lesson"] is not None:
                            memory.write_fact(res["lesson"]); w1 += 1
                            logger.event("step_write_l1", task=ep.task_id, gold=st.act_repr,
                                         correct=res["correct"], genuine=res["genuine"],
                                         item={"statement": res["lesson"].statement[:200],
                                               "key": res["lesson"].key, "scope": res["lesson"].scope})
                    nc = sum(a["correct"] for a in ok)
                    if layer2 and is_llm and 0 < nc < len(ok):
                        attempts = [{k: a[k] for k in
                                     ("thought", "chosen", "correct", "genuine", "surprised")} for a in ok]
                        items = brain.extract_step_experiences(task_obj, st, attempts, st.act_repr, record_mode)
                        for it in items:
                            memory.write_fact(it)
                        w2 += len(items)
                        logger.event("step_write_l2", task=ep.task_id, n=len(ok), n_correct=nc,
                                     wrote=len(items), gold=st.act_repr,
                                     items=[{"statement": it.statement[:200], "scope": it.scope,
                                             "key": it.key} for it in items])
                logger.event("stream_step", tag=tag, task_idx=ti, step_idx=si, scope=ep.scope,
                             greedy_correct=el[-1], nc=sum(a["correct"] for a in ok), n=len(ok), gold=st.act_repr)
                history += f"Observation: `{st.target_obs[:300]}`\nAction: `{st.target_act}` ({st.act_repr})\n"
            n_steps = len(ep.steps)
            rows.append({"idx": ti, "task_id": ep.task_id, "website": ep.website,
                         "element_acc": _mean(el), "action_f1": _mean(f1), "step_success": _mean(sf),
                         "task_success": 1 if (n_steps > 0 and sum(sf) == n_steps) else 0,
                         "n_steps": n_steps, "wrote": 0})
            logger.event("stream_task", tag=tag, task_idx=ti, scope=ep.scope, task=ep.task,
                         step_success=rows[-1]["step_success"], element_acc=rows[-1]["element_acc"],
                         n_fact=memory.stats().get("n_fact", 0))
    finally:
        pool.shutdown(wait=True)
    s = _summarize(rows)
    s.update({"layer1_writes": w1, "layer2_writes": w2})
    write_csv(os.path.join(logger.dir, f"metrics_{tag}.csv"), rows)
    return s


def run(cfg) -> dict:
    load_dotenv()
    logger = RunLogger(cfg.run.out_dir, cfg.run.name, level=cfg.logging.level, jsonl=cfg.logging.jsonl)
    m2w = cfg.get("m2w", {}) or {}
    data_dir = m2w.get("data_dir", "data/mind2web")
    top_k = int(m2w.get("top_k", 5))
    n_traj = max(1, cfg.agent.n_traj)

    # brain / embeddings
    client = None
    if cfg.brain == "llm":
        from ..brain import LLMBrain
        from ..llm import LLMClient
        client = LLMClient(model=cfg.llm.model, embed_model=cfg.llm.embed_model,
                           temperature=cfg.llm.temperature, max_tokens=cfg.llm.max_tokens,
                           cache=cfg.llm.cache, budget_usd=cfg.run.budget_usd,
                           min_interval=float(os.environ.get("HIPPO_MIN_INTERVAL", "0") or 0))
        brain = LLMBrain(client, cfg)
        embed_fn = brain.embed
    else:
        from ..brain import MockBrain
        brain = MockBrain(cfg)
        embed_fn = _hash_embed

    # build learn / test episode sets
    learn_split = m2w.get("learn_split", "")
    test_split = m2w.get("test_split", m2w.get("split", "test_task"))
    stream_mode = m2w.get("protocol") == "stream"
    if stream_mode:                                   # ONE streaming pass, no holdout
        learn_eps = []
        test_eps = _load_eps(data_dir, test_split, top_k)
    elif learn_split:                                 # separate splits (e.g. train -> test_task)
        learn_eps = _load_eps(data_dir, learn_split, top_k)
        test_eps = _load_eps(data_dir, test_split, top_k)
    else:                                             # per-website holdout within one split
        eps = _load_eps(data_dir, test_split, top_k)
        learn_eps, test_eps = _holdout_split(eps, float(m2w.get("holdout", 0.5)), cfg.run.seed)
    if int(m2w.get("learn_limit", 0)):
        learn_eps = learn_eps[: int(m2w["learn_limit"])]
    if m2w.get("test_on_learn"):
        # positive control: test on the very tasks we learned (memory holds their exact
        # procedure). If memory still doesn't help here, the mechanism is broken; if it
        # helps a lot here but not on held-out tasks, the problem is coverage.
        test_eps = list(learn_eps)
    if int(m2w.get("test_limit", 0)):
        test_eps = test_eps[: int(m2w["test_limit"])]

    logger.info(f"run_id={logger.run_id} brain={cfg.brain} learn={len(learn_eps)} "
                f"test={len(test_eps)} n_traj={n_traj} surprise={cfg.surprise.source}")
    logger.event("run_start", n_learn=len(learn_eps), n_test=len(test_eps), config=dict(cfg))

    summary = {"n_learn": len(learn_eps), "n_test": len(test_eps), "n_traj": n_traj,
               "surprise_source": cfg.surprise.source, "test_split": test_split}
    step_mode = m2w.get("protocol") == "step_evolve"
    test_fn = step_test_phase if step_mode else test_phase   # step mode = per-step retrieval
    record_mode = m2w.get("record_mode", "aggregate")
    try:
        if stream_mode:
            # 边学边升级: one pass, memory grows as we go. Baseline = same stream, memory OFF.
            empty = Memory(embed_fn, cfg)
            summary["stream_nomem"] = stream_phase(cfg, brain, empty, test_eps, logger, n_traj,
                                                   record_mode, learn=False, tag="nomem")
            memory = Memory(embed_fn, cfg)
            summary["stream_withmem"] = stream_phase(cfg, brain, memory, test_eps, logger, n_traj,
                                                     record_mode, learn=True, tag="stream")
            summary["learned_memory"] = memory.stats()
            if m2w.get("memory_out"):
                memory.save(m2w["memory_out"])
        else:
            # baseline: test with NO memory
            empty = Memory(embed_fn, cfg)
            summary["test_nomem"] = test_fn(cfg, brain, empty, test_eps, logger, "nomem")
            # get the learned memory: either load a saved store (skip learning) or learn now
            memory = Memory(embed_fn, cfg)
            if m2w.get("memory_in"):
                memory.load(m2w["memory_in"])
                logger.info(f"loaded memory from {m2w['memory_in']} -> {memory.stats()}")
            elif m2w.get("protocol") == "step_evolve":
                step_learn_phase(cfg, brain, memory, learn_eps, logger, n_traj,
                                 m2w.get("record_mode", "aggregate"))
                if m2w.get("memory_out"):
                    memory.save(m2w["memory_out"])
            else:
                learn_phase(cfg, brain, memory, learn_eps, logger, n_traj)
                if m2w.get("memory_out"):
                    memory.save(m2w["memory_out"])
            summary["learned_memory"] = memory.stats()
            # test with learned memory, frozen (retrieval policy = cfg.memory.* knobs)
            summary["test_withmem"] = test_fn(cfg, brain, memory, test_eps, logger, "withmem")
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"run halted: {type(exc).__name__}: {exc}")
        logger.event("run_error", error=str(exc))

    if client is not None:
        summary["llm_calls"] = client.calls
        summary["spent_usd"] = round(client.spent_usd, 4)
    logger.save_json("summary.json", summary)
    nm = summary.get("test_nomem") or summary.get("stream_nomem") or {}
    wm = summary.get("test_withmem") or summary.get("stream_withmem") or {}
    logger.info(f"A/B step_success: nomem={nm.get('step_success')} -> withmem={wm.get('step_success')} "
                f"| element_acc: {nm.get('element_acc')} -> {wm.get('element_acc')} "
                f"| withmem curve 1st/2nd half: {wm.get('step_sr_first_half')}/{wm.get('step_sr_second_half')} "
                f"(delta {wm.get('learning_delta')}) | learned {summary.get('learned_memory')}")
    logger.close()
    return summary


def _mean(xs):
    return round(sum(xs) / len(xs), 4) if xs else 0.0


def _summarize(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0}
    n = len(rows)
    def avg(k):
        return round(sum(r[k] for r in rows) / n, 4)
    half = n // 2
    first = sum(r["step_success"] for r in rows[:half]) / max(half, 1)
    second = sum(r["step_success"] for r in rows[half:]) / max(n - half, 1)
    return {"n": n, "element_acc": avg("element_acc"), "action_f1": avg("action_f1"),
            "step_success": avg("step_success"), "task_success": avg("task_success"),
            "step_sr_first_half": round(first, 4), "step_sr_second_half": round(second, 4),
            "learning_delta": round(second - first, 4), "writes": sum(r["wrote"] for r in rows)}


def main():
    cfg = load_config(sys.argv[1:])
    if "brain" not in cfg:
        cfg["brain"] = "llm"
    run(cfg)


if __name__ == "__main__":
    main()
