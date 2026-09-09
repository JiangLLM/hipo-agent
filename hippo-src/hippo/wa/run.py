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
import multiprocessing
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FutureTimeout
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

from dotenv import load_dotenv

from ..config import load_config
from ..eval import write_csv
from ..llm import BudgetExceeded, LLMClient
from ..logging_utils import RunLogger
from ..memory import Memory
from .brain import WaBrain
from .data import assert_site_env, load_tasks, set_site_env
from .rollout import compact_trace, run_episode


def _on(v) -> bool:
    return str(v).lower() not in ("off", "false")


def _norm(t: str) -> str:
    return " ".join(t.lower().split())


def reset_site(cfg, logger, tag, required: bool = False, site: str | None = None):
    """Restore every box in the fleet to its pristine images before an arm starts.

    Why a script and not an HTTP endpoint: the endpoint form (wa.reset_url, browsergym's
    WA_FULL_RESET contract) assumes a reset service somebody deployed. We never deployed one, the
    config default is empty, and no launcher ever passed it — so this function returned
    immediately on every run we have ever done, while its own docstring claimed the sites were
    being reset. It also only ever addressed ONE box, which cannot work now that a run spans eight.

    scripts/wa_fleet.sh reset does the real thing on all eight in parallel: delete the four
    containers, recreate them from the pristine images, and write each box's own IP back into
    Magento and GitLab. That works because the containers keep no volumes, so the writable layer
    IS the entire site state.

    required=True makes an unavailable reset fatal. For mutating tasks that is the only safe
    setting: without a reset the withmem arm starts on whatever the nomem arm left behind, and the
    comparison is meaningless in a way no downstream metric can reveal."""
    import subprocess
    import time

    wa = cfg.get("wa", {}) or {}
    if not _on(wa.get("fleet_reset", "off")):
        if required:
            raise RuntimeError(
                "this task set writes to the server, so the arms must start from identical state, "
                "but wa.fleet_reset is off. Turn it on (the fleet script resets all 8 boxes), or "
                "select read-only tasks with --wa.task_filter readonly.")
        return
    root = Path(__file__).resolve().parents[3]
    script = root / "scripts" / "wa_fleet.sh"
    if not script.exists():
        if required:
            raise RuntimeError(f"fleet reset requested but {script} is missing")
        logger.event("reset_skipped", tag=tag, why="script missing")
        return
    # site=None resets all four sites; a site name resets just that one (much cheaper — forum
    # recreates in ~30s, the full reset takes minutes). The container for reddit is named "forum".
    container = {"reddit": "forum"}.get(site, site)
    what = container or "all sites"
    logger.info(f"[{tag}] resetting {what} from pristine images")
    t0 = time.time()
    try:
        proc = subprocess.run(["bash", str(script), "reset"] + ([container] if container else []),
                              cwd=str(root),
                              capture_output=True, text=True, timeout=45 * 60)
    except subprocess.TimeoutExpired:
        logger.event("reset_timeout", tag=tag)
        if required:
            raise
        return
    took = round(time.time() - t0, 1)
    if proc.returncode == 0:
        logger.event("reset_done", tag=tag, seconds=took, site=what)
        logger.info(f"[{tag}] reset of {what} done in {took}s")
    else:
        logger.event("reset_failed", tag=tag, seconds=took, err=proc.stdout[-800:])
        if required:
            raise RuntimeError(f"fleet reset failed, refusing to score mutating tasks on dirty "
                               f"state:\n{proc.stdout[-800:]}")
        logger.warn(f"[{tag}] fleet reset FAILED after {took}s, continuing (read-only task set)")


# ---- parallel rollout workers (multi-rollout write arm) ---------------------------------
# browsergym's sync Playwright is a per-PROCESS singleton, so the N rollouts of one task can't
# run concurrently inside one process (threads crash on env.reset). We fan them out to N worker
# PROCESSES: each imports browsergym once (persistent pool), applies the SAME grader patch + site
# env (reward is computed in the worker's env.step, so the patch must live there too), and runs one
# rollout. run_episode is side-effect-free w.r.t. memory (it only READS a memory_text string), so
# this preserves the design exactly — all N rollouts see the same pre-task snapshot; L1/L2 writes
# happen in the parent afterward. Per-step events are collected and replayed into the real logger.
_WORKER: dict = {}


