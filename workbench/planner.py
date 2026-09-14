"""The Planner: turns a request into steps the workbench can run, checked in code before any step runs.

    .venv\\Scripts\\python -m workbench.planner "Draft the approval note for exchanger E-4461"
    .venv\\Scripts\\python -m workbench.planner "..." --model granite4.1:8b     # an override, recorded as one

It delegates only (docs/WHOLE_PICTURE.md §3): it calls no tool, and what it
produces is data --

    request -> the model the Router chooses for `plan` replies in JSON: the parts of the
               request, each with the kind of work that does it or none; steps, each a kind
               of work the workbench already does (orchestration.yaml, planner.step_kinds)
               with its arguments; and what cannot be done
            -> code checks the plan: kinds, reports and tasks exist; a report is one the
               request names; parts and steps agree (every step does a part, every part
               with a kind has a step, a part nobody can do is said); nothing repeated;
               within max_steps
            -> failed: one re-plan with the problems named; failed again: nothing runs

A regulated request is never quietly planned as something else (§3, "Two ways
of working"): when the request asks for regulated work
(planner.regulated_request_patterns), a plan with steps but no regulated step is
refused, whatever the model wrote. The patterns are configuration; the rule is
code.

The model server is given the plan's shape as a JSON schema whose only choices
are the listed kinds, reports and tasks. Code checks every plan anyway: the
schema is a convenience, the checks are the rule.

Every plan -- the request, each attempt and its problems, the outcome -- goes to
a hash-chained log, logs/planner.jsonl.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import httpx
import yaml

from mcp_servers.audit import LOG_DIR, AuditLog
from workbench import agents, router, tools
from workbench.evidence import CORPUS

ORCHESTRATION = Path(__file__).resolve().parent / "orchestration.yaml"
NAME = "planner"

Emit = Callable[[dict], None]


@dataclass
class Catalogue:
    """What a plan may name. From configuration and data, never from this file."""
    step_kinds: dict[str, dict]     # orchestration.yaml, planner.step_kinds
    documents: dict[str, str]       # doc_id -> equipment tag, data/corpus/index.json
    tasks: dict[str, str]           # task_id -> what it computes, workbench/coding_tasks.py
    library: dict[str, str]         # document id -> title, from the library's index (empty if not built)
    max_steps: int
    no_step: str                    # the kind of a part no step kind can do
    regulated_patterns: list[str]


def _library_documents() -> dict[str, str]:
    from workbench import library
    try:
        chunks = library.loaded().chunks
    except (OSError, sqlite3.Error):
        return {}
    return dict(sorted({c["doc_id"]: c["title"] for c in chunks.values()}.items()))


def catalogue() -> Catalogue:
    from workbench import coding_tasks
    s = yaml.safe_load(ORCHESTRATION.read_text(encoding="utf-8"))["planner"]
    index = json.loads((CORPUS / "index.json").read_text(encoding="utf-8"))
    return Catalogue(step_kinds=s["step_kinds"],
                     documents={e["doc_id"]: e["equipment_tag"] for e in index},
                     tasks={t.task_id: " ".join(t.purpose.split()) for t in coding_tasks.TASKS.values()},
                     library=_library_documents(),
                     max_steps=s["max_steps"], no_step=s["no_step"],
                     regulated_patterns=s["regulated_request_patterns"])


@dataclass
class Plan:
    request: str
    outcome: str                    # planned | not possible | failed checks | no qualified model | error
    text: str = ""                  # what the person sees
    parts: list[dict] = field(default_factory=list)     # {"text", "kind"}: the request as the Planner split it
    steps: list[dict] = field(default_factory=list)     # {"kind", "args", "why", "title", "agents"}
    not_possible: str = ""          # what the request asks that no step can do
    regulated_by: str | None = None # the pattern that made the request regulated work
    model: str | None = None
    routed: str = ""
    attempts: list[dict] = field(default_factory=list)
    seconds: float = 0.0
    history: list[dict] = field(default_factory=list)   # the earlier turns of the chat the Planner was shown


_LOG: AuditLog | None = None


def _log() -> AuditLog:
    global _LOG
    if _LOG is None:
        _LOG = AuditLog(NAME, LOG_DIR / f"{NAME}.jsonl")
    return _LOG


def _send(emit: Emit | None, event: dict) -> None:
    if emit is None:
        return
    try:
        emit(event)
    except Exception:  # a broken viewer never breaks the agent it is watching
        pass


# --- what code decides ---------------------------------------------------------------

def regulated_by(request: str, cat: Catalogue) -> str | None:
    """The first pattern that makes `request` regulated work, or None."""
    return next((p for p in cat.regulated_patterns if re.search(p, request, re.I)), None)


def named_documents(request: str, cat: Catalogue) -> set[str]:
    """Reports whose equipment tag the request names as a whole token ("R-2247", not "R-22470")."""
    return {doc for doc, tag in cat.documents.items()
            if re.search(rf"(?<![\w-]){re.escape(tag)}(?![\w-])", request, re.I)}


def turns(history, limit: int) -> list[dict]:
    """The last `limit` earlier turns of a chat, each {"request", "plan": [titles], "not_possible"} as plain
    text. Sent by the interface, which keeps the chat: anything malformed is dropped."""
    out = []
    for t in (history if isinstance(history, list) and limit > 0 else [])[-limit:]:
        if not isinstance(t, dict) or not str(t.get("request") or "").strip():
            continue
        steps = t.get("plan") if isinstance(t.get("plan"), list) else []
        out.append({"request": " ".join(str(t["request"]).split()),
                    "plan": [" ".join(str(s).split()) for s in steps if str(s).strip()],
                    "not_possible": " ".join(str(t.get("not_possible") or "").split())})
    return out


def history_text(earlier: list[dict]) -> str:
    """What the checks count as named earlier in the chat: the requests, and the titles of what was planned."""
    return " ".join(f"{t['request']} {' '.join(t['plan'])}" for t in earlier)


def document_names(cat: Catalogue) -> list[str]:
    """Every report id, equipment tag and library document id: the organisation's own documents, longest first."""
    return sorted({*cat.documents, *cat.documents.values(), *cat.library}, key=lambda n: (-len(n), n))


