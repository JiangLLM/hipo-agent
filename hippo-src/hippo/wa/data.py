"""WebArena task metadata: ids, sites, intent templates.

BrowserGym registers the 812 tasks; what it doesn't expose directly is the metadata
we need for experiment design — which SITE a task lives on and which INTENT TEMPLATE
instantiated it. Templates are the revisit structure of this benchmark (241 templates
x ~3.4 instances), so the template id is what lets us split "seen-template new
instance" from "unseen template" — the measurement the knowledge-revisit theory needs.

We read the raw config that ships inside the installed webarena package, so there is
no separate config-generation step and no dependency on site URLs at load time.
"""
from __future__ import annotations

import json
from pathlib import Path


def _raw_config_text() -> str:
    # libwebarena is a namespace package (no __init__, __file__ is None), so read the
    # bundled config the way browsergym itself does — importlib.resources on the package.
    import importlib.resources as ir

    return ir.files("webarena").joinpath("test.raw.json").read_text()


def load_manifest(path: str) -> dict[int, bool]:
    """task_id -> mutating?, from the frozen classification (scripts/classify_wa_tasks.py).

    Statefulness is NOT derivable from the eval field, which is why this is a checked-in
    artefact rather than a heuristic evaluated at run time: `require_reset` is False for all
    812 upstream tasks, ~a quarter of program_html tasks only check "did you end up on a page
    containing X" (pure navigation), and a handful of pure string_match tasks do place orders.
    """
    import os

    p = Path(path)
    if not p.is_absolute():                 # resolve from the repo root, not the process cwd:
        root = Path(__file__).resolve().parents[3]   # src/hippo/wa/data.py -> repo root
        p = (root / path) if (root / path).exists() else p
    with open(p) as fh:
        blob = json.load(fh)
    m = {int(r["task_id"]): bool(r["mutating"]) for r in blob["tasks"]}
    # A short/stale manifest must not quietly shrink the denominator. Without this, a truncated
    # file made load_tasks return 0 tasks and the arm reported n=0, reward_sr=0.0 as a clean run.
    n_raw = len(json.loads(_raw_config_text()))
    if len(m) != n_raw:
        raise ValueError(f"task manifest {p} covers {len(m)} tasks but the benchmark has {n_raw}; "
                         "regenerate with scripts/classify_wa_tasks.py")
    return m


def load_tasks(cfg) -> list[dict]:
    """Rows: {task_id, sites, template_id, intent, eval_types, reference, mutating}.

    Selection is controlled by wa.task_filter:
      string_match — legacy: single-site AND eval_types == ["string_match"]. Reproduces the
                     230-task runs exactly (gitlab 43 / shopping 88 / shopping_admin 88 /
                     reddit 11); keep it to re-derive any earlier number.
      readonly     — single-site AND not mutating, per the frozen manifest. 434 tasks
                     (shopping 139 / map 109 / shopping_admin 109 / gitlab 67 / reddit 10):
                     +95 over legacy on sites already deployed, because url_match and
                     navigation-only program_html tasks change nothing server-side and were
                     being discarded for no reason — and it also drops the 12 genuinely
                     mutating tasks that legacy let through on an eval-type technicality.
      all          — every task for the site, mutating included. Only sound when each rollout
                     gets its own deployment (or the rollouts are serialised with a reset
                     between them): 8 concurrent rollouts share one server, one account and
                     therefore one copy of whatever the grader reads, so a mutating task
                     cannot yield 8 independent rewards.

    Ordered by task_id, the canonical stream order (memory accumulates along it)."""
    wa = cfg.get("wa", {}) or {}
    raw = json.loads(_raw_config_text())
    site = str(wa.get("site", "shopping"))
    mode = str(wa.get("task_filter", "") or "").strip().lower()
    if not mode:                       # legacy flag, kept so old commands still mean the same
        mode = "string_match" if bool(wa.get("readonly_only", False)) else "all"
    if mode not in ("string_match", "readonly", "all"):
        raise ValueError(f"wa.task_filter must be string_match|readonly|all, got {mode!r}")
    # Always load it, in every mode. The statefulness flag is not only a filter — the runner
    # refuses to fan mutating tasks out over a shared deployment, and that guard reads this field.
    # Loading it only for mode=="readonly" left `mutating` None under task_filter=all, so the guard
    # counted zero mutating tasks and never fired: a safety check that is silently absent exactly
    # when it is needed.
    mutating = load_manifest(str(wa.get("task_manifest", "config/wa_task_class.json")))
    rows = []
    for r in raw:
        if r.get("sites") != [site]:
            continue
        tid = int(r["task_id"])
        etypes = r.get("eval", {}).get("eval_types", [])
        if mode == "string_match" and etypes != ["string_match"]:
            continue
        if mode == "readonly" and mutating.get(tid, True):
            continue
        rows.append({"task_id": tid, "sites": r["sites"],
                     "template_id": int(r.get("intent_template_id", -1)),
                     "intent": r.get("intent", ""),
                     "eval_types": etypes,
                     # whether finishing this task writes to the server — drives rollout
                     # scheduling (a mutating task must not fan out onto a shared deployment)
                     "mutating": bool(mutating.get(tid)),
                     # reference answer(s) for the LEARNING signal only (judge/reflect see it
                     # AFTER the rollout); the agent never gets it while solving.
                     "reference": r.get("eval", {}).get("reference_answers", {}),
                     "requires_login": bool(r.get("require_login", False))})
    rows.sort(key=lambda r: r["task_id"])
    if flt := int(wa.get("limit", 0) or 0):
        rows = rows[:flt]
    # shard "i/n": round-robin partition for parallel READONLY runs (each shard is a
    # separate process with its own Playwright browser; readonly tasks don't mutate server
    # state so concurrent shards on the same site don't interfere). Round-robin (not
    # contiguous) balances template families/difficulty across shards. Streaming/withmem
    # must NOT be sharded — its memory accumulates across tasks in order.
    shard = str(wa.get("shard", "") or "")
    if shard and "/" in shard:
        i, n = (int(x) for x in shard.split("/"))
        rows = [r for j, r in enumerate(rows) if j % n == i]
    return rows


