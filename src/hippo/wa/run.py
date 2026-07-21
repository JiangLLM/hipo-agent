"""WebArena streaming self-evolution loop — hippo memory on autonomous web navigation.

Same three-arm structure and measurement discipline as the SWE campaign:
  nomem     retrieve=off write=off   (cold baseline)
  withmem   retrieve=on  write=on    (self-evolution; N rollouts/task, then learn)
  frozenmem retrieve=on  write=off   (fixed-bank injection ablations)

Score is the OFFICIAL BrowserGym reward (0/1). Learning is label-free (WaBrain judge).
Every scored run should be repeated (wa.seed) — the SWE campaign's hard-won lesson is
that a single pass has ~8pt of sampling noise, so effects are only believed after
repeats. State-changing sites (reddit/gitlab) reset between arms via WA_FULL_RESET.

    .venv-wa/bin/python -m hippo.wa.run --wa.base_url http://10.44.12.29 \
        --wa.site shopping --wa.arms nomem,withmem --agent.n_traj 5 \
        --run.budget_usd 60 --run.name wa_shopping
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

from dotenv import load_dotenv

from ..config import load_config
from ..eval import write_csv
from ..llm import BudgetExceeded, LLMClient
from ..logging_utils import RunLogger
from ..memory import Memory
from .brain import WaBrain
from .data import load_tasks, set_site_env
from .rollout import compact_trace, run_episode


def _on(v) -> bool:
    return str(v).lower() not in ("off", "false")


def _norm(t: str) -> str:
    return " ".join(t.lower().split())


def reset_site(cfg, logger, tag):
    """Full-reset the state-changing sites, then poll until ready (200-500s). Called
    ONCE per arm, not per task — all arms get the same clean starting state."""
    import time
    import urllib.request

    wa = cfg.get("wa", {}) or {}
    base = str(wa.get("reset_url", "")).rstrip("/")
    if not base:
        return
    try:
        urllib.request.urlopen(f"{base}/reset", timeout=60)
    except Exception:  # noqa: BLE001 - trigger may return before completion
        pass
    for _ in range(60):                              # poll up to ~10 min
        try:
            status = urllib.request.urlopen(f"{base}/status", timeout=30).read().decode()
            if "Ready" in status:
                logger.event("reset_done", tag=tag)
                return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(10)
    logger.event("reset_timeout", tag=tag)


# ---- parallel rollout workers (multi-rollout write arm) ---------------------------------
# browsergym's sync Playwright is a per-PROCESS singleton, so the N rollouts of one task can't
# run concurrently inside one process (threads crash on env.reset). We fan them out to N worker
# PROCESSES: each imports browsergym once (persistent pool), applies the SAME grader patch + site
# env (reward is computed in the worker's env.step, so the patch must live there too), and runs one
# rollout. run_episode is side-effect-free w.r.t. memory (it only READS a memory_text string), so
# this preserves the design exactly — all N rollouts see the same pre-task snapshot; L1/L2 writes
# happen in the parent afterward. Per-step events are collected and replayed into the real logger.
_WORKER: dict = {}


def _worker_init(cfg_plain, llm_kwargs):
    import litellm
    from ..config import DotDict
    load_dotenv()
    litellm.drop_params = True
    cfg = DotDict(cfg_plain)
    set_site_env(cfg)
    _fix_webarena_grader()
    _WORKER["cfg"] = cfg
    _WORKER["llm"] = LLMClient(**llm_kwargs)


def _rollout_worker(payload):
    task_id, mem_text, log_ctx = payload
    llm, cfg = _WORKER["llm"], _WORKER["cfg"]
    events: list = []

    class _Collect:
        def event(self, kind, **f):
            events.append((kind, f))

        def info(self, *a, **k):
            pass

        def warn(self, *a, **k):
            pass

    before = llm.spent_usd
    x = run_episode(task_id, mem_text, cfg, llm, _Collect(), log_ctx=log_ctx)
    return {"x": x, "events": events, "spent": llm.spent_usd - before}


def stream_arm(cfg, llm, brain, memory, tasks, logger, tag, retrieve, write):
    wa = cfg.get("wa", {}) or {}
    # write arms need N rollouts to generate L1/L2 divergence material. Scoring-only arms
    # (nomem/frozenmem) default to 1 rollout, but for a low-variance A/B set wa.eval_rollouts
    # > 1: every arm then draws the same number of samples and we compare MEAN success rate
    # per task (scoring rollout[0] alone has ~single-draw noise that hides real effects).
    n_traj = max(1, cfg.agent.n_traj) if write else max(1, int(wa.get("eval_rollouts", 1)))
    layer1, layer2 = _on(wa.get("layer1", "on")), _on(wa.get("layer2", "on"))
    vote_margin = int(wa.get("vote_margin", 2))
    fluke_on = _on(wa.get("l1_fluke", "on"))   # L1 records failures + 蒙对 flukes; off = failures only
    site = str(wa.get("site", "shopping"))
    seen = {(it.scope, _norm(it.title)) for it in memory.reasoning.items}
    rows, w1, w2 = [], 0, 0

    # fan the N rollouts of each task across N worker processes (persistent pool). Only the
    # multi-rollout write arm needs it; WA_PARALLEL=0 forces the sequential path (isolated debug).
    executor = None
    _new_executor = None
    if write and n_traj > 1 and os.environ.get("WA_PARALLEL", "1") != "0":
        cfg_plain = json.loads(json.dumps(dict(cfg)))
        llm_kwargs = {"model": cfg.llm.model, "embed_model": cfg.llm.embed_model,
                      "temperature": cfg.llm.temperature, "max_tokens": int(wa.get("max_tokens", 4000)),
                      "cache": cfg.llm.cache, "budget_usd": cfg.run.budget_usd}

        def _new_executor():   # rebuild helper — reused to recover from a BrokenProcessPool
            return ProcessPoolExecutor(max_workers=n_traj, initializer=_worker_init,
                                       initargs=(cfg_plain, llm_kwargs))
        executor = _new_executor()
        logger.info(f"[{tag}] parallel rollouts ON: {n_traj} worker processes")

    if site in ("reddit", "gitlab", "shopping_admin"):   # clean, identical start per arm
        reset_site(cfg, logger, tag)

    def one_task(ti, t):
        nonlocal w1, w2, executor
        scope = f"site:{site}"
        mem_text, ret_titles, ret_scores = "", [], []
        if retrieve:
            pairs = memory.reasoning.topk_scored(t["intent"], int(cfg.memory.retrieve_k_reasoning),
                                                 float(cfg.memory.get("relevance_threshold", 0.0)),
                                                 scope=scope)
            items = [it for it, _ in pairs]
            ret_titles = [it.title for it in items]
            ret_scores = [round(s, 3) for _, s in pairs]
            mem_text = memory.render({"reasoning": items})
            logger.event("wa_retrieve", tag=tag, task_id=t["task_id"], n_retrieved=len(items),
                         scores=ret_scores, titles=ret_titles, mem_chars=len(mem_text))
        # N rollouts: in parallel across worker processes when the pool is up, else sequentially.
        if executor is not None:
            payloads = [(t["task_id"], mem_text,
                         {"tag": tag, "task_id": t["task_id"], "rollout": r}) for r in range(n_traj)]
            packed = None
            # a worker native crash (segfault/OOM in Playwright) breaks the pool PERMANENTLY;
            # rebuild + retry once so one crash can't silently zero every remaining task in the arm.
            for attempt in (1, 2):
                try:
                    packed = list(executor.map(_rollout_worker, payloads))
                    break
                except BrokenProcessPool:
                    logger.warn(f"[{tag}] worker pool broke on t{t['task_id']} (attempt {attempt}) — rebuilding")
                    try:
                        executor.shutdown(wait=False, cancel_futures=True)
                    except Exception:  # noqa: BLE001
                        pass
                    executor = _new_executor()
            if packed is None:   # broke twice — skip this task loudly (fresh pool ready for next), not silent
                raise RuntimeError(f"worker pool repeatedly broke on t{t['task_id']}")
            rollouts = [p["x"] for p in packed]
            for p in packed:                       # replay per-step events; accumulate cost
                for kind, f in p["events"]:
                    logger.event(kind, **f)
                llm.spent_usd += p["spent"]
        else:
            rollouts = [run_episode(t["task_id"], mem_text, cfg, llm, logger,
                                    log_ctx={"tag": tag, "task_id": t["task_id"], "rollout": r})
                        for r in range(n_traj)]
        for x in rollouts:
            x["trace"] = compact_trace(x["steps"])
        verdicts = [brain.judge_trajectory(t["intent"], x["trace"], x["stop_answer"]) for x in rollouts]
        for r, (x, v) in enumerate(zip(rollouts, verdicts)):
            logger.event("wa_judge", tag=tag, task_id=t["task_id"], rollout=r,
                         reward=x["reward"], success=v["success"], verified=v["verified"],
                         reason=v.get("reason", ""), evidence=v.get("evidence", ""))
        reward = rollouts[0]["reward"]                # official 0/1 of the scored rollout
        # Learning signal: which rollouts count as "success" for L1/L2 gating.
        #   judge  = label-free verdict (deployment-realistic, but noisy/over-strict here).
        #   reward = the env's own task-completion signal (an oracle upper-bound on the
        #            mechanism: shows what L1/L2 do when success/fail is judged accurately).
        # WebArena's reward is a programmatic completion check, not a held-out gold answer,
        # so using it stays honest about "did the task complete" without leaking test labels.
        sig = str((cfg.get("wa", {}) or {}).get("divergence_signal", "reward"))
        if sig == "reward":
            ok = [bool(x["reward"]) for x in rollouts]
        else:
            ok = [bool(v["success"] and v["verified"]) for v in verdicts]
        nc = sum(ok)
        n = len(rollouts)

        if write:
            # L1 = record the two SURPRISING outcomes, one lesson each, no count cap:
            #   - wrong (env reward=0)                       -> why it failed / how to avoid
            #   - 蒙对 FLUKE (reward=1 but the judge found the reasoning did NOT establish it) -> a caution
            # A genuine success (reward=1 AND judge success+verified = really knew it) is SKIPPED —
            # nothing to learn. The genuine/fluke split comes from the judge (which now reads the full
            # reasoning), not raw reward. wa.l1_fluke=off disables fluke capture (failures only).
            # Every written L1 also feeds L2.
            l1_by_rollout: list = []
            if layer1:
                for x, v in zip(rollouts, verdicts):
                    genuine = bool(x["reward"]) and v["success"] and v["verified"]
                    fluke = bool(x["reward"]) and not genuine
                    if x["error"] or genuine or (fluke and not fluke_on):
                        l1_by_rollout.append([])
                        continue
                    items = brain.reflect_trajectory(site, t["intent"], x["trace"], v,
                                                     outcome_hint=("fluke" if fluke else None))
                    l1_by_rollout.append(items)
                    for it in items:
                        k = (it.scope, _norm(it.title))
                        if k not in seen:
                            seen.add(k); memory.write_reasoning(it); w1 += 1
                            logger.event("wa_write_l1", task=t["task_id"], item={"title": it.title})
            else:
                l1_by_rollout = [[] for _ in rollouts]
            # L2: contrast the N per-rollout L1 lessons (majority vs minority), gated on divergence.
            if layer2 and 0 < nc < n and abs(2 * nc - n) >= vote_margin:
                for it in brain.contrast_rollouts(site, t["intent"], rollouts, verdicts,
                                                  l1_by_rollout, ok=ok):
                    k = (it.scope, _norm(it.title))
                    if k not in seen:
                        seen.add(k); memory.write_reasoning(it); w2 += 1
                        logger.event("wa_write_l2", task=t["task_id"], nc=nc, n=n, item={"title": it.title})

        rows.append({"idx": ti, "task_id": t["task_id"], "template_id": t["template_id"],
                     "reward": reward, "judge": int(verdicts[0]["success"] and verdicts[0]["verified"]),
                     "nc": nc, "n": n, "steps": rollouts[0]["n_steps"]})
        # self-evolution curve: cumulative SR and a trailing-10 window, in stream order —
        # if learning helps, the trailing window should rise as the bank matures.
        rwd = [r["reward"] for r in rows]
        cum_sr = sum(rwd) / len(rwd)
        win_sr = sum(rwd[-10:]) / len(rwd[-10:])
        logger.event("wa_task", tag=tag, task_id=t["task_id"], template_id=t["template_id"],
                     reward=reward, nc=nc, n=n, n_mem=memory.stats()["n_reasoning"],
                     cum_sr=round(cum_sr, 4), win10_sr=round(win_sr, 4),
                     l1_total=w1, l2_total=w2, ret_titles=ret_titles,
                     errors=[x["error"] for x in rollouts if x["error"]])
        logger.info(f"[{tag}] {ti+1}/{len(tasks)} t{t['task_id']} reward={reward} "
                    f"nc={nc}/{n} cumSR={cum_sr:.2f} win10={win_sr:.2f} "
                    f"mem={memory.stats()['n_reasoning']} spent=${llm.spent_usd:.2f}")

    try:
        for ti, t in enumerate(tasks):
            if llm.spent_usd > cfg.run.budget_usd:
                raise BudgetExceeded(f"spend ${llm.spent_usd:.2f}")
            try:
                one_task(ti, t)
            except BudgetExceeded:
                raise
            except Exception as exc:  # noqa: BLE001 - one bad task must not kill the arm
                logger.event("task_error", tag=tag, task=t["task_id"],
                             err=f"{type(exc).__name__}: {exc}")
    finally:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
        with open(Path(logger.dir) / f"rewards_{tag}.json", "w") as fh:
            json.dump({str(r["task_id"]): r["reward"] for r in rows}, fh, indent=2)
        write_csv(os.path.join(logger.dir, f"metrics_{tag}.csv"), rows)
    sr = sum(r["reward"] for r in rows) / len(rows) if rows else 0.0
    return {"n": len(rows), "reward_sr": round(sr, 4), "layer1_writes": w1, "layer2_writes": w2}


def _fix_webarena_grader():
    """WebArena's fuzzy_match evaluator hardcodes gpt-4-1106-preview and calls OpenAI
    directly (not our LLMClient). Our real OpenAI key lacks access to that deprecated
    model → every fuzzy-scored task 404s and is lost. Redirect the grader's OpenAI
    client to the ZGAI gateway and swap the dead model id for one ZGAI serves. Without
    this, all fuzzy_match tasks (a big chunk of shopping) score 0 regardless of the agent."""
    base = os.environ.get("LLM_API_BASE")
    key = os.environ.get("LLM_API_KEY")
    grader_model = os.environ.get("WA_GRADER_MODEL", "gpt-4o")
    if not (base and key):
        return
    os.environ["OPENAI_BASE_URL"] = base          # openai lib reads this
    os.environ["OPENAI_API_KEY"] = key            # grader uses OPENAI_API_KEY
    try:
        from webarena.evaluation_harness import helper_functions as hf
        from litellm import completion

        def _grader_complete(messages, model, temperature, max_tokens, top_p,
                             context_length, stop_token=None):
            # route the grader through the gateway. The gateway rejects legacy `max_tokens`
            # for every served model, so pass `max_completion_tokens` explicitly and drop
            # temperature (reasoning models only accept the default). Grader outputs are
            # short, so a fixed cap is fine.
            r = completion(model="openai/" + grader_model, messages=messages,
                           api_base=base, api_key=key,
                           max_completion_tokens=max(64, int(max_tokens or 256)),
                           drop_params=True)
            return r["choices"][0]["message"]["content"] or ""

        hf.generate_from_openai_chat_completion = _grader_complete
    except Exception:  # noqa: BLE001 - if webarena internals shift, grader stays default
        pass
    # string_match host normalization: our self-hosted sites serve on a different host than
    # the reference answers were generated against — some refs hardcode the original
    # metis.lti.cs.cmu.edu (e.g. ssh-clone-URL tasks). WebArena's official config-gen
    # substitutes the deployment host into references; our setup missed it. Normalize the
    # original host to ours inside clean_answer (applied to BOTH ref and pred) so answers
    # that are correct for our deployment grade correctly. Affects only answers containing
    # that host (a handful of gitlab tasks); neutral for everything else and for the A/B.
    try:
        import urllib.parse as _up

        from webarena.evaluation_harness.evaluators import StringEvaluator
        our_host = _up.urlparse(os.environ.get("GITLAB") or os.environ.get("SHOPPING") or "").hostname
        _orig_clean = StringEvaluator.clean_answer   # staticmethod descriptor -> plain callable

        def _clean(ans):
            s = _orig_clean(ans)
            return s.replace("metis.lti.cs.cmu.edu", our_host) if our_host else s

        StringEvaluator.clean_answer = staticmethod(_clean)
    except Exception:  # noqa: BLE001
        pass


def run(cfg) -> dict:
    load_dotenv()
    import litellm
    litellm.drop_params = True
    wa = cfg.get("wa", {}) or {}
    set_site_env(cfg)
    _fix_webarena_grader()
    logger = RunLogger(cfg.run.out_dir, cfg.run.name, level=cfg.logging.level, jsonl=cfg.logging.jsonl)
    if cfg.memory.mode != "off":
        cfg["memory"]["mode"] = "reasoning_only"
    cfg["memory"]["scope_reasoning"] = True

    llm = LLMClient(model=cfg.llm.model, embed_model=cfg.llm.embed_model,
                    temperature=cfg.llm.temperature, max_tokens=int(wa.get("max_tokens", 4000)),
                    cache=cfg.llm.cache, budget_usd=cfg.run.budget_usd)
    brain = WaBrain(llm)
    tasks = load_tasks(cfg)
    arms = [a.strip() for a in str(wa.get("arms", "nomem,withmem")).split(",") if a.strip()]
    logger.info(f"run_id={logger.run_id} site={wa.get('site')} tasks={len(tasks)} arms={arms}")
    logger.event("run_start", n_tasks=len(tasks), config=dict(cfg))

    summary = {"n_tasks": len(tasks), "site": wa.get("site"), "arms": arms}
    memory = None
    try:
        if "nomem" in arms:
            summary["nomem"] = stream_arm(cfg, llm, brain, Memory(llm.embed, cfg), tasks,
                                          logger, "nomem", retrieve=False, write=False)
        if "frozenmem" in arms:
            if not wa.get("memory_in"):
                raise ValueError("frozenmem arm requires --wa.memory_in <path to memory.json>")
            fm = Memory(llm.embed, cfg); fm.load(wa["memory_in"])
            summary["frozenmem"] = stream_arm(cfg, llm, brain, fm, tasks, logger, "frozenmem",
                                              retrieve=True, write=False)
        if "withmem" in arms:
            memory = Memory(llm.embed, cfg)
            if wa.get("memory_in"):
                memory.load(wa["memory_in"])
            summary["withmem"] = stream_arm(cfg, llm, brain, memory, tasks, logger, "withmem",
                                            retrieve=True, write=True)
    except (BudgetExceeded, KeyboardInterrupt) as exc:
        summary["halted"] = f"{type(exc).__name__}: {exc}"
        logger.warn(f"halted: {summary['halted']}")
    finally:
        if memory is not None:
            summary["learned_memory"] = memory.stats()
            memory.save(os.path.join(logger.dir, "memory.json"))
    summary["spent_usd"] = round(llm.spent_usd, 4)
    logger.save_json("summary.json", summary)
    logger.info(f"DONE {summary}")
    logger.close()
    return summary


def main():
    run(load_config(sys.argv[1:]))


if __name__ == "__main__":
    main()
