# Stage 0 — AnythingLLM integration test: running log

Started 2026-09-10. Goal and pass criteria: [ARCHITECTURE §4](../../docs/ARCHITECTURE.md).
Evidence files sit alongside this note.

## Setup (online phase)

| Item | Value |
|---|---|
| AnythingLLM image | `mintplexlabs/anythingllm@sha256:5fb4a84c91735d2880c5cbc83de6de17a06c66d2b3dcd4315169badd74d7e0b7` (created 2026-09-09, 1.10 GB) |
| Container | `anythingllm-stage0`; port bound to `127.0.0.1:3001` only; **no** `SYS_ADMIN` capability (only its web scraper needs it) |
| Model server | bare `ollama serve` (not the desktop app), `OLLAMA_NO_CLOUD=1`; models `llama3.1:8b`, `nomic-embed-text` |
| Test tool | `stage0/docgen_mcp_server.py` — MCP Python SDK v2, streamable HTTP on `127.0.0.1:8765/mcp`; every call logged to `tool_calls.jsonl` |
| AnythingLLM config | `stage0/anythingllm/.env` (gitignored): Ollama for LLM and embeddings, LanceDB, `DISABLE_TELEMETRY=true`; MCP server list in `plugins/anythingllm_mcp_servers.json` |

## Findings so far

1. **Bare `ollama serve` logged no update check** at startup
   (`ollama_serve.err.log`), unlike the Windows desktop app in F001. Log-based
   only; confirm under packet capture in the offline phase.
2. **Ollama ships with its cloud features switched on.** The default server
   config shows `OLLAMA_NO_CLOUD:false` and `OLLAMA_REMOTES:[ollama.com]`. The
   sovereign build must set `OLLAMA_NO_CLOUD=1`; applied and confirmed in
   `ollama_serve_nocloud.err.log`.
3. **MCP Python SDK v2 renamed FastMCP to `MCPServer`**, and host, port and path
   moved from the constructor to `run()`. `docs/ARCHITECTURE.md` and
   `docs/STACK_INVENTORY.md` §3.10 name FastMCP and need updating.

## Progress

- ✅ **Container boots and answers** — `{"online":true}` about 8 s after start.
  The startup log confirms `[TELEMETRY DISABLED] … no events will send`
  (`anythingllm_startup.log`).
- ✅ **Container reaches host Ollama** at `host.docker.internal:11434` (HTTP 200)
  while Ollama listens on `127.0.0.1` only — no need to expose it on the LAN.
- ⚠️ **Container → MCP test tool returned HTTP 421 (Misdirected Request).**
  Cause, from the installed SDK source (`mcp/server/mcpserver/server.py`): an
  MCP server bound to `127.0.0.1` without explicit settings only accepts the
  Host headers `127.0.0.1:*`, `localhost:*` and `[::1]:*`. Requests from
  Docker arrive as `host.docker.internal:8765`. AnythingLLM surfaced this only
  as `Failed to start MCP server: sih-docgen [NO_CODE] fetch failed`. Fix:
  add `host.docker.internal:*` to the allowed hosts, keeping DNS-rebinding
  protection on.
- ⚠️ **AnythingLLM's internal API is unauthenticated when no password is set.**
  Its `validatedRequest` middleware passes every request through when
  `AUTH_TOKEN` is unset — which is how we created an API key without the web
  UI (`POST /api/system/generate-api-key`). Safe here only because port 3001
  is bound to `127.0.0.1`. Any shared or demo deployment must set
  `AUTH_TOKEN` or use multi-user mode.
- ✅ **API key created** without the web UI; stored in
  `stage0/anythingllm/api_key.txt` (gitignored).
- ✅ **API spec extracted** (`anythingllm_openapi.json`, v1.0.0): upload,
  workspace create/update, update-embeddings, chat, stream-chat and
  vector-search are all present.
- ℹ️ **The 1.4 tok/s in `ollama_warmup.txt` is not a throughput figure** — the
  reply was two tokens, so it measures start-up overhead. Cold load of
  `llama3.1:8b` took 22.6 s (`load_duration`); 7.4 GB VRAM in use afterwards.

## Online run 1 — `run_20260911-002923.json`

| Step | Result |
|---|---|
| API key, workspace, agent model | ✅ |
| Scan upload and OCR | ✅ 2,710 characters extracted from the PNG in 28 s; contains `R-2247` |
| Test A — agent → MCP tool → Word file | ✅ **Genuine.** Our tool log and the file on disk match the requested text exactly |
| Test B — agent writes an approval note | ❌ **False pass.** The file contains literal placeholders: "[list findings]", "[list thickness readings]". The agent never read the report (4.5 s end to end). The check only asked whether a file appeared. |

