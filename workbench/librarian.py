"""The Librarian: answers from the reference library, cites every sentence, or says the library does not know.

    .venv\\Scripts\\python -m workbench.librarian "Who could sign an approval note for a Major finding on 10 February 2026?"
    .venv\\Scripts\\python -m workbench.librarian "..." --model granite4.1:8b     # an override, recorded as one

The first agent defined as data: its purpose, tool list, budgets, instructions,
messages and output shape are in workbench/agents.yaml. This file enforces them.

    question -> search_library (the only tool it may call) -> numbered passages
             -> the model the Router chooses for answer_from_library answers in JSON:
                sentences, each naming the passages that state it -- or "not answerable"
             -> code checks every sentence against the passages it cites
             -> failed: one rewrite with the problems named; failed again: no answer, passages shown

What the checks catch -- each item in a sentence must appear in the passages
that sentence cites: a citation to a passage that was never retrieved, and a
number, identifier, quotation or name the cited passages do not contain. What
they cannot catch: a sentence made only of words the passage has, that the
passage does not mean. That is why every sentence carries its citation.

Every answer -- the question, what was retrieved, each attempt and its problems,
the outcome -- goes to a hash-chained log, logs/librarian.jsonl.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

import httpx
import yaml

from mcp_servers.audit import LOG_DIR, AuditLog
from workbench import library, router

AGENTS = Path(__file__).resolve().parent / "agents.yaml"
NAME = "librarian"
TOOLS = {"search_library": library.search}      # every tool that exists; the agent's list says which it may use


@lru_cache(maxsize=None)
def definition() -> dict:
    return yaml.safe_load(AGENTS.read_text(encoding="utf-8"))[NAME]


_LOG: AuditLog | None = None


def _log() -> AuditLog:
    global _LOG
    if _LOG is None:
        _LOG = AuditLog(NAME, LOG_DIR / f"{NAME}.jsonl")
    return _LOG


class ToolNotAllowed(PermissionError):
    pass


def call_tool(name: str, **kwargs):
    """The only way this agent reaches a tool. A tool outside its list is refused, and the refusal logged."""
    allowed = definition()["tools"]
    if name not in allowed:
        _log().write({"event": "tool_refused", "agent": NAME, "tool": name, "allowed": allowed})
        raise ToolNotAllowed(f"{NAME} may not call {name}; allowed: {allowed}")
    return TOOLS[name](**kwargs)


@dataclass
class Answer:
    question: str
    outcome: str                # answered | not in library | failed checks | no qualified model | error
    text: str                   # what the person sees
    sentences: list[dict]       # {"text", "sources": labels, "citations"}
    missing: str
    model: str | None
    routed: str
    passages: list[dict]        # {"label", "citation", "doc_id", "section", "pages", "chunk_id", "why"}
    attempts: list[dict] = field(default_factory=list)
    seconds: float = 0.0


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in re.findall(definition()["checks"]["number"], text)}


def _about(h: library.Hit) -> str:
    """What a passage says, including its own identity: "SOP-INSP-004 section 5 applies
    OISD-STD-118 Cl. 6.2" is supported by that section, though its text never names itself."""
    return f"{h.citation()} {h.title} {h.heading} {h.text}"


