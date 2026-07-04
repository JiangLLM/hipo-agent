"""Thin litellm wrapper: disk cache (by prompt hash), budget guard, retry, throttle.

Caching makes runs cheap and reproducible. The budget guard hard-stops a run before
it can burn more than `budget_usd`. All real LLM access goes through here.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from typing import Any

from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)


class BudgetExceeded(RuntimeError):
    pass


class LLMClient:
    def __init__(
        self,
        model: str,
        embed_model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        cache: bool = True,
        cache_dir: str = ".cache",
        budget_usd: float = 5.0,
        min_interval: float = 0.0,
    ):
        self.model = model
        self.embed_model = embed_model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.cache = cache
        self.cache_dir = cache_dir
        self.budget_usd = budget_usd
        self.min_interval = min_interval
        self.spent_usd = 0.0
        self.calls = 0
        self._lock = threading.Lock()
        self._last_call = 0.0
        if cache:
            os.makedirs(os.path.join(cache_dir, "chat"), exist_ok=True)
            os.makedirs(os.path.join(cache_dir, "embed"), exist_ok=True)

    # -- internals -----------------------------------------------------------
    def _key(self, payload: dict) -> str:
        blob = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()

    def _cache_get(self, sub: str, key: str) -> Any | None:
        if not self.cache:
            return None
        path = os.path.join(self.cache_dir, sub, key + ".json")
        if os.path.exists(path):
            with open(path) as fh:
                return json.load(fh)
        return None

    def _cache_put(self, sub: str, key: str, value: Any) -> None:
        if not self.cache:
            return
        path = os.path.join(self.cache_dir, sub, key + ".json")
        with open(path, "w") as fh:
            json.dump(value, fh)

    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            wait = self.min_interval - (time.time() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.time()

    def _charge(self, response: Any) -> None:
        try:
            import litellm

            cost = litellm.completion_cost(completion_response=response) or 0.0
        except Exception:
            cost = 0.0
        with self._lock:
            self.spent_usd += cost
            self.calls += 1
            if self.spent_usd > self.budget_usd:
                raise BudgetExceeded(f"spent ${self.spent_usd:.4f} > budget ${self.budget_usd}")

    # -- public --------------------------------------------------------------
    def chat(self, messages: list[dict], temperature: float | None = None, **kw: Any) -> str:
        temp = self.temperature if temperature is None else temperature
        payload = {"model": self.model, "messages": messages, "temperature": temp,
                   "max_tokens": self.max_tokens, **kw}
        # Only cache deterministic calls; temperature>0 should vary across trajectories.
        cacheable = temp == 0.0
        key = self._key(payload)
        if cacheable:
            hit = self._cache_get("chat", key)
            if hit is not None:
                return hit
        text = self._call_chat(payload)
        if cacheable:
            self._cache_put("chat", key, text)
        return text

    @retry(retry=retry_if_not_exception_type(BudgetExceeded),
           stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=1, max=30))
    def _call_chat(self, payload: dict) -> str:
        import litellm

        self._throttle()
        resp = litellm.completion(**payload)
        self._charge(resp)
        return resp["choices"][0]["message"]["content"] or ""

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = [None] * len(texts)  # type: ignore[list-item]
        todo: list[tuple[int, str]] = []
        for i, t in enumerate(texts):
            key = self._key({"model": self.embed_model, "input": t})
            hit = self._cache_get("embed", key)
            if hit is not None:
                out[i] = hit
            else:
                todo.append((i, t))
        if todo:
            vectors = self._call_embed([t for _, t in todo])
            for (i, t), vec in zip(todo, vectors):
                out[i] = vec
                self._cache_put("embed", self._key({"model": self.embed_model, "input": t}), vec)
        return out  # type: ignore[return-value]

    @retry(retry=retry_if_not_exception_type(BudgetExceeded),
           stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=1, max=30))
    def _call_embed(self, texts: list[str]) -> list[list[float]]:
        import litellm

        self._throttle()
        resp = litellm.embedding(model=self.embed_model, input=texts)
        return [d["embedding"] for d in resp["data"]]