def _kill_pool(pool) -> None:
    """Tear a pool down for real. shutdown(cancel_futures=True) leaves RUNNING futures running and
    their processes alive, so a rebuilt pool would race the corpse — on a per-deployment pool that
    means two rollouts of one task on one box, i.e. the contamination we are paying 8 boxes to
    avoid. Kill the processes, then let shutdown collect.

    The forged results below are load-bearing. A RUNNING work item whose worker was SIGKILLed
    never produces a result, so it sits in pending_work_items forever; the manager thread then
    never satisfies its exit condition and parks in connection.wait — and because our shutdown's
    wakeup fires in the same select() as the dead-worker sentinel, the elif in
    wait_result_broken_or_wakeup reads the wakeup FIRST and never notices the corpse. A parked
    non-daemon manager thread deadlocks interpreter exit (threading._shutdown joins it), which
    turned 'watchdog killed a hung rollout at 21:36' into 'the whole run is a zombie at 08:00'.
    Feeding a fabricated result per pending item lets the thread drain, see pending empty, and
    walk its normal shutdown path."""
    try:
        from concurrent.futures.process import _ResultItem
        rq = getattr(pool, "_result_queue", None)
        pending = dict(getattr(pool, "_pending_work_items", {}) or {})
        if rq is not None:
            for wid in pending:
                try:
                    rq.put(_ResultItem(wid, exception=BrokenProcessPool(
                        "rollout watchdog killed this worker")))
                except Exception:  # noqa: BLE001 - queue already closed
                    break
    except Exception:  # noqa: BLE001 - stdlib internals moved; kills below still matter most
        pass
    try:
        # NOT list(d).values() — list(dict) yields KEYS, and the resulting AttributeError was
        # silently swallowed here for weeks: this loop never killed anything. It only looked
        # fine because on the BrokenProcessPool path the workers were already corpses.
        for proc in list((getattr(pool, "_processes", None) or {}).values()):
            try:
                proc.kill()
            except Exception:  # noqa: BLE001 - already gone
                pass
    except Exception:  # noqa: BLE001 - private attr moved; shutdown below is still worth trying
        pass
    # Order matters: join the manager thread BEFORE calling shutdown(). The forged results and
    # the dead-worker sentinels drive it through its own broken-pool teardown, which was verified
    # to terminate it; racing shutdown(cancel_futures=True) against that teardown was verified to
    # park it forever (its wakeup masks the sentinel in the same select()).
    mgr = getattr(pool, "_executor_manager_thread", None)
    if mgr is not None:
        mgr.join(timeout=30)
        if mgr.is_alive():   # would deadlock interpreter exit later — say so NOW, mid-run
            print(f"[warn] pool manager thread refused to die; "
                  f"process exit may hang (thread={mgr.name})", file=sys.stderr, flush=True)
    try:
        pool.shutdown(wait=False, cancel_futures=True)
    except Exception:  # noqa: BLE001
        pass


