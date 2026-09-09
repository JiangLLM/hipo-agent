"""Structured JSONL logging + per-run directory management.

Every meaningful event is one JSON line keyed by run/task/traj/step so we can
reconstruct exactly what was retrieved, why something was (not) written, and what
it cost — which is what we need for post-hoc A/B analysis.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import asdict, is_dataclass
from typing import Any


def _default(o: Any) -> Any:
    if is_dataclass(o) and not isinstance(o, type):
        d = asdict(o)
        d.pop("embedding", None)   # don't dump raw vectors into the log
        return d
    return str(o)


class RunLogger:
    def __init__(self, out_dir: str, run_name: str, level: str = "info", jsonl: bool = True):
        ts = time.strftime("%Y%m%d_%H%M%S")
        self.run_id = f"{run_name}_{ts}"
        self.dir = os.path.join(out_dir, self.run_id)
        os.makedirs(self.dir, exist_ok=True)
        self.jsonl_enabled = jsonl
        self._fh = open(os.path.join(self.dir, "events.jsonl"), "a") if jsonl else None
        self._levels = {"debug": 10, "info": 20, "warn": 30, "error": 40}
        self._min = self._levels.get(level, 20)
        self._lock = threading.Lock()   # events may be emitted from worker threads

    def event(self, kind: str, **fields: Any) -> None:
        if not self.jsonl_enabled or self._fh is None:
            return
        rec = {"t": round(time.time(), 3), "run_id": self.run_id, "kind": kind, **fields}
        line = json.dumps(rec, default=_default) + "\n"
        with self._lock:
            self._fh.write(line)
            self._fh.flush()

    def log(self, level: str, msg: str) -> None:
        if self._levels.get(level, 20) >= self._min:
            print(f"[{level}] {msg}", file=sys.stderr)

    def info(self, msg: str) -> None:
        self.log("info", msg)

    def warn(self, msg: str) -> None:
        self.log("warn", msg)

    def save_json(self, name: str, obj: Any) -> str:
        path = os.path.join(self.dir, name)
        with open(path, "w") as fh:
            json.dump(obj, fh, indent=2, default=_default)
        return path

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
