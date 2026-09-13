# Session handoff — SIH26117

Updated 2026-09-14, early morning. **The agent loop now runs on LangGraph, every
agent is held to its tool list in code, and a run that stops for a person resumes
from the Review tab — verified in a real browser.** Everything is committed and
pushed. Read this, then **`results/stage3/NOTES.md` §8** (what was measured) and
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
| Repo | `github.com/RiteshRiverwolf/noExitCode`, branch `main` — everything pushed at handoff (`git log -1`) |
| Local | `C:\SIH 2026` — Windows 11, RTX 4070 **12 GB**, 32 GB RAM |
| Plan | **`docs/WHOLE_PICTURE.md`** (§5 demo statuses, §7d memory, §10 engine, §10a what LangGraph keeps) |
| Results | **`results/stage3/NOTES.md`** (§8 = this session), stage 2, 1, 0 notes |
| Deck brief | `docs/TECHNICAL_APPROACH_BRIEF.md` — paste into Claude to generate the technical approach document (14 Mermaid diagrams, statuses current) |

---

## 2. How the user wants you to work

- **Current priority:** the system must be visibly **multi-agent, multi-modal, and choose the LLM per task**; the pitch demo and its frontend come first. Latest instruction (13 Sep): *"push and then start working forward for the demo and in general run"*. Testing other models for the Librarian is deferred.
- **Nothing hard-coded.** Documents, model names, addresses, thresholds, prompts, messages live in config: `models.yaml`, `library.yaml`, `agents.yaml`, `service.yaml`, `orchestration.yaml`, graph files. **The only exception is the demo scenario** — `workbench/demo.yaml`. Safety rules stay in code by design.
- **Clean context in every model test**: new conversation per question; qualification scorers reload the model (`router.fresh`).
- **Keep the original plan visible**: ICM, procedural graphs with self-healing, the GitHub Copilot SDK ideas, three kinds of memory (WHOLE_PICTURE §7d, §10a). GraphRAG later.
- **Answer direct questions plainly first**, idea before mechanics.
- **No Claude co-author** in commits or PRs. Commit and push when asked; `git fetch` / `git pull` first.
- **Research, don't recall**; **check again before building on a result**; never tune on held-out questions.
- **Never claim an 8B model beats a 30B one.** Ambitious framing, honest status — Proven / Built / Proposed.
- **The frontend belongs to Ritesh and Sanji.** Wiring and panels were asked for; the Review card's input, name field and two buttons were added under "work forward for the demo". **Ask before any redesign.** **Never run a Docker prune.**
- **Store choice confirmed**: our own SQLite index, not AnythingLLM's LanceDB (13 Sep).
- **Coder variability on stage**: show retries as a feature; a failure shows honestly as "handed to a person" (13 Sep).

---

## 3. Where things stand

| Piece | Status |
|---|---|
| R1 local deployment | Runs offline on the 12 GB bench |
| R2 model auto-selection | **Built** — Router + `models.yaml`; "Why this model" tab |
| R3 scan → note | **Built and measured**; self-healing passes on the new engine |
| R4 sandbox coding | **Done**; repair loop improved (below) |
| R5 scanned documents | Measured on printed scans; photographs/drawings untested |
| R6 no external calls | Stage-0 packet capture; live network footer + audit-log chains |
| Evidence store, reference library | **Built and checked** (see stage 3 notes §1–3) |
| Librarian agent | **Built, NOT qualified**; model testing deferred |
| **Agent loop on LangGraph** | **Built** — `workbench/graph_engine.py`, default in `orchestration.yaml`; 609/609 identical traces vs the old runner (kept as fallback) |
| **Tool allow-lists + lifecycle** | **Built** — `workbench/tools.py`; every stage runs as an agent (`agent_id` in the graph); refusals/calls/lifecycle in `logs/agents.jsonl`; 16/16 |
| **Stop for a person, then resume** | **Built** — graph v3 `review_values`; service pauses (`interrupt()`), Review tab resumes; 27/27; browser-verified. Paused runs live in memory only |
| Planner | Not started — the demo labels its plan as the scenario |
| Approval step on tool calls (Sentinel gate) | Not started |

### The demo, as it runs (press "Run demo" at http://127.0.0.1:8770)

| Step | Agents | What the judge sees |
|---|---|---|
| 1. Scanned R-2247 report → draft note | Document Reader, Evidence Builder, Rules Engine, Router, Report Writer, QA Checker | ESCALATE on CML-03 (12.32 < 12.70); injected wrong value caught, sent back, passes on attempt 2; `.docx` |
| 2. Procedure behind the escalation | Librarian (search) | SOP-INSP-001 §4 cited + the referenced SOP-INSP-003 §4 |
| 3. Same report, blurred digit | Document Reader, Evidence Builder, Engineer | **Paused for a person**; Review tab shows the crop, "column prints 2 decimals" |
| 4. When is the next inspection due? | Router, Coder, Sandbox | program written, run sealed in Docker, accepted by hidden tests (or honestly handed to a person) |
| After the mission: Review tab | Engineer → Rules Engine, Report Writer, QA Checker | type **12.3** → refused with the reason; type **12.32** + a name → "Resumed" group, ESCALATE, note whose Appendix B says who entered the value and what the scan read |

Browser run (headless Edge): demo 34 s, refusal 1 s, resumed run 7 s, 0 JS errors, 0 external connections, audit logs 6/6.

---

## 4. Uncommitted work

None of ours. Not ours, leave alone: `results/stage0/tool_calls.jsonl` and four `results/stage0/*.log`.

---

