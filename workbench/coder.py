"""The Coder agent: a model writes code, the sandbox runs it, our tests decide.

    .venv\\Scripts\\python -m workbench.coder cml_report
    .venv\\Scripts\\python -m workbench.coder --list

This is R4 ("a coding task run and verified in a sandbox"), and it is the same
shape as the summary writer: **the model produces, code decides.** The rule
that makes it mean anything:

    The model's own tests do not count. A task is accepted only when the
    acceptance tests WE wrote pass, and the model never sees their source --
    only the failure messages, the way a developer sees CI output.

Without that rule, "verified" means a model marked its own homework. With it, a
passing run is evidence: the code did the job on inputs it was not written
against.

The loop, bounded and recorded:

    write  ->  run in the sandbox (no network, no host access)  ->  read the
    failures  ->  fix  ->  repeat, at most max_attempts times  ->  hand what
    is left to a person

Every attempt keeps the code, the sandbox output and the isolation it ran
under, so the whole thing can be audited afterwards. A result produced under
the development fallback (no Docker) is labelled and is not evidence.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from workbench import agents, sandbox

ROOT = Path(__file__).resolve().parent.parent
CODE_FENCE = re.compile(r"```(?:python)?\s*(.*?)```", re.S)

# The Coder's instructions, messages and settings: workbench/agents.yaml.
# The model comes from the caller (the Router, in main() and the service).
AGENT = agents.definition("coder")
SYSTEM = AGENT["instructions"]


@dataclass
class CodingTask:
    task_id: str
    brief: str                              # what the model is told to build
    entry: str                              # the file the model writes
    acceptance: str                         # OUR test file -- never shown to the model
    inputs: dict[str, str] = field(default_factory=dict)   # data files placed in the sandbox
    max_attempts: int = 3
    timeout: int = 30


@dataclass
class Attempt:
    n: int
    code: str
    passed: bool
    exit_code: int
    stdout: str
    stderr: str
    seconds: float
    isolation: str


@dataclass
class CodingResult:
    task_id: str
    accepted: bool
    model: str
    attempts: list[Attempt] = field(default_factory=list)
    code: str | None = None                 # the accepted program
    isolation: str = ""
    seconds: float = 0.0

    def summary(self) -> str:
        if self.accepted:
            return (f"accepted on attempt {len(self.attempts)} of {self.attempts[-1].n} "
                    f"({self.seconds:.1f}s)")
        return f"not accepted after {len(self.attempts)} attempt(s) -- handed to a person"


def extract_code(reply: str) -> str:
    """The program out of the model's reply. A reply with no code block is a failure."""
    blocks = CODE_FENCE.findall(reply)
    if blocks:
        return max(blocks, key=len).strip()
    return reply.strip() if reply.strip().startswith(("import ", "def ", "from ", "#")) else ""


def ask_model(messages: list[dict], model: str) -> str:
    r = agents.chat(model, messages, "coder")
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


def failure_report(result: sandbox.SandboxResult) -> str:
    """What the model is told after a failed run: the symptoms, never our test code."""
    msg, tail = AGENT["messages"], AGENT["output_tail_chars"]
    if result.timed_out:
        return msg["timed_out"]
    parts = []
    if result.stdout.strip():
        parts.append(f"Output:\n{result.stdout.strip()[-tail:]}")
    if result.stderr.strip():
        parts.append(f"Errors:\n{result.stderr.strip()[-tail:]}")
    return "\n\n".join(parts) or msg["silent_exit"].replace("{code}", str(result.exit_code))


def solve(task: CodingTask, model: str,
          force_subprocess: bool = False,
          emit: Callable[[dict], None] | None = None) -> CodingResult:
    """`emit`, if given, receives attempt_start before each model call and attempt
    after each result -- the live view of the loop. A broken viewer cannot break it."""
    t0 = time.time()
    out = CodingResult(task_id=task.task_id, accepted=False, model=model)

    def send(event: dict) -> None:
        if emit is not None:
            try:
                emit(event)
            except Exception:
                pass

    def announce(attempt: Attempt) -> None:
        out.attempts += [attempt]
        send({"type": "attempt", **asdict(attempt)})
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": task.brief}]

    for n in range(1, task.max_attempts + 1):
        send({"type": "attempt_start", "n": n, "max_attempts": task.max_attempts})
        try:
            reply = ask_model(messages, model)
        except Exception as e:
            announce(Attempt(n, "", False, -1, "", f"{type(e).__name__}: {e}",
                                        0.0, "model unavailable"))
            break
        code = extract_code(reply)
        if not code:
            messages += [{"role": "assistant", "content": reply},
                         {"role": "user", "content": AGENT["messages"]["no_code_block"]}]
            announce(Attempt(n, "", False, -1, "", "no code block in the reply",
                                        0.0, "not run"))
            continue

        # The acceptance test is placed beside the program and is what runs.
        files = {task.entry: code, "acceptance_test.py": task.acceptance, **task.inputs}
        run = sandbox.run(files, entry="acceptance_test.py", timeout=task.timeout,
                          force_subprocess=force_subprocess)
        out.isolation = run.isolation
        announce(Attempt(n, code, run.ok, run.exit_code, run.stdout, run.stderr,
                                    run.seconds, run.isolation))
        if run.ok:
            out.accepted, out.code = True, code
            break
        messages += [{"role": "assistant", "content": reply},
                     {"role": "user", "content":
                      AGENT["messages"]["failed_tests"].replace("{report}", failure_report(run))}]

    out.seconds = round(time.time() - t0, 1)
    return out


# --- the tasks ----------------------------------------------------------------

def _load_tasks() -> dict[str, CodingTask]:
    from workbench import coding_tasks
    return coding_tasks.TASKS


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("task_id", nargs="?")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--model", default=None,
                    help="override the Router's choice (recorded as an override)")
    ap.add_argument("--out", type=Path, default=None, help="write the full record as JSON")
    ap.add_argument("--force-subprocess", action="store_true",
                    help="run without Docker -- NOT isolated, for development only")
    args = ap.parse_args()

    tasks = _load_tasks()
    if args.list or not args.task_id:
        for name, t in tasks.items():
            print(f"{name:16} {t.brief.splitlines()[0][:80]}")
        return 0
    if args.task_id not in tasks:
        print(f"no such task: {args.task_id}. Known: {', '.join(tasks)}")
        return 2

    task = tasks[args.task_id]
    if not args.force_subprocess and not (sandbox.docker_available() and sandbox.image_present()):
        print("The sandbox is not available (Docker or the image is missing). Run "
              "`python -m workbench.sandbox --self-test` to see why.")
        return 2

    if args.model:
        model, why = args.model, "set by hand (Router overridden)"
    else:
        from workbench import router
        decision = router.route("code", {"coding_task": task.task_id})
        if decision.chosen is None:
            print(f"No model is qualified to write code: {decision.reason}")
            return 2
        model, why = decision.chosen, f"chosen by the Router: {decision.reason}"

    print(f"task: {task.task_id}   model: {model}  ({why})")
    result = solve(task, model, args.force_subprocess)
    for a in result.attempts:
        mark = "PASS" if a.passed else "fail"
        first = (a.stderr.strip() or a.stdout.strip() or "").splitlines()
        print(f"  attempt {a.n}: {mark}  {a.seconds:>5.1f}s  {first[-1][:90] if first else ''}")
    print(f"\n{result.summary()}")
    print(f"isolation: {result.isolation}")
    if result.accepted:
        print(f"\n--- accepted program ---\n{result.code}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
        print(f"\nwritten: {args.out}")
    return 0 if result.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
