"""The Chat agent: answers greetings, questions about the workbench, and general questions, in a few checked sentences.

    .venv\\Scripts\\python -m workbench.chat "What can you do?"
    .venv\\Scripts\\python -m workbench.chat "..." --model granite4.1:8b     # an override, recorded as one

The Planner gives it the parts of a request that need none of the organisation's
reports, documents or data (orchestration.yaml, step kind `reply`). It calls no
tool, and code checks every reply before anyone sees it:

  - no verdict only people give ("approved", "fit for service") -- the Report Writer's check;
  - no report, equipment tag or library document named: what the organisation's
    documents say comes from the inspection and library steps, with evidence,
    never from a chat reply;
  - no claim to have done work ("I have drafted the note"): work is a planned step;
  - at most max_words (style: accepted on the last attempt).

Failed: one rewrite with the problems named; failed again: nothing is shown, and
the person is told so. A reply that is shown is labelled as a general answer,
not from the organisation's documents. Its instructions, budgets and messages are
in agents.yaml (`chat`); every reply -- question, attempts, problems, outcome --
goes to a hash-chained log, logs/chat.jsonl.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Callable

import httpx

from mcp_servers.audit import LOG_DIR, AuditLog
from workbench import agents, planner, prose, router, tools

NAME = "chat"

Emit = Callable[[dict], None]


@dataclass
class Reply:
    question: str
    outcome: str                    # answered | failed checks | no qualified model | error
    text: str = ""                  # what the person sees
    label: str = ""                 # shown with an answer: whose it is, and that it is not from the documents
    model: str | None = None
    routed: str = ""
    attempts: list[dict] = field(default_factory=list)
    seconds: float = 0.0


_LOG: AuditLog | None = None


def _log() -> AuditLog:
    global _LOG
    if _LOG is None:
        _LOG = AuditLog(NAME, LOG_DIR / f"{NAME}.jsonl")
    return _LOG


def capabilities_text(cat: planner.Catalogue) -> str:
    """What the chat agent may say the workbench does: the step kinds and coding tasks, never the documents."""
    kinds = [f"- {k}: {' '.join(v['description'].split())}" for k, v in cat.step_kinds.items() if not v.get("no_documents")]
    tasks = [f"- coding task {t}: {p}" for t, p in cat.tasks.items()]
    return "\n".join(kinds + tasks)


def check(text: str, cat: planner.Catalogue) -> list[str]:
    """Problems with a reply; an empty list means it may be shown."""
    d = agents.definition(NAME)
    plain = prose.HYPHENS.sub("-", text)
    if not plain.strip():
        return ["empty"]
    problems = []
    if m := prose.VERDICT.search(plain):
        problems.append(f"gives a verdict ('{m.group(0)}'): only people approve")
    problems += [f"names {n}: what the organisation's reports and documents say comes from the inspection and "
                 f"library steps, not from a reply" for n in planner.names_in(plain, cat)]
    if m := re.search(d["checks"]["claims_done"], plain, re.I):
        problems.append(f"says it has done work ('{m.group(0)}'): a reply does no work")
    words = len(plain.split())
    if words > d["max_words"]:
        problems.append(f"longer than {d['max_words']} words ({words})")
    return problems


def reply(question: str, model: str | None = None, emit: Emit | None = None) -> Reply:
    """Reply as the Chat agent (workbench/tools.py): no tools, its lifecycle logged. `emit` receives route."""
    with tools.acting(NAME, emit, question=question) as act:
        result = _reply(question, model, emit)
        if result.outcome != "answered":
            act.fail(result.outcome)
    return result


def _finish(result: Reply, started: float) -> Reply:
    result.seconds = round(time.monotonic() - started, 2)
    _log().write({"event": "reply", "agent": NAME, **json.loads(json.dumps(asdict(result), default=str))})
    return result


def _reply(question: str, model: str | None, emit: Emit | None) -> Reply:
    d = agents.definition(NAME)
    msg = d["messages"]
    started = time.monotonic()
    result = Reply(question, "no qualified model")
    if model:
        result.model, result.routed = model, f"override: {model} requested by the caller"
    else:
        decision = router.route(d["router_task"], {"agent": NAME, "question": question})
        result.model, result.routed = decision.chosen, decision.line()
        if emit is not None:
            try:
                emit({"type": "route", "task": d["router_task"], "chosen": decision.chosen, "decision": decision.reason})
            except Exception:
                pass
    if not result.model:
        result.text = msg["no_model"].replace("{reason}", result.routed)
        return _finish(result, started)

    cat = planner.catalogue()
    system = (d["instructions"].replace("{capabilities}", capabilities_text(cat))
              .replace("{max_words}", str(d["max_words"])))
    messages = [{"role": "system", "content": system}, {"role": "user", "content": question}]
    extra = {"think": d["think"]} if "think" in d else {}
    style = tuple(d["style_only"])
    for i in range(1, d["max_attempts"] + 1):
        try:
            r = agents.chat(result.model, messages, NAME, **extra)
            r.raise_for_status()
            raw = r.json()["message"]["content"]
        except (httpx.HTTPError, KeyError, NotImplementedError) as e:
            result.attempts.append({"attempt": i, "messages_sent": len(messages), "error": f"{type(e).__name__}: {e}"})
            result.outcome, result.text = "error", msg["error"].replace("{error}", type(e).__name__)
            return _finish(result, started)
        text = raw.strip()
        problems = check(text, cat)
        # messages_sent proves what the model saw: 2 on a first attempt -- nothing from an earlier message
        result.attempts.append({"attempt": i, "messages_sent": len(messages), "reply": text, "problems": problems})
        if not [p for p in problems if not p.startswith(style)] and (not problems or i == d["max_attempts"]):
            result.outcome, result.text = "answered", text
            result.label = msg["label"].replace("{model}", result.model)
            return _finish(result, started)
        messages += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": d["retry_instructions"].replace("{problems}", "; ".join(problems))}]
    result.outcome, result.text = "failed checks", msg["failed_checks"]
    return _finish(result, started)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("question")
    ap.add_argument("--model", default=None, help="override the Router (recorded as an override)")
    args = ap.parse_args()
    r = reply(args.question, args.model)
    print(f"[{r.outcome}] {r.model or '-'} ({r.seconds} s, {len(r.attempts)} attempt(s)) -- {r.routed}\n")
    print(r.text)
    if r.label:
        print(f"\n({r.label})")
    for att in r.attempts:
        if att.get("problems") or att.get("error"):
            print(f"  attempt {att['attempt']}: {att.get('problems') or att.get('error')}")
    return 0 if r.outcome == "answered" else 1


if __name__ == "__main__":
    raise SystemExit(main())
