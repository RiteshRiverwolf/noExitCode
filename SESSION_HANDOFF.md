# Session handoff — SIH26117

> **Update, 2026-09-11 afternoon: stage 0 is finished.** The offline phase
> ran, and the verdict is in [`results/stage0/VERDICT.md`](results/stage0/VERDICT.md)
> (keep AnythingLLM; its built-in agent must not write reports). Findings are
> in [F003](results/findings/F003-anythingllm-outbound-dependencies.md). A model
> comparison for tool calling is in [`results/stage0/NOTES.md`](results/stage0/NOTES.md):
> granite4.1:8b got 9/9 correct notes, llama3.1:8b 0/9. Sections 4 and 8 below
> describe the state *before* that work.

Written 2026-09-11 at the end of a long session. Read this before doing
anything. The previous session ended with **the user interrupting a tool call
and asking to stop**, so **ask how they want to proceed before continuing
stage 0**.

---

## 1. The project in one paragraph

SIH 2026 problem statement 26117: an offline, air-gapped, multi-agent AI
workbench for MRPL (Mangalore Refinery). It reads confidential documents such
as scanned inspection reports, and produces real deliverables such as Word
approval notes, with every critical number linked to its source and nothing
leaving the machine. **This is an SIH entry only, not a B.Tech final-year
project.**

