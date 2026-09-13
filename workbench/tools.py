"""The one door from an agent to a tool: allow-lists enforced, every call logged, lifecycle events.

Agents differ in authority, not just in prompt (docs/WHOLE_PICTURE.md §3). Each
agent's `tools` list in workbench/agents.yaml is the only set of tools it may
reach, and this module is where that is enforced:

    with tools.acting("rules_engine", emit) as act:
        decision = tools.call("apply_rules", ev=evidence)

  - Whoever starts a piece of work says which agent does it (`acting`); the code
    doing the work names only the tool. A call made while no agent is acting is
    refused.
  - A tool outside the acting agent's list is refused: ToolNotAllowed is raised,
    and the refusal is written to the hash-chained log and emitted.
  - Every call is logged with the agent, the tool, the argument names, how long
    it took and whether it raised -- never the argument values, which can be
    whole scanned pages.
  - Lifecycle events tagged with the agent's id -- started, completed, failed
    (the GitHub Copilot SDK's idea, §10a) -- go to the same log and to `emit`.

Model calls are not tools: they go through agents.chat with the agent's own
settings, and the Router picks the model.
"""

from __future__ import annotations

import importlib
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Callable, Iterator

from mcp_servers.audit import LOG_DIR, AuditLog
from workbench import agents


class ToolNotAllowed(PermissionError):
    """An agent asked for a tool its definition does not list."""


def _lazy(module: str, name: str) -> Callable:
    """A tool that imports its module on first use, so importing this file stays cheap."""
    def call(**kwargs):
        return getattr(importlib.import_module(module), name)(**kwargs)
    call.__qualname__ = f"{module}.{name}"
    return call


def _read_pages(work_dir: Path, doc_id: str | None = None, quality: str | None = None,
                files: list[Path] | None = None):
    """A document's pages: the given files (one PDF, or the page images of one report), else the corpus report."""
    from workbench import pagesource, scan_reader
    if files:
        paths = [Path(p) for p in files]
        return (pagesource.open_document(paths[0], work_dir) if paths[0].suffix.lower() == ".pdf"
                else pagesource.open_pages(paths, work_dir))
    return scan_reader.corpus_pages(doc_id, quality, work_dir)


def _stamp_note(ev, decision, summary, run: dict, out: Path, qa_results: list):
    """Stamp read-back results into a note -- only results that all passed. The QA Checker writes nothing else."""
    from workbench import report_writer
    if not qa_results or not all(ok for _, ok, _ in qa_results):
        raise ValueError("a note is stamped only with read-back checks that all passed")
    return report_writer.render(ev, decision, summary, run, out, qa_results=qa_results)


# Every tool that exists. Which agent may use which: its `tools` list in agents.yaml.
TOOLS: dict[str, Callable] = {
    "read_pages": _read_pages,
    "build_evidence": _lazy("workbench.scan_reader", "build_evidence"),
    "ground_truth_stand_in": _lazy("workbench.evidence", "from_ground_truth"),
    "apply_rules": _lazy("workbench.rules", "evaluate"),
    "write_note": _lazy("workbench.report_writer", "render"),
    "read_back_note": _lazy("workbench.report_writer", "verify"),
    "stamp_note": _stamp_note,
    "search_library": _lazy("workbench.library", "search"),
    "sandbox": _lazy("workbench.sandbox", "run"),
}

_ACTING: ContextVar[tuple[str, Callable | None] | None] = ContextVar("acting_agent", default=None)
_LOG: AuditLog | None = None
_LOG_LOCK = threading.Lock()


def _log() -> AuditLog:
    """One writer per process for logs/agents.jsonl (see run_inspection._audit)."""
    global _LOG
    with _LOG_LOCK:
        if _LOG is None:
            _LOG = AuditLog("agents", LOG_DIR / "agents.jsonl")
        return _LOG


def _send(emit: Callable[[dict], None] | None, event: dict) -> None:
    if emit is None:
        return
    try:
        emit(event)
    except Exception:  # a broken viewer never breaks the agent it is watching
        pass


def _plain(tags: dict) -> dict:
    return {k: v if isinstance(v, (str, int, float, bool, type(None))) else str(v) for k, v in tags.items()}


def current_agent() -> str | None:
    acting = _ACTING.get()
    return acting[0] if acting else None


class Act:
    """Given to the body of `acting`: `fail(reason)` records the work as failed without raising."""

    def __init__(self) -> None:
        self.failure: str | None = None

    def fail(self, reason: str) -> None:
        self.failure = reason


@contextmanager
def acting(agent_id: str, emit: Callable[[dict], None] | None = None, **tags) -> Iterator[Act]:
    """Run the body as `agent_id`: its tool list applies, and its lifecycle is logged and emitted."""
    try:
        agents.definition(agent_id)
    except KeyError:
        raise ValueError(f"no agent {agent_id!r} in workbench/agents.yaml") from None
    act, t0 = Act(), time.monotonic()
    tags = _plain(tags)

    def lifecycle(phase: str, **extra) -> None:
        facts = {"agent_id": agent_id, "phase": phase, **tags, **_plain(extra)}
        _log().write({"event": f"agent_{phase}", **facts})
        _send(emit, {"type": "agent", **facts})

    token = _ACTING.set((agent_id, emit))
    lifecycle("started")
    try:
        yield act
    except Exception as e:
        lifecycle("failed", error=f"{type(e).__name__}: {e}", seconds=round(time.monotonic() - t0, 2))
        raise
    else:
        seconds = round(time.monotonic() - t0, 2)
        if act.failure is not None:
            lifecycle("failed", reason=act.failure, seconds=seconds)
        else:
            lifecycle("completed", seconds=seconds)
    finally:
        _ACTING.reset(token)


def call(tool: str, /, **kwargs):
    """Call `tool` as the acting agent. Refused -- raised, logged, emitted -- unless its list names the tool."""
    acting_now = _ACTING.get()
    agent_id, emit = acting_now if acting_now else (None, None)
    allowed = list(agents.definition(agent_id).get("tools") or []) if agent_id else []
    if agent_id is None or tool not in allowed or tool not in TOOLS:
        reason = ("no agent is acting" if agent_id is None
                  else f"{agent_id} may use only: {', '.join(allowed) or 'no tools'}" if tool not in allowed
                  else f"{tool} is listed for {agent_id} but the workbench has no such tool")
        _log().write({"event": "tool_refused", "agent_id": agent_id, "tool": tool, "allowed": allowed,
                      "reason": reason})
        _send(emit, {"type": "tool", "agent_id": agent_id, "tool": tool, "status": "refused", "reason": reason})
        raise ToolNotAllowed(f"{tool} refused: {reason}")

    def record(status: str, **extra) -> None:
        facts = {"agent_id": agent_id, "tool": tool, "status": status, "arguments": sorted(kwargs),
                 "seconds": round(time.monotonic() - t0, 2), **extra}
        _log().write({"event": "tool_call", **facts})
        _send(emit, {"type": "tool", **facts})

    t0 = time.monotonic()
    try:
        result = TOOLS[tool](**kwargs)
    except Exception as e:
        record("error", error=f"{type(e).__name__}: {e}")
        raise
    record("ok")
    return result
