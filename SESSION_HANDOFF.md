# Session handoff — SIH26117

Updated 2026-09-13, late evening. **The pitch demo is built, wired into the
frontend and verified in a real browser. Nothing from today is committed.**
Read this, then **`results/stage3/NOTES.md`** (what was measured) and
`docs/WHOLE_PICTURE.md` (the plan). Then ask the user how to proceed (section 9).

---

## 1. The project in one paragraph

SIH 2026 problem statement 26117 (`docs/PS26117.md`, known — never list it as an
open question): a **sovereign, air-gapped, multi-agent AI workbench** — an
organisation's own team of AI specialists that plan multi-step work, use local
tools, write and run code in a sandbox, read scans, and produce real Word, Excel
and PowerPoint deliverables grounded in the organisation's own documents, with
visible proof that nothing leaves the machine. **The inspection approval note is
one mission, not the product.** Our difference is the evidence spine: every
critical value traceable to its cell, rules in code, deliverables verified by
reading the file back, and stopping for a person rather than guessing. **SIH
entry only.**

| | |
|---|---|
| User | Rudraansh Bhati — directs the project |
| Team | Ritesh and Sanji (frontend authors); always `git fetch` first |
| Repo | `github.com/RiteshRiverwolf/noExitCode`, branch `main` — local HEAD **`d4f97f0`** (Sanji's offline frontend rewrite, pulled today); nothing newer on the remote at handoff |
| Local | `C:\SIH 2026` — Windows 11, RTX 4070 **12 GB**, 32 GB RAM |
| Plan | **`docs/WHOLE_PICTURE.md`** (§5 demo statuses updated; §7b store; §7d memory; §10a what LangGraph must keep) |
| Results | **`results/stage3/NOTES.md`** (today), stage 2, 1, 0 notes |

---

## 2. How the user wants you to work

- **Current priority (latest):** the system must be visibly **multi-agent, multi-modal, and choose the LLM per task**. The pitch demo and its frontend come first. **Testing other models for the Librarian is deferred** — "we will have much better LLMs later".
- **Nothing hard-coded.** Documents, model names, addresses, thresholds, prompts, messages live in config: `models.yaml` (models, servers, via the Router), `library.yaml`, `agents.yaml`, `service.yaml`. **The only exception is the demo scenario** — `workbench/demo.yaml`. Pure definitions and protocol paths are fine; safety rules stay in code by design.
- **Clean context in every model test**: new conversation per question; the qualification scorer unloads and reloads the model first (`router.fresh`) and fails on any first attempt with more than 2 messages.
- **Keep the original plan visible**: ICM, procedural graphs with self-healing, the GitHub Copilot SDK ideas, three kinds of memory (WHOLE_PICTURE §7d, §10a). GraphRAG later, when needed (recorded graph first).
- **Answer direct questions plainly first**, idea before mechanics.
- **No Claude co-author** in commits or PRs. **Commit and push only when asked**; `git fetch` / `git pull` first ("git pull, there have been changes").
- **Research, don't recall**; **check again before building on a result** (held-out questions are never used to tune).
- **Never claim an 8B model beats a 30B one.** Ambitious framing, honest status — Proven / Built / Proposed.
- **The frontend belongs to Ritesh and Sanji.** The user explicitly asked today to wire it and add panels; ask before any further redesign. **Never run a Docker prune.**

---

## 3. Where things stand

| Piece | Status |
|---|---|
| R1 local deployment | Runs offline on the 12 GB bench |
| R2 model auto-selection | **Built** — Router + `models.yaml`; shown live in the frontend's "Why this model" tab |
| R3 scan → note | **Built and measured**; regression-checked after today's refactor |
| R4 sandbox coding | **Done**; in the demo |
| R5 scanned documents | Measured on printed scans; photographs/drawings untested |
| R6 no external calls | Stage-0 packet capture; **live network footer** (connection snapshot + audit-log chains) |
| Evidence store | **Built and checked** (4 = 4 below-minimum, 45 = 45 findings) |
| Reference library | **Built and measured** — 44/44 synthetic sections match truth; retrieval 22/22 top-5; multi-document 4/4; SQLite chosen (`docs/KNOWLEDGE_STORE_COMPARISON.md`) |
| Librarian agent | **Built, NOT qualified** (answers nearby questions with real text); model testing deferred by the user |
| Agents as data | **Built** — `agents.yaml`: librarian, report_writer, coder, second_reader |
| **Pitch demo** | **Built and verified** — `demo.yaml` + `demo.py`, `POST /api/demo`; runs 18–42 s |
| **Frontend** | **Wired to the service**, Sanji's design kept; verified in headless Edge, no JS errors |
| Agent loop (LangGraph) | Not started |
| Planner | Not started — the demo labels its plan as the scenario |

### The demo, as it runs (press "Run demo" at http://127.0.0.1:8770)

| Step | Agents | What the judge sees |
|---|---|---|
| 1. Scanned R-2247 report → draft note | Document Reader (OCR), Evidence Builder, Rules Engine (code), Router, Report Writer, QA Checker | ESCALATE on CML-03 (12.32 < 12.70); Router picks granite; injected wrong value caught, "sent back → render_note", passes on attempt 2; `.docx` downloads |
| 2. Procedure behind the escalation | Librarian (search) | SOP-INSP-001 section 4 cited, plus the section it references (SOP-INSP-003 s4) |
| 3. Same report, blurred digit | Document Reader, Evidence Builder, Person | "stopped for a person"; Review tab shows the real "12.3" crop and why |
| 4. When is the next inspection due? | Router, Coder, Sandbox | program written, run in Docker (no network), accepted by hidden tests |

Frontend panels: Agent Activity (live events), Request (plan, replies, note link), Evidence / **Why this model** / **Review** tabs, header + footer with live external-connection count and audit logs intact.

---

## 4. Uncommitted work

`git status` at handoff — **nothing below is pushed**:

| File | What | Tested |
|---|---|---|
| `workbench/demo.yaml`, `demo.py` | The pitch demo: scenario as data; runs each beat with real code, streams events | Yes — API run and three browser runs |
| `frontend/index.html` | Sanji's page wired to the service: live stages, evidence with crops, library passages, coder card, Why this model, Review, live network; fixed missing `overflow-*` classes, form-control reset, duplicate cards | Yes — Node syntax check, headless Edge screenshots, no console errors |
| `workbench/server.py` | + `GET/POST /api/demo`; settings from `service.yaml`; health check address from `models.yaml` | Yes |
| `workbench/service.yaml` | Service port, upload limits, watched processes | Yes |
| `workbench/evidence_store.py` | SQLite evidence store | Yes |
| `workbench/library.py`, `library.yaml` | Library: bold headings, footnotes, margin furniture, hybrid BM25 + vector + identifier search, reference following, index cached in memory until the file changes | Yes |
| `workbench/librarian.py` | Librarian: allow-list, JSON-schema answers, checks, retry, refusal, hash-chained log | Yes — checks 22/22; two model runs (not qualified) |
| `workbench/agents.yaml`, `agents.py` | Agent definitions; one chat path | Yes — prompts byte-identical to before |
| `workbench/router.py` | + `endpoint()`, + `fresh()` | Yes |
| `workbench/models.yaml` | + `answer_from_library`, nomic prefixes and retrieval evidence, `model_lifecycle` | Yes |
| `workbench/prose.py`, `coder.py`, `reader.py` | Hard-coded address, defaults, prompts, settings → config | Yes — full regression suite passed |
| `bench/library/`, `bench/stage3/` | Synthetic library + 30 questions (8 held-out); retrieval and Librarian scorers; checks test; LangGraph network test | Yes |
| `results/stage3/` | NOTES.md, library_retrieval.json, librarian_granite4.1-8b.json | — |
| `docs/KNOWLEDGE_STORE_COMPARISON.md` | SQLite vs LanceDB, Chroma, Qdrant, pgvector, FAISS, sqlite-vec — sourced and measured | — |
| `docs/WHOLE_PICTURE.md` | §5 demo statuses, §7b store, §7d memory, §10a, sources | — |
| `requirements-workbench.txt`, `.gitignore` | Dependency record; ignores `data/evidence/`, `data/library/` | — |

Not ours, leave alone: `results/stage0/tool_calls.jsonl` and four `results/stage0/*.log`.

---

## 5. Key findings today (details in `results/stage3/NOTES.md`)

1. **Search scores hid broken reading** (16/17 while headings were deleted). Fixed with bold from PDF fonts, footnote splitting, margin-only furniture → 44/44 sections.
2. **Retrieval 22/22**; answerable and unanswerable similarity ranges overlap — refusal cannot be a threshold.
3. **The Librarian answers nearby questions with real text** (a clause's words → the procedure applying it). Checks can't see it; an instruction didn't generalise (held-out H02). Deferred.
4. **SQLite is the right store here** (only option with BM25 + vectors offline, citations, nothing to run). Vector search 6 ms at 100k passages; reading vectors per question cost 500 ms → now cached.
5. **Refactor changed no behaviour**: prompts byte-identical; inspection, self-healing, Coder, Reader score, unreadable-severity pass.
6. **The demo runs end to end** via API (42 s) and in the browser (18–36 s), 0 external connections, audit logs 5/5 intact.
7. **Demo variability**: the Coder took 4 of 4 attempts once and 1 attempt in other runs; granite's summary once failed its checks twice and code wrote it (still correct).

---

## 6. Tooling gotchas

- **The service serves `frontend/index.html` from disk on each request** — frontend edits need no restart; Python edits do.
- **Headless browser check**: Edge at `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe` with `--headless=new --remote-debugging-port=<port> --remote-allow-origins=*`, driven over CDP with the `websockets` package (16.1.1, in `.venv`); no Playwright or Selenium installed. Node 22 is installed (`node --check` for the page's script).
- **`gh` is not logged in** (exit 4); read public repo data via `https://api.github.com/repos/...`.
- **LangGraph pulls in `langsmith`** — force `LANGSMITH_TRACING=false`. Only in-memory checkpointer/store installed.
- **Ollama 0.30.3 honours a JSON schema in `format`** for granite; qwen3.5:9b thinks by default (needs a per-model `think` setting before any test).
- **nomic-embed-text needs prefixes** (`models.yaml`); the index records its embed model and `library.yaml` hash.
- **Don't edit files a running test or the service imports** (they are read at start); **the audit log has one writer** — stop the service before bench scripts.
- **Kill process trees:** `taskkill /PID <pid> /T /F`. **Docker Desktop goes offline**; `docker info` to check.

---

## 7. What's running, and commands

**At handoff the workbench service is RUNNING** (pid 67692, started from this session; http://127.0.0.1:8770; Ollama, Docker, sandbox image and OCR environment all healthy). Stop it with `taskkill /PID 67692 /T /F` before running bench scripts. Ollama and Docker Desktop are up.

```powershell
$env:OLLAMA_NO_CLOUD = "1"; $env:LANGSMITH_TRACING = "false"
# the pitch demo
.venv\Scripts\python -m workbench.server                           # open http://127.0.0.1:8770, press "Run demo"
.venv\Scripts\python -m workbench.demo                             # the same mission, printed
# knowledge base
.venv\Scripts\python bench\library\make_library.py
.venv\Scripts\python -m workbench.library build
.venv\Scripts\python bench\stage3\library_score.py
.venv\Scripts\python bench\stage3\librarian_checks_test.py
.venv\Scripts\python bench\stage3\librarian_score.py --model granite4.1:8b
.venv\Scripts\python -m workbench.evidence_store ingest
# regression suite after touching pipeline code (service stopped)
.venv\Scripts\python -m workbench.router --all --no-log
.venv\Scripts\python -m workbench.run_inspection insp_1002 --source pdf --inject-fault render
.venv\Scripts\python -m workbench.coder next_due_date
.venv\Scripts\python bench\stage2\reader_score.py
.venv\Scripts\python bench\stage2\unreadable_severity_test.py
```

---

## 8. Plan for what comes next

1. **Rehearse the demo** several times; decide how to present a Coder run that needs all its attempts (or that fails).
2. **Tell Ritesh and Sanji** their `frontend/index.html` is wired (design kept, two tabs added); then **commit when the user asks** (pull first).
3. **The agent loop on LangGraph** (WHOLE_PICTURE §10a): agents from `agents.yaml` with enforced allow-lists, per-agent lifecycle events, approval on tool calls, the procedural-graph YAML compiled into LangGraph with the self-healing demo unchanged, memory per §7d, `interrupt()` so the Review tab's buttons can resume a stopped run.
4. **The Planner**: JSON plan validated in code; regulated requests always take the fixed inspection graph — then the demo's plan can come from the Planner instead of the scenario file.
5. Implement today's two decisions: "Maior" → a person, pre-filled; missing equipment tag → stop for a person.
6. Later: qualify better models for the Librarian (and a Verifier pass for "nearby answers"); GraphRAG when needed.

---

## 9. Waiting on the user — ask first

1. **Commit** today's work (and whether to message Ritesh and Sanji about the frontend first).
2. **Demo rehearsal**: how to handle Coder variability live.
3. **Store choice** — SQLite over AnythingLLM's LanceDB, backed by the comparison doc; not explicitly confirmed.
4. Still open for the team: venue GPU/OS; document access control; SIH rules on AI-assisted development; how judges read "two task types" for R2.
