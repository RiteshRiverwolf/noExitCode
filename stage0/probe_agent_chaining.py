"""Why does AnythingLLM's agent skip the document search in Test B?

Runs the approval-note request in three wordings, several times each, and
records for every run whether the agent called the document-search skill
(`rag-memory`, read from the container log) and our Word tool (read from our
own tool log), and whether the note names the below-minimum reading.

  V1 original   -- Test B's wording: names our tool, asks for a search in prose
  V2 no-tool    -- same, but does not name any tool
  V3 explicit   -- names both tools and the order: rag-memory search, then Word

    .venv\\Scripts\\python stage0\\probe_agent_chaining.py

Writes results/stage0/probe_chaining_<timestamp>.json.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_integration_test as h  # noqa: E402

REPS = int(os.environ.get("PROBE_REPS", "3"))
MODEL = os.environ.get("PROBE_MODEL", h.MODEL)  # any Ollama model with tool support
CONTAINER = "anythingllm-stage0"


def variants(tag: str) -> dict[str, str]:
    ask = (f"List each finding with its severity, and every thickness reading "
           f"with its minimum required value.")
    return {
        "V1 original": (
            f"@agent Search this workspace's documents for the inspection report on "
            f"equipment {tag}. {ask} Then use the create_word_document tool to write "
            f"a short approval note titled 'Approval Note {tag}' that summarises them."
        ),
        "V2 no-tool": (
            f"@agent Search this workspace's documents for the inspection report on "
            f"equipment {tag}. {ask} Then write a short Word approval note titled "
            f"'Approval Note {tag}' that summarises them."
        ),
        "V3 explicit": (
            f"@agent Step 1: call the rag-memory tool with action 'search' to find the "
            f"inspection report on equipment {tag}. Step 2: from the search results "
            f"only, {ask[0].lower() + ask[1:]} Step 3: call create_word_document with "
            f"title 'Approval Note {tag}' and a body summarising them, including every "
            f"reading below its minimum."
        ),
    }


def agent_tools_since(since_iso: str) -> list[str]:
    """Tool names the agent tried to call, from the container log."""
    out = subprocess.run(
        ["docker", "logs", "--since", since_iso, CONTAINER],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    tools = []
    for line in (out.stdout + out.stderr).splitlines():
        if "is attempting to call `" in line:
            tools.append(line.split("is attempting to call `", 1)[1].split("`", 1)[0])
    return tools


def main() -> int:
    key = h.KEY_FILE.read_text(encoding="utf-8").strip()
    api = h.Api(key)
    facts = h.expected_facts()

    code, body, _ = api.call("POST", "/v1/workspace/new", json={
        "name": f"probe-{datetime.now():%H%M%S}", "chatMode": "chat", "openAiTemp": 0.2})
    slug = h.field(body, "workspace", "slug")
    api.call("POST", f"/v1/workspace/{slug}/update",
             json={"agentProvider": "ollama", "agentModel": MODEL})
    code, body, secs, docs, text = h.upload(api, h.SCAN, "image/png", slug)
    print(f"model {MODEL}; workspace {slug}; scan upload {code}, {len(text)} chars")

    runs = []
    for name, message in variants(facts["tag"]).items():
        for rep in range(1, REPS + 1):
            since = datetime.now(timezone.utc).isoformat()
            offset, t0 = h.tool_log_len(), __import__("time").time()
            code, body, secs = api.call(
                "POST", f"/v1/workspace/{slug}/chat",
                json={"message": message, "mode": "chat",
                      "sessionId": f"probe-{name.split()[0]}-{rep}"},
                timeout=h.CHAT_TIMEOUT,
            )
            files = h.docx_since(t0)
            note = h.docx_text(files[-1]) if files else ""
            checks = h.content_checks(note, facts) if note else {}
            agent_tools = agent_tools_since(since)
            run = {
                "variant": name, "rep": rep, "status": code, "seconds": secs,
                "agent_tools_in_order": agent_tools,
                "searched_documents": any("rag-memory" in t for t in agent_tools),
                "word_file": bool(files),
                "note_correct": bool(checks) and all(checks.values()),
                "note": note,
                "reply": h.field(body, "textResponse"),
            }
            runs.append(run)
            print(f"{name:12} #{rep}: tools={agent_tools} searched={run['searched_documents']} "
                  f"word={run['word_file']} correct={run['note_correct']} ({secs}s)")

    print("\nsummary (searched / word file / correct note, out of runs):")
    for name in variants(facts["tag"]):
        rs = [r for r in runs if r["variant"] == name]
        print(f"  {name:12} {sum(r['searched_documents'] for r in rs)}/{len(rs)}  "
              f"{sum(r['word_file'] for r in rs)}/{len(rs)}  "
              f"{sum(r['note_correct'] for r in rs)}/{len(rs)}")

    safe_model = MODEL.replace(":", "-").replace("/", "-")
    out = h.RESULTS / f"probe_chaining_{safe_model}_{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps({"model": MODEL, "workspace": slug, "runs": runs},
                              indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