def set_site_env(cfg) -> None:
    """Point BrowserGym at our self-hosted sites. Must run before gym.make."""
    import os

    wa = cfg.get("wa", {}) or {}
    base = str(wa.get("base_url", "")).rstrip("/")
    if not base:
        raise ValueError("wa.base_url is required (e.g. http://10.44.12.29)")
    mapping = {"WA_SHOPPING": f"{base}:7770",
               "WA_SHOPPING_ADMIN": f"{base}:7780/admin",
               "WA_REDDIT": f"{base}:9999",
               "WA_GITLAB": f"{base}:8023",
               "WA_WIKIPEDIA": f"{base}:8888/wikipedia_en_all_maxi_2022-05/A/User:The_other_Kiwix_guy/Landing",
               "WA_MAP": f"{base}:3000",
               "WA_HOMEPAGE": f"{base}:4399"}
    for k, v in mapping.items():
        # ASSIGN, never setdefault. A spawned worker inherits the parent's environment, and the
        # parent has already called this function with ITS base_url — so setdefault made every
        # per-worker override a no-op and all N rollouts silently shared one deployment while the
        # log claimed 8. Nothing downstream could detect it: agent and grader in a worker were
        # primed from the same wrong value, so the rewards looked entirely plausible.
        os.environ[k] = v
        # webarena's env_config.py reads the BARE names (REDDIT, SHOPPING, ...) at import
        # time; browsergym normally copies WA_* -> bare, but if we import webarena directly
        # (e.g. to patch the grader) that hasn't run yet, so set both.
        os.environ[k.removeprefix("WA_")] = v
    if reset := wa.get("reset_url"):
        os.environ.setdefault("WA_FULL_RESET", str(reset))   # env may legitimately override


def assert_site_env(cfg) -> None:
    """Fail loudly if this process is not actually pointed at the deployment it was given.

    The bug this guards against was invisible by construction, so the check has to be explicit:
    verify the value webarena will really use, after imports have frozen it."""
    import os

    base = str((cfg.get("wa", {}) or {}).get("base_url", "")).rstrip("/")
    for name in ("SHOPPING", "SHOPPING_ADMIN", "REDDIT", "GITLAB"):
        got = os.environ.get(name, "")
        if not got.startswith(base):
            raise RuntimeError(f"deployment mismatch: {name}={got!r} does not belong to {base!r} — "
                               "this worker would run against the wrong WebArena box")