def _unsupported(text: str, source: str, free_sentence_starts: bool = False) -> tuple[list[str], list[str]]:
    """Names (identifiers and capitalised words) and numbers in `text` that `source` does not contain.

    Passage labels ("P3") and words of the agent's own instructions ("passage")
    are the protocol, not claims. Nothing from the question is exempt: a question
    can carry a false premise ("tested every 12 months?"), and repeating it is
    not evidence.

    A capitalised word that starts a sentence may be an ordinary word ("Nothing
    says ..."). It passes if the library uses it in lower case -- a name never
    appears so. Where that is too strict to matter (free_sentence_starts, for a
    refusal's note, which asserts an absence) any sentence-starting word passes;
    names inside a sentence are still checked.
    """
    d = definition()
    text = re.sub(re.escape(d["passage_label"]).replace(re.escape("{n}"), r"\d+"), " ", text)
    vocabulary = (d["instructions"] + " " + d["retry_instructions"]).lower()
    ids = [m.group(0) for p in library.config()["search"]["identifier_patterns"] for m in re.finditer(p, text)]
    names = [i for i in ids if library._ident(i) not in library._ident(source)]
    for i in ids:                                   # an identifier's parts are not checked again as words and numbers
        text = text.replace(i, " ")
    ordinary = library.vocabulary()
    min_letters = d["checks"]["sentence_end_min_letters"]
    for m in re.finditer(d["checks"]["proper_term"], text):
        word, before = m.group(0).lower(), text[:m.start()].rstrip()
        # A full stop after "Dr" or the initial in "R. Menon" does not end a sentence; so the
        # word before a stop must be long enough. Too strict for "it." -- the safe direction.
        stop = re.search(r"([A-Za-z]*)[.!?:;]$", before)
        starts_sentence = not before or (stop is not None and len(stop.group(1)) >= min_letters)
        if word in source.lower() or word in vocabulary or (starts_sentence and (free_sentence_starts or word in ordinary)):
            continue
        names.append(m.group(0))
    return list(dict.fromkeys(names)), sorted(_numbers(text) - _numbers(source))


def check(reply, passages: dict[str, library.Hit], question: str) -> list[str]:
    """Problems with a reply; an empty list means it may be shown."""
    d = definition()
    if not isinstance(reply, dict) or not {"answerable", "sentences", "missing"} <= set(reply):
        return ["the reply is not the required JSON object"]
    sentences = reply.get("sentences") or []
    problems = []

    # Even a refusal must not invent: its note on what is missing may name only
    # what the question or the passages name. (The question may be repeated here:
    # the note asserts an absence, not a fact.)
    names, numbers = _unsupported(_norm(str(reply.get("missing", ""))),
                                  _norm(" ".join(_about(h) for h in passages.values())) + " " + question,
                                  free_sentence_starts=True)
    problems += [f'the note on what is missing names "{x}", which neither the question nor any passage contains'
                 for x in names]
    problems += [f"the note on what is missing gives the number {n}, which neither the question nor any passage "
                 f"contains" for n in numbers]
    if not reply["answerable"]:
        if sentences:
            problems.append("it says the passages cannot answer, but still gives sentences")
        return problems
    if not sentences:
        return problems + ["it says the question is answerable but gives no sentences"]

    words = 0
    for i, s in enumerate(sentences, 1):
        text = _norm(str(s.get("text", "")))
        words += len(text.split())
        labels = [str(x).strip() for x in s.get("sources") or []]
        if not labels:
            problems.append(f"sentence {i} cites no passage")
            continue
        unknown = [l for l in labels if l not in passages]
        if unknown:
            problems.append(f"sentence {i} cites {', '.join(unknown)}, which the search did not return")
        cited = [passages[l] for l in labels if l in passages]
        if not cited:
            continue
        source = _norm(" ".join(_about(h) for h in cited))
        names, numbers = _unsupported(text, source)
        problems += [f'sentence {i} names "{x}", which its cited passages do not contain' for x in names]
        problems += [f"sentence {i} gives the number {n}, which its cited passages do not contain" for n in numbers]
        for q in re.findall(d["checks"]["quote"], text):
            if _norm(q).lower() not in source.lower():
                problems.append(f'sentence {i} quotes "{q}", which its cited passages do not contain word for word')
    if words > d["max_words"]:
        problems.append(f"the answer is longer than {d['max_words']} words ({words})")
    return problems


def _chat(model: str, messages: list[dict]) -> str:
    d = definition()
    registry, _ = router.load_registry()
    served_by = registry["models"][model]["served_by"]
    if served_by != "ollama":
        raise NotImplementedError(f"{model} is served by {served_by}; the Librarian speaks only the Ollama chat API so far")
    r = httpx.post(router.endpoint(model, registry) + "/api/chat", timeout=d["timeout_seconds"], json={
        "model": model, "messages": messages, "stream": False,
        "format": d["output_schema"], "options": d["options"]})
    r.raise_for_status()
    return r.json()["message"]["content"]


