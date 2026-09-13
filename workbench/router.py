"""The Router: picks a model for each step from measured results, and says why.

    .venv\\Scripts\\python -m workbench.router write_summary
    .venv\\Scripts\\python -m workbench.router --all
    .venv\\Scripts\\python -m workbench.router --request "write a script to list breached CMLs"

R2 asks for "model auto selection across at least two different task types".
Selecting is easy; AnythingLLM already routes on keywords and token counts.
What this router adds is the reason a choice is *allowed*:

    1. eligibility comes from a qualification test on our own harness
       (workbench/models.yaml, each result naming its evidence file) --
       untested is not qualified, and a bigger model is not qualified by size;
    2. a safety GATE decides who may do a task at all (a model that ever wrote
       a false approval is out); a RANK then orders those left;
    3. the model has to be available on this machine and fit the GPU;
    4. every decision is written to a hash-chained log with every candidate
       considered and why each one was or was not chosen.

When no model is qualified for a task the router says so and chooses nothing.
That is a correct answer, not a failure: "we have not tested a model for
photographs" is what a judge should hear, rather than a guess dressed up as a
routing decision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx
import yaml

from mcp_servers.audit import LOG_DIR, AuditLog

REGISTRY = Path(__file__).resolve().parent / "models.yaml"
ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Candidate:
    model: str
    eligible: bool
    reason: str
    rank_key: list = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    limits: str | None = None


@dataclass
class Decision:
    task: str
    chosen: str | None
    status: str                     # "chosen" | "no qualified model"
    reason: str
    candidates: list[Candidate]
    registry_sha256: str
    classified_by: str | None = None

    def line(self) -> str:
        if self.chosen:
            return f"{self.task} -> {self.chosen}: {self.reason}"
        return f"{self.task} -> nothing: {self.reason}"


# --- the registry ---------------------------------------------------------------

def load_registry(path: Path = REGISTRY) -> tuple[dict, str]:
    raw = path.read_bytes()
    return yaml.safe_load(raw), hashlib.sha256(raw).hexdigest()


def running_models(registry: dict) -> dict[str, bool]:
    """Which servers are up and which models they hold. Nothing is started here."""
    up: dict[str, bool] = {}
    try:
        tags = httpx.get(f"{registry['servers']['ollama']}/api/tags", timeout=3).json()
        ollama = {m["name"] for m in tags.get("models", [])}
    except Exception:
        ollama = None
    try:
        llama_up = httpx.get(f"{registry['servers']['llama-server']}/health", timeout=3).status_code == 200
    except Exception:
        llama_up = False
    for name, spec in registry["models"].items():
        if spec["served_by"] == "ollama":
            up[name] = ollama is not None and name in ollama
        else:
            up[name] = llama_up
    return up


# --- the decision --------------------------------------------------------------

def _gate(result: dict, gate: dict) -> str | None:
    """None if the result passes every gate condition, else why it does not."""
    for key, want in gate.items():
        have = result.get(key)
        if have is None:
            return f"no measurement of {key}"
        if key.endswith("_max"):
            if have > want:
                return f"{key} {have} is above the limit {want}"
        elif isinstance(want, bool):
            if have is not want:
                return f"{key} is {have}"
        elif isinstance(want, (int, float)) and key in ("unsafe_accepted", "wrong_outputs"):
            if have > want:
                return f"{key} = {have} (must be {want})"
        elif have != want and not (isinstance(want, float) and have >= want):
            return f"{key} = {have} (needs {want})"
    return None


def _rank_key(result: dict, rank: list[str]) -> list:
    key = []
    for field_name in rank:
        desc = field_name.startswith("-")
        v = result.get(field_name.lstrip("-"))
        v = float("inf") if v is None else float(v)
        key.append(-v if desc else v)
    return key


def choose(task: str, registry: dict | None = None, sha: str | None = None,
           running: dict[str, bool] | None = None, vram_free_gb: float | None = None) -> Decision:
    if registry is None:
        registry, sha = load_registry()
    spec = registry["tasks"].get(task)
    if spec is None:
        raise ValueError(f"unknown task {task!r}; known: {', '.join(registry['tasks'])}")
    running = running_models(registry) if running is None else running
    vram = registry["hardware"]["vram_gb"] if vram_free_gb is None else vram_free_gb

    candidates: list[Candidate] = []
    for name, model in registry["models"].items():
        caps = set(model.get("capabilities", []))
        missing = set(spec["needs"]) - caps
        result = (model.get("results") or {}).get(task)
        c = Candidate(model=name, eligible=False, reason="",
                      evidence=(result or {}).get("evidence", []),
                      limits=(result or {}).get("limits"))
        if missing:
            c.reason = f"cannot: lacks {', '.join(sorted(missing))}"
        elif result is None:
            c.reason = "not qualified: never tested for this task"
        elif result.get("qualified") is False:
            # Listed as a candidate, never tested. Not a failure -- an absence.
            c.reason = "not qualified: a candidate, but no qualification test has been run"
        elif (why := _gate(result, spec["gate"])) is not None:
            c.reason = f"failed the safety gate: {why}"
        elif model.get("vram_gb", model["size_gb"]) > vram:
            c.reason = f"does not fit: needs {model.get('vram_gb', model['size_gb'])} GB, {vram} GB available"
        elif not running.get(name):
            # "Available", not "running": for Ollama this means the model is on the
            # machine (Ollama loads it into memory on first use); for llama-server,
            # that its server is answering.
            c.reason = f"qualified, but not available on this machine ({model['served_by']})"
        else:
            c.eligible = True
            c.rank_key = _rank_key(result, spec["rank"])
            c.reason = "qualified and available; " + ", ".join(
                f"{f.lstrip('-')} {result.get(f.lstrip('-'))}" for f in spec["rank"])
        candidates.append(c)

    eligible = sorted((c for c in candidates if c.eligible), key=lambda c: c.rank_key)
    if not eligible:
        near = [c for c in candidates if c.reason.startswith("qualified, but not available")]
        reason = ("no model has passed a qualification test for this task"
                  if not near else
                  f"qualified model(s) not available: {', '.join(c.model for c in near)}")
        return Decision(task, None, "no qualified model", reason, candidates, sha)

    best = eligible[0]
    runner_up = f"; next was {eligible[1].model}" if len(eligible) > 1 else "; the only eligible model"
    reason = f"{best.reason}{runner_up}"
    return Decision(task, best.model, "chosen", reason, candidates, sha)


# --- turning a request into a task -----------------------------------------------

RULES = [
    ("an image or scan is attached and a transcription is wanted",
     lambda r, img: img and re.search(r"\b(read|transcrib|extract|table|reading)", r, re.I), "second_read"),
    ("an image is attached",
     lambda r, img: img, "describe_image"),
    ("the request asks for code",
     lambda r, img: re.search(r"\b(code|script|program|function|python|tool that|write a tool)\b", r, re.I), "code"),
    # Only the approval note's summary is write_summary: it is written from
    # evidence records already in hand. "Find the vendor letters and summarise
    # them" has to search first -- that is a tool_agent job, and routing it to
    # the summary writer would hand a model a task with no evidence to write from.
    ("the request asks for an approval note's summary",
     lambda r, img: re.search(r"\b(approval note|draft the note|note for|summary for the note)\b", r, re.I),
     "write_summary"),
]


def classify(request: str, image_attached: bool = False) -> tuple[str, str]:
    """A task type for a request, by plain rules -- and which rule fired.

    Rules, not a model, on purpose: the classification is then as auditable as
    the choice it leads to. Anything the rules do not recognise becomes a
    tool_agent job, the general multi-step case.
    """
    for description, test, task in RULES:
        if test(request, image_attached):
            return task, description
    return "tool_agent", "no specific rule matched: a general multi-step job"


# --- the log ------------------------------------------------------------------------

_LOG: AuditLog | None = None


def log_decision(decision: Decision, context: dict | None = None) -> dict:
    global _LOG
    if _LOG is None:
        _LOG = AuditLog("router", LOG_DIR / "router_decisions.jsonl")
    return _LOG.write({"event": "route", **(context or {}),
                       **json.loads(json.dumps(asdict(decision), default=str))})


def route(task: str, context: dict | None = None) -> Decision:
    """Choose, log, return. What the workflows call."""
    decision = choose(task)
    log_decision(decision, context)
    return decision


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("task", nargs="?")
    ap.add_argument("--all", action="store_true", help="show the decision for every task type")
    ap.add_argument("--request", help="classify a plain-language request, then route it")
    ap.add_argument("--image", action="store_true", help="the request comes with an image")
    ap.add_argument("--no-log", action="store_true")
    args = ap.parse_args()

    registry, sha = load_registry()
    running = running_models(registry)

    if args.request:
        task, rule = classify(args.request, args.image)
        tasks = [task]
        print(f"request: {args.request!r}\nclassified as {task} ({rule})\n")
    elif args.all:
        tasks = list(registry["tasks"])
    elif args.task:
        tasks = [args.task]
    else:
        ap.print_help()
        return 2

    for task in tasks:
        d = choose(task, registry, sha, running)
        if args.request:
            d.classified_by = rule
        if not args.no_log:
            log_decision(d, {"request": args.request} if args.request else None)
        print(f"=== {task}: {registry['tasks'][task]['description']}")
        print(f"    -> {d.chosen or 'NO MODEL'}   ({d.reason})")
        for c in d.candidates:
            mark = "+" if c.eligible else "-"
            print(f"       {mark} {c.model:42} {c.reason}")
        chosen = next((c for c in d.candidates if c.model == d.chosen), None)
        if chosen and chosen.limits:
            print(f"    limits of the evidence: {' '.join(str(chosen.limits).split())}")
        if chosen and chosen.evidence:
            print(f"    evidence: {', '.join(chosen.evidence)}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