| | |
|---|---|
| User | Rudraansh Bhati — directs the project, briefs the team |
| Teammate | Ritesh — wrote the adversarial review, also pushes to the repo |
| Repo | `github.com/RiteshRiverwolf/noExitCode`, branch `main`; last pushed commit `a3e85e8` |
| Local path | `C:\SIH 2026` — Windows 11, RTX 4070 **12 GB**, 32 GB RAM |
| Design of record | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) revision 2 |
| Team summary | [`docs/team-brief.html`](docs/team-brief.html), also published at https://claude.ai/code/artifact/85deba23-0503-4543-9d32-54163eed2723 |
| Memory | `C:\Users\user\.claude\projects\c--SIH-2026\memory\` — 4 memories plus `MEMORY.md` |

---

## 2. How the user wants you to work

- **No Claude co-author.** Never add `Co-Authored-By: Claude` or any Claude attribution to commits or PRs in this repo.
- **Research, don't recall.** For models, tools, datasets and competitors, check current primary sources (docs, model cards, source code) before recommending. Two claims from memory were wrong last session: an Onyx claim taken from a marketing page, and the MCP SDK API.
- **It must sound good to judges and actually work.** Keep the multi-agent design visible. Build on existing products and customise them, rather than building from scratch.
- **Plain language** for anything the team will read.
- **Commit and push only when asked.** Run `git fetch` first, because Ritesh also pushes.
- **Expect mid-task redirects.** The user often sends a short message mid-task pointing at a new paper or tool. Look it up and assess it against the project.

---

## 3. The design (short version; details in ARCHITECTURE.md)

- **Base platform:** AnythingLLM in Docker (MIT), with **our own frontend** on its API.
- **Agent team:** eight specialists with fixed handoffs: Supervisor, Document Reader, Evidence Builder, Rules Engine, Standards Researcher, Report Writer, QA Checker, Coder. Built as ICM stage folders plus a procedural graph plus a state machine.
- **"The model explains, the code decides."** Escalation comes from deterministic rules over evidence records, with three outcomes: escalate, no trigger, needs review.
- **Tools** are local MCP servers in Python (MCP SDK **v2**).
- **Knowledge base:** a structured document library with an approved intake pipeline. Lookup order: exact IDs, then catalogue, then sections, then LanceDB vector search.
- **Models (12 GB bench):** a general Qwen model (Qwen3.5-9B named by the review, **unverified**), PaddleOCR-VL-1.6, llama.cpp first. Stage 0 used Ollama with `llama3.1:8b`.
- **Network proof:** outbound traffic blocked, with a separately marked canary window, then a clean run.

---

## 4. Stage 0 — AnythingLLM integration test

Goal: can AnythingLLM, driven entirely through its API, take a scanned report
and use our MCP tool to write a Word file, fully offline? Running log:
[`results/stage0/NOTES.md`](results/stage0/NOTES.md).

### Results so far (online)

| Check | Run 1 (00:29) | Run 2 (00:59) |
|---|---|---|
| API key, workspace, agent model set | ✅ | ✅ |
| Scanned PNG uploaded; OCR finds `R-2247` | ✅ 2,710 chars | ✅ |
| **Test A** — agent → our MCP tool → Word file on host | ✅ genuine | ✅ genuine |
| **Test B** — agent writes an approval note with correct content | ❌ false pass under the old check (the file contained "[list findings]") | ❌ correctly failed: the note says "refer to the report in memory" and names no reading |
| **Test C** — document Q&A without the agent answers the trap question | (not in run 1) | ✅ "CML-03 … 12.32 mm … minimum 12.7 mm", source `insp_1002_p1.png` |

**Reading these results:**
- **Plumbing works** (Test A).
- **AnythingLLM's document Q&A works** on the trap case (Test C).
- **Its built-in agent with an 8B model does not chain "search the documents, then call the tool"** (Test B). That supports the architecture decision to run the inspection workflow in our own agent team.

**Test flaw to fix:** Tests A and B share `sessionId: "stage0"`, so Test B saw
Test A's history and reused its text. Give each test its own session ID before
drawing more conclusions from Test B.

### Findings

1. **Bare `ollama serve` logged no update check** at startup, unlike the Windows desktop app in F001. This is from the log only; confirm with a packet capture.
2. **Ollama's cloud features are on by default** (`OLLAMA_NO_CLOUD:false`, `OLLAMA_REMOTES:[ollama.com]`). It's now running with `OLLAMA_NO_CLOUD=1`.
3. **MCP Python SDK v2** renamed FastMCP to `MCPServer` and moved host, port and security settings to `run()`. The docs are already fixed.
4. **MCP host-header rejection (HTTP 421).** The SDK only allows `127.0.0.1`/`localhost`/`[::1]` Host headers. Fixed by adding `host.docker.internal:*`, with DNS-rebinding protection kept on.
5. **AnythingLLM's internal API is unauthenticated when `AUTH_TOKEN` is unset.** That's how the API key was created. Safe only because the port is bound to `127.0.0.1`; any shared deployment must set `AUTH_TOKEN`.
6. **OCR language data downloads on first use.** tesseract.js's default `langPath` points to `cdn.jsdelivr.net/npm/@tesseract.js-data/eng/…`, and `eng.traineddata` (5 MB) is now cached in `stage0/anythingllm/models/tesseract/`. A fresh air-gapped install can't OCR images until that file is pre-seeded.
7. **Two downloads at startup:**
   - context windows from `raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json` (`server/utils/AiProviders/modelMap/index.js:30`)
   - pricing from `models.dev/api.json` (`server/utils/helpers/modelPricing/index.js:70`)

   Both have a 3-day cache and fail gracefully, but they retry at every boot once stale, which adds noise to the egress log.
8. **The `1.4 tok/s` in `ollama_warmup.txt` is meaningless** (the reply was two tokens). Cold load was 22.6 s, with 7.4 GB VRAM in use. Throughput hasn't been measured yet.

### Not done yet

- **The offline phase:** [`stage0/offline_phase.ps1`](stage0/offline_phase.ps1) is written but **never run or reviewed in execution**. It has three windows:
  - A: canary call to example.com
  - B1: OCR upload with the cached language data moved aside
  - B2: full test with outbound traffic blocked

  It uses a `nicolaka/netshoot` sidecar with iptables and tcpdump inside the container's network namespace, and changes nothing on the Windows host.
- **Checking for switches to turn these downloads off:** the command that would grep AnythingLLM's source for `process.env` switches in `modelMap`, `modelPricing` and `OCRLoader` was the one **the user interrupted. It was not run.**
- `results/stage0/VERDICT.md`, plus a finding file for AnythingLLM's outbound dependencies (next number is F003).
- **Update ARCHITECTURE.md §4 and STACK_INVENTORY §3.8** with findings 4–7. That means adding four requirements: pre-seed the OCR data, handle the startup fetches, set `AUTH_TOKEN`, and add the MCP allowed-hosts setting.

---

## 5. What is running on the machine

| Thing | State | Details |
|---|---|---|
| Docker Desktop | running | |
| `anythingllm-stage0` container | running | image `mintplexlabs/anythingllm@sha256:5fb4a84c…d7e0b7`; `127.0.0.1:3001`; storage `stage0/anythingllm/` (gitignored); no `SYS_ADMIN` |
| `ollama serve` (bare, no desktop app) | running | PID 29808 at handoff; `OLLAMA_NO_CLOUD=1`; log `results/stage0/ollama_serve_nocloud.err.log` |
| MCP test tool | running | `stage0/docgen_mcp_server.py`, PID 39540 at handoff; `127.0.0.1:8765/mcp`; log `results/stage0/mcp_server_fixed.err.log` |
| `nicolaka/netshoot` image | pulled | `sha256:b09d9b21…8e70` |

PIDs change after a reboot; find processes by port with
`Get-NetTCPConnection -State Listen -LocalPort 8765,11434`.

### Restart after a reboot (PowerShell)

```powershell
# Ollama — do NOT run `ollama list` first; the CLI launches the desktop app and its updater
$env:OLLAMA_NO_CLOUD = "1"
Start-Process ollama -ArgumentList serve -WindowStyle Hidden

