"""Main loop: stream tasks, run N trajectories, gate by surprise, replay-consolidate.

    python -m hippo.run --mock --memory.mode both --surprise.source traj_divergence
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

from .agent import rollout
from .config import load_config
from .consolidate import consolidate
from .envs import make_env
from .eval import summarize, write_csv
from .logging_utils import RunLogger
from .memory import Memory
from .schema import BufferEntry
from .surprise import compute_surprise


def build_brain(cfg, mock: bool):
    selector = cfg.get("brain", "mock" if mock else "llm")
    if selector == "mock" or mock:
        from .brain import MockBrain

        return MockBrain(cfg), None
    if selector == "random":
        from .brain import RandomBrain

        return RandomBrain(cfg), None
    from .brain import LLMBrain
    from .llm import LLMClient

    client = LLMClient(
        model=cfg.llm.model, embed_model=cfg.llm.embed_model,
        temperature=cfg.llm.temperature, max_tokens=cfg.llm.max_tokens,
        cache=cfg.llm.cache, budget_usd=cfg.run.budget_usd,
        min_interval=float(os.environ.get("HIPPO_MIN_INTERVAL", "0") or 0),
    )
    return LLMBrain(client, cfg), client


def run(cfg) -> dict:
    mock = bool(cfg.run.get("mock", False))
    logger = RunLogger(cfg.run.out_dir, cfg.run.name, level=cfg.logging.level, jsonl=cfg.logging.jsonl)
    logger.info(f"run_id={logger.run_id} mock={mock} mode={cfg.memory.mode} "
                f"surprise={cfg.surprise.source} n_traj={cfg.agent.n_traj}")
    logger.save_json("config.json", dict(cfg))

    brain, client = build_brain(cfg, mock)
    env = make_env(cfg.get("env", "mock"), cfg)
    memory = Memory(brain.embed, cfg)
    tasks = env.tasks()
    logger.event("run_start", n_tasks=len(tasks), config=dict(cfg))

    buffer: list[BufferEntry] = []
    rows: list[dict] = []
    pool = ThreadPoolExecutor(max_workers=max(1, cfg.run.concurrency))

    try:
        for idx, task in enumerate(tasks):
            retrieved = memory.retrieve(task)
            mem_text = memory.render(retrieved)
            predicted_solvable = brain.predict_solvable(task, mem_text)

            n = max(1, cfg.agent.n_traj)
            trajs = list(pool.map(
                lambda i: rollout(task, env, brain, mem_text, salt=f"{cfg.run.seed}:{i}"),
                range(n)))
            outcomes = [brain.judge(task, t) for t in trajs]

            sr = compute_surprise(cfg, trajs, outcomes, predicted_solvable)
            route_fact = route_reasoning = False
            if sr.write:
                route_fact, route_reasoning = brain.attribute(task, trajs, outcomes)
            buffer.append(BufferEntry(task=task, trajs=trajs, outcomes=outcomes,
                                      surprise=sr.score, route_fact=route_fact,
                                      route_reasoning=route_reasoning, signals=sr.signals))

            pass1 = bool(outcomes[0].success)
            passk = any(o.success for o in outcomes)
            retrieved_repr = {
                "fact": [f"{it.polarity[:3]}:{it.statement[:60]}" for it in retrieved.get("fact", [])],
                "reasoning": [it.title for it in retrieved.get("reasoning", [])],
            }
            thoughts = [(t.steps[0].thought[:120] if t.steps else "") for t in trajs]
            logger.event("task", idx=idx, task_id=task.id, task_type=task.task_type,
                         scope=task.scope, n_retrieved={k: len(v) for k, v in retrieved.items()},
                         retrieved=retrieved_repr, predicted_solvable=predicted_solvable,
                         pass1=pass1, passk=passk,
                         gold=task.gold, actions=[t.final_answer for t in trajs],
                         can_derive=[t.meta.get("can_derive") for t in trajs], thoughts=thoughts,
                         surprise=sr.score, write=sr.write, signals=sr.signals,
                         route={"fact": route_fact, "reasoning": route_reasoning})

            # consolidation schedule
            if cfg.replay.enabled:
                if cfg.replay.schedule == "online":
                    consolidate(buffer, memory, brain, env, logger)
                elif (idx + 1) % cfg.replay.batch_size == 0:
                    n_w = consolidate(buffer, memory, brain, env, logger)
                    logger.event("consolidate", at_task=idx, written=n_w, **memory.stats())

            rows.append({"idx": idx, "task_id": task.id, "task_type": task.task_type,
                         "pass1": int(pass1), "passk": int(passk),
                         "surprise": round(sr.score, 3), "wrote": int(sr.write),
                         **memory.stats()})

        if cfg.replay.enabled and buffer:
            consolidate(buffer, memory, brain, env, logger)

    except Exception as exc:  # budget / API errors: stop gracefully, keep partial metrics
        logger.warn(f"run halted: {type(exc).__name__}: {exc}")
        logger.event("run_error", error=str(exc))

    summary = summarize(rows)
    summary["mock"] = mock
    summary["memory_mode"] = cfg.memory.mode
    summary["surprise_source"] = cfg.surprise.source
    summary["n_traj"] = cfg.agent.n_traj
    if client is not None:
        summary["llm_calls"] = client.calls
        summary["spent_usd"] = round(client.spent_usd, 4)
    write_csv(os.path.join(logger.dir, "metrics.csv"), rows)
    logger.save_json("summary.json", summary)
    logger.event("run_end", **summary)
    logger.info("SUMMARY " + " ".join(f"{k}={v}" for k, v in summary.items()))
    logger.close()
    pool.shutdown(wait=True)
    return summary


def main() -> None:
    load_dotenv()
    cfg = load_config(sys.argv[1:])
    run(cfg)


if __name__ == "__main__":
    main()
