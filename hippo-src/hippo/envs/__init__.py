from .base import BaseEnv  # noqa: F401


def make_env(name: str, cfg):
    if name == "mock":
        from .mock import MockEnv

        return MockEnv(cfg)
    if name == "jsonl":
        from .jsonl import JsonlEnv

        return JsonlEnv(cfg)
    raise ValueError(f"unknown env: {name!r} (available: mock, jsonl)")
