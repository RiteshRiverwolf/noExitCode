"""Does the LangGraph engine run a procedural graph exactly as the old runner does?

Both engines run the same graph with scripted stage outcomes -- no model, no
OCR, no files -- and must produce the same trace (node, agent, attempt, status,
note, next), the same end, the same on_enter and on_step calls, and hand every
stage the same `attempt` and `guidance`. Named scenarios cover the paths the
demo uses; seeded random outcomes cover the rest, on the real inspection graph,
on copies with small step budgets, and on a small graph with a missing ok edge.

    .venv\\Scripts\\python bench\\stage3\\engine_parity_test.py
"""
from __future__ import annotations

import copy
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from workbench import graph_engine as new  # noqa: E402
from workbench import procedural_graph as old  # noqa: E402

INSPECTION = old.Graph.load(ROOT / "workbench" / "graphs" / "inspection.yaml")
RANDOM_RUNS = 600


def play(engine, graph: old.Graph, outcome) -> dict:
    calls: dict[str, int] = {}
    seen, entered, stepped = [], [], []

    def handler_for(node: str):
        def handle(ctx: dict) -> old.StageResult:
            i = calls.get(node, 0)
            calls[node] = i + 1
            seen.append((node, ctx["attempt"], ctx["guidance"]))
            kind = outcome(node, i)
            if kind == "raise":
                raise RuntimeError(f"{node} broke on call {i}")
            return old.StageResult(kind, f"{node} call {i}: {kind}")
        return handle

    handlers = {n: handler_for(n) for n, spec in graph.nodes.items() if spec["kind"] != "end"}
    result = engine.run(graph, handlers, {}, on_step=lambda s: stepped.append((s.node, s.next)),
                        on_enter=lambda n, a, k: entered.append((n, a, k)))
    return {"end": result.end, "entered": entered, "stepped": stepped, "seen": seen,
            "trace": [(s.node, s.agent, s.attempt, s.status, s.note, s.next) for s in result.trace]}


def scripted(**per_node):
    """Each node's outcomes in order; "ok" once its list runs out."""
    return lambda node, i: per_node[node][i] if i < len(per_node.get(node, [])) else "ok"


def seeded(seed: int, p_fail: float, p_raise: float):
    def outcome(node: str, i: int) -> str:
        r = random.Random(f"{seed}:{node}:{i}").random()
        return "raise" if r < p_raise else "fail" if r < p_raise + p_fail else "ok"
    return outcome


def with_budget(graph: old.Graph, budget: int) -> old.Graph:
    g = copy.copy(graph)
    g.step_budget = budget
    return g


# A graph the inspection file does not exercise: a stage with no ok edge, and a
# check sent back to a stage that has no exhausted edge.
SMALL = old.Graph("small", 1, "a", 12, {
    "a": {"kind": "stage", "agent": "A", "max_attempts": 2},
    "b": {"kind": "check", "agent": "B", "max_attempts": 1},
    "c": {"kind": "stage", "agent": "C", "max_attempts": 1},
    "needs_review": {"kind": "end", "agent": "Person"},
    "done": {"kind": "end", "agent": "Person"},
}, [
    {"from": "a", "to": "b", "when": "ok", "guidance": "check it"},
    {"from": "b", "to": "a", "when": "fail", "pitfalls": "do not edit the file"},
    {"from": "b", "to": "c", "when": "ok"},
], ROOT / "small.yaml")

NAMED = {
    "all stages pass": (INSPECTION, scripted()),
    "injected fault caught by qa_check, repaired": (INSPECTION, scripted(qa_check=["fail"])),
    "qa_check never passes: render_note exhausted": (INSPECTION, scripted(qa_check=["fail"] * 10)),
    "doubtful value: build_evidence stops for a person": (INSPECTION, scripted(build_evidence=["fail"] * 10)),
    "a stage crashes once, then passes": (INSPECTION, scripted(read_document=["raise"])),
    "rules engine fails (one attempt only)": (INSPECTION, scripted(apply_rules=["fail"])),
    "step budget runs out mid-loop": (with_budget(INSPECTION, 5), scripted(qa_check=["fail"] * 10)),
    "step budget exactly the path length": (with_budget(INSPECTION, 6), scripted()),
    "small graph: no ok edge": (SMALL, scripted()),
}


def compare(label: str, graph: old.Graph, outcome) -> bool:
    a, b = play(old, graph, outcome), play(new, graph, outcome)
    if a == b:
        return True
    print(f"MISMATCH: {label}")
    for key in a:
        if a[key] != b[key]:
            print(f"  {key}:\n    old {a[key]}\n    new {b[key]}")
    return False


def main() -> int:
    failures = 0
    for label, (graph, outcome) in NAMED.items():
        ok = compare(label, graph, outcome)
        failures += not ok
        end = play(new, graph, outcome)["end"]
        print(f"  [{'same' if ok else 'DIFF'}] {label:52} -> {end}")

    graphs = [INSPECTION, *(with_budget(INSPECTION, b) for b in (1, 3, 5, 7, 9)), SMALL]
    ends: dict[str, int] = {}
    for seed in range(RANDOM_RUNS):
        rng = random.Random(seed)
        graph = graphs[seed % len(graphs)]
        outcome = seeded(seed, p_fail=rng.uniform(0.0, 0.6), p_raise=rng.uniform(0.0, 0.15))
        failures += not compare(f"random seed {seed} on {graph.name} budget {graph.step_budget}", graph, outcome)
        end = play(new, graph, outcome)
        key = "step budget" if end["trace"] and end["trace"][-1][0] == new.BUDGET else end["end"]
        ends[key] = ends.get(key, 0) + 1
    print(f"random runs: {RANDOM_RUNS}, ends reached: {ends}")
    print("PARITY: identical" if failures == 0 else f"PARITY: {failures} mismatch(es)")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
