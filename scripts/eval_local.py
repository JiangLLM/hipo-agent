"""Local ground-truth evaluation on Apple Silicon.

Bridges two things the official stack doesn't connect: swebench's harness always
keys images as x86_64 (and forces the container platform to match), while Epoch AI
publishes prebuilt arm64 per-instance images under its own registry name. We build
TestSpecs with arch="arm64" (so the platform is linux/arm64/v8), retag the pulled
Epoch image to the exact local name the spec expects, and hand everything to the
UNMODIFIED official `run_instance` — patch apply, eval script, grading and report
files are all stock swebench.

    .venv/bin/python scripts/eval_local.py runs/<run>/preds_nomem.json --run-id calib_local
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import docker
from datasets import load_dataset
from swebench.harness.run_evaluation import run_instance
from swebench.harness.test_spec.test_spec import make_test_spec

EPOCH = "ghcr.io/epoch-research/swe-bench.eval.arm64.{iid}:latest"


def ensure_retagged(iid: str, spec) -> bool:
    """Tag the Epoch image as BOTH the instance image and the env image the spec
    expects. The env tag only satisfies build_instance_image's existence check
    (which unfortunately runs before its own skip-if-instance-exists check); with
    the instance image present, nothing is ever built FROM the env tag."""
    src = EPOCH.format(iid=iid).lower()
    if subprocess.run(["docker", "image", "inspect", src], capture_output=True).returncode != 0:
        if subprocess.run(["docker", "pull", "-q", src], capture_output=True,
                          timeout=1800).returncode != 0:
            return False
    for key in (spec.instance_image_key, spec.env_image_key):
        if subprocess.run(["docker", "image", "inspect", key], capture_output=True).returncode != 0:
            if subprocess.run(["docker", "tag", src, key], capture_output=True).returncode != 0:
                return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("preds", help="preds_*.json produced by hippo.swe.run")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--timeout", type=int, default=1200)
    args = ap.parse_args()

    preds = json.loads(Path(args.preds).read_text())
    nonempty = {k: v for k, v in preds.items() if v.get("model_patch", "").strip()}
    empty = sorted(set(preds) - set(nonempty))
    print(f"{len(nonempty)} non-empty patches ({len(empty)} empty -> unresolved by definition)")

    ds = {r["instance_id"]: r for r in load_dataset("princeton-nlp/SWE-bench_Verified", split="test")}
    client = docker.from_env()
    results = {}
    for i, (iid, pred) in enumerate(sorted(nonempty.items())):
        spec = make_test_spec(ds[iid], arch="arm64")
        if not ensure_retagged(iid, spec):
            print(f"[{i + 1}/{len(nonempty)}] {iid}: NO IMAGE, skipped")
            results[iid] = None
            continue
        try:
            out = run_instance(spec, pred, rm_image=False, force_rebuild=False,
                               client=client, run_id=args.run_id, timeout=args.timeout)
            resolved = bool(out and out.get("resolved", False))
        except Exception as exc:  # noqa: BLE001
            print(f"[{i + 1}/{len(nonempty)}] {iid}: EVAL ERROR {type(exc).__name__}: {exc}")
            results[iid] = None
            continue
        results[iid] = resolved
        print(f"[{i + 1}/{len(nonempty)}] {iid}: {'RESOLVED' if resolved else 'unresolved'}")

    for iid in empty:
        results[iid] = False
    n_eval = sum(1 for v in results.values() if v is not None)
    n_res = sum(1 for v in results.values() if v)
    print(f"\nRESOLVED {n_res}/{n_eval} evaluated ({len(results) - n_eval} skipped/errored)")
    out_path = Path(args.preds).with_name(f"gt_{args.run_id}.json")
    out_path.write_text(json.dumps(results, indent=2))
    print(f"saved {out_path}")


if __name__ == "__main__":
    sys.exit(main())