**Harness fixed:** Test B now passes only if the note names the below-minimum
reading from ground truth (CML-03, 12.32 mm against 12.7 mm) and contains no
placeholders. **Test C added:** the same trap question through plain document
retrieval, no agent — the path AnythingLLM owns in our architecture.

## Online run 2 — 00:59

Test A ✅. Test B ❌, correctly failed: the note said "refer to the report in
memory" and named no reading. Test C ✅: "CML-03 … 12.32 mm … minimum 12.7 mm",
source `insp_1002_p1.png`. **Flaw:** Tests A and B shared `sessionId:
"stage0"`, so Test B saw Test A's history.

## Online run 3 — `run_online_20260911-122747.json`

Harness fixed first: Tests A, B and C now use their own sessions
(`stage0-A`, `stage0-B`, `stage0-C`). Services restarted after a reboot.

| Step | Result |
|---|---|
| API key, workspace, agent model, scan upload, OCR finds `R-2247` | ✅ (upload 5 s; language data already cached) |
| Test A — agent → MCP tool → Word file | ✅ 8.4 s |
| Test B — approval note with the right content | ❌ **3.2 s. A confident false approval.** The note says "Thickness readings meet minimum requirements", the opposite of the report (CML-03 is 12.32 mm against a 12.7 mm minimum) |
| Test C — trap question through document Q&A, no agent | ✅ 1.3 s |

**Test B was a fair test.** The container log shows the `rag-memory`
(document search) skill attached to the agent, and llama3.1:8b called
`create_word_document` directly without searching. No agent-skill settings
had been changed in the database (`system_settings` has no agent/skill rows),
so this is the stock configuration.

**What this means for the design:** with an 8B model, AnythingLLM's built-in
agent will write a plausible, wrong approval note rather than read the report
first. That is the exact failure the architecture's "the model explains, the
code decides" rule is there to stop. The inspection workflow stays in our own
agent team with deterministic rules; AnythingLLM's document Q&A (Test C) is
reliable and stays in scope.

## Outbound dependencies found

None of these appear in AnythingLLM's logs. They were spotted as files
appearing in storage, then confirmed in the source.

| What | Where in the source | Destination | When |
|---|---|---|---|
| OCR language data (`eng.traineddata`, 5 MB) | `collector/utils/OCRLoader` sets only `cachePath`, so tesseract.js falls back to its default `langPath` | `cdn.jsdelivr.net/npm/@tesseract.js-data/eng/…` | First OCR of an image |
| Model context windows | `server/utils/AiProviders/modelMap/index.js:30` | `raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json` | Startup; cached in `storage/models/context-windows/` |
| Model pricing | `server/utils/helpers/modelPricing/index.js:70` | `models.dev/api.json` | Startup; cached in `storage/models/pricing/` |

| Agent web skills | `web-scraping` and `web-browsing` are attached to every agent run by default (container log, run 3) | Any URL the model chooses | Whenever the agent decides to use them |

**Implication:** a fresh air-gapped AnythingLLM cannot OCR images until the
language data is pre-seeded — a one-file fix (place `eng.traineddata` in
`storage/models/tesseract/`). Whether the two startup fetches fail gracefully
offline is checked next.

**No switches exist to turn these off** (source searched 2026-09-11 in the
pinned image):
- `OCRLoader` passes tesseract.js only `cachePath` (`STORAGE_DIR/models/tesseract`),
  never `langPath`, and reads no environment variable for it. Pre-seeding the
  cache folder is the only lever short of patching the source.
- `modelMap` and `modelPricing` read no environment variable except
  `NODE_ENV === "test"`, which skips the fetch but is not a production
  setting. Options: pre-seed both caches and keep `.cached_at` fresh, patch
  the two URLs out, or accept a logged, failing fetch at every boot.
- The web skills can be disabled in AnythingLLM's agent-skill settings; to be
  confirmed and set in the sovereign build.

## Offline script review — 2026-09-11

Problems found in `offline_phase.ps1` before its first run, all fixed:
1. **Wrong address family.** `getent hosts host.docker.internal` returns the
   IPv6 address (`fdc4:f303:9324::254`) first; the script fed that to IPv4
   `iptables`, so the Ollama and MCP allow rules would have failed. Now uses
   `getent ahostsv4` (→ `192.168.65.254`).
2. **DNS is not a loopback resolver here.** On Docker's default bridge the
   container asks `192.168.65.7` over eth0, and `host.docker.internal` is not in
   `/etc/hosts`. Blocking egress would have cut AnythingLLM off from Ollama and
   failed B2 for the wrong reason. The script now pins the IPv4 address in
   `/etc/hosts` for the test and restores it afterwards; DNS stays blocked.
