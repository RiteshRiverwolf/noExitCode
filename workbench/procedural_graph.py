"""Runs a procedural graph: enforces its transitions, budgets retries, records the path.

Each stage is a Python function taking the run context and returning a
StageResult ("ok" or "fail"). The runner:
  - allows only transitions that exist in the graph file;
  - retries a failing stage up to its max_attempts, then follows its
    `when: exhausted` edge (usually to needs_review);
  - follows `when: fail` edges from checks back to the stage that caused the
    failure -- the bounded self-healing loop;
  - stops after `step_budget` steps whatever happens;
  - gives each stage the guidance and pitfalls from its outgoing edges;
  - records every step in a trace that goes into the note and the run folder.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml


@dataclass
class StageResult:
    status: str             # "ok" | "fail"
    note: str = ""


@dataclass
class Step:
    node: str
    agent: str
    attempt: int
    status: str
    note: str
    seconds: float
    next: str | None = None


@dataclass
class Graph:
    name: str
    version: int
    start: str
    step_budget: int
    nodes: dict
    edges: list[dict]
    path: Path

    @classmethod
    def load(cls, path: Path) -> "Graph":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        g = cls(data["graph"], data["version"], data["start"], data.get("step_budget", 20),
                data["nodes"], data["edges"], Path(path))
        for e in g.edges:
            if e["from"] not in g.nodes or e["to"] not in g.nodes:
                raise ValueError(f"edge {e['from']} -> {e['to']} names an unknown node")
            if e.get("when") not in ("ok", "fail", "exhausted"):
                raise ValueError(f"edge {e['from']} -> {e['to']} needs when: ok | fail | exhausted")
        return g

    def edge(self, node: str, on: str) -> dict | None:
        matches = [e for e in self.edges if e["from"] == node and e.get("when") == on]
        if len(matches) > 1:
            raise ValueError(f"graph is ambiguous: {len(matches)} '{on}' edges leave {node}")
        return matches[0] if matches else None

    def guidance(self, node: str) -> str:
        """The notes on a node's outgoing edges, as text for a model's instructions."""
        lines = []
        for e in self.edges:
            if e["from"] == node:
                for key in ("condition", "guidance", "pitfalls"):
                    if e.get(key):
                        lines.append(f"{key.capitalize()}: {e[key]}")
        return "\n".join(lines)


@dataclass
class RunResult:
    end: str
    trace: list[Step] = field(default_factory=list)


def run(graph: Graph, handlers: dict[str, Callable[[dict], StageResult]], ctx: dict,
        on_step: Callable[[Step], None] | None = None) -> RunResult:
    missing = [n for n, spec in graph.nodes.items() if spec["kind"] != "end" and n not in handlers]
    if missing:
        raise ValueError(f"no handler for: {', '.join(missing)}")

    result = RunResult(end="needs_review")
    attempts: dict[str, int] = {}
    node = graph.start
    for _ in range(graph.step_budget):
        spec = graph.nodes[node]
        if spec["kind"] == "end":
            result.end = node
            return result
        attempts[node] = attempts.get(node, 0) + 1
        ctx["guidance"] = graph.guidance(node)
        ctx["attempt"] = attempts[node]
        t0 = time.monotonic()
        try:
            outcome = handlers[node](ctx)
        except Exception as e:  # a crashing stage is a failed attempt, not a crashed run
            outcome = StageResult("fail", f"{type(e).__name__}: {e}")
        step = Step(node, spec.get("agent", ""), attempts[node], outcome.status, outcome.note,
                    round(time.monotonic() - t0, 2))

        if outcome.status == "ok":
            e = graph.edge(node, "ok")
        else:
            e = graph.edge(node, "fail")          # a check sends the work back to its cause
            if e is None:                          # a stage retries itself, within budget
                if attempts[node] < spec.get("max_attempts", 1):
                    e = {"to": node}
                else:
                    e = graph.edge(node, "exhausted") or {"to": "needs_review"}
        target = e["to"] if e else "needs_review"
        # A stage sent back to more often than its budget allows is exhausted too.
        if target != node and graph.nodes[target]["kind"] != "end" \
                and attempts.get(target, 0) >= graph.nodes[target].get("max_attempts", 1) \
                and outcome.status != "ok":
            target = (graph.edge(target, "exhausted") or {"to": "needs_review"})["to"]
        step.next = target
        result.trace.append(step)
        if on_step:
            on_step(step)
        node = target
    result.end = "needs_review"
    result.trace.append(Step("step_budget", "runner", 0, "fail",
                             f"stopped after {graph.step_budget} steps", 0.0, "needs_review"))
    return result
