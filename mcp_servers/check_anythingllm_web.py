"""End to end: an AnythingLLM agent uses our web_access server, and a
scripted stand-in for the person approves on the approval page.

Needs AnythingLLM (stage 0 container) with sih-web registered, and
web_access running in ask mode:

    .venv\\Scripts\\python -m mcp_servers.web_access --mode ask
    .venv\\Scripts\\python -m mcp_servers.check_anythingllm_web [model]

Shows which tools the agent called (container log), what the person was asked
(approval page), what the agent answered, and the audit-log entries.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from mcp_servers.audit import LOG_DIR, verify

ROOT = Path(__file__).resolve().parent.parent
ALLM = "http://127.0.0.1:3001/api"
KEY = (ROOT / "stage0" / "anythingllm" / "api_key.txt").read_text(encoding="utf-8").strip()
PAGE = "http://127.0.0.1:8766"
TOKEN = (LOG_DIR / "web_access_approval_url.txt").read_text(encoding="utf-8").split("token=")[1].strip()
LOG = LOG_DIR / "web_access_tool_calls.jsonl"
MODEL = sys.argv[1] if len(sys.argv) > 1 else "granite4.1:8b"
QUESTION = ("@agent Search the web for what the Indian standard OISD-STD-116 covers, "
            "then answer in two sentences and give the link you used.")


async def stand_in_person(stop: asyncio.Event, seen: list[dict]) -> None:
    """Approve every request that appears, like a person clicking Approve."""
    async with httpx.AsyncClient(base_url=PAGE, headers={"X-Approval-Token": TOKEN}) as http:
        while not stop.is_set():
            for p in (await http.get("/approvals/state")).json()["pending"]:
                seen.append(p)
                await http.post("/approvals/decide", json={"id": p["id"], "decision": "approve"})
            await asyncio.sleep(0.3)


async def main() -> int:
    since = datetime.now(timezone.utc).isoformat()
    log_start = sum(1 for _ in LOG.open(encoding="utf-8"))
    headers = {"Authorization": f"Bearer {KEY}"}
    async with httpx.AsyncClient(base_url=ALLM, headers=headers, timeout=300) as api:
        ws = (await api.post("/v1/workspace/new", json={"name": f"web-demo-{datetime.now():%H%M%S}"})).json()
        slug = ws["workspace"]["slug"]
        await api.post(f"/v1/workspace/{slug}/update", json={"agentProvider": "ollama", "agentModel": MODEL})
        print(f"workspace {slug}, agent model {MODEL}")

        stop, seen = asyncio.Event(), []
        person = asyncio.create_task(stand_in_person(stop, seen))
        t0 = time.monotonic()
        r = await api.post(f"/v1/workspace/{slug}/chat",
                           json={"message": QUESTION, "mode": "chat", "sessionId": "web-demo"})
        stop.set()
        await person
        secs = round(time.monotonic() - t0, 1)

    reply = r.json().get("textResponse") if r.status_code == 200 else r.text
    print(f"\n--- asked the person ({len(seen)}):")
    for p in seen:
        print(f"  {p['tool']}: {p['target']!r}  warnings={p['warnings']}  client={p['client']}")
    print(f"\n--- agent reply ({secs}s, HTTP {r.status_code}):\n{reply}")

    out = subprocess.run(["docker", "logs", "--since", since, "anythingllm-stage0"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    lines = [re.sub(r"\x1b\[[0-9;]*m", "", line) for line in (out.stdout + out.stderr).splitlines()]
    print("\n--- skills attached to the agent:")
    for line in lines:
        if "Attached" in line and "plugin" in line or "MCP tool to Agent" in line:
            print("  " + line.split("] ", 1)[-1][:110])
    print("--- tools the agent called:")
    for line in lines:
        if "is attempting to call `" in line:
            print("  " + line.split("is attempting to call `", 1)[1].split("`", 1)[0])

    print("\n--- audit log entries from this run:")
    for line in LOG.open(encoding="utf-8").readlines()[log_start:]:
        e = json.loads(line)
        print(f"  {e.get('event') or e.get('tool'):18} {e.get('decision', ''):9} "
              f"{e.get('decided_by', ''):22} {e.get('outcome', '')} {e.get('query') or e.get('url') or e.get('target') or ''}")
    ok, n, msg = verify(LOG)
    print(f"  chain: {'OK' if ok else 'BROKEN'} ({n} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