def names_in(text: str, cat: Catalogue) -> list[str]:
    """The organisation's documents that `text` names, each as a whole token."""
    return [n for n in document_names(cat) if re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", text, re.I)]


def check(reply, request: str, cat: Catalogue, earlier_text: str = "") -> tuple[list[str], list[dict]]:
    """(problems, steps). A plan may run only when there are no problems.
    `earlier_text`: the chat's earlier turns (history_text) -- a report they name counts as named."""
    if (not isinstance(reply, dict) or not isinstance(reply.get("parts"), list)
            or not isinstance(reply.get("steps"), list) or not isinstance(reply.get("not_possible"), str)):
        return ["the reply is not the required JSON object"], []
    problems, steps, seen = [], [], set()
    named = named_documents(f"{request} {earlier_text}", cat)
    namer = "neither the request nor the earlier messages name" if earlier_text else "the request does not name"

    parts: list[tuple[str, str]] = []
    for j, part in enumerate(reply["parts"], 1):
        kind = str(part.get("kind") or "").strip() if isinstance(part, dict) else ""
        if kind != cat.no_step and kind not in cat.step_kinds:
            problems.append(f"part {j} has kind {kind!r}: a part's kind is a listed step kind or {cat.no_step!r}")
            continue
        parts.append((" ".join(str(part.get("text") or "").split()), kind))
    if not reply["parts"]:
        problems.append("the plan lists no parts of the request")

    for i, raw in enumerate(reply["steps"], 1):
        if not isinstance(raw, dict):
            problems.append(f"step {i} is not an object")
            continue
        kind = str(raw.get("kind") or "").strip()
        spec = cat.step_kinds.get(kind)
        if spec is None:
            problems.append(f"step {i} has kind {kind!r}, which is not a listed step kind")
            continue
        args = {a: str(raw.get(a) or "").strip() for a in spec["args"]}   # arguments the kind does not take are dropped
        for a, v in args.items():
            if not v:
                problems.append(f"step {i} ({kind}) needs {a}")
            elif a == "doc_id" and v not in cat.documents:
                problems.append(f"step {i} names the report {v!r}, which is not in the Documents list")
            elif a == "doc_id" and v not in named:
                problems.append(f"step {i} uses the report {v} ({cat.documents[v]}), but {namer} {cat.documents[v]}")
            elif a == "task_id" and v not in cat.tasks:
                problems.append(f"step {i} names the coding task {v!r}, which is not in the list")
            elif spec.get("no_documents") and (hits := names_in(v, cat)):
                problems.append(f"step {i} ({kind}) asks about {', '.join(hits)}: questions about the organisation's "
                                f"reports and documents are inspection or library steps")
        key = (kind, tuple(sorted(args.items())))
        if key in seen:
            problems.append(f"step {i} repeats an earlier step: one step can do several parts, so list it once")
        seen.add(key)
        if kind not in {k for _, k in parts}:
            problems.append(f"step {i} is kind {kind}, but no part of the request is")
        steps.append({"kind": kind, "args": args, "why": " ".join(str(raw.get("why") or "").split())})

    # Every part is done by a step, or said to be impossible: a part nobody does is never silently dropped.
    planned = {s["kind"] for s in steps}
    undone = [text for text, kind in parts if kind == cat.no_step or kind not in planned]
    said = bool(reply["not_possible"].strip())
    if undone and not said:
        problems += [f'the part "{text}" has no step, so not_possible must say why it cannot be done' for text in undone]
    if said and parts and not undone:
        problems.append("not_possible says something cannot be done, but every part of the request has a step")
    if len(steps) > cat.max_steps:
        problems.append(f"the plan has {len(steps)} steps; a plan has at most {cat.max_steps}")
    if not steps and not said:
        problems.append("the plan has no steps and does not say why in not_possible")
    regulated = [k for k, v in cat.step_kinds.items() if v.get("regulated")]
    if regulated_by(request, cat) and steps and not any(s["kind"] in regulated for s in steps):
        problems.append(f"the request asks to read a report or draft a note, so the plan needs a step of kind "
                        f"{' or '.join(regulated)} for the report it names -- or no steps, saying in "
                        f"not_possible what is missing")
    return problems, steps


def output_schema(cat: Catalogue) -> dict:
    """The output contract in agents.yaml, with the catalogue's kinds, reports and tasks as the only choices."""
    schema = json.loads(json.dumps(agents.definition(NAME)["output_schema"]))
    schema["properties"]["parts"]["items"]["properties"]["kind"]["enum"] = list(cat.step_kinds) + [cat.no_step]
    step = schema["properties"]["steps"]["items"]["properties"]
    step["kind"]["enum"] = list(cat.step_kinds)
    step["doc_id"]["enum"] = [""] + list(cat.documents)
    step["task_id"]["enum"] = [""] + list(cat.tasks)
    return schema


def request_message(request: str, cat: Catalogue, earlier: list[dict] | None = None) -> str:
    """What the model is shown: the chat's earlier turns if there are any, the request, and the catalogue."""
    d = agents.definition(NAME)
    text = d["request_template"]
    listing = {
        "{step_kinds}": "\n".join(f"- {k} (needs {', '.join(v['args'])}): {' '.join(v['description'].split())}"
                                  for k, v in cat.step_kinds.items()),
        "{documents}": "\n".join(f"- {doc}: {tag}" for doc, tag in cat.documents.items()),
        "{tasks}": "\n".join(f"- {t}: {p}" for t, p in cat.tasks.items()),
        "{library}": "\n".join(f"- {doc}: {title}" for doc, title in cat.library.items()) or "- (not built)",
    }
    for key, value in listing.items():
        text = text.replace(key, value)
    text = text.replace("{request}", request)      # after the catalogue, so a request cannot fill in its fields
    if not earlier:
        return text
    shown = "\n".join(d["history_turn"]
                      .replace("{plan}", "; ".join(t["plan"]) if t["plan"] else
                               d["history_nothing_planned"].replace("{not_possible}", t["not_possible"] or "-"))
                      .replace("{request}", t["request"]) for t in earlier)
    return d["history_template"].replace("{turns}", shown) + "\n" + text


def capabilities(cat: Catalogue | None = None) -> dict:
    """What the workbench can be asked for, from the catalogue alone -- shown when nothing was planned. No model."""
    cat = cat or catalogue()
    return {"intro": agents.definition(NAME)["messages"]["help"],
            "kinds": [{"kind": k, "description": " ".join(v["description"].split())} for k, v in cat.step_kinds.items()],
            "reports": sorted(cat.documents.values()),
            "tasks": [{"task_id": t, "purpose": p} for t, p in cat.tasks.items()],
            "library": [{"doc_id": doc, "title": title} for doc, title in cat.library.items()]}


def describe(step: dict, cat: Catalogue) -> dict:
    """A checked step with what people see: its title and the agents that do the work."""
    spec = cat.step_kinds[step["kind"]]
    title = spec["title"]
    for key, value in {**step["args"], "tag": cat.documents.get(step["args"].get("doc_id", ""), "")}.items():
        title = title.replace("{" + key + "}", value)
    return {**step, "title": title, "agents": list(spec["agents"])}


# --- planning ---------------------------------------------------------------------------

def plan(request: str, model: str | None = None, emit: Emit | None = None, history: list | None = None) -> Plan:
    """Plan as the Planner (workbench/tools.py): no tools, its lifecycle logged. `emit` receives route and plan.
    `history`: the chat's earlier turns, as the interface keeps them (see `turns`)."""
    with tools.acting(NAME, emit, request=request) as act:
        result = _plan(request, model, emit, history)
        if result.outcome not in ("planned", "not possible"):
            act.fail(result.outcome)
    _send(emit, {"type": "plan", **{k: v for k, v in asdict(result).items() if k != "attempts"},
                 "attempts": [{k: a.get(k) for k in ("attempt", "problems", "error") if k in a}
                              for a in result.attempts]})
    return result


def _finish(result: Plan, started: float) -> Plan:
    result.seconds = round(time.monotonic() - started, 2)
    _log().write({"event": "plan", "agent": NAME, **json.loads(json.dumps(asdict(result), default=str))})
    return result


def _plan(request: str, model: str | None, emit: Emit | None, history: list | None) -> Plan:
    d = agents.definition(NAME)
    msg = d["messages"]
    cat = catalogue()
    started = time.monotonic()
    earlier = turns(history, d["history_turns"])
    result = Plan(request, "no qualified model", regulated_by=regulated_by(request, cat), history=earlier)
    if model:
        result.model, result.routed = model, f"override: {model} requested by the caller"
    else:
        decision = router.route(d["router_task"], {"agent": NAME, "request": request})
        result.model, result.routed = decision.chosen, decision.line()
        _send(emit, {"type": "route", "task": d["router_task"], "chosen": decision.chosen,
                     "decision": decision.reason})
    if not result.model:
        result.text = msg["no_model"].replace("{reason}", result.routed)
        return _finish(result, started)

    schema = output_schema(cat)
    extra = {"format": schema, **({"think": d["think"]} if "think" in d else {})}
    messages = [{"role": "system", "content": d["instructions"]},
                {"role": "user", "content": request_message(request, cat, earlier)}]
    problems: list[str] = []
    for i in range(1, d["max_attempts"] + 1):
        try:
            r = agents.chat(result.model, messages, NAME, **extra)
            r.raise_for_status()
            raw = r.json()["message"]["content"]
            reply = json.loads(raw)
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, NotImplementedError) as e:
            # messages_sent proves what the model saw: 2 on a first attempt -- nothing from an earlier request
            result.attempts.append({"attempt": i, "messages_sent": len(messages), "error": f"{type(e).__name__}: {e}"})
            result.outcome, result.text = "error", msg["error"].replace("{error}", type(e).__name__)
            return _finish(result, started)
        problems, steps = check(reply, request, cat, history_text(earlier))
        result.attempts.append({"attempt": i, "messages_sent": len(messages), "reply": reply, "problems": problems})
        if not problems:
            result.parts = [{"text": " ".join(str(p.get("text") or "").split()), "kind": p.get("kind")}
                            for p in reply["parts"]]
            result.steps = [describe(s, cat) for s in steps]
            result.not_possible = " ".join(reply["not_possible"].split())
            if result.steps:
                result.outcome = "planned"
                result.text = (msg["planned"].replace("{model}", result.model).replace("{n}", str(len(result.steps)))
                               + (" " + msg["partly"].replace("{not_possible}", result.not_possible)
                                  if result.not_possible else ""))
            else:
                result.outcome = "not possible"
                result.text = msg["not_possible"].replace("{not_possible}", result.not_possible)
            return _finish(result, started)
        messages += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": d["retry_instructions"].replace("{problems}", "; ".join(problems))}]
    result.outcome = "failed checks"
    result.text = msg["failed_checks"].replace("{problems}", "; ".join(problems))
    return _finish(result, started)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("request")
    ap.add_argument("--model", default=None, help="override the Router (recorded as an override)")
    args = ap.parse_args()
    p = plan(args.request, args.model)
    print(f"[{p.outcome}] {p.model or '-'} ({p.seconds} s, {len(p.attempts)} attempt(s)) -- {p.routed}")
    if p.regulated_by:
        print(f"regulated request (matched {p.regulated_by!r})")
    print(p.text)
    for i, s in enumerate(p.steps, 1):
        print(f"  {i}. {s['title']}  [{', '.join(s['agents'])}]  -- {s['why']}")
    for att in p.attempts:
        if att.get("problems") or att.get("error"):
            print(f"  attempt {att['attempt']}: {att.get('problems') or att.get('error')}")
    return 0 if p.outcome in ("planned", "not possible") else 1


if __name__ == "__main__":
    raise SystemExit(main())
