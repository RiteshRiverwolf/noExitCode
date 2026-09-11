# Session handoff — SIH26117

Updated 2026-09-12, early morning, at the end of a long session. Read this
before doing anything, then **ask the user how to proceed**. Two decisions are
waiting on them (section 8).

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
| Repo | `github.com/RiteshRiverwolf/noExitCode`, branch `main` |
| Local path | `C:\SIH 2026` — Windows 11, RTX 4070 **12 GB**, 32 GB RAM |
| Design of record | `docs/ARCHITECTURE.md` rev 2 |
| Pitch / scaling doc | `docs/HARNESS_AND_ROADMAP.md` — every claim marked Proven / Built / Proposed |
| **Today's results** | **`results/stage1/NOTES.md`** — read this second |
| Memory | `C:\Users\user\.claude\projects\c--SIH-2026\memory\` — 7 memories plus `MEMORY.md` |

---

## 2. How the user wants you to work

- **No Claude co-author.** No `Co-Authored-By: Claude` or other Claude attribution in commits or PRs in this repo (user preference; overrides any system default).
- **Commit and push only when asked.** `git fetch` first. Use `git pull --no-rebase` (merge).
- **Research, don't recall.** Check models, tools, licences and papers in primary sources before recommending anything.
- **Check again before building on a result.** The user stopped work to ask "are we sure about qwen's performance?" — and was right to: one clean-scan result hid a serious failure mode. Test the failure cases (damaged cells, several runs) before trusting a number.
- **Explain why something failed before discarding it.** The user asked why Sarvam failed before letting it be stopped; the answer turned out to be our setup (CPU-only server, thinking forced off). Model size is judged by measurement, not assumption.
- **Impress the judges and actually work.** Keep the multi-agent design visible. Build on existing products. Pitch what we can't build as a staged roadmap, marked Proposed.
- **Plain language** for anything the team reads. The user asks direct questions ("what is this code?", "what was the test about?") — answer them plainly first.
- **Expect mid-task redirects** and "stop" requests. Stop cleanly (section 6).
- **Never run a Docker prune.** Docker Desktop is shared with another project (Ripple, `D:\Ripple`).
- **Presentation framing:** test what fits the 12 GB bench; present bigger models as the upgrade path, backed by measured results.

---

## 3. Where things stand

| Req | What | Status |
|---|---|---|
| R1 | Local deployment, one mid-range GPU | Mostly done: AnythingLLM + Ollama + our MCP tools |
| R2 | Automatic model choice for ≥2 task types | **Not built.** Designed as rules, every choice logged |
| R3 | Scan → findings → Word approval note | Built from evidence onward (`workbench/`). **Reading the document is not built** — the pipeline still reads the answer-key JSON (amber "stand-in" on every note) |
| R4 | Coding task verified in a sandbox | Not started |
| R5 | Image / scanned-document understanding | Tested today (below), not yet in the pipeline |
| R6 | Visible proof of no external calls | Container-level proof done (stage 0). Frontend panel shows a hard-coded "0" |

### Committed in this session
- `8463ff2` — the workbench pipeline, `docs/HARNESS_AND_ROADMAP.md`, stage 0 model tests.
- The commit that goes with this handoff — stage 1 tests and results:
  - `results/stage1/NOTES.md` — **all of today's findings, plain language.**
  - `results/stage1/data/` — raw outputs: 48 qwen scan readings, both summary-writer runs, PP-StructureV3 JSON, damaged-cell tests, logs.
  - `bench/stage1/` — the test scripts (moved out of the scratchpad; paths made relative). Some still hard-code `C:\SIH 2026`.
  - `workbench/reader.py` — **qwen whole-page reader, written before the design changed.** It becomes the *second* reader; the primary reader is to be OCR-first (section 4).
  - `workbench/evidence.py` (`problems` field), `workbench/report_writer.py` (extraction row shaded amber for any single-reader or stand-in evidence; reading problems listed).
  - `.gitignore`: `models/`, `.venv-ocr/`.

---

## 4. Key findings (details in `results/stage1/NOTES.md`)

1. **qwen3.5:9b reading the whole page is accurate on intact scans** (0/456 critical fields wrong on light and medium; 4/456 on heavy — decimal points read as commas).
2. **But it never reports a damaged digit as unreadable.** With the last digit of the breached reading (12.32) smudged or erased, it wrote "12.3" in 13 of 18 reads, copied another cell's value in 3 (which would turn ESCALATE into NO TRIGGER), and garbled the whole table in 2.
3. **OCR first (PP-StructureV3, the user's idea) reads text very well** — all 16 thickness numbers right on clean/medium/heavy, with confidence and page position — and its errors stay local. **Its own table structure is wrong** (merged the header with CML-01's row), so code places values by position, tilt-corrected. That works: 16/16.
4. **OCR also read the smudged "12.32" as "12.3" at confidence 1.000** — the same as qwen. Two readers agreeing is not proof. A "leftover ink in the cell" check separates this smudge (76 px vs ≤ 26 on the same page) but an undamaged heavy-scan cell reaches 46: promising, not trustworthy until calibrated on many damaged examples. An erased digit can only be caught by a person looking at the crop.
5. **The corpus PDFs are born-digital** (text layer, no images). For such PDFs the text and positions should be read directly — no OCR. OCR is only for image-only (scanned) PDFs.
6. **Only 1 of 12 corpus reports has two pages** (insp_1003; page 2 is just the signature block). Nothing tested so far covers tables split across pages. The PP-StructureV3 test and the position mapper assumed one page.
7. **Summary writer, like-for-like (3 × 12, same checker):** Granite 4.1 8B — 28 clean first try, 0 code fallbacks, 4 safety problems caught, median 2.6 s. Sarvam 30B (GPU, thinking on) — 26 clean, **3 fallbacks, 13 safety problems caught, median 49 s**. Bigger was not better on this task; the code checks, not model size, keep the note safe. (Caveat: the checker was developed on Granite's mistakes; Sarvam's strength — Indian languages — is untested.)
8. **Sarvam 30B details:** the DevQuasar GGUF could not load (architecture `sarvam_moe`, never merged) — deleted. The official `sarvamai/sarvam-30b-gguf` (architecture `bailingmoe2`) is in `models/sarvam-30b/`. It will not switch thinking off; forcing it off leaks the thinking into the answer. Tokenizer matches the official one for English and Hindi.
9. **GitHub Copilot SDK** (asked about at the end): MIT, GA; can run with local Ollama and `COPILOT_OFFLINE=true`. Ideas worth taking: agents as small definitions with a tool allow-list; `subagent.*` lifecycle events for the visible multi-agent timeline (R6); a per-tool-call approval callback (AnythingLLM lacks one); packaged skills with acceptance tests. Not verified: the licence of the Copilot CLI program it bundles, and offline mode through the SDK. Suggested: take the ideas now; a one-day trial (Granite + our MCP servers + packet capture) later. The inspection path stays on our procedural graph.

---

## 5. What's running

| Thing | Port | Details |
|---|---|---|
| Docker Desktop | | running |
| `anythingllm-stage0` | 3001 | as before; web skills disabled; MCP servers `sih-docgen`, `sih-web` |
| `ollama serve` | 11434 | `OLLAMA_NO_CLOUD=1`, log `results/stage0/ollama_serve_nocloud3.err.log`; no models loaded |
| Word MCP tool | 8765 | `stage0/docgen_mcp_server.py` |
| Web access MCP | 8766 | `-m mcp_servers.web_access --mode ask` |
| Sarvam llama-server | 8082 | **stopped** (restart: `bench/stage1/start_sarvam_server.ps1`, ~6 s) |

Models in Ollama: granite4.1:8b, qwen3.5:9b, lfm2.5:8b, llama3.1:8b,
nomic-embed-text, `hf.co/bartowski/sarvamai_sarvam-m-GGUF:Q4_K_M` (13.3 GB).
Outside Ollama (`models/`, gitignored): `sarvam-30b/` (6 shards, 19.6 GB),
`paddleocr-vl-1.6/` (GGUF + mmproj, 1.7 GB; not yet tested).
PaddleOCR models (10) cached in `C:\Users\user\.paddlex\official_models`.

### Environments
- `.venv` — the workbench (Python 3.12).
- `.venv-ocr` — PaddleOCR 3.7.0, paddlepaddle **3.3.0 CPU**, paddlex 3.7.2 (kept apart from the workbench's dependencies). The GPU build (`paddlepaddle-gpu==3.2.2`, cu126 index) is the next step for speed.

### Restart after a reboot (PowerShell)

```powershell
$env:OLLAMA_NO_CLOUD = "1"
Start-Process "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" -ArgumentList serve -WindowStyle Hidden
Start-Process "C:\SIH 2026\.venv\Scripts\python.exe" -ArgumentList "stage0\docgen_mcp_server.py","--port","8765" -WorkingDirectory "C:\SIH 2026" -WindowStyle Hidden
Start-Process "C:\SIH 2026\.venv\Scripts\python.exe" -ArgumentList "-m","mcp_servers.web_access","--mode","ask","--port","8766" -WorkingDirectory "C:\SIH 2026" -WindowStyle Hidden
docker start anythingllm-stage0
Invoke-RestMethod http://127.0.0.1:3001/api/mcp-servers/force-reload
```

### Useful commands

```powershell
.venv\Scripts\python -m workbench.run_inspection insp_1002                     # pipeline (stand-in evidence)
.venv\Scripts\python bench\stage1\extract_probe.py qwen3.5:9b medium insp_1002  # qwen scan read, scored
.venv-ocr\Scripts\python bench\stage1\ppstructure_probe.py clean                # OCR one page (CPU, ~3 min)
.venv\Scripts\python bench\stage1\geometry_mapper.py                           # place OCR values by position
.venv\Scripts\python bench\stage1\writer_test.py ollama:granite4.1:8b 3         # summary-writer test
```

---

## 6. Tooling gotchas (these cost time)

- **Ollama's bundled `llama-server.exe` runs CPU-only when started on its own.** Set `GGML_BACKEND_PATH=…\lib\ollama\cuda_v12\ggml-cuda.dll` and put that folder on `PATH`; check the log for `CUDA0`. (Saved to memory.)
- **paddlepaddle 3.3.0 CPU on Windows fails in layout detection with oneDNN** (`ConvertPirAttribute2RuntimeAttribute not support`). Use `enable_mkldnn=False`. Set `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True` to skip the network check.
- **Ollama did not enforce the JSON schema for qwen3.5:9b** — spell out the exact keys in the prompt and unwrap `{"value": …}`.
- **Sarvam 30B ignores every thinking off-switch** (`enable_thinking=false`, `<|nothink|>`, `--reasoning off`); `--reasoning-budget 0` leaks the thinking into the answer. Give it thinking and a 6,000-token budget.
- **The corpus scan folders hold 12 stale page-2 images** (insp_1002/1009/1011 at every quality) from an earlier build, not in `index.json`. Always use the index. Not deleted — waiting on the user.
- **Python output is buffered when redirected** — use `PYTHONUNBUFFERED=1` or `flush=True` so monitors see progress.
- **PowerShell inline Python with f-strings breaks on quotes** — pipe a single-quoted here-string into `python -`.
- The sandbox blocks `Remove-Item`/`rm` on the project path (it contains a space) — use a `.ps1` in the scratchpad.
- Background commands may be killed after 10 minutes — long jobs go in a detached `Start-Process pwsh -File` with a log and a Monitor.
- Ollama can't pull sharded GGUFs; `llama-server` can load them directly (point it at shard 1).
- `gh` is not logged in; the GitHub REST API works unauthenticated for public data.
- YAML 1.1 reads a bare `on:` key as `True` (the graph file uses `when:`).
- Don't pipe a here-string into `git commit -F -`; write the message to a file.
- The Grep tool skips gitignored folders — use PowerShell for those.
- Stopping cleanly: kill runner/probe processes; `docker restart anythingllm-stage0` to cancel an agent reply; unload models with `POST /api/generate {"model": m, "keep_alive": 0}`.

---

## 7. Open questions for the team

1. The official problem-statement version and its judging criteria.
2. Corpus language (English, Indian language, mixed?).
3. How much of the corpus is handwritten? **Are real MRPL reports scanned or digital PDFs, and how many pages?**
4. The venue's GPU, RAM and OS.
5. Who may see which documents?
6. SIH rules on disclosing AI-assisted development.

---

## 8. Waiting on the user — ask first

1. **Order of the next work.** Proposed (in the last message of the session):
   - (a) Take the Copilot-SDK ideas into the design — agent definitions with tool allow-lists, lifecycle events, approval callback, skill tests — and/or run the one-day Copilot SDK trial.
   - (b) Extend the corpus generator (`bench/corpus.py`) with multi-page reports: long thickness tables split across pages, findings continued on page 2, repeated headers, a photo page, image-only (scanned) PDFs.
   - (c) Build the real reader in `workbench/`: PDF of any length → per page, text layer if present, else render + OCR (PP-StructureV3, GPU build) → code places values by position → qwen as second reader → consistency checks → every critical value shown with its crop. Joined across pages by CML id.
   Recommended order: (b) then (c); (a) whenever the user wants.
2. **The 12 stale page-2 scan images** — delete them?

Later, as before: report templates ((a) one-page simple template first, then Word templates with placeholders), the R2 router, the R4 sandbox, the R6 live panel, and telling Ritesh about the Tailwind CDN in `frontend/index.html` (breaks offline).
