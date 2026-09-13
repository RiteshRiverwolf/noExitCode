"""Agent definitions, and the one way an agent's model is called.

What each agent is -- purpose, tool list, Router task, budgets, instructions,
messages, output shape -- lives in workbench/agents.yaml. Which models exist,
which server serves each and at what address: workbench/models.yaml, reached
through the Router. Nothing in this file names a model or an address.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import httpx
import yaml

from workbench import router

AGENTS = Path(__file__).resolve().parent / "agents.yaml"


@lru_cache(maxsize=None)
def _all() -> dict:
    return yaml.safe_load(AGENTS.read_text(encoding="utf-8"))


def definition(name: str) -> dict:
    return _all()[name]


def chat(model: str, messages: list[dict], agent: str, **extra) -> httpx.Response:
    """One chat call to `model` with `agent`'s options and timeout, on the server models.yaml names for it.

    `extra` goes into the request as is (a JSON schema as `format`, `think`).
    Only the Ollama chat API is spoken so far; a model on any other server
    raises NotImplementedError rather than being sent to the wrong address.
    """
    d = definition(agent)
    registry, _ = router.load_registry()
    served_by = registry["models"][model]["served_by"]
    if served_by != "ollama":
        raise NotImplementedError(f"{model} is served by {served_by}; only the Ollama chat API is implemented")
    return httpx.post(f"{router.endpoint(model, registry)}/api/chat", timeout=d["timeout_seconds"],
                      json={"model": model, "messages": messages, "stream": False, "options": d["options"], **extra})
