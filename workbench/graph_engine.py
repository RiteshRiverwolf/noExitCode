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
    to each stage in `ctx["guidance"]`.

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
                  checkpointer=None):
    """The graph file as a compiled LangGraph graph. Steps are appended to `trace` as they finish."""
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


def run(graph: Graph, handlers: dict[str, Callable[[dict], StageResult]], ctx: dict,
        on_step: Callable[[Step], None] | None = None,
        on_enter: Callable[[str, str, int], None] | None = None) -> RunResult:
    """Drop-in for procedural_graph.run: on_step fires when a stage has finished,
    on_enter(node, agent, attempt) as it starts."""
    result = RunResult(end="needs_review")
    app = compile_graph(graph, handlers, ctx, result.trace, on_step, on_enter, InMemorySaver())
    config = {"configurable": {"thread_id": uuid.uuid4().hex},
              "recursion_limit": graph.step_budget + 3}   # every stage, then one end or budget node
    final = app.invoke({"pg_attempts": {}, "pg_steps": 0, "pg_next": graph.start, "pg_end": ""}, config)
    result.end = final["pg_end"] or "needs_review"
    return result
