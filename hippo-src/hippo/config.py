"""Config loading: YAML + dotted CLI overrides.

Usage: `python -m hippo.run --mock --surprise.source store_all --agent.n_traj 3`
Any `--a.b value` overrides `config/default.yaml` key `a.b`. A bare `--flag`
(no following value) is treated as boolean true; `--mock` maps to `run.mock`.
"""
from __future__ import annotations

import os
from typing import Any

import yaml

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config", "default.yaml")


class DotDict(dict):
    """dict with recursive attribute access (read-mostly)."""

    def __getattr__(self, key: str) -> Any:
        try:
            val = self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc
        return DotDict(val) if isinstance(val, dict) else val

    __setattr__ = dict.__setitem__  # type: ignore[assignment]


def _coerce(val: str) -> Any:
    if not isinstance(val, str):
        return val
    low = val.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("none", "null"):
        return None
    for cast in (int, float):
        try:
            return cast(val)
        except ValueError:
            continue
    return val


def _set_dotted(d: dict, dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = d
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
        if not isinstance(cur, dict):  # pragma: no cover - defensive
            raise ValueError(f"cannot set {dotted}: {p} is not a mapping")
    cur[parts[-1]] = value


def parse_overrides(argv: list[str]) -> dict[str, Any]:
    over: dict[str, Any] = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            key = a[2:]
            if key == "mock":
                _set_dotted(over, "run.mock", True)
                i += 1
                continue
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                _set_dotted(over, key, _coerce(argv[i + 1]))
                i += 2
            else:
                _set_dotted(over, key, True)
                i += 1
        else:
            i += 1
    return over


def _deep_update(base: dict, extra: dict) -> dict:
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v
    return base


def load_config(argv: list[str] | None = None, path: str | None = None) -> DotDict:
    path = path or _DEFAULT_PATH
    with open(path, "r") as fh:
        raw = yaml.safe_load(fh) or {}
    raw.setdefault("run", {}).setdefault("mock", False)
    if argv:
        _deep_update(raw, parse_overrides(argv))
    return DotDict(raw)
