"""End-to-end check of the web_access server, with a scripted stand-in for the person.

Start the server first, in ask mode with a short timeout so the timeout case
is quick:

    .venv\\Scripts\\python -m mcp_servers.web_access --mode ask --approval-timeout 8
    .venv\\Scripts\\python -m mcp_servers.check_web_access

Cases: tools listed; a search approved (real internet); a search with
confidential-looking terms, warned about and declined; no decision -> timeout;
a file:// address refused before anyone is asked; the approval page itself
refused as a fetch target even when approved; a real page fetched; the
15-minute window; the audit log's hash chain intact, and a tampered copy
detected.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

import httpx
from mcp import Client

from mcp_servers.audit import LOG_DIR, verify

BASE = "http://127.0.0.1:8766"
LOG = LOG_DIR / "web_access_tool_calls.jsonl"
TOKEN = (LOG_DIR / "web_access_approval_url.txt").read_text(encoding="utf-8").split("token=")[1].strip()
HEADERS = {"X-Approval-Token": TOKEN}

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


def text_of(result) -> str:
    return "".join(getattr(c, "text", "") for c in result.content)


async def person(decision: str, wait: float = 6.0) -> dict | None:
    """Stand-in for the person: wait for one pending request, then decide it."""
    async with httpx.AsyncClient(base_url=BASE, headers=HEADERS) as http:
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            pending = (await http.get("/approvals/state")).json()["pending"]
            if pending:
                p = pending[0]
                await http.post("/approvals/decide", json={"id": p["id"], "decision": decision})
                return p
            await asyncio.sleep(0.2)
    return None


async def call_with_person(client: Client, tool: str, args: dict, decision: str | None):
    """Call a tool while the stand-in approves or declines (None = nobody answers)."""
    helper = asyncio.create_task(person(decision)) if decision else None
    t0 = time.monotonic()
    out = text_of(await client.call_tool(tool, args))
    seen = await helper if helper else None
    return out, seen, round(time.monotonic() - t0, 1)


async def main() -> int:
    lines_before = sum(1 for _ in LOG.open(encoding="utf-8")) if LOG.exists() else 0

    async with Client(f"{BASE}/mcp") as client:
        names = sorted(t.name for t in (await client.list_tools()).tools)
        check("tools listed", names == ["fetch_page", "web_search"], str(names))

        out, seen, secs = await call_with_person(
            client, "web_search", {"query": "OISD-STD-116 fire protection refinery", "max_results": 3}, "approve")
        check("search approved -> real results", out.startswith("Web results for") and "1. " in out,
              f"{secs}s; warnings shown: {seen['warnings'] if seen else None}")
        check("public standard name not flagged as confidential", seen is not None and not seen["warnings"],
              str(seen["warnings"] if seen else None))

        out, seen, secs = await call_with_person(
            client, "web_search", {"query": "R-2247 reactor corrosion MRPL"}, "decline")
        check("confidential-looking query shows warnings", seen is not None and len(seen["warnings"]) >= 2,
              str(seen["warnings"] if seen else None))
        check("declined search -> nothing sent", "declined" in out, out[:80])

        out, _, secs = await call_with_person(client, "fetch_page", {"url": "https://example.com"}, None)
        check("no decision -> timeout, nothing sent", "No one approved" in out and secs >= 7, f"{secs}s")

        async with httpx.AsyncClient(base_url=BASE, headers=HEADERS) as http:
            t0 = time.monotonic()
            out = text_of(await client.call_tool("fetch_page", {"url": "file:///C:/Windows/win.ini"}))
            asked = (await http.get("/approvals/state")).json()["recent"][:1]
        check("file:// refused before anyone is asked", "Only http" in out and time.monotonic() - t0 < 2, out[:60])

        out, _, _ = await call_with_person(
            client, "fetch_page", {"url": f"{BASE}/approvals?token={TOKEN}"}, "approve")
        check("approval page cannot be fetched, even when approved", "not a public internet address" in out, out[:90])

        out, _, secs = await call_with_person(client, "fetch_page", {"url": "https://example.com"}, "approve")
        check("page fetched after approval", "Example Domain" in out, f"{secs}s")

        async with httpx.AsyncClient(base_url=BASE, headers=HEADERS) as http:
            await http.post("/approvals/window", json={"action": "open"})
            t0 = time.monotonic()
            out = text_of(await client.call_tool("web_search", {"query": "python lxml documentation", "max_results": 2}))
            quick = time.monotonic() - t0
            await http.post("/approvals/window", json={"action": "close"})
        check("15-minute window: no question asked", out.startswith("Web results for"), f"{quick:.1f}s")

    entries = [json.loads(line) for line in LOG.open(encoding="utf-8")][lines_before:]
    calls = [e for e in entries if e.get("tool") and not e.get("event")]
    decisions = [e for e in entries if e.get("event") == "approval_decision"]
    check("every call logged", len(calls) == 7, f"{len(calls)} tool calls")
    check("every decision on the page logged", len(decisions) == 4, f"{len(decisions)} decisions")
    decided_by = {str(e.get("decided_by")) for e in calls}
    check("log records who decided",
          {"person:approval-page", "timeout", "policy:url-check", "person:allow-window"} <= decided_by,
          str(sorted(decided_by)))
    ok, n, msg = verify(LOG)
    check("audit chain intact", ok, f"{n} entries")

    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "tampered.jsonl"
        shutil.copy(LOG, copy)
        # A believable edit: turn a declined call into an allowed one. The line
        # stays valid JSON, so only the hash chain can catch it.
        lines = copy.read_text(encoding="utf-8").splitlines()
        target = next(i for i, line in enumerate(lines[:-1]) if '"decision": "declined"' in line)
        lines[target] = lines[target].replace('"decision": "declined"', '"decision": "allowed"', 1)
        json.loads(lines[target])
        copy.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ok, n, msg = verify(copy)
        check("edited entry detected by the hash chain", not ok and "chain broken" in msg,
              f"edited entry {target + 1}; {msg}")

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
