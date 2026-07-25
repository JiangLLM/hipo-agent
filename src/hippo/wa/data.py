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


def _raw_config_text() -> str:
    # libwebarena is a namespace package (no __init__, __file__ is None), so read the
    # bundled config the way browsergym itself does — importlib.resources on the package.
    import importlib.resources as ir

    return ir.files("webarena").joinpath("test.raw.json").read_text()


def load_tasks(cfg) -> list[dict]:
    """Rows: {task_id, sites, template_id, intent, requires_login}. Filtered by
    wa.site (single-site tasks only — cross-site tasks confound the site-scoped
    memory design), ordered by task_id (the canonical stream order)."""
    wa = cfg.get("wa", {}) or {}
    raw = json.loads(_raw_config_text())
    site = str(wa.get("site", "shopping"))
    # readonly_only: keep only pure string_match tasks (info-seeking, no server-side
    # mutation). Avoids (a) N-rollout state pollution, (b) idempotency bugs when a learned
    # "click Create" replays on an already-created object, (c) the flaky program_html evals.
    readonly = bool(wa.get("readonly_only", False))
    rows = []
    for r in raw:
        if r.get("sites") != [site]:
            continue
        etypes = r.get("eval", {}).get("eval_types", [])
        if readonly and etypes != ["string_match"]:
            continue
        rows.append({"task_id": int(r["task_id"]), "sites": r["sites"],
                     "template_id": int(r.get("intent_template_id", -1)),
                     "intent": r.get("intent", ""),
                     "eval_types": etypes,
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
        os.environ.setdefault(k, v)
        # webarena's env_config.py reads the BARE names (REDDIT, SHOPPING, ...) at import
        # time; browsergym normally copies WA_* -> bare, but if we import webarena directly
        # (e.g. to patch the grader) that hasn't run yet, so set both.
        os.environ.setdefault(k.removeprefix("WA_"), v)
    if reset := wa.get("reset_url"):
        os.environ.setdefault("WA_FULL_RESET", str(reset))
