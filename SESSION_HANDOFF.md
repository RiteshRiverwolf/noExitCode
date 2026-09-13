# Session handoff — SIH26117

Updated 2026-09-13, end of a long session. Read this first, then
**`docs/WHOLE_PICTURE.md`** (the plan the team works from) and
**`results/stage2/NOTES.md`** (everything measured this session). Then ask the
user how to proceed — decisions are waiting (section 8).

---

## 1. The project in one paragraph

SIH 2026 problem statement 26117 (`docs/PS26117.md`, known — do not list it as
an open question): a **sovereign, air-gapped, multi-agent AI workbench** — an
organisation's own team of AI specialists that plan multi-step work, use local
tools, write and run code in a sandbox, read scans, and produce real Word,
Excel and PowerPoint deliverables grounded in the organisation's own documents,
with visible proof that nothing leaves the machine. **The inspection approval
note is one mission, not the product** (the user corrected this firmly). Our
difference is the evidence spine: every critical value traceable to its cell,
rules in code, deliverables verified by reading the file back, and stopping for
a person rather than guessing. **SIH entry only**, not a final-year project.

| | |
|---|---|
| User | Rudraansh Bhati — directs the project |
| Team | Ritesh and Sanji (frontend authors); always `git fetch` first |
| Repo | `github.com/RiteshRiverwolf/noExitCode`, branch `main` |
| Local | `C:\SIH 2026` — Windows 11, RTX 4070 **12 GB**, 32 GB RAM |
| Plan | **`docs/WHOLE_PICTURE.md`** — agent team, demo, knowledge base, connectors, observability, workstreams, mapped to SIH scoring |
| Results | **`results/stage2/NOTES.md`** (this session), `results/stage1/NOTES.md`, `results/stage0/NOTES.md` |
| Design of record | `docs/ARCHITECTURE.md` rev 2 (older than WHOLE_PICTURE in places) |

---

## 2. How the user wants you to work

- **No Claude co-author** in commits or PRs in this repo (the history has none).
- **Commit and push when asked** — this session the user asked to push after each piece. `git fetch` first; `git pull --no-rebase`.
- **Research, don't recall.** Primary sources for models, tools, licences, benchmarks.
- **Check again before building on a result.** This session that caught: a test that passed for the wrong reason (a flag on a *different* column counted as a catch); a scorer that counts a report-level flag as catching non-critical errors; a "fix" that broke the PDFs. **The born-digital PDFs are a control group** — exact text never needs a near match, so any change there is a regression.
- **Never claim an 8B model beats a 30B one.** Granite won the note-writing test because it is strong at tool calling and the checker was built on its mistakes. Say: the qualification test picks the model per task; safety comes from code, not size.
- **Be ambitious in framing, honest in status.** Everything is marked Proven / Built / Proposed. Unfinished parts are presented as a staged path backed by market evidence.
- **SIH judging** (published weights): innovation 25%, problem understanding 20%, feasibility 20%, impact and scale 20%, presentation 15%. A stable working prototype beats an ambitious broken one.
- **Settled:** corpus is **English**, **no handwritten notes**; the **knowledge base is wanted** (not built yet); **LangSmith is ruled out** (proprietary, self-host is Enterprise-only, and outside an air-gap licence it needs egress to `beacon.langchain.com`) — use OpenTelemetry + self-hosted Langfuse; **connectors** (Teams/Slack) carry notice, never content; **agents may write code** to answer questions.
- **The frontend belongs to Ritesh and Sanji** (`git log -- frontend/`). Ask before rewriting it.
- **Plain language** for anything the team reads. Expect mid-task redirects.
- **Never run a Docker prune** — Docker Desktop is shared with another project (Ripple).

---

## 3. Where things stand

