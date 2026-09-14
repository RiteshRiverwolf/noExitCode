# Session handoff — SIH26117

Updated 2026-09-14, morning. **The Planner is built and plans the demo; a Chat agent
answers greetings and general questions; typed requests in the chat box run as
missions; the Agent Activity panel draws agents and tool calls. Rehearsed in a real
browser.** Nothing from this session is committed yet. Read this, then
**`results/stage3/NOTES.md` §9** (what was measured) and `docs/DEMO_RUN_SHEET.md`.

---

## 1. The project in one paragraph

SIH 2026 problem statement 26117 (`docs/PS26117.md`): a **sovereign, air-gapped,
multi-agent AI workbench** — an organisation's own team of AI specialists that plan
work, use local tools, write and run code in a sandbox, read scans, and produce real
deliverables grounded in the organisation's own documents, with visible proof that
nothing leaves the machine. Our difference is the evidence spine: every value
traceable to its cell, rules in code, deliverables read back and checked, stopping for
a person rather than guessing. **SIH entry only.**

| | |
|---|---|
| User | Rudraansh Bhati — directs the project |
| Team | Ritesh and Sanji (frontend authors); always `git fetch` first |
| Repo | `github.com/RiteshRiverwolf/noExitCode`, branch `main` — last pushed `733458f`; **this session uncommitted** |
| Local | `C:\SIH 2026` — Windows 11, RTX 4070 12 GB, 32 GB RAM |
| Plan | `docs/WHOLE_PICTURE.md` |
| Results | `results/stage3/NOTES.md` (§9 = this session) |
| Demo | `docs/DEMO_RUN_SHEET.md` (written for the presenters) |

---

## 2. How the user wants you to work

- **Priority now: the demo and the general chatbot.** Latest instructions (14 Sep): "lets work on the demo and the general chatbot"; then "leave this test, move forward with the demo".
- **The chat must converse** (memory `chat-must-converse`): greetings and normal questions get a real reply — rails stay (qualified model, checks, label).
- **Nothing hard-coded** except the demo scenario (`workbench/demo.yaml`). Safety rules stay in code.
- **Clean context per model test; never tune on held-out; say when an expectation changed after a run.**
- **Ambitious framing, honest status** — Proven / Built / Proposed; never claim an 8B beats a 30B.
- **Frontend belongs to Ritesh and Sanji**: wiring and small additions only; ask before any redesign. **Never Docker prune.**
- **No Claude co-author** in commits or PRs. Commit/push only when asked.

---

## 3. Built this session

| Piece | Where | Status |
|---|---|---|
| Planner | `workbench/planner.py`; agent `planner` in `agents.yaml`; step kinds + regulated patterns in `orchestration.yaml` | **Built**; qualified (`models.yaml`, task `plan`) **for single messages only**: 40/40 on the current prompt (partial run), 90/90 on the prompt before `reply` |
| Missions + `POST /api/missions` | `workbench/missions.py`, `server.py`, `service.yaml` | Built; typed chat requests plan and run |
| Demo planned by the Planner | `workbench/demo.py`, `demo.yaml` (`step_settings`, `staged` beat, `plan_notes`) | Built; damaged-digit beat labelled "from the demo scenario" |
| Chat agent (`reply`) | `workbench/chat.py`; agent `chat` | Built; qualified on **dev messages only** (6/6, one run) |
| Chat memory | frontend keeps turns, sends them; `planner.turns` | Built and checked, **switched off** (`history_turns: 0`): held-out follow-ups failed the gate (G04) |
| Help when nothing runs | `planner.capabilities`, frontend `renderHelp` | Built |
| Agent Activity draws `agent` / `tool` events | `frontend/index.html` | Built; browser-verified |
| Tests | `bench/stage3/planner_checks_test.py`, `chat_checks_test.py` (no model); `planner_score.py` + `planner_requests.yaml` (47 requests); `chat_score.py` + `chat_requests.yaml` (14 messages) | checks all passed; qualification runs partial (see §5) |

Browser rehearsal (headless Edge, driver in the session scratchpad, not in the repo):
demo 49.5 s; 12.3 refused, 12.32 resumed in 7 s; greeting, E-4461 note, V-1668 note +
"emailing not possible", "order plates" → not possible + help; **0 JS errors, 0
external connections, audit logs 8/8**. The Coder failed next_due_date 4/4 in that run
(handed to a person).

---

## 4. Uncommitted work

All of this session's changes (see `git status`). Not ours, leave alone:
`results/stage0/tool_calls.jsonl` and four `results/stage0/*.log`.

---

## 5. Open, in order

1. **Demo is rehearsed and ready** (5 browser runs; NOTES §9 items 6–7). The scenario request was reworded so the Planner's library question cites SOP-INSP-001 §4. Next: a human rehearsal with the run sheet, and a name for the Review step.
2. **Finish qualification when there is time**: Chat agent held-out messages (14 × 3); the Planner's full 47 × 3 run on the current prompt; qwen3.5:9b not scored.
3. **Chat memory back on** needs a fresh held-out follow-up set (the G set has been seen) and a fix for G04 (a follow-up asking for an action no step can do).
4. **Unchecked wording** (NOTES §9 items 5): "safely restarted" in a summary; "approve" in the Planner's `not_possible` note. The user deferred the "safe" decision.
5. Re-run `planner_checks_test.py` and `chat_checks_test.py` (service stopped) after any change to the Planner or Chat agent.
6. The team: tell Ritesh and Sanji about the new frontend wiring (`/api/missions`, `plan`, `reply`, `agent`, `tool`, `mission_start/end` events, help list); fill "name to type" in the run sheet.
7. Earlier plan items still open: approval gate on tool calls (Sentinel), persist paused runs, "Maior" → a person, missing tag → stop.

---

## 6. Tooling gotchas

- **The service serves `frontend/index.html` from disk** — frontend edits need no restart. `models.yaml` and `demo.yaml` are read per call; **`agents.yaml` is cached** — restart after editing it.
- **One writer per audit log**: stop the service before scorers or checks tests; never run two scorers at once.
- **Stopping a background shell on Windows can leave its Python child running** — kill by command line (`Get-CimInstance Win32_Process`) or by port 8770.
- qwen3.5:9b ignores Ollama's JSON schema with `think: false` (writes prose).
- YAML flow mappings (`[{request: ...}]`) break on `?` in unquoted strings — quote them.
- Print Unicode from Python in Git Bash with `PYTHONIOENCODING=utf-8`.
- Earlier gotchas still apply: LangGraph `interrupt()` re-runs the node; paused runs are in memory; `git commit -F <file>`; Docker Desktop goes offline (`docker info`).

---

## 7. Commands

```powershell
$env:OLLAMA_NO_CLOUD = "1"; $env:LANGSMITH_TRACING = "false"
.venv\Scripts\python -m workbench.server                     # http://127.0.0.1:8770
.venv\Scripts\python -m workbench.planner "Draft the approval note for E-4461"
.venv\Scripts\python -m workbench.chat "What can you do?"
# service stopped:
.venv\Scripts\python bench\stage3\planner_checks_test.py
.venv\Scripts\python bench\stage3\chat_checks_test.py
.venv\Scripts\python bench\stage3\planner_score.py --model granite4.1:8b --runs 3
.venv\Scripts\python bench\stage3\chat_score.py --model granite4.1:8b --runs 3
```
