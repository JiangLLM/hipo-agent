"""SWE-bench instance loading + Epoch AI arm64 image resolution.

We run agent rollouts inside Epoch AI's rebuilt per-instance images
(ghcr.io/epoch-research, MIT) because the official swebench images are x86_64-only
and this machine is Apple Silicon. arm64 coverage is 420/500 on Verified (missing
images cluster in matplotlib / xarray / scikit-learn, which need compiled wheels);
`ensure_image` lets the runner skip uncovered instances instead of crashing.
"""
from __future__ import annotations

import re
import subprocess

DATASET_DEFAULT = "princeton-nlp/SWE-bench_Verified"
EPOCH_REGISTRY = "ghcr.io/epoch-research/swe-bench.eval"


def load_instances(cfg) -> list[dict]:
    """Load + filter instances. Stream order = sorted instance_id, which groups by
    repo and is roughly chronological within a repo — what a memory stream wants."""
    from datasets import load_dataset

    swe = cfg.get("swe", {}) or {}
    ds = load_dataset(swe.get("dataset", DATASET_DEFAULT), split=swe.get("split", "test"))
    instances = sorted(ds, key=lambda i: i["instance_id"])
    repos = str(swe.get("repos", "") or "")
    if repos:
        keys = [r.strip() for r in repos.split(",") if r.strip()]
        instances = [i for i in instances if any(k in i["repo"] for k in keys)]
    if flt := str(swe.get("filter", "") or ""):
        instances = [i for i in instances if re.match(flt, i["instance_id"])]
    if int(swe.get("limit", 0) or 0):
        instances = instances[: int(swe["limit"])]
    return instances


def image_name(instance: dict, arch: str = "arm64") -> str:
    return f"{EPOCH_REGISTRY}.{arch}.{instance['instance_id']}:latest".lower()


def ensure_image(name: str, pull_timeout: int = 1800, retries: int = 3) -> bool:
    """Pull `name` unless present. Pre-pulling (once, before the N parallel attempts
    start containers) avoids N racing pulls; returns False when the image doesn't
    exist for this arch so the caller can skip the instance. Network hiccups during
    the pull are retried, then reported as False — never raised (a flaky pull must
    not kill a 30-hour campaign)."""
    import time

    have = subprocess.run(["docker", "image", "inspect", name],
                          capture_output=True, text=True)
    if have.returncode == 0:
        return True
    for i in range(retries):
        try:
            pulled = subprocess.run(["docker", "pull", "-q", name],
                                    capture_output=True, text=True, timeout=pull_timeout)
            if pulled.returncode == 0:
                return True
            if "not found" in (pulled.stderr or "").lower():
                return False                     # image truly absent — don't retry
        except Exception:  # noqa: BLE001 - timeout/daemon hiccup
            pass
        time.sleep(30 * (i + 1))
    return False