| Req | What | Status |
|---|---|---|
| R1 | Local deployment, one mid-range GPU | Runs offline on the 12 GB bench |
| R2 | Model auto-selection, ≥2 task types | **Built** — `workbench/router.py` + `models.yaml`: granite for summaries/tools/code, qwen for second readings, nothing for photographs (untested), nomic for embeddings; safety gate shuts out llama3.1 and lfm2.5 (false approvals); hash-chained decision log |
| R3 | Scan → findings → Word note | **Built and measured** — the reader reads the document (text layer or OCR), wired into the pipeline |
| R4 | Coding task verified in a sandbox | **Done** — Docker `--network none` sandbox with a self-test; Coder agent; model's own tests don't count, held-out tests decide |
| R5 | Scanned-document understanding | Reader measured on all 48 scan runs; photographs/drawings untested |
| R6 | Visible proof of no external calls | Stage-0 packet capture; the service now has a live network panel (netstat of the workbench's own processes — a snapshot, not a capture) |

### Built this session (all on `main`, see `git log`)
- `workbench/pagesource.py`, `ocr_worker.py`, `tablemap.py`, `scan_reader.py` — the reader.
- `workbench/run_inspection.py` — reads the real document; `run_job(JobConfig, emit)` streams events.
- `workbench/sandbox.py`, `coder.py`, `coding_tasks.py` — R4.
- `workbench/router.py`, `models.yaml` — R2.
- `workbench/server.py` — local service (Starlette, loopback only, port 8770): missions, SSE events, crops and notes, network panel, sandbox self-test. Smoke-tested end to end.
- `bench/stage2/` — `reader_score.py`, `pipeline_stops.py`, `damaged_cell_test.py`, `unreadable_severity_test.py`, `missing_header_test.py`, `ocr_corpus.py`.
- `docs/WHOLE_PICTURE.md`, `results/stage2/NOTES.md`.

---

## 4. Key findings (details in `results/stage2/NOTES.md`)

1. **Reader, all sources, 0 accepted wrong critical fields.** 12 PDFs 395/395 in 0.1 s each; scans: clean 386, light 392, medium 393, heavy 380 right (of 395).
2. **Decisions, 48 scan runs:** 28 approval notes, every one with the correct outcome; 19 right stops; 1 false alarm (a correct value at OCR confidence 0.894); **0 wrong outcomes**.
3. **Column precision catches the damaged digit** — both blurred and *erased* "12.32" read as "12.3", caught because the column prints two decimals. **Leftover ink does not work** (stage 1's claim corrected).
4. **Safety hole closed:** an unreadable severity was silently "not Major" — on a severity-only report that gives NO TRIGGER and a finished note. Fixed in the rules (EVD-01) and the pipeline gate; test proven to fail on the old code.
5. **Layout traps:** "Observation" is a column header *and* a grade (header fitted as a tilted line); the last table row bounded by column alignment; template words tolerate one letter of OCR damage, headings keep their section number exact, values are never repaired.
6. **Missing header fields** no longer crash or print "None" — written as "(not read from the document)".
7. **Coder:** three tasks pass; `next_due_date` hung, was killed by the sandbox time limit, and fixed itself on the next attempt — the demo moment.
8. **Parsers:** PaddleOCR-VL-1.6 (0.9B, Apache 2.0, in `models/`) scores 96.33 on OmniDocBench v1.6 vs PP-StructureV3's 64.45 — worth a trial, admitted only if it gives per-value boxes and 0 accepted wrong on the damaged-cell test.

---

## 5. What's running, and how to start it

At the end of this session: Ollama and Docker Desktop were started; the service
was stopped; the OCR run finished (every corpus page cached in
`data/cache/ocr/`, gitignored).

```powershell
$env:OLLAMA_NO_CLOUD = "1"
Start-Process "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" -ArgumentList serve -WindowStyle Hidden
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"      # user noted Docker was offline once
.venv\Scripts\python -m workbench.server                               # http://127.0.0.1:8770
```

### Useful commands

```powershell
.venv\Scripts\python -m workbench.run_inspection insp_1002 --source scan --scan-quality medium
.venv\Scripts\python -m workbench.run_inspection insp_1002 --source pdf --inject-fault render   # self-healing demo
.venv\Scripts\python -m workbench.run_inspection x --image path\to\file.pdf                     # any document
.venv\Scripts\python -m workbench.coder next_due_date                  # the repair-loop demo
.venv\Scripts\python -m workbench.sandbox --self-test                  # isolation, shown not claimed
.venv\Scripts\python -m workbench.router --all --no-log
.venv\Scripts\python bench\stage2\reader_score.py --quality heavy
.venv\Scripts\python bench\stage2\pipeline_stops.py --quality heavy
.venv\Scripts\python bench\stage2\unreadable_severity_test.py
```

---

## 6. Tooling gotchas (these cost time)

- **The audit log has one writer.** `AuditLog` reads the last hash once, when it is created. A long-running `workbench.server` plus CLI runs at the same time would fork the chain. Stop the service before running bench scripts. (Proper fix — re-read the tail under a file lock in `mcp_servers/audit.py` — not done.)
- **Kill process trees, not PIDs.** `.venv\Scripts\python.exe` is a launcher that starts a child interpreter; `Stop-Process` on it leaves the child holding the port. Use `taskkill /PID <pid> /T /F`.
- **Docker Desktop goes offline** (it happened twice). `docker info` to check. The sandbox needs `python:3.12-slim`; for the air-gapped machine `docker save` / `docker load` it.
- **PaddleOCR on CPU: ~85 s a page.** The cache makes re-runs instant. `enable_mkldnn=False`; `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True`.
- **Damaged-digit fixtures** live in gitignored `bench/stage1/partial/`; regenerate byte-identically with `.venv\Scripts\python bench\stage1\partial_test.py make`.
- **Scorer caveat:** `reader_score.py` counts a report-level flag as catching non-critical errors. Critical fields are checked per field; check any "caught" claim on the field itself.
- Ollama's bundled `llama-server.exe` is CPU-only unless `GGML_BACKEND_PATH` points at `cuda_v12\ggml-cuda.dll` (memory).
- PowerShell inline Python: use a single-quoted here-string. The Grep tool skips gitignored folders (`logs/`, `runs/`, `data/`). Don't pipe a here-string into `git commit -F -` from PowerShell; the Bash tool's heredoc works.

---

## 7. Open questions for the team

1. The venue's GPU, RAM and OS.
2. Who may see which documents (access control on both knowledge-base stores).
3. SIH rules on disclosing AI-assisted development.
4. Does "model auto-selection across two task types" mean two task-specific LLMs, or OCR plus reasoning?
5. **A grade one letter off** ("Maior", "Obseryation") currently stops the run — values are never repaired. Should it instead reach a person pre-filled?
6. **A missing equipment tag or report number** is written as "(not read)" but does not stop the run. It arguably should: a note that does not name the asset could be attached to the wrong one.

---

## 8. Waiting on the user — ask first

1. **The frontend.** `frontend/index.html` (Ritesh and Sanji) is fully simulated, and in places untrue: it names PaddleOCR-VL (we run PP-StructureV3), shows invented ports, a made-up CML-014 with a fake source for the minimum, and a hard-coded "0 external calls". The service and its event contract are ready (`workbench/server.py` docstring). Wire the prototype to it, or hand the contract to them? Tailwind from a CDN also breaks offline — demo-blocker.
2. **Next build**, from `docs/WHOLE_PICTURE.md` §14 — candidates: the frontend wiring; LangGraph behind the same handlers (`interrupt()` for the review pause); the knowledge base (evidence store + reference library, with a refusal test); PaddleOCR-VL-1.6 trial; corpus v2 (multi-page reports); OpenTelemetry spans; the audit-log file lock.
3. Questions 5 and 6 above.
