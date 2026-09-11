# Session handoff — SIH26117

Updated 2026-09-11, late evening, at the end of a long session. Read this
before doing anything, then **ask the user how to proceed**. Several decisions
are waiting on them (section 8).

---

## 1. The project in one paragraph

SIH 2026 problem statement 26117: an offline, air-gapped, multi-agent AI
workbench for MRPL (Mangalore Refinery). It reads confidential documents such
as scanned inspection reports, and produces real deliverables such as Word
approval notes, with every critical number linked to its source and nothing
leaving the machine. **This is an SIH entry only, not a B.Tech final-year
project.** The judged requirements R1–R6 are in `docs/PS_ANALYSIS.md`; the
official text is in `docs/PS26117.md` ("Expected Solution").

| | |
|---|---|
| User | Rudraansh Bhati — directs the project, briefs the team |
| Teammate | Ritesh — pushes often (frontend, guidelines); always `git fetch` first |
| Repo | `github.com/RiteshRiverwolf/noExitCode`, branch `main`; local = origin at `43d33f8` |
| Local path | `C:\SIH 2026` — Windows 11, RTX 4070 **12 GB**, 32 GB RAM |
| Design of record | `docs/ARCHITECTURE.md` rev 2 (+ stage 0 result in §4) |
| Pitch / scaling doc | `docs/HARNESS_AND_ROADMAP.md` (new, uncommitted) — marks every claim Proven / Built / Proposed |
| Memory | `C:\Users\user\.claude\projects\c--SIH-2026\memory\` — 6 memories plus `MEMORY.md` |

---

## 2. How the user wants you to work

- **No Claude co-author.** No `Co-Authored-By: Claude` or other Claude attribution in commits or PRs in this repo.
- **Commit and push only when asked.** `git fetch` first. Use `git pull --no-rebase` (merge): a rebase got stuck on log files held open by running services.
- **Research, don't recall.** Check models, tools, licences and papers in primary sources before recommending anything.
- **Impress the judges and actually work.** Keep the multi-agent design visible. Build on existing products. Pitch what we can't build (knowledge graph, 30B+ models) as a staged roadmap backed by published benchmarks, marked as proposed.
- **Plain language** for anything the team reads.
- **Expect mid-task redirects**, and "stop the process" requests. Stop cleanly: kill the processes, restart the AnythingLLM container to cancel an agent run, and unload models (section 6).
- **Never run a Docker prune.** Docker Desktop is shared with another project (Ripple, `D:\Ripple`). On 2026-09-11 a `docker container prune` deleted its four stopped containers. The user said to leave them.
- **Presentation framing** (user decision): test only what fits the 12 GB bench; present bigger models as the upgrade path, backed by measured results rather than "bigger is obviously better".

---

## 3. Where things stand

| Req | What | Status |
|---|---|---|
| R1 | Local deployment, one mid-range GPU | Mostly done: AnythingLLM + Ollama + our MCP tools on the RTX 4070 |
| R2 | Automatic model choice for ≥2 task types | **Not built.** Designed as rules (image → vision model, code → coder, else Granite), with every choice logged |
| R3 | Scan → findings → Word approval note | **Built from evidence onward** (`workbench/`); **reading the scan is not built** |
| R4 | Coding task verified in a sandbox | Not started |
| R5 | Image / scanned-document understanding | Not started. qwen3.5:9b (vision) is installed |
| R6 | Visible proof of no external calls | Container-level proof done (stage 0). Frontend panel is **not connected** and shows a hard-coded "0" |

### Done and committed (up to `43d33f8`)
- **Stage 0 verdict:** keep AnythingLLM for chat and search; its built-in agent must not write reports. See `results/stage0/VERDICT.md` and finding F003 (a fresh offline install crashes on its first scan unless `eng.traineddata` is pre-seeded).
- **`mcp_servers/web_access.py`:** the only route to the internet. Modes off / ask / allow, an approval page on 127.0.0.1 with a token, a hash-chained log, and 15/15 checks. AnythingLLM's own web skills are disabled.
- **Ritesh's frontend prototype** (`frontend/index.html`) and his 13 guidelines (the file `counter features`).

### Done this session, **not committed**
- **`workbench/`, the inspection pipeline**, run by a Procedural Graph:
  `read_document → build_evidence → apply_rules → write_summary → render_note → qa_check`.
  - `evidence.py`: evidence records. **Stand-in:** built from `data/corpus/truth/*.json`, not the scan. Every note says so in amber.
  - `rules.py`: THK-01, SEV-01, EVD-01 → ESCALATE / NO TRIGGER / NEEDS REVIEW. Decimal arithmetic; demo rule set.
  - `prose.py`: Granite writes the summary, and code checks it for numbers not in the evidence, invented breaches, a measured value given as a minimum, wrong units, severity miscounts, and verdict words. One repair attempt, then a code-written fallback. Length is style only.
  - `report_writer.py`: a two-page styled Word note (python-docx) and a read-back verification.
  - `procedural_graph.py` + `graphs/inspection.yaml`: enforced transitions, retry budgets, and a self-healing loop (QA fail → re-render). Edge notes are given to the model as guidance.
  - `run_inspection.py`: `python -m workbench.run_inspection insp_1002 [--inject-fault render] [--no-model]`.
- **Results on the 12-report corpus:** rules 12/12 correct; final run 12/12 summaries accepted (9 clean, 1 repaired, 2 long but accurate); 12/12 read-back passes.
- **What the checker caught:** Granite invented thickness breaches (insp_1006, insp_1008), gave measured values as minimums (insp_1011), and miscounted severities. The fix that worked was giving the model each reading's status and the severity counts from code.
- **Model tests** (`results/stage0/NOTES.md`, corrected checker): granite4.1:8b **9/9** (twice), qwen3.5:9b 6/9 (never wrong, sometimes no file), lfm2.5:8b 0/9 (licence free only under $10M revenue), llama3.1:8b 0/9. Sarvam-M 24B: one run of 590 s, no file, no tool support in its Ollama build, stopped by the user. Sarvam 30B: downloaded, **not tested**. Sarvam has no 10B model; the 105B (59.8 GB) doesn't fit.
- **`stage0/run_integration_test.py`:** tests use separate sessions; the note checker judges safety content (hyphen-normalised).
- **`docs/HARNESS_AND_ROADMAP.md`:** models as plug-ins (registry, qualification tests, hardware tiers), Procedural Graph self-evolution (validation + engineer approval), a three-layer knowledge graph (recorded → LightRAG → HippoRAG 2), and Ritesh's 13 guidelines mapped to status.
- **`.gitignore`:** adds `logs/` and `runs/`, and ignores full packet captures (they contain the API key).

Uncommitted file list: `.gitignore`, `results/stage0/NOTES.md`, `stage0/run_integration_test.py`, `docs/HARNESS_AND_ROADMAP.md`, `workbench/`, plus several new files in `results/stage0/` (probe JSONs and logs). **Don't commit** `results/stage0/tool_calls.jsonl` or the live `*_run4*` / `*nocloud3*` logs; they're written by running services.

---

## 4. Key findings to remember

1. **Model size didn't predict results.** Four 8–9B models scored 0–9 out of 9.
2. **Even the best model invents facts.** That's why code decides and every number is checked.
3. **llama3.1:8b makes one tool call and stops.** Granite and Qwen chain calls properly.
4. **AnythingLLM:** tool approval works only in its web UI or Telegram (auto-denied over the API). Its MCP client (SDK 1.24.3) has no approval step or elicitation. It waits 60 s per tool call (JS SDK default). It names its MCP client after the server entry.
5. **Frontend offline gap:** `frontend/index.html` line 7 loads `https://cdn.tailwindcss.com`. Offline it loses all styling, and the monitor would log an external call. Not fixed, because it's Ritesh's file.
6. **The Procedural Graphs paper** (Lu, Chen, Wu, Arık, arXiv 2609.09153): the refiner keeps an edit only if held-out validation holds, and remembers rejected edits.

---

## 5. What's running

| Thing | Port | Details |
|---|---|---|
| Docker Desktop | | running |
| `anythingllm-stage0` | 3001 | image `mintplexlabs/anythingllm@sha256:5fb4a84c…d7e0b7`; storage `stage0/anythingllm/` (gitignored); web skills disabled; MCP servers `sih-docgen` and `sih-web` |
| `ollama serve` | 11434 | `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`, `OLLAMA_NO_CLOUD=1`, log `results/stage0/ollama_serve_nocloud3.err.log` |
| Word MCP tool | 8765 | `stage0/docgen_mcp_server.py` |
| Web access MCP | 8766 | `-m mcp_servers.web_access --mode ask --approval-timeout 45`; approval link in `logs/web_access_approval_url.txt` |

Models: granite4.1:8b, qwen3.5:9b, lfm2.5:8b, llama3.1:8b, nomic-embed-text,
`hf.co/bartowski/sarvamai_sarvam-m-GGUF:Q4_K_M` (13.3 GB),
`hf.co/DevQuasar/sarvamai.sarvam-30b-GGUF:Q4_K_M` (18.2 GB).
AnythingLLM's default chat model is still llama3.1:8b.

### Restart after a reboot (PowerShell)

```powershell
# Ollama -- don't use the `ollama` CLI (it starts the desktop app and its updater); use the API
$env:OLLAMA_NO_CLOUD = "1"
Start-Process "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" -ArgumentList serve -WindowStyle Hidden

# Our MCP servers (run from the repo root)
Start-Process "C:\SIH 2026\.venv\Scripts\python.exe" -ArgumentList "stage0\docgen_mcp_server.py","--port","8765" -WorkingDirectory "C:\SIH 2026" -WindowStyle Hidden
Start-Process "C:\SIH 2026\.venv\Scripts\python.exe" -ArgumentList "-m","mcp_servers.web_access","--mode","ask","--port","8766" -WorkingDirectory "C:\SIH 2026" -WindowStyle Hidden

# AnythingLLM, then reconnect it to both MCP servers
docker start anythingllm-stage0
Invoke-RestMethod http://127.0.0.1:3001/api/mcp-servers/force-reload
```

### Useful commands

```powershell
.venv\Scripts\python -m workbench.run_inspection insp_1002            # full pipeline, trap case
.venv\Scripts\python -m workbench.run_inspection insp_1002 --inject-fault render   # self-healing demo
.venv\Scripts\python -m mcp_servers.check_web_access                   # 15 checks (server in ask mode)
.venv\Scripts\python -m mcp_servers.audit logs\workbench_runs.jsonl    # verify a hash-chained log
$env:PROBE_MODEL="granite4.1:8b"; .venv\Scripts\python stage0\probe_agent_chaining.py   # 9-run tool test
```

Notes land in `runs/<job-id>/05_render_note/`. Word can export a note to PDF
over COM (`Word.Application`, `SaveAs2(path, 17)`) for a visual check.

---

## 6. Tooling gotchas (these cost time)

- **The sandbox blocks `Remove-Item` or `rm` together with the project path** (the path contains a space). Put such commands in a `.ps1` file in the scratchpad.
- **Stopping cleanly:** kill the runner and probe processes; then `docker restart anythingllm-stage0` to cancel an in-flight agent reply; then unload models with `POST /api/generate {"model": m, "keep_alive": 0}` until `/api/ps` is empty.
- **Background commands may be killed after 10 minutes.** For long jobs, write a `.ps1` in the scratchpad, launch it with `Start-Process pwsh -File`, and watch its log with the Monitor tool (check the PID too).
- **Ollama can't pull sharded GGUFs** from Hugging Face; use a repository that has single-file quantisations.
- **YAML 1.1 reads a bare `on:` key as `True`.** The graph file uses `when:`.
- **Don't pipe a PowerShell here-string into `git commit -F -`.** Write the message to a file and use `-F <file>`.
- **The Grep tool skips gitignored folders** (`.venv`, `stage0/anythingllm`, `data/corpus`, `logs`, `runs`). Use PowerShell or Python for those.
- **Use PowerShell, not Git Bash, for `docker` commands with `-v` paths.**
- **MCP SDK v2 (2.2.0):** `MCPServer`, `custom_route`, `ctx: Context` injection, and `ctx.elicit` all exist. The client is `from mcp import Client` → `Client("http://…/mcp")`.
- **AnythingLLM internal routes are unauthenticated here** (no `AUTH_TOKEN`): `/api/mcp-servers/force-reload`, `/api/admin/system-preferences`, `/api/system/generate-api-key`. The API key is in `stage0/anythingllm/api_key.txt`.

---

## 7. Open questions for the team

1. The official problem-statement version and its judging criteria.
2. The corpus language: English, an Indian language, or mixed? Granite has no Indian languages; Sarvam does.
3. How much of the corpus is handwritten?
4. The venue's GPU, RAM and OS.
5. Who may see which documents?
6. SIH rules on disclosing AI-assisted development. The code in `workbench/` and `mcp_servers/` was written with Claude Code, and a team member should be able to explain it.

---

## 8. Waiting on the user — ask first

1. **Commit and push** the uncommitted work in section 3 (no co-author line).
2. **Report templates:** (a) add a one-page "simple" template with a template choice, (b) support Word-made templates with placeholders (docxtpl, LGPL-2.1, or our own filler), or (c) both, starting with (a). The safety floor stays the same for every template.
3. **Step ① — reading the scan** (the biggest gap): test qwen3.5:9b on the scans, alongside PaddleOCR-VL, to produce real evidence records with cell positions.
4. **R2 router with visible decisions**, then R4 sandbox, then R6: a small local API feeding the frontend from the hash-chained logs.
5. **Tell Ritesh about the Tailwind CDN**, or fix it together; also switch AnythingLLM's chat default to Granite.
6. **Optional:** a 3-run test of Sarvam 30B (already downloaded; slow on 12 GB); a cold offline start test for R1.