## 5. Key findings this session (details in `results/stage3/NOTES.md` §8)

1. **LangGraph engine is a drop-in**: 9 named + 600 random scripted runs gave identical traces, ends, callbacks, attempts and guidance; the self-healing run and the unreadable-severity test pass unchanged.
2. **Tool gate**: the Rules Engine cannot reach the sandbox, the Coder cannot search the library, the QA Checker cannot write a note (it can only stamp checks that all passed), a call with no agent acting is refused.
3. **Stop and resume**: entries are checked against the printed column (decimals), grades against the report's grades; a name is required; a paused run is claimed once; the note records the entry. The command line cannot pause and ends at needs_review as before (one extra `review_values` line in its output).
4. **The Coder repeated itself**: its failures were the *same failed program* resubmitted byte for byte. Fix in the loop (not the task): a repeat is not run; a fresh conversation shows the program and its failure with `repeat_options`. `next_due_date` 9/10 accepted (was 4/6). Small samples; `models.yaml` figures unchanged.
5. **Observation, not acted on**: granite's summary once ended "…to ensure safe operation" and passed the prose checks. Close to the approval language the checks forbid — decide with the user whether "safe" in any phrase should be refused (don't tune on the fly).
6. **Team pulled**: Sanji's collapsible sidebar and resizable panels (`bbfd229`).

---

## 6. Tooling gotchas

- **The service serves `frontend/index.html` from disk on each request** — frontend edits need no restart; Python edits do.
- **LangGraph `interrupt()` re-runs the node from the top on resume** — nothing with side effects may come before it (in `graph_engine.run_stage` it is the first statement).
- **Paused runs are in memory** (InMemorySaver + `run_inspection._PAUSED`): a service restart loses them.
- **Headless browser check**: Edge `--headless=new --remote-debugging-port=<port> --remote-allow-origins=* --user-data-dir=<tmp>`, driven over CDP with `websockets` (in `.venv`). Kill with `taskkill /PID <pid> /T /F`. Group titles are CSS-uppercase, so `innerText` returns them uppercase.
- **`git commit -F -` with a PowerShell here-string does not pipe** — write the message to a file and `git commit -F <file>`.
- **LangGraph pulls in `langsmith`** — `graph_engine.py` forces `LANGSMITH_TRACING=false`.
- **Ollama 0.30.3 honours a JSON schema in `format`**; qwen3.5:9b thinks by default.
- **Don't edit files a running test or the service imports**; **one writer per audit log** — stop the service before bench scripts, and start it again *after* them (each process caches the chain's last hash).
- **Docker Desktop goes offline**; `docker info` to check. `gh` is not logged in.

---

## 7. What's running, and commands

**At handoff the workbench service is RUNNING** (started from this session in the background; http://127.0.0.1:8770). Find and stop it with
`Get-NetTCPConnection -LocalPort 8770 -State Listen` → `taskkill /PID <pid> /T /F` before bench scripts.

```powershell
$env:OLLAMA_NO_CLOUD = "1"; $env:LANGSMITH_TRACING = "false"
.venv\Scripts\python -m workbench.server                           # the demo, http://127.0.0.1:8770
.venv\Scripts\python -m workbench.demo                             # the same mission, printed (beat 3 pauses; nobody resumes)
# orchestration checks (service stopped)
.venv\Scripts\python bench\stage3\engine_parity_test.py
.venv\Scripts\python bench\stage3\tool_gate_test.py
.venv\Scripts\python bench\stage3\review_resume_test.py
# regression after touching pipeline code
.venv\Scripts\python -m workbench.run_inspection insp_1002 --source pdf --inject-fault render
.venv\Scripts\python bench\stage2\unreadable_severity_test.py
.venv\Scripts\python -m workbench.coder next_due_date
.venv\Scripts\python bench\stage3\librarian_checks_test.py
.venv\Scripts\python -m workbench.router --all --no-log
.venv\Scripts\python bench\stage2\reader_score.py
# knowledge base
.venv\Scripts\python -m workbench.library build
.venv\Scripts\python bench\stage3\library_score.py
```

---

## 8. Plan for what comes next

1. **Rehearse the demo end to end, including the Review step**: who types the value, what name, and what to say while the resumed run drafts the note.
2. **Show agents in the interface**: the `agent` (started/completed/failed) and `tool` (call/refused) events already stream; the Agent Activity panel does not draw them yet. Ask Ritesh and Sanji.
3. **The Planner**: JSON plan validated in code; regulated requests always take the fixed inspection graph — then the demo's plan comes from the Planner.
4. **Approval step on tool calls** (Sentinel gate) — the same `interrupt()` mechanism now proven for review.
5. **Persist paused runs** (a SQLite checkpointer, vendored and tested with the network off) so a restart does not lose them.
6. The two earlier decisions: "Maior" → a person, pre-filled (the Review card already offers a grade picker for unreadable grades); missing equipment tag → stop for a person.
7. Later: qualify better models for the Librarian (and a Verifier pass for "nearby answers"); Excel/PowerPoint deliverables; GraphRAG when needed.

---

## 9. Waiting on the user — ask first

1. **"…to ensure safe operation"** in a model summary passed the checks — should the prose check refuse "safe" in any phrase?
2. **Tell Ritesh and Sanji** about the Review card (input, name, Confirm / Re-measure, "Resumed" group) and the new `review` / `run_resumed` / `agent` / `tool` events.
3. Which of §8 next: rehearsal, agents drawn in the interface, Planner, or the approval gate.
4. Still open for the team: venue GPU/OS; document access control; SIH rules on AI-assisted development; how judges read "two task types" for R2.
