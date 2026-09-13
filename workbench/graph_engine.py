"""Runs a procedural graph on LangGraph: same graph file, same rules, same trace as procedural_graph.run.

The YAML graph stays the source of truth (docs/WHOLE_PICTURE.md §10a). It is
compiled, not rewritten by hand:

  - each stage becomes a LangGraph node; each end becomes a node that records
    where the run ended;
  - the `when: ok / fail / exhausted` edges become one conditional edge per
    stage, chosen by the same transition rule the old runner applies: a failing
    stage retries within max_attempts, a failed check sends the work back to its
    cause, a stage sent back to more often than its budget allows is exhausted;
  - `step_budget` stays an enforced counter, and guidance and pitfalls still go
    to each stage in `ctx["guidance"]`;
  - a `kind: review` node runs like any stage, except that with pause_at_review,
    when ctx holds a `review_request`, the run pauses there (LangGraph
    `interrupt()`) and Execution.resume continues from exactly that node with the
    person's decision in `ctx["review_decision"]`.

Stage handlers are the same plain functions, with no framework imports. The
run's working data (pages, evidence, the summary) stays in `ctx` and in the run
folder on disk; the checkpointed LangGraph state holds only where the run is --
attempts per node, steps taken, the next node, where it ended -- so the
checkpoint never has to serialise a scanned page.

bench/stage3/engine_parity_test.py runs this engine and the old runner on the
same scripted outcomes and requires identical traces.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Callable, TypedDict

# LangGraph pulls in langsmith, which sends traces to LangChain's cloud when
# tracing is switched on. This machine sends nothing out (§9): off, not a setting.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.types import Command, interrupt  # noqa: E402

from workbench.procedural_graph import Graph, RunResult, StageResult, Step  # noqa: E402

BUDGET = "step_budget"                 # the node reached when the step budget runs out (the old trace's name)


class RunState(TypedDict):
    pg_attempts: dict                  # node -> attempts so far
    pg_steps: int                      # stages run so far
    pg_next: str                       # the node the transition rule chose
    pg_end: str                        # the end node reached; "" while running


def next_node(graph: Graph, node: str, status: str, attempts: dict[str, int]) -> str:
    """Where the run goes after `node` finished with `status` -- the rule procedural_graph.run applies."""
    spec = graph.nodes[node]
    if status == "ok":
        e = graph.edge(node, "ok")
    else:
        e = graph.edge(node, "fail")                  # a check sends the work back to its cause
        if e is None:                                  # a stage retries itself, within budget
            if attempts[node] < spec.get("max_attempts", 1):
                e = {"to": node}
            else:
                e = graph.edge(node, "exhausted") or {"to": "needs_review"}
    target = e["to"] if e else "needs_review"
    # A stage sent back to more often than its budget allows is exhausted too.
    if target != node and graph.nodes[target]["kind"] != "end" \
            and attempts.get(target, 0) >= graph.nodes[target].get("max_attempts", 1) \
            and status != "ok":
        target = (graph.edge(target, "exhausted") or {"to": "needs_review"})["to"]
    return target


def compile_graph(graph: Graph, handlers: dict[str, Callable[[dict], StageResult]], ctx: dict,
                  trace: list[Step],
                  on_step: Callable[[Step], None] | None = None,
                  on_enter: Callable[[str, str, int], None] | None = None,
                  checkpointer=None, pause_at_review: bool = False):
    """The graph file as a compiled LangGraph graph. Steps are appended to `trace` as they finish.
    With pause_at_review, review nodes pause for a person (needs a checkpointer)."""
    missing = [n for n, spec in graph.nodes.items() if spec["kind"] != "end" and n not in handlers]
    if missing:
        raise ValueError(f"no handler for: {', '.join(missing)}")
    reserved = set(RunState.__annotations__) | {BUDGET}
    clash = reserved & set(graph.nodes)
    if clash:
        raise ValueError(f"graph node names reserved by the engine: {', '.join(sorted(clash))}")

    def route(state: RunState) -> str:
        return BUDGET if state["pg_steps"] >= graph.step_budget else state["pg_next"]

    def stage(name: str):
        spec = graph.nodes[name]

        def run_stage(state: RunState) -> dict:
            if pause_at_review and spec["kind"] == "review" and ctx.get("review_request"):
                # Pause for a person. On resume LangGraph runs this node again from the top,
                # and interrupt() returns the person's decision instead of pausing.
                ctx["review_decision"] = interrupt(ctx["review_request"])
            attempts = dict(state["pg_attempts"])
            attempts[name] = attempts.get(name, 0) + 1
            ctx["guidance"] = graph.guidance(name)
            ctx["attempt"] = attempts[name]
            if on_enter:
                on_enter(name, spec.get("agent", ""), attempts[name])
            t0 = time.monotonic()
            try:
                outcome = handlers[name](ctx)
            except Exception as e:  # a crashing stage is a failed attempt, not a crashed run
                outcome = StageResult("fail", f"{type(e).__name__}: {e}")
            target = next_node(graph, name, outcome.status, attempts)
            step = Step(name, spec.get("agent", ""), attempts[name], outcome.status, outcome.note,
                        round(time.monotonic() - t0, 2), target)
            trace.append(step)
            if on_step:
                on_step(step)
            return {"pg_attempts": attempts, "pg_steps": state["pg_steps"] + 1, "pg_next": target}

        return run_stage

    def end(name: str):
        def reach_end(state: RunState) -> dict:
            return {"pg_end": name}
        return reach_end

    def out_of_budget(state: RunState) -> dict:
        trace.append(Step(BUDGET, "runner", 0, "fail", f"stopped after {graph.step_budget} steps",
                          0.0, "needs_review"))
        return {"pg_end": "needs_review"}

    destinations = [*graph.nodes, BUDGET]
    sg = StateGraph(RunState)
    for name, spec in graph.nodes.items():
        if spec["kind"] == "end":
            sg.add_node(name, end(name))
            sg.add_edge(name, END)
        else:
            sg.add_node(name, stage(name))
            sg.add_conditional_edges(name, route, destinations)
    sg.add_node(BUDGET, out_of_budget)
    sg.add_edge(BUDGET, END)
    sg.add_conditional_edges(START, route, destinations)
    return sg.compile(checkpointer=checkpointer)


class Execution:
    """One run of a graph, which may pause at a review node for a person and be resumed there.

    The run's position is checkpointed in memory: a paused run lives as long as
    this object, not across a restart of the process. While paused,
    `result.end` is "paused" and `paused_at` names the node.
    """

    def __init__(self, graph: Graph, handlers: dict[str, Callable[[dict], StageResult]], ctx: dict,
                 on_step: Callable[[Step], None] | None = None,
                 on_enter: Callable[[str, str, int], None] | None = None,
                 pause_at_review: bool = False):
        self.graph = graph
        self.result = RunResult(end="needs_review")
        self.app = compile_graph(graph, handlers, ctx, self.result.trace, on_step, on_enter,
                                 InMemorySaver(), pause_at_review=pause_at_review)
        self.config = {"configurable": {"thread_id": uuid.uuid4().hex},
                       "recursion_limit": graph.step_budget + 3}   # every stage, then one end or budget node
        self.paused_at: str | None = None
        self._started = False

    def start(self) -> RunResult:
        if self._started:
            raise RuntimeError("this run has already started")
        self._started = True
        return self._drive({"pg_attempts": {}, "pg_steps": 0, "pg_next": self.graph.start, "pg_end": ""})

    def resume(self, decision) -> RunResult:
        """Continue a paused run from its review node; the node receives `decision`."""
        if self.paused_at is None:
            raise RuntimeError("this run is not paused")
        return self._drive(Command(resume=decision))

    def _drive(self, value) -> RunResult:
        final = self.app.invoke(value, self.config)
        waiting = self.app.get_state(self.config).next
        if waiting:
            self.paused_at, self.result.end = waiting[0], "paused"
        else:
            self.paused_at, self.result.end = None, final.get("pg_end") or "needs_review"
        return self.result


def run(graph: Graph, handlers: dict[str, Callable[[dict], StageResult]], ctx: dict,
        on_step: Callable[[Step], None] | None = None,
        on_enter: Callable[[str, str, int], None] | None = None) -> RunResult:
    """Drop-in for procedural_graph.run, never pausing: on_step fires when a stage has finished,
    on_enter(node, agent, attempt) as it starts."""
    return Execution(graph, handlers, ctx, on_step, on_enter).start()
