"""Metrics over the task stream."""
from __future__ import annotations

import csv
import os


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    if n == 0:
        return {"n": 0}
    sr1 = sum(r["pass1"] for r in rows) / n
    srk = sum(r["passk"] for r in rows) / n
    by_type: dict[str, list[dict]] = {}
    for r in rows:
        by_type.setdefault(r["task_type"], []).append(r)
    type_sr = {t: round(sum(x["pass1"] for x in rs) / len(rs), 3) for t, rs in by_type.items()}

    # learning curve: cumulative pass@1 over the stream, plus first/second half
    half = n // 2
    first = sum(r["pass1"] for r in rows[:half]) / max(half, 1)
    second = sum(r["pass1"] for r in rows[half:]) / max(n - half, 1)
    return {
        "n": n,
        "sr_pass1": round(sr1, 3),
        "sr_passk": round(srk, 3),
        "sr_by_type": type_sr,
        "sr_first_half": round(first, 3),
        "sr_second_half": round(second, 3),
        "learning_delta": round(second - first, 3),
        "writes": sum(r["wrote"] for r in rows),
    }


def write_csv(path: str, rows: list[dict]) -> None:
    if not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cols = list(rows[0].keys())
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