def _worker_init(cfg_plain, llm_kwargs):
    import litellm
    from ..config import DotDict
    load_dotenv()
    litellm.drop_params = True
    cfg = DotDict(cfg_plain)
    set_site_env(cfg)
    # this worker owns exactly one deployment for its whole life; prove it before touching a browser
    assert_site_env(cfg)
    _fix_webarena_grader()
    _patch_browsergym_infra()
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

    # In-worker deadline. Twice now a worker wedged itself in a 100%-CPU greenlet spin inside
    # the playwright sync bridge (browser and node driver alive and idle, python spinning),
    # which no step timeout can interrupt because no step ever returns. The parent's 1800s
    # watchdog contains the damage; this deadline turns it into a cheap, SELF-DIAGNOSING kill:
    # dump every thread's python stack to stderr (which the launcher redirects into the run
    # log — the autopsy we could never capture from outside without root), then hard-exit.
    # The parent sees BrokenProcessPool and retries the rollout once on a fresh worker.
    import faulthandler
    import threading
    deadline = int((cfg.get("wa", {}) or {}).get("episode_timeout", 900))

    def _boom():
        print(f"[worker] episode deadline {deadline}s exceeded on t{task_id} "
              f"(rollout {log_ctx.get('rollout')}) — python stacks follow, then self-destruct",
              file=sys.stderr, flush=True)
        faulthandler.dump_traceback(file=sys.stderr)
        os._exit(70)

    timer = threading.Timer(deadline, _boom)
    timer.daemon = True
    if deadline > 0:
        timer.start()
    try:
        before = llm.spent_usd
        x = run_episode(task_id, mem_text, cfg, llm, _Collect(), log_ctx=log_ctx)
    finally:
        timer.cancel()
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
    site = str(wa.get("site", "shopping"))
    seen = {(it.scope, _norm(it.title)) for it in memory.reasoning.items}
    rows, w1, w2 = [], 0, 0

    # fan the N rollouts of each task across N worker processes (persistent pool). Only the
    # multi-rollout write arm needs it; WA_PARALLEL=0 forces the sequential path (isolated debug).
    executor = None
    _new_executor = None
    # wa.base_urls pins rollout r to deployment r (one WebArena box per rollout). This is the only
    # way a MUTATING task can yield N independent rewards: the N rollouts share one account per
    # site, and the grader reads server state, so on a single deployment "did the bio change / did
    # the order appear" is one shared answer for all N — first success scores everyone, and the L2
    # contrast is then built on rollouts that were tripping over each other mid-episode.
    #
    # It has to be per-PROCESS, not per-rollout: webarena freezes the site URLs into module
    # constants at first import (browser_env/env_config.py), so re-setting the env vars later has
    # no effect. And it cannot be handed out by a shared counter, because max_tasks_per_child
    # recycles workers — a replacement would draw an index still held by a live worker and two
    # rollouts would quietly land on the same box. Hence one single-worker pool per deployment:
    # the binding is structural, and recycling still works inside each pool.
    raw_urls = wa.get("base_urls", "")
    base_urls = ([] if raw_urls in (True, False, None)     # a bare --wa.base_urls parses as True
                 else [u.strip() for u in str(raw_urls).split(",") if u.strip()])
    # Refuse the combination that produces confidently-wrong numbers: mutating tasks fanned out
    # over a SHARED deployment. One box cannot answer "did the order appear" N different ways, so
    # the first success scores every rollout. Better to stop than to publish that.
    n_mut = sum(1 for t in tasks if t.get("mutating"))
    if n_traj > 1 and n_mut and len(base_urls) < n_traj:
        raise ValueError(
            f"{n_mut} of {len(tasks)} tasks write to the server, but wa.base_urls lists "
            f"{len(base_urls)} deployments for n_traj={n_traj}. Give every rollout its own box "
            f"(scripts/wa_fleet.sh urls), or select read-only tasks (--wa.task_filter readonly), "
            f"or drop to --agent.n_traj 1.")
    if base_urls and len(base_urls) < n_traj:
        raise ValueError(f"wa.base_urls has {len(base_urls)} deployments but n_traj={n_traj}; "
                         "every rollout needs its own box or the isolation is a fiction")
    pools: list = []
    # NOT gated on `write`: a scoring arm running eval_rollouts>1 needs the same isolation, or the
    # baseline we compare against is itself contaminated (rollout 1's purchase is visible to 2..N)
    # — and it would run N rollouts sequentially in the parent, N times slower for no reason.
    if n_traj > 1 and os.environ.get("WA_PARALLEL", "1") != "0":
        llm_kwargs = {"model": cfg.llm.model, "embed_model": cfg.llm.embed_model,
                      "temperature": cfg.llm.temperature, "max_tokens": int(wa.get("max_tokens", 4000)),
                      "cache": cfg.llm.cache, "budget_usd": cfg.run.budget_usd}
        _mp = multiprocessing.get_context("spawn")   # max_tasks_per_child requires a non-fork ctx
        recycle = int(wa.get("worker_recycle", 10))

        def _cfg_for(url: str) -> dict:
            plain = json.loads(json.dumps(dict(cfg)))
            if url:
                plain["wa"]["base_url"] = url
            return plain

        if base_urls:
            # Recycle far more aggressively here than on the shared pool. There, `recycle` tasks
            # are spread over n_traj workers, so a wedged one is replaced after roughly
            # recycle/n_traj rollouts. Here each pool has exactly ONE worker, so the same number
            # means it must serve `recycle` whole tasks before it is refreshed — and a Playwright
            # loop that wedges early ("no running event loop") then poisons every remaining
            # rollout on that box. That is what cost the shopping_admin nomem arm 32 rollouts.
            per_pool_recycle = max(1, recycle // max(1, n_traj))

            def _new_pool(i):
                # max_workers=1 so this pool's single process keeps deployment i for its whole life
                return ProcessPoolExecutor(max_workers=1, mp_context=_mp, initializer=_worker_init,
                                           initargs=(_cfg_for(base_urls[i]), llm_kwargs),
                                           max_tasks_per_child=per_pool_recycle)
            _new_executor = _new_pool
            pools = [_new_pool(i) for i in range(n_traj)]
            logger.info(f"[{tag}] rollout isolation ON: {n_traj} deployments "
                        f"{base_urls[:n_traj]}")
        else:
            # single shared deployment: correct for read-only tasks only (nothing is written, so
            # the N rollouts cannot see each other), which is what wa.task_filter=readonly selects.
            cfg_plain = _cfg_for("")
            def _new_executor():   # rebuild helper — recovers from a BrokenProcessPool
                # recycling replaces a worker whose Playwright asyncio loop has wedged (the "no
                # running event loop" crash) instead of routing every later rollout to a dead one.
                return ProcessPoolExecutor(max_workers=n_traj, mp_context=_mp,
                                           initializer=_worker_init, initargs=(cfg_plain, llm_kwargs),
                                           max_tasks_per_child=recycle)
            executor = _new_executor()
            logger.info(f"[{tag}] parallel rollouts ON: {n_traj} worker processes, ONE deployment "
                        f"(sound for read-only tasks; mutating tasks need wa.base_urls)")

    # Reset when this arm will WRITE to the sites, not by a hardcoded site list. The old list left
    # shopping out even though its cart, orders and reviews are all mutable, and it would have
    # reset gitlab for a run of pure lookups. Statefulness is a property of the task set, and the
    # frozen manifest already tells us: if any task mutates, both arms must start from the same
    # state, and an unavailable reset is then fatal rather than a warning.
    if n_mut:
        reset_site(cfg, logger, tag, required=True)

    def one_task(ti, t):
        nonlocal w1, w2, executor
        scope = f"site:{site}"
        mem_text, ret_titles, ret_scores = "", [], []
        if retrieve:
            k = int(cfg.memory.retrieve_k_reasoning)
            thr = float(cfg.memory.get("relevance_threshold", 0.0))
            # inject ONLY L2 by default; L1 stays in the bank (written for debug) but not retrieved.
            # Layer-filter happens INSIDE the store (before top-k) so L2 isn't starved by the L1 flood.
            layer = "L2" if _on(wa.get("inject_only_l2", "on")) else None
            if str(wa.get("inject_gate", "none")) == "llm":
                # cosine recall a small pool, then let the LLM pick the ONE genuinely-applicable
                # lesson (or none) — resolves the generic-vs-specific ties raw cosine can't (e.g. a
                # "branch main" task needs the branch lesson, not the generic Contributors one).
                fetch = int(wa.get("retrieve_fetch_k", 5))
                cands = memory.reasoning.topk_scored(t["intent"], fetch, thr, scope=scope, layer=layer)
                chosen = brain.select_lesson(t["intent"], [it for it, _ in cands])
                pairs = [(it, s) for it, s in cands if it is chosen] if chosen is not None else []
            else:
                pairs = memory.reasoning.topk_scored(t["intent"], k, thr, scope=scope, layer=layer)
            items = [it for it, _ in pairs]
            ret_titles = [it.title for it in items]
            ret_scores = [round(s, 3) for _, s in pairs]
            mem_text = memory.render({"reasoning": items})
            logger.event("wa_retrieve", tag=tag, task_id=t["task_id"], n_retrieved=len(items),
                         scores=ret_scores, titles=ret_titles, mem_chars=len(mem_text))
        # N rollouts: in parallel across worker processes when a pool is up, else sequentially.
        if pools or executor is not None:
            payloads = [(t["task_id"], mem_text,
                         {"tag": tag, "task_id": t["task_id"], "rollout": r}) for r in range(n_traj)]
            packed = None
            # Wall-clock cap per task batch. Without one, f.result() waits forever: a reddit run
            # froze at task 35/106 for 11 hours because all 8 workers hung in browser SETUP
            # (playwright greenlet-spinning on a browser that died mid-launch) — a phase that
            # step_timeout does not cover, and no step means no timeout ever fires. All N futures
            # start together, so one shared deadline bounds a fully-hung task to ~one `wall`.
            wall = int(wa.get("rollout_timeout", 1800))
            deadline = time.time() + wall
            # a worker native crash (segfault/OOM in Playwright) breaks the pool PERMANENTLY;
            # rebuild + retry once so one crash can't silently zero every remaining task in the arm.
            if pools:
                # one pool per deployment: rollout r ALWAYS runs on box r. Retry PER ROLLOUT, never
                # as a batch: collecting with [f.result() for f in futs] raises on the first broken
                # future while the other N-1 are still running, and shutdown(cancel_futures=True)
                # cannot cancel a RUNNING future — so re-submitting the whole batch put a second
                # rollout of the same task on a box that still had the first one live. That is the
                # shared-cart contamination the fleet exists to remove, reintroduced by the retry.
                results: list = [None] * n_traj
                futs = {r: pools[r].submit(_rollout_worker, payloads[r]) for r in range(n_traj)}
                for r, f in futs.items():
                    try:
                        results[r] = f.result(timeout=max(1.0, deadline - time.time()))
                    except FutureTimeout:
                        # A hang is not a crash: no retry. A worker that sat on one rollout for
                        # `wall` seconds is spinning, and retrying a deterministic hang would cost
                        # another `wall` per rollout (8x the damage on a task that hangs all 8).
                        # Kill the pool so box r gets a fresh worker for the NEXT task, and drop
                        # this rollout — the denominator accounting below already handles absences.
                        logger.warn(f"[{tag}] pool {r} (box {base_urls[r]}) HUNG on "
                                    f"t{t['task_id']} ({wall}s) — killing it, dropping the rollout")
                        _kill_pool(pools[r])
                        pools[r] = _new_executor(r)
                    except BrokenProcessPool:
                        logger.warn(f"[{tag}] pool {r} (box {base_urls[r]}) broke on "
                                    f"t{t['task_id']} — killing it and retrying that rollout only")
                        _kill_pool(pools[r])
                        pools[r] = _new_executor(r)
                        try:
                            results[r] = pools[r].submit(
                                _rollout_worker, payloads[r]).result(timeout=wall)
                        except Exception as exc:  # noqa: BLE001 - one box down != lose the task
                            logger.warn(f"[{tag}] pool {r} failed twice on t{t['task_id']}: {exc}")
                            _kill_pool(pools[r])
                            pools[r] = _new_executor(r)
                if all(x is None for x in results):
                    raise RuntimeError(f"every deployment failed on t{t['task_id']}")
                # a rollout that never produced a result is dropped, not faked: nc/n below counts
                # only what actually ran, so a dead box shrinks N instead of scoring a false 0.
                packed = [x for x in results if x is not None]
            else:
                for attempt in (1, 2):
                    try:
                        # submit+result instead of map: map() has no per-future timeout, and one
                        # worker hung in browser setup would freeze the whole arm forever.
                        futs2 = [executor.submit(_rollout_worker, p) for p in payloads]
                        end = time.time() + wall
                        packed = [f.result(timeout=max(1.0, end - time.time())) for f in futs2]
                        break
                    except (BrokenProcessPool, FutureTimeout):
                        logger.warn(f"[{tag}] worker pool broke or hung on t{t['task_id']} "
                                    f"(attempt {attempt}) — rebuilding")
                        _kill_pool(executor)
                        executor = _new_executor()
                if packed is None:   # broke twice — skip this task loudly, not silently
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
        verdicts = [brain.judge_trajectory(t["intent"], x["trace"], x["stop_answer"],
                                           x["reward"], t.get("reference")) for x in rollouts]
        for r, (x, v) in enumerate(zip(rollouts, verdicts)):
            logger.event("wa_judge", tag=tag, task_id=t["task_id"], rollout=r,
                         reward=x["reward"], outcome=v["outcome"], reason=v.get("reason", ""))
        reward = rollouts[0]["reward"]                # official 0/1 of the scored rollout
        # Ground truth is the env grader (reward). The judge only labels HOW a CORRECT rollout got
        # there: genuine (really derived) vs fluke (correct by luck / shallow match). ok/nc stay
        # reward-based for the top-line metrics; the L1/L2 gates below use the genuine/fluke labels.
        ok = [bool(x["reward"]) for x in rollouts]
        nc = sum(ok)
        # Denominator counts rollouts that actually RAN. A rollout that died in the browser
        # (Target crashed, goto timeout, a wedged Playwright loop) carries reward=0 and would
        # otherwise be scored as a wrong answer. That is not a measurement, it is a missing
        # sample, and it is not symmetric across arms: on shopping_admin the nomem arm lost 32
        # rollouts to browser crashes against the withmem arm's 4, which alone moved the paired
        # delta by 3.2 points — in the direction that flattered memory.
        n_err = sum(1 for x in rollouts if x.get("error"))
        n = len(rollouts) - n_err
        if n <= 0:                     # every rollout died: no evidence either way
            logger.event("wa_task_all_failed", tag=tag, task_id=t["task_id"], n_err=n_err)
            return
        if n_err:
            logger.event("wa_rollouts_dropped", tag=tag, task_id=t["task_id"],
                         n_err=n_err, n_scored=n)

        if write:
            # L1 = reflect ONLY on genuine FAILURES (reward=0), one lesson each, no cap. Genuine
            # successes have nothing to learn; FLUKES are NO-OP (skipped here AND dropped from L2).
            # The reference answer is passed in so the lesson targets the procedure that would have
            # reached the correct result. Every written L1 also feeds L2.
            l1_by_rollout: list = []
            if layer1:
                for x, v in zip(rollouts, verdicts):
                    if x["error"] or v["outcome"] != "failure":
                        l1_by_rollout.append([])
                        continue
                    items = brain.reflect_trajectory(site, t["intent"], x["trace"], v)
                    l1_by_rollout.append(items)
                    for it in items:
                        k = (it.scope, _norm(it.title))
                        if k not in seen:
                            seen.add(k); memory.write_reasoning(it); w1 += 1
                            logger.event("wa_write_l1", task=t["task_id"], item={"title": it.title})
            else:
                l1_by_rollout = [[] for _ in rollouts]
            # L2: FLUKE rollouts are dropped entirely (no-op), then contrast the rest by the
            # genuine-success ratio — 4 cases inside contrast_rollouts (all-wrong / half /
            # majority-right / majority-wrong). Fires only with >1 non-fluke rollouts that are not
            # a clean sweep of genuine successes.
            keep = [i for i, v in enumerate(verdicts) if v["outcome"] != "fluke"]
            ok_l2 = [verdicts[i]["outcome"] == "genuine" for i in keep]
            ncg = sum(ok_l2); nkeep = len(keep)
            if layer2 and nkeep > 1 and ncg < nkeep:
                for it in brain.contrast_rollouts(site, t["intent"],
                                                  [rollouts[i] for i in keep],
                                                  [verdicts[i] for i in keep],
                                                  [l1_by_rollout[i] for i in keep],
                                                  ok=ok_l2):
                    k = (it.scope, _norm(it.title))
                    if k not in seen:
                        seen.add(k); memory.write_reasoning(it); w2 += 1
                        logger.event("wa_write_l2", task=t["task_id"], nc=ncg, n=nkeep,
                                     n_fluke=n - nkeep, item={"title": it.title})

        rows.append({"idx": ti, "task_id": t["task_id"], "template_id": t["template_id"],
                     "reward": reward, "judge": int(verdicts[0]["outcome"] == "genuine"),
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

    # Per-mutating-task reset (wa.reset_per_task). Postmill rate-limits POSTING per account,
    # server-side: after ~10 posting tasks every submission returns "You cannot post more. Wait a
    # while before trying again", and from there on the grader hands out zeros that measure the
    # rate limiter, not the agent (observed live: reddit-all froze/zeroed from t603 on, twice).
    # The counter lives in the container, so recreating the site between mutating tasks is the
    # only reliable flush. `dirty` skips redundant resets: read-only tasks change nothing, and
    # the arm-start reset already covers the first mutating task.
    reset_per_task = _on(wa.get("reset_per_task", "off"))
    dirty = False
    try:
        for ti, t in enumerate(tasks):
            if llm.spent_usd > cfg.run.budget_usd:
                raise BudgetExceeded(f"spend ${llm.spent_usd:.2f}")
            if reset_per_task and t.get("mutating") and dirty:
                reset_site(cfg, logger, tag, required=True, site=site)
                dirty = False
            if t.get("mutating"):
                dirty = True   # pessimistic: even a failed attempt may have posted something
            try:
                one_task(ti, t)
                _LAST_PROGRESS[0] = time.time()
            except BudgetExceeded:
                raise
            except Exception as exc:  # noqa: BLE001 - one bad task must not kill the arm
                logger.event("task_error", tag=tag, task=t["task_id"],
                             err=f"{type(exc).__name__}: {exc}")
    finally:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
        for p in pools:
            try:
                p.shutdown(wait=True, cancel_futures=True)
            except Exception:  # noqa: BLE001 - teardown must not mask the real error
                pass
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

        # N/A equivalence (deterministic, symmetric to both arms). Official flow for
        # fuzzy_match=="N/A": exact_match on the literal "N/A", else llm_ua_match asks an LLM
        # whether pred declares the task unachievable — and browsergym calls validate() every
        # step with the placeholder answer "whatever", so a per-step LLM lottery hands out
        # rewards to agents that never answered (12 shopping tasks: 82-89% of scoring rollouts
        # had NO answer), while an agent that concluded "None" gets rejected (t24: semantically
        # correct, 0/8). Two deterministic rails before the LLM:
        #   empty/"whatever"  -> 0.0  (no answer is not a claim of unachievability)
        #   explicit none-y   -> 1.0  ("none", "no results", "not found", "does not exist", ...)
        # Anything else still goes to the LLM as before.
        import re as _re

        from webarena.evaluation_harness import evaluators as _ev
        _orig_ua = hf.llm_ua_match
        _NONE_RX = _re.compile(
            r"^(n/?a|none|no|nothing|not found|no result(s)?|no such .{0,60}|"
            r"(there (is|are) )?no .{0,60}|does not exist|not (available|achievable|possible)"
            r"[.!]?)$", _re.I)

        def _ua(pred, ref, intent):
            p = (pred or "").strip()
            if not p or p.lower() == "whatever":
                return 0.0
            if _NONE_RX.match(p):
                return 1.0
            return _orig_ua(pred, ref, intent)

        hf.llm_ua_match = _ua
        _ev.llm_ua_match = _ua      # evaluators imported the name by value; patch both
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
        # reddit references embed a second placeholder host, with a PORT-ful deployment on our
        # side: ref "http://www.reddit.com/f/books/59396" must match pred
        # "http://10.44.12.x:9999/f/books/59396", so the replacement needs the full netloc.
        # Full-benchmark audit (2026-08-14): www.reddit.com x2 and metis are the ONLY placeholder
        # hosts in reference_answers; web.cmoa.org (map t256) is a real museum website that IS the
        # answer — do not normalize it. Cost of the gap: reddit t66, 13/16 rollouts named exactly
        # the right posts and scored 0.
        reddit_netloc = _up.urlparse(os.environ.get("REDDIT") or "").netloc
        _orig_clean = StringEvaluator.clean_answer   # staticmethod descriptor -> plain callable

        def _clean(ans):
            s = _orig_clean(ans)
            if our_host:
                s = s.replace("metis.lti.cs.cmu.edu", our_host)
            if reddit_netloc:
                s = s.replace("www.reddit.com", reddit_netloc)
            return s

        StringEvaluator.clean_answer = staticmethod(_clean)
    except Exception:  # noqa: BLE001
        pass


def _patch_browsergym_infra():
    """Two infra fixes for the flaky self-hosted browser env (must run in whatever process calls
    env.step — i.e. every worker + the main process):
    (B) browsergym hardcodes a 500ms Playwright timeout on every locator action (fill/click/…),
        so a slightly-slow element throws TimeoutError and the agent wastes a step. Bump exactly
        those 500ms locator calls to 3000ms at the Playwright Locator level.
    (C) browsergym retries DOM/AXTree extraction EXTRACT_OBS_MAX_TRIES(=5) times per step; on an
        iframe-marking-bug page (e.g. t307) it burns all 5 retries every step. Lower the cap to 2
        — the final try is already lenient (skips the unmarkable frame)."""
    try:
        import browsergym.core.env as _bgenv
        if getattr(_bgenv, "EXTRACT_OBS_MAX_TRIES", 5) > 2:
            _bgenv.EXTRACT_OBS_MAX_TRIES = 2
    except Exception:  # noqa: BLE001 - browsergym internals may shift; leave default
        pass
    try:
        from playwright.sync_api import Locator
        for _name in ("click", "dblclick", "fill", "clear", "check", "uncheck",
                      "select_option", "hover", "press", "focus", "type"):
            _orig = getattr(Locator, _name, None)
            if _orig is None or getattr(_orig, "_wa_bumped", False):
                continue

            def _mk(o):
                def _w(self, *a, **k):
                    if k.get("timeout") == 500:      # only the hardcoded 500ms; leave timeout=0 etc.
                        k["timeout"] = 3000
                    return o(self, *a, **k)
                _w._wa_bumped = True
                return _w
            setattr(Locator, _name, _mk(_orig))
    except Exception:  # noqa: BLE001
        pass


def _arm_stall_reporter():
    """Diagnosis that survives us. A power blip overnight changed the machine's network identity;
    every LLM socket went CLOSE_WAIT, the workers (predating the in-worker deadline) slept on dead
    reads for 7 hours, and the parent froze somewhere we could never see because py-spy needs root
    on macOS. Two remedies, both about VISIBILITY rather than prevention:
      * SIGUSR1 dumps every thread's python stack on demand: `kill -USR1 <pid>` from any shell.
      * A daemon thread watches _LAST_PROGRESS and dumps all stacks to stderr (=> the run log)
        whenever no task has completed for 30 minutes, once per stall-interval.
    Neither kills anything — the parent watchdog and the in-worker deadline do the healing; this
    makes sure the NEXT freeze arrives with its own autopsy attached."""
    import faulthandler
    import signal
    import threading
    faulthandler.register(signal.SIGUSR1, all_threads=True, chain=False)

    def _watch():
        while True:
            time.sleep(300)
            quiet = time.time() - _LAST_PROGRESS[0]
            if quiet > 1800:
                print(f"[stall] no task finished for {quiet/60:.0f} min — python stacks of all "
                      f"threads follow (kill -USR1 {os.getpid()} re-dumps on demand)",
                      file=sys.stderr, flush=True)
                faulthandler.dump_traceback(file=sys.stderr)
                _LAST_PROGRESS[0] = time.time()   # rate-limit: one autopsy per stall interval

    threading.Thread(target=_watch, daemon=True, name="stall-reporter").start()


_LAST_PROGRESS = [0.0]


def run(cfg) -> dict:
    load_dotenv()
    import litellm
    litellm.drop_params = True
    _LAST_PROGRESS[0] = time.time()
    _arm_stall_reporter()
    wa = cfg.get("wa", {}) or {}
    set_site_env(cfg)
    _fix_webarena_grader()
    _patch_browsergym_infra()
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
