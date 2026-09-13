"""Does LangGraph (with langsmith pulled in by langchain-core) try to reach the network?

Every socket connect and DNS lookup in this process is recorded from BEFORE the
import, so a call at import time is caught too. Then a graph is compiled and
run many times -- plain, streamed, with a checkpointer and with an interrupt.
"""
import os
import socket
import subprocess
import time

attempts: list[str] = []
_connect, _connect_ex, _getaddrinfo = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo


def spy_connect(self, address):
    attempts.append(f"connect {address}")
    return _connect(self, address)


def spy_connect_ex(self, address):
    attempts.append(f"connect_ex {address}")
    return _connect_ex(self, address)


def spy_getaddrinfo(host, *a, **k):
    attempts.append(f"dns {host}")
    return _getaddrinfo(host, *a, **k)


socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = spy_connect, spy_connect_ex, spy_getaddrinfo

print("LANG*/LANGSMITH* environment:", {k: v for k, v in os.environ.items() if k.startswith(("LANG", "LANGSMITH"))} or "none set")
t0 = time.time()
from typing import TypedDict  # noqa: E402

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.types import Command, interrupt  # noqa: E402

print(f"imported in {time.time() - t0:.1f}s; attempts so far: {attempts or 'none'}")


class State(TypedDict):
    n: int
    decision: str


def step(state: State) -> dict:
    return {"n": state["n"] + 1}


def ask_person(state: State) -> dict:
    return {"decision": interrupt({"question": "accept this value?", "n": state["n"]})}


g = StateGraph(State)
g.add_node("step", step)
g.add_node("ask_person", ask_person)
g.add_edge(START, "step")
g.add_edge("step", "ask_person")
g.add_edge("ask_person", END)
app = g.compile(checkpointer=InMemorySaver())

for i in range(30):
    cfg = {"configurable": {"thread_id": f"t{i}"}}
    first = app.invoke({"n": i, "decision": ""}, cfg)
    assert "__interrupt__" in first, "the graph did not pause"
    for _ in app.stream(Command(resume="accepted"), cfg, stream_mode="updates"):
        pass
    assert app.get_state(cfg).values["decision"] == "accepted"
print("30 runs: paused at the interrupt, resumed with a person's answer, finished")

import langsmith.utils as lsu  # noqa: E402

print("langsmith tracing_is_enabled():", lsu.tracing_is_enabled())
time.sleep(2)
out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
mine = [line.strip() for line in out.splitlines() if line.split()[-1:] == [str(os.getpid())]]
print("TCP/UDP entries held by this process:", mine or "none")
print("socket connects and DNS lookups recorded:", attempts or "NONE")