3. **IPv6.** The container has no IPv6 address or route today; ip6tables now
   drops everything but loopback anyway.
4. **Canary output was ambiguous** (`000BLOCKED`). Now reports curl's exit code,
   adds a by-IP canary (1.1.1.1) and a reachability check for the MCP tool.
5. **Host sampling missed Ollama's model runner**, which is a separate
   process. Now samples every `ollama*` process each second.

## Still to do

- [x] Restart the MCP tool with the host fix; confirm AnythingLLM lists the tool —
  after `/api/mcp-servers/force-reload`: `sih-docgen running=True`, tool
  `create_word_document` listed. A plain GET from the container now gets HTTP
  400 (malformed MCP request) instead of 421, so the Host check passes.
- [x] Create an API key without the web UI
- [x] Upload a scanned report through the API — OCR works online, but see the dependency above
- [x] Agent run through the API calls the tool; Word file lands on the host (Test A)
- [x] Online run 2 with the stricter Test B and the new Test C
- [x] Online run 3 with separate sessions per test
- [x] Search the source for switches that turn the downloads off (none)
- [x] Review `offline_phase.ps1` (five fixes, above)
- [x] Offline phase (`stage0/offline_phase.ps1`): canary; full task with language data pre-seeded; OCR with no cached language data
- [ ] Check whether the two startup fetches fail gracefully offline (needs a cold offline start)

## Offline run 1 — 12:59 (evidence kept as `*_run1`)

Window A passed. **Window B1 crashed the container** (the OCR language
download fails and tesseract.js throws an uncaught error), so B2 never ran.
Two script flaws showed up: B1 must run last, and dropped packets never reach
tcpdump, so the captures showed no blocked attempts at all.

**Script fixed:** an `NFLOG` rule in front of `DROP` copies every blocked
packet to a second capture (`<window>_dropped.pcap`); B1 now runs last and
records the container's state and last log lines.

## Offline run 2 — 13:32 (`offline_summary.txt`, `pcap/`)

| Window | Result |
|---|---|
| A: canary | ✅ `example.com` exit 6 and `1.1.1.1` exit 28 (both blocked, both in the dropped capture); Ollama 200 and MCP 400 (reached) |
| B2: full task, egress blocked | ✅ OCR, Test A, Test C. ❌ Test B (false approval again: "Thickness readings meet or exceed minimum required values"). Dropped: 2 packets, a reverse lookup of `172.17.0.1`. No external connections; host samples empty |
| B1: no cached language data | 💥 Container crashed again (`exit=1`, not OOM); dropped capture shows the DNS query for `cdn.jsdelivr.net` |

Verdict: [`VERDICT.md`](VERDICT.md). Finding: [F003](../findings/F003-anythingllm-outbound-dependencies.md).

**Incident during the run (not a test result):** cleaning up a throwaway test
container with `docker container prune -f` also deleted four stopped
containers from an unrelated local project (Ripple). Their named volumes
survived. Only named containers are removed from now on.

## Why the agent skips the document search — `probe_chaining_20260911-135316.json`

`stage0/probe_agent_chaining.py` ran the approval-note request in three
wordings, three times each (llama3.1:8b, online, clean session per run):

