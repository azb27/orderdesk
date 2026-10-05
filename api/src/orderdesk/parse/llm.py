"""A thin, testable wrapper around the Messages API: forced tool calls, cost accounting, a disk cache.

The cache key is the full request, so an eval re-run with unchanged prompts costs nothing and returns the
same answers, and any prompt change misses the cache. Tests inject a scripted fake instead of a client.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import anthropic

from orderdesk import config

PRICES = {  # USD per million tokens (platform.claude.com pricing, checked 2026-09-24)
    "claude-sonnet-5": {"input": 2.0, "output": 10.0, "cache_write": 2.5, "cache_read": 0.20},
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0, "cache_write": 1.25, "cache_read": 0.10},
    "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_write": 5.0, "cache_read": 0.20},
}
CACHE_DIR = config.RUNS / "llm_cache"


class ToolModel(Protocol):
    model: str

    def call(self, system: str, content: list[dict], tool: dict) -> tuple[dict, dict]:
        """Return (tool input, usage dict with input/output/cache_write/cache_read tokens and cost_usd)."""
        ...


@dataclass
class Meter:
    calls: int = 0
    cost_usd: float = 0.0
    seconds: float = 0.0
    cached: int = 0
    tokens: dict = field(default_factory=lambda: {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0})

    def add(self, usage: dict) -> None:
        self.calls += 1
        self.cost_usd += usage.get("cost_usd", 0.0)
        self.seconds += usage.get("seconds", 0.0)
        self.cached += int(usage.get("from_cache", False))
        for k in self.tokens:
            self.tokens[k] += usage.get(k, 0)


def cost(model: str, u: dict) -> float:
    p = PRICES[model]
    return sum(u.get(k, 0) * p[k] for k in p) / 1e6


class Claude:
    """Forced single-tool call. Raises on API failure; callers decide what a failure means."""

    def __init__(
        self, model: str | None = None, cache: bool = True, max_tokens: int = 4000, timeout: float = 60.0
    ):
        self.model = model or config.MODEL
        if self.model not in PRICES:
            raise ValueError(f"no price for {self.model}; add it to parse/llm.py")
        self.client = anthropic.Anthropic(max_retries=3, timeout=timeout)
        self.cache = cache and os.environ.get("ORDERDESK_LLM_CACHE", "1") == "1"
        self.max_tokens = max_tokens

    def call(self, system: str, content: list[dict], tool: dict) -> tuple[dict, dict]:
        req = {"model": self.model, "max_tokens": self.max_tokens, "system": system, "tools": [tool],
               "tool_choice": {"type": "tool", "name": tool["name"]}, "messages": [{"role": "user", "content": content}]}  # fmt: skip
        key = hashlib.sha256(json.dumps(req, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        path: Path = CACHE_DIR / key[:2] / f"{key}.json"
        if self.cache and path.exists():
            hit = json.loads(path.read_text())
            return hit["input"], {**hit["usage"], "from_cache": True, "cost_usd": 0.0, "seconds": 0.0}
        t0 = time.perf_counter()
        resp = self.client.messages.create(
            **{**req, "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]}
        )
        block = next(b for b in resp.content if getattr(b, "type", "") == "tool_use")
        u = resp.usage
        usage = {"input": u.input_tokens or 0, "output": u.output_tokens or 0,
                 "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
                 "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0}  # fmt: skip
        usage["cost_usd"] = cost(self.model, usage)
        usage["seconds"] = round(time.perf_counter() - t0, 3)
        if self.cache:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"input": block.input, "usage": usage}, ensure_ascii=False))
        return dict(block.input), usage


class Scripted:
    """A fake model for tests: returns queued tool inputs and records what it was asked."""

    def __init__(self, replies: list[dict], model: str = "scripted"):
        self.model = model
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    def call(self, system: str, content: list[dict], tool: dict) -> tuple[dict, dict]:
        self.requests.append({"system": system, "content": content, "tool": tool})
        return self.replies.pop(0), {"input": 0, "output": 0, "cost_usd": 0.0, "seconds": 0.0}