def _finish(result: Answer, started: float) -> Answer:
    result.seconds = round(time.monotonic() - started, 2)
    _log().write({"event": "answer", "agent": NAME, **json.loads(json.dumps(asdict(result), default=str))})
    return result


def answer(question: str, model: str | None = None, k: int | None = None) -> Answer:
    d, msg = definition(), definition()["messages"]
    started = time.monotonic()
    if model:
        routed = f"override: {model} requested by the caller"
    else:
        decision = router.route(d["router_task"], {"agent": NAME, "question": question})
        model, routed = decision.chosen, decision.line()

    hits = call_tool("search_library", query=question, k=k)
    passages = {d["passage_label"].replace("{n}", str(i)): h for i, h in enumerate(hits, 1)}
    listed = [{"label": l, "citation": h.citation(), "doc_id": h.doc_id, "section": h.section,
               "pages": list(h.pages), "chunk_id": h.chunk_id, "why": h.why} for l, h in passages.items()]
    result = Answer(question, "no qualified model", "", [], "", model, routed, listed)
    if not model:
        result.text = msg["no_model"].replace("{reason}", routed)
        return _finish(result, started)

    shown = "\n\n".join(f"[{l}] {h.citation()} -- {h.title}" + (f", {h.heading}" if h.heading else "") + f"\n{h.text}"
                        for l, h in passages.items())
    messages = [{"role": "system", "content": d["instructions"].replace("{max_words}", str(d["max_words"]))},
                {"role": "user", "content": f"Question: {question}\n\nPassages:\n\n{shown}"}]
    style = tuple(d["checks"]["style_only"])
    for i in range(1, d["max_attempts"] + 1):
        try:
            raw = _chat(model, messages)
            reply = json.loads(raw)
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            result.attempts.append({"attempt": i, "messages_sent": len(messages), "error": f"{type(e).__name__}: {e}"})
            result.outcome, result.text = "error", msg["error"].replace("{error}", type(e).__name__)
            return _finish(result, started)
        problems = check(reply, passages, question)
        # messages_sent proves what the model saw: 2 on a first attempt (instructions, question
        # with passages) -- nothing from any earlier question; a retry adds its own failed reply.
        result.attempts.append({"attempt": i, "messages_sent": len(messages), "reply": reply, "problems": problems})
        if not [p for p in problems if not p.startswith(style)] and (not problems or i == d["max_attempts"]):
            if reply["answerable"]:
                result.outcome = "answered"
                result.sentences = [{"text": _norm(s["text"]), "sources": s["sources"],
                                     "citations": [passages[l].citation() for l in s["sources"]]}
                                    for s in reply["sentences"]]
                result.text = " ".join(f"{s['text']} ({'; '.join(s['citations'])})" for s in result.sentences)
            else:
                result.outcome, result.missing = "not in library", _norm(reply["missing"])
                result.text = msg["not_in_library"].replace("{missing}", result.missing)
            return _finish(result, started)
        messages += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": d["retry_instructions"].replace("{problems}", "; ".join(problems))}]
    result.outcome, result.text = "failed checks", msg["failed_checks"]
    return _finish(result, started)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("question")
    ap.add_argument("--model", default=None, help="override the Router (recorded as an override)")
    ap.add_argument("-k", type=int, default=None, help="passages to retrieve; default: search.k in library.yaml")
    args = ap.parse_args()
    a = answer(args.question, args.model, args.k)
    print(f"[{a.outcome}] {a.model or '-'} ({a.seconds} s, {len(a.attempts)} attempt(s)) -- {a.routed}\n")
    print(a.text + "\n")
    for p in a.passages:
        print(f"  {p['label']:4} {p['citation']}  {p['why']}")
    for att in a.attempts:
        if att.get("problems"):
            print(f"  attempt {att['attempt']} problems: {att['problems']}")
    return 0 if a.outcome in ("answered", "not in library") else 1


if __name__ == "__main__":
    raise SystemExit(main())
