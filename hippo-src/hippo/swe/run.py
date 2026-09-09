"""SWE-bench streaming self-evolution loop — hippo's task-level two-layer memory.

Protocol (per arm, same instance order):
  nomem   — 1 attempt/task, no retrieval, no writes. The cold baseline.
  withmem — retrieve repo-scoped strategies -> N parallel attempts (own containers)
            -> judge each (evidence-gated) -> L1 on surprising attempts (capped)
            -> L2 on divergence with a vote-margin gate -> dedup-write -> next task.

Ground truth is NEVER used in the loop (label-free like deployment); it enters only
afterwards, via sb-cli on the emitted preds_{arm}.json files. The judge's verdicts
give an online proxy metric so the stream curve is visible immediately.

    python -m hippo.swe.run --swe.repos django --swe.limit 25 --agent.n_traj 5 \
        --run.budget_usd 40 --run.name swe_stream
    python -m hippo.swe.run --swe.arms nomem --swe.limit 25   # baseline only
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

from ..config import load_config
from ..eval import write_csv
from ..llm import BudgetExceeded, LLMClient
from ..logging_utils import RunLogger
from ..memory import Memory
from ..schema import Task
from .brain import SweBrain
from .data import ensure_image, image_name, load_instances
from .rollout import run_attempt


def _on(value) -> bool:
    """YAML parses bare on/off to bools; CLI passes strings. Accept both."""
    return str(value).lower() not in ("off", "false")


def _norm_title(title: str) -> str:
    return " ".join(title.lower().split())


class Dedup:
    """ReasoningStore is append-only; near-duplicate strategies (same title, same
    repo) are the flooding vector, so the runner refuses them at the door."""

    def __init__(self):
        self.seen: set[tuple[str, str]] = set()

    def fresh(self, item) -> bool:
        key = (item.scope, _norm_title(item.title))
        if key in self.seen:
            return False
        self.seen.add(key)
        return True


def stream_arm(cfg, llm, brain, memory, instances, logger, tag, agent_cost: list,
               retrieve: bool, write: bool):
    """One pass over the stream. Arm semantics via two orthogonal switches:
      nomem     retrieve=False write=False  (cold baseline, 1 attempt, parallel)
      withmem   retrieve=True  write=True   (self-evolution, N attempts, sequential)
      frozenmem retrieve=True  write=False  (fixed bank injection ablations, parallel)

    Only the WRITING arm is sequential across tasks (each task must see what the
    previous one wrote); non-writing arms have no cross-task coupling and run
    concurrently (swe.task_workers) — a pure wall-clock optimization."""
    swe = cfg.get("swe", {}) or {}
    n_traj = max(1, cfg.agent.n_traj) if write else 1
    gate = str(swe.get("injection_gate", "none"))
    layer1 = _on(swe.get("layer1", "on"))
    layer2 = _on(swe.get("layer2", "on"))
    vote_margin = int(swe.get("vote_margin", 2))
    l1_cap = int(swe.get("l1_max_per_task", 2))
    dedup = Dedup()
    for it in memory.reasoning.items:       # resume: pre-seed so old titles stay unique
        dedup.seen.add((it.scope, _norm_title(it.title)))
    pool = ThreadPoolExecutor(max_workers=min(n_traj, max(1, cfg.run.concurrency)))
    rows, preds, w1, w2 = [], {}, 0, 0
    traj_dir = Path(logger.dir) / "trajs"

    def one_task(pair):
        """Budget stop propagates (intentional halt); anything else skips the task —
        a transient network/docker failure must not kill a multi-day campaign."""
        try:
            return _one_task(pair)
        except BudgetExceeded:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.event("task_error", tag=tag, instance=pair[1]["instance_id"],
                         err=f"{type(exc).__name__}: {exc}"[:200])
            return None

    def _one_task(pair):
        nonlocal w1, w2
        ti, inst = pair
        if _spent(llm, agent_cost) > cfg.run.budget_usd:
            raise BudgetExceeded(f"total spend ${_spent(llm, agent_cost):.2f}")
        iid = inst["instance_id"]
        if not ensure_image(image_name(inst, swe.get("arch", "arm64"))):
            logger.event("skip_instance", tag=tag, instance=iid, why="no arm64 image")
            return None
        scope = f"repo:{inst['repo']}"
        task_obj = Task(id=iid, prompt=inst["problem_statement"][:2000], scope=scope)
        ret_items, ret_scores, mem_text = [], [], ""
        if retrieve:
            try:
                k = int(cfg.memory.retrieve_k_reasoning)
                fetch_k = max(k, int(swe.get("retrieve_fetch_k", 10))) if gate == "llm" else k
                thr = float(cfg.memory.get("relevance_threshold", 0.0))
                # memory_scope=global searches the whole bank (RB-style storage scope,
                # content held fixed) — the storage-scope arm of the final campaign.
                mem_scope = None if swe.get("memory_scope") == "global" else scope
                pairs = memory.reasoning.topk_scored(task_obj.prompt, fetch_k, thr, scope=mem_scope)
                ret_scores = [round(s, 3) for _, s in pairs]
                ret_items = [it for it, _ in pairs]
                if gate == "llm":               # injection-side relevance gate (can keep 0)
                    ret_items = brain.select_relevant(inst, ret_items)[:k]
                mem_text = memory.render({"reasoning": ret_items})
            except BudgetExceeded:
                raise
            except Exception as exc:  # noqa: BLE001 - degrade to no memory, don't halt
                ret_items, ret_scores, mem_text = [], [], ""
                logger.event("retrieve_error", instance=iid, err=type(exc).__name__)

        def attempt(r, inst=inst, mem_text=mem_text):
            return run_attempt(inst, mem_text, cfg,
                               traj_dir / f"{inst['instance_id']}.{tag}.a{r}.traj.json")
        attempts = list(pool.map(attempt, range(n_traj))) if n_traj > 1 else [attempt(0)]
        agent_cost[0] += sum(a["cost"] for a in attempts)

        verdicts = [brain.judge_attempt(inst, a) for a in attempts]
        nc = sum(1 for v in verdicts if v["success"] and v["verified"])
        n = len(attempts)
        preds[iid] = {"model_name_or_path": f"hippo-{tag}", "instance_id": iid,
                      "model_patch": attempts[0]["patch"]}

        if write:
                # LAYER 1: surprising attempts only (failed / success-but-unverified),
                # capped per task — the Mind2Web flooding lesson, encoded.
                if layer1:
                    written = 0
                    for a, v in zip(attempts, verdicts):
                        if written >= l1_cap:
                            break
                        if (v["success"] and v["verified"]) or a["exit_status"] == "SetupError":
                            continue
                        for it in brain.reflect_attempt(inst, a, v):
                            if dedup.fresh(it):
                                memory.write_reasoning(it)
                                w1 += 1
                                written += 1
                                logger.event("swe_write_l1", instance=iid, scope=scope,
                                             item={"title": it.title, "content": it.content[:200]})
                # LAYER 2: divergence + vote margin. A 3:2 judge split flips on one
                # misjudgment, so close votes are logged and skipped, not extracted.
                if layer2 and 0 < nc < n:
                    if abs(2 * nc - n) >= vote_margin:
                        for it in brain.contrast_attempts(inst, attempts, verdicts):
                            if dedup.fresh(it):
                                memory.write_reasoning(it)
                                w2 += 1
                                logger.event("swe_write_l2", instance=iid, scope=scope, nc=nc, n=n,
                                             item={"title": it.title, "content": it.content[:200]})
                    else:
                        logger.event("swe_l2_skipped_close_vote", instance=iid, nc=nc, n=n)

        row = {"idx": ti, "instance_id": iid, "repo": inst["repo"],
               "judge_success": int(verdicts[0]["success"] and verdicts[0]["verified"]),
               "nc": nc, "n": n, "steps": attempts[0]["n_steps"],
               "cost": round(sum(a["cost"] for a in attempts), 4)}
        logger.event("swe_task", tag=tag, idx=ti, instance=iid, scope=scope, nc=nc, n=n,
                     exit_statuses=[a["exit_status"] for a in attempts],
                     judge=[{k: v[k] for k in ("success", "verified", "reason")} for v in verdicts],
                     n_retrieved=len(ret_items), ret_scores=ret_scores,
                     mem_chars=len(mem_text), n_memory=memory.stats()["n_reasoning"])
        logger.info(f"[{tag}] {ti + 1}/{len(instances)} {iid} nc={nc}/{n} "
                    f"mem={memory.stats()['n_reasoning']} spent=${_spent(llm, agent_cost):.2f}")
        return row

    try:
        # consume incrementally so a mid-stream halt (budget) keeps completed rows
        if write:
            results = map(one_task, enumerate(instances))
        else:
            task_pool = ThreadPoolExecutor(max_workers=max(1, int(swe.get("task_workers", 4))))
            results = task_pool.map(one_task, enumerate(instances))
        for r in results:
            if r:
                rows.append(r)
    finally:
        if not write:
            task_pool.shutdown(wait=True, cancel_futures=True)
        pool.shutdown(wait=True)
        with open(Path(logger.dir) / f"preds_{tag}.json", "w") as fh:
            json.dump(preds, fh, indent=2)
        write_csv(os.path.join(logger.dir, f"metrics_{tag}.csv"), rows)

    return _summarize(rows) | {"layer1_writes": w1, "layer2_writes": w2}


def _spent(llm, agent_cost: list) -> float:
    return llm.spent_usd + agent_cost[0]


def _summarize(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0}
    n = len(rows)
    half = n // 2
    sr = [r["judge_success"] for r in rows]
    return {"n": n, "judge_sr": round(sum(sr) / n, 4),
            "judge_sr_first_half": round(sum(sr[:half]) / max(half, 1), 4),
            "judge_sr_second_half": round(sum(sr[half:]) / max(n - half, 1), 4),
            "divergent_tasks": sum(1 for r in rows if 0 < r["nc"] < r["n"]),
            "total_cost": round(sum(r["cost"] for r in rows), 2)}


def run(cfg) -> dict:
    load_dotenv()
    import litellm

    litellm.drop_params = True  # reasoning models (gpt-5 family) reject temperature etc.
    logger = RunLogger(cfg.run.out_dir, cfg.run.name, level=cfg.logging.level,
                       jsonl=cfg.logging.jsonl)
    swe = cfg.get("swe", {}) or {}
    # SWE memory is task-level strategies: reasoning store, repo-scoped.
    if cfg.memory.mode != "off":
        cfg["memory"]["mode"] = "reasoning_only"
    cfg["memory"]["scope_reasoning"] = True

    llm = LLMClient(model=cfg.llm.model, embed_model=cfg.llm.embed_model,
                    temperature=cfg.llm.temperature, max_tokens=int(swe.get("judge_max_tokens", 8000)),
                    cache=cfg.llm.cache, budget_usd=cfg.run.budget_usd)
    brain = SweBrain(llm)
    instances = load_instances(cfg)
    if skip := swe.get("skip_done"):        # resume: drop instances a prior run finished
        done = set(json.loads(Path(skip).read_text()).keys())
        instances = [i for i in instances if i["instance_id"] not in done]
        logger.info(f"skip_done: {len(done)} already finished -> {len(instances)} remaining")
    arms = [a.strip() for a in str(swe.get("arms", "nomem,withmem")).split(",") if a.strip()]
    logger.info(f"run_id={logger.run_id} instances={len(instances)} arms={arms} "
                f"agent_model={swe.get('agent_model', cfg.llm.model)} n_traj={cfg.agent.n_traj}")
    logger.event("run_start", n_instances=len(instances), config=dict(cfg))

    agent_cost = [0.0]
    summary: dict = {"n_instances": len(instances), "arms": arms}
    memory = None
    try:
        if "nomem" in arms:
            empty = Memory(llm.embed, cfg)
            summary["nomem"] = stream_arm(cfg, llm, brain, empty, instances, logger,
                                          "nomem", agent_cost, retrieve=False, write=False)
        if "frozenmem" in arms:             # injection ablations on a FIXED bank
            frozen = Memory(llm.embed, cfg)
            frozen.load(swe["memory_in"])   # required: a saved memory.json
            logger.info(f"frozen bank {frozen.stats()} from {swe['memory_in']}")
            summary["frozenmem"] = stream_arm(cfg, llm, brain, frozen, instances, logger,
                                              "frozenmem", agent_cost, retrieve=True, write=False)
        if "withmem" in arms:
            memory = Memory(llm.embed, cfg)
            if swe.get("memory_in"):        # resume: continue evolving a saved store
                memory.load(swe["memory_in"])
                logger.info(f"loaded memory {memory.stats()} from {swe['memory_in']}")
            summary["withmem"] = stream_arm(cfg, llm, brain, memory, instances, logger,
                                            "withmem", agent_cost, retrieve=True, write=True)
    except (BudgetExceeded, KeyboardInterrupt) as exc:
        summary["halted"] = f"{type(exc).__name__}: {exc}"
        logger.warn(f"run halted: {summary['halted']}")
    finally:
        if memory is not None:   # persist even on halt — 20h of learned memory is the artifact
            summary["learned_memory"] = memory.stats()
            memory.save(os.path.join(logger.dir, "memory.json"))

    summary["judge_llm_calls"] = llm.calls
    summary["spent_usd"] = round(_spent(llm, agent_cost), 4)
    logger.save_json("summary.json", summary)
    nm, wm = summary.get("nomem") or {}, summary.get("withmem") or {}
    logger.info(f"A/B judge_sr: nomem={nm.get('judge_sr')} -> withmem={wm.get('judge_sr')} "
                f"| withmem curve {wm.get('judge_sr_first_half')} -> {wm.get('judge_sr_second_half')} "
                f"| writes L1={wm.get('layer1_writes')} L2={wm.get('layer2_writes')} "
                f"| total ${summary['spent_usd']}")
    logger.close()
    return summary


def main():
    cfg = load_config(sys.argv[1:])
    run(cfg)


if __name__ == "__main__":
    main()