| Wording | Searched documents | Wrote Word file | Correct note |
|---|---|---|---|
| V1 original (Test B's prompt) | 1/3 | 2/3 | 0/3 |
| V2 without naming any tool | 1/3 | 2/3 | 0/3 |
| V3 explicit steps: "Step 1 call rag-memory … Step 3 call create_word_document" | **0/3** | 3/3 | 0/3 |

**The model makes exactly one tool call per request, then stops.** In 9 of 9
runs it called one tool, never two. When it searched, it didn't write the
file: once it said the report "has not been found", and once it wrote a good
note (it named CML-03 below the 12.7 mm minimum) as chat text instead of
calling the Word tool. When it wrote the file, it hadn't searched.
**Spelling out the steps made it worse:** it jumped straight to the tool named
last.

**The platform is not the limit.** AnythingLLM allows up to 10 chained tool
calls per response (`AGENT_MAX_TOOL_CALLS`, default 10, `aibitat/index.js:87`)
and uses Ollama's native tool calling. The `rag-memory` description is clear:
"Search your local documents and workspace files…".

**Conclusion:** with this model, the sequence must be driven by code, not by
the model: our state machine runs the search/evidence step itself and gives
the model only the writing step, with the evidence already in its context.
Not yet tested: a stronger tool-calling model (only llama3.1:8b is installed).

## Other models for tool calling — 2026-09-11, 14:16–14:42

Same probe (3 wordings × 3 runs, online, AnythingLLM agent defaults incl.
thinking mode), one model at a time. Files:
`probe_chaining_<model>_20260911-*.json`.

| Model (Ollama tag) | Licence | Searched | Word file | Correct note | Wrong note written | Time per request |
|---|---|---|---|---|---|---|
| llama3.1:8b | Llama Community | 2/9 | 7/9 | **0/9** | **7** (false approvals) | 3–12 s |
| qwen3.5:9b | Apache 2.0 | 9/9 | 6/9 | 6/9 | **0** (3 runs wrote no file) | 29–210 s |
| **granite4.1:8b** | **Apache 2.0** | **9/9** | **9/9** | **9/9** | **0** | **15–37 s** |
| lfm2.5:8b (MoE, ~1.5B active) | LFM Open (free only < $10M revenue) | 9/9 | 2/9 | **0/9** (re-scored) | **2** (false approval; self-contradicting CML-03 line) | 21–48 s |

**Checker corrected, 2026-09-11 evening.** The original note check only
asked whether "CML-03", "12.32" and "12.7" appeared *somewhere* in the note.
Two problems came up:
- Granite sometimes writes `CML‑03` with a non-breaking hyphen, so correct
  notes failed. Every hyphen-like character now counts as "-".
- With that fixed, LFM2.5's false approval ("CML-03 … Current 18.75 mm,
  Minimum required 12.32 mm") passed, because every number appears somewhere.

The rule now judges the safety content, not the layout. The CML-03 line must
flag the breach ("below", "<", …); 12.32 mm must be on that line, or anywhere
in the note if the line flags the breach; 12.7 mm must be stated; and no
CML-03 line may give a different minimum. Every saved note was re-scored and
each failure read by hand. Granite 9/9 in both runs, Qwen 6/9 (no wrong
notes), LFM 0/9 (2 wrong), llama 0/9 (7 wrong).

**Granite control run** (`probe_chaining_granite4.1-8b_20260911-175741.json`):
repeated with AnythingLLM's web skills off and our `sih-web` tools attached.
9/9 again. Blemishes: one note had literal `\n` instead of line breaks; one
ended "Prepared by: S. Prakash Nayak … Date: 11 Sep 2026", presenting the
inspector as the author of this note, dated today.

**Granite's notes, checked line by line against `truth/insp_1002.json`:**
all 36 thickness values correct; clauses, inspector name and certificate,
corrosion rate 0.077 mm/yr and remaining life 0 years are all genuinely in
the report. Smaller errors in 4 of 9 notes:
- F-03/F-05 severity given as "No Observation" or "not specified" instead of
  "Observation" (3 notes);
- CML-01 location "2‑80°" instead of 180° (1 note);
- "≥12.7”" with an inch mark (1 note);
- **"Approved by: S. Prakash Nayak"** — the inspector who *wrote* the report,
  presented as the approver (1 note). A fabricated sign-off.

**LFM2.5's wrong note** read clause numbers as severities ("Severity 6.2"),
took the previous reading 18.75 mm as CML-03's current value and 12.32 mm as
its minimum, and ended "Approval is granted".

**Qwen3.5's three misses** searched correctly, then answered in chat (or
returned only thinking text) instead of calling the Word tool.

**What this means:**
- The single-tool-call behaviour was llama3.1:8b's, not AnythingLLM's.
  Granite 4.1 and Qwen3.5 chain search → write reliably.
- Granite 4.1-8B is the best candidate on this test: correct, fast, Apache
  2.0, 5.3 GB. It is text-only, so a vision model is still needed.
- Even the best model mislabels severities and invented a sign-off, so the
  design rule stands: numbers, labels and sign-off fields come from evidence
  records and templates, not from the model.
- Limits: one document, 9 runs per model, online. Needs the full corpus and
  the offline setup before a model is chosen.

## Web search and approval (source, 2026-09-11)

- AnythingLLM's `web-browsing` and `web-scraping` skills **never ask for
  approval**; they don't call `requestToolApproval`.
- With no search provider configured, `web-browsing` uses **You.com's keyless
  API, falling back to DuckDuckGo** (`web-browsing.js`, default branch).
- `requestToolApproval` works only in AnythingLLM's own web UI or its Telegram
  integration. Over the developer API it **auto-denies** anything needing
  approval (`http-socket.js`), unless the skill is listed in
  `AGENT_AUTO_APPROVED_SKILLS`.
- Its MCP client (SDK 1.24.3) has no approval step and doesn't handle MCP
  elicitation, so MCP tools run as soon as the model calls them.
- Our MCP Python SDK (2.2.0) supports elicitation (`Context.elicit`), but its
  own docstring notes an agent client may answer automatically, so it is not
  proof that a person approved.