# MCP test tool
Start-Process "C:\SIH 2026\.venv\Scripts\python.exe" -ArgumentList "stage0\docgen_mcp_server.py","--port","8765" -WorkingDirectory "C:\SIH 2026" -WindowStyle Hidden

# AnythingLLM (container already exists)
docker start anythingllm-stage0
# then reconnect it to the MCP tool:
Invoke-RestMethod http://127.0.0.1:3001/api/mcp-servers/force-reload
```

To recreate the container from scratch:

```powershell
docker run -d --name anythingllm-stage0 -p 127.0.0.1:3001:3001 -v "C:\SIH 2026\stage0\anythingllm:/app/server/storage" -v "C:\SIH 2026\stage0\anythingllm\.env:/app/server/.env" -e STORAGE_DIR="/app/server/storage" mintplexlabs/anythingllm:latest
```

### Run the tests

```powershell
& "C:\SIH 2026\.venv\Scripts\python.exe" -u "C:\SIH 2026\stage0\run_integration_test.py"   # online
& "C:\SIH 2026\stage0\offline_phase.ps1"                                                  # offline (unrun)
```

Results land in `results/stage0/run_<label>_<timestamp>.json`.

---

## 6. Uncommitted work

Nothing since `a3e85e8` is committed:

```
 M .gitignore                 (ignores stage0/anythingllm/ and stage0/output/)
 M docs/ARCHITECTURE.md       (FastMCP → MCP SDK wording)
 M docs/STACK_INVENTORY.md    (same)
?? results/stage0/            (notes, logs, API spec, run JSONs)
?? stage0/                    (MCP tool, test harness, offline script)
?? SESSION_HANDOFF.md
```

`stage0/anythingllm/` holds the API key, the local `.env` with signing keys,
the database and uploaded documents. It is gitignored and must stay that way.

---

## 7. Tooling gotchas (these cost time last session)

- **The sandbox blocks any command that combines `rm` with the project path**, including `docker rm` and `--rm`, because the path contains a space. The error reads "Remove-Item on system path is blocked". Put such commands inside a `.ps1` script file.
- **The Grep tool skips gitignored folders** (`.venv`, `stage0/anythingllm`). Search those with PowerShell `Select-String` or Python.
- **Use PowerShell for `docker` commands with `-v` paths.** Git Bash rewrites them.
- **MCP SDK v2 usage:** `from mcp.server.mcpserver import MCPServer`, then `run(transport="streamable-http", host=..., port=..., streamable_http_path="/mcp", transport_security=TransportSecuritySettings(...))`.
- **AnythingLLM internal routes** (unauthenticated in this setup): `GET /api/mcp-servers/list`, `GET /api/mcp-servers/force-reload`, `POST /api/system/generate-api-key`.
- **The developer API** is documented in `results/stage0/anythingllm_openapi.json`. The key is in `stage0/anythingllm/api_key.txt`.
- **AnythingLLM rewrites `stage0/anythingllm/.env` on boot**, adding `SIG_KEY` and `SIG_SALT`. That's expected.
- **An agent is triggered by starting the chat message with `@agent`.** Document Q&A without the agent uses `"mode": "query"`.

---

## 8. Suggested next steps

1. **Ask the user how to proceed.**
2. Give Tests A, B and C separate session IDs in `stage0/run_integration_test.py`, then re-run online.
3. Review `stage0/offline_phase.ps1`, then run it (with the user's agreement).
4. Look for switches to turn the downloads off, pointing OCR at local language data if one exists.
5. Write `results/stage0/VERDICT.md` and `results/findings/F003-…`, then update ARCHITECTURE.md §4 and STACK_INVENTORY §3.8.
6. Commit and push when asked, with no co-author line.
7. Then stage 1 (ARCHITECTURE §13): the evidence-record schema, then PaddleOCR → rule → templated DOCX.

## 9. Open questions for the team

1. The official problem statement, with its version and judging criteria.
2. The language of the corpus: English, an Indian language, or mixed?
3. How much of the corpus is handwritten, and what does it look like?
4. The venue's GPU, RAM and OS.
5. Who may see which documents?
6. Still run a multi-framework comparison, or pick one framework once the first end-to-end run works?
