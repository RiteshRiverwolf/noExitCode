# Stage 3 notes — the knowledge base, and the first agent defined as data

13 September 2026. Bench: RTX 4070 12 GB, 32 GB RAM, Windows 11, everything
offline. Library: 11 synthetic procedures and memos (`bench/library/content.py`,
every page marked synthetic) plus one real public document, the US Chemical
Safety Board's 132-page Chevron Richmond report. Good results on 12 documents do
not prove good results on MRPL's real library.

---

## 1. What was built

| Piece | Job | Status |
|---|---|---|
| `workbench/evidence_store.py` | Every reading and finding from the inspection reports in SQLite, exact numbers, with their source | **Built, checked**: on the 12 corpus PDFs, below-minimum readings 4 = 4 and findings 45 = 45 against ground truth |
| `workbench/library.py` + `library.yaml` | Reads documents into sections and chunks, and searches them | **Built, measured** (§2–3) |
| `workbench/librarian.py` | The Librarian agent: answers only from retrieved passages, cites every sentence, or says the library does not contain it | **Built, not qualified** (§4) |
| `workbench/agents.yaml` + `agents.py` | Agents as data: purpose, allowed tools, Router task, limits, instructions, messages, output shape | **Built** — Librarian, Report Writer, Coder, second Reader |
| `bench/stage3/library_score.py` | Does search find the right passage? | Run |
| `bench/stage3/librarian_score.py` | Does the Librarian answer right, cite, and refuse when it should? The qualification test for the Router | Run twice |
| `bench/stage3/librarian_checks_test.py` | The Librarian's checks on 21 hand-made replies, no model needed | 22/22 pass |
| `bench/stage3/langgraph_network_test.py` | Does LangGraph make network calls? | **None**; pause and resume worked 30/30 |

How the library works, in one picture:

```
build (once):  PDFs -> the Reader -> sections -> chunks -> data/library/index.sqlite
               (text, document, section, page, box, BM25 keyword index, vectors)
question:      BM25 keywords + vector similarity + exact codes -> top 5
               + sections those passages refer to -> the Librarian -> checked, cited answer
```

## 2. Reading documents correctly — three bugs found by checking, not by search scores

Search scored 16/17 on the first run, which looked fine. Checking the index
against the documents' own truth file showed it was not:

| Bug | Effect | Fix |
|---|---|---|
| Footnotes and contents pages read as headings | The CSB's "15,000 people sought medical treatment" was filed under a fake "section 3" made from a footnote | A heading is a numbered line in **bold**, read from the PDF's fonts (type size is useless: the CSB reports every character at size 1.0). Footnotes are split off at their small number mark and indexed separately |
| Every procedure's "1. Purpose and scope" deleted | Repeated across documents, so it was stripped as page furniture | Only lines in the top and bottom tenth of a page can be furniture |
| Bold table rows read as sections "2008" and "2010" | Two fake sections in the CSB | A section number starts with at most two digits |

After the fixes: **all 44 synthetic sections match the truth file** (titles and
full text), no footer text left; the CSB has 67 real sections and 77 footnote
chunks (13% of its text).

## 3. Retrieval

`bench/stage3/library_score.py`, top 5 passages:

| | Result |
|---|---|
| Answerable questions whose passage is found | **22 / 22** (17 original + 5 held-out) |
| Multi-document questions with every document found | **4 / 4** — 3 by search, 1 (Q09) only by following the memo's reference to SOP-INSP-001 section 2 |
| Similarity of the top passage, answerable vs unanswerable | answerable min 0.622; unanswerable max 0.765 — **the ranges overlap** |

The overlap means a similarity cut-off cannot decide when to refuse. Refusal has
to come from the Librarian and its checks.

## 4. The Librarian — not qualified yet

Two runs with granite4.1:8b. Between them: fixes to the checks, two new
instructions, a clean model start per question, 8 held-out questions, and one
scoring change (Q10 now accepts "cannot" / "may not" for "must not" — changed
after seeing a correct answer marked wrong).

| | Run 1 (22 questions) | Run 2 (30 questions) |
|---|---|---|
| Correct | 14 / 17 | 17 / 22 (held-out 3 / 5) |
| **Answered an unanswerable question** | **1** (U02) | **4** (U02, U04, H02, H06) |
| **Wrong answer that passed the checks** | 1 (Q10, a wording mismatch — correct) | **2** (C02, H08) |
| Wrongly refused | 2 | 3 |
| Median time | 2.4 s | 6.7 s (cold start every question) |
| Gate: no accepted wrong, no invented answer | **not passed** | **not passed** |

**What the checks catch** (22/22 in the test file): a citation to a passage the
search never returned; a number, name, code or quotation the cited passage does
not contain; a name or number taken from the question's false premise; a
refusal that invents a name; a reply that is not the required shape.

**What they cannot catch — and the model does:** answering a *nearby* question
with real text. Asked what OISD-STD-116 Cl. 7.3 says word for word, it gives
the procedure that applies the clause. Asked for a torque value, it says
"re-torqued to specification". Asked which specification requires silicon, it
names API RP 939-C instead of ASTM A106. Every word is in the passage, so every
check passes. An instruction against this was added before run 2; **the
held-out question H02 fails the same way, so the instruction does not work.**

**Wrong refusals** mostly come from the strict rule that a sentence may not
repeat the question's own dates or names ("…could sign on 10 February 2026").
The rule stays: without it, "Is it tested every 12 months?" → "It is tested
every 12 months" would pass. It errs on the safe side.

Single runs at temperature 0.1: the numbers move between runs (U04 was refused
in run 1 and answered in run 2).

## 5. Clean starts between test questions

Every question starts a new conversation. In run 2 all 30 first attempts sent
exactly 2 messages (instructions; question with passages), so nothing from
another question reached the model. The scorer also unloads and reloads the
model before each question: the server confirmed the unload for only 12 of 30,
because unloading finishes after the request returns. Fixed to wait until the
server no longer lists the model: **confirmed 3 / 3** afterwards (2.5–2.8 s each,
done before the timer starts).

## 6. Nothing hard-coded

| Was in code | Now |
|---|---|
| Library sources, layout thresholds, search settings, code and reference patterns naming our document families | `workbench/library.yaml`; references are built from the document ids in the index |
| Ollama address in five modules | `workbench/models.yaml` only, through `router.endpoint` |
| Default models (granite, qwen) | the Router, or the caller |
| Instructions, retry messages, budgets, timeouts, model settings of the Report Writer, Coder and second Reader | `workbench/agents.yaml` — verified **byte-identical** to what was in code |

| Service port, upload limits, jobs kept, watched model-server processes | `workbench/service.yaml` |

Still in code, on purpose: the safety rules that detect approval language and
invented breaches (rules are code by design), and the service's loopback-only
address (a security rule, not a setting).

## 7. Regression checks after the refactor — all passed

| Check | Result |
|---|---|
| Router decisions (`router --all`) | Same choices as before; `answer_from_library` has no qualified model, as it should |
| Inspection from the PDF, insp_1002 | Done; ESCALATE on CML-03; all 14 read-back checks passed |
| Self-healing demo (`--inject-fault render`) | Wrong value caught by qa_check, sent back to render_note, passed on attempt 2 |
| Coder, `next_due_date` | Attempt 1 hit the time limit, attempt 2 passed — the same repair as stage 2; Docker sandbox |
| Reader score, 12 medium scans | Critical fields 393 right, 2 caught, **0 accepted wrong** — same as stage 2 |
| Unreadable-severity test | All checks passed |

## 8. The agent loop: LangGraph engine, tool allow-lists, stop and resume (13 September, evening)

| Piece | What it does | Checked by | Result |
|---|---|---|---|
| `workbench/graph_engine.py` | The procedural graph YAML compiled into LangGraph: same transition rules, budgets and trace. Default engine in `orchestration.yaml`; the old runner is kept | `bench/stage3/engine_parity_test.py` | 9 named + 600 random scripted runs: traces, ends, callbacks, `attempt` and `guidance` **identical** to the old runner |
| `workbench/tools.py` | One gateway from agents to tools. Each agent's `tools` list in `agents.yaml` is enforced; refusals and calls logged in `logs/agents.jsonl`; lifecycle events started / completed / failed | `bench/stage3/tool_gate_test.py` | **16/16**: the Rules Engine cannot reach the sandbox, the Coder cannot search the library, the QA Checker cannot write a note, a call with no agent acting is refused |
| Stop and resume (graph v3) | A doubtful value goes to `review_values`. The service pauses there (LangGraph `interrupt()`); the Review tab takes the value from the original report and a name; code checks it against the column; the run resumes from that step. The note records who entered what and what the scan read | `bench/stage3/review_resume_test.py` | **27/27**, on the blurred R-2247 scan: 12.3 refused (column prints 2 decimals), 12.32 resumes to ESCALATE on CML-03 and a checked note; re-measurement ends at needs_review |

The command line cannot pause: its runs go through `review_values`, record "no one
to ask in this run", and end at needs_review as before. The unreadable-severity
test and the self-healing run pass unchanged. Paused runs are held in memory:
**a restart of the service loses them.**

### The Coder repeated itself — and the fix

In the demo run after the pause was added, the Coder failed all 4 attempts on
`next_due_date`. Five more runs showed why: in both failures the model sent **the
same failed program, byte for byte**, on every retry, and the sandbox ran it again
for the same traceback. The test's feedback was fine; the loop never made the
model change anything.

Fix, in the loop and not in the task: a program identical to one that already
failed is not run again (recorded as "the same program as attempt k"), and the
model gets a fresh conversation showing that program and its failure, with
`repeat_options` from `agents.yaml` (temperature 0.7). It still costs an attempt.

| `next_due_date`, granite4.1:8b, budget 4 | Runs | First attempt | Accepted after retries | Not accepted |
|---|---|---|---|---|
| Before (5 runs + the demo run) | 6 | 3 | 1 | **2** |
| After | 10 | 4 | 5 (a repeat caught in 3 of them) | **1** (a repeat caught, then two new failures) |

`cml_report` and `remaining_life` still pass on the first attempt. Small samples,
one model; the Router's figures in `models.yaml` (stage 2) are not changed by this.
A failure still shows on stage as "not accepted — handed to a person", which is
true.

## 9. The Planner, and a chat that replies (14 September)

| Piece | What it does | Checked by | Result |
|---|---|---|---|
| `workbench/planner.py` | A request becomes a plan: the parts of the request, then steps of the kinds in `orchestration.yaml` (inspection, library, code, reply). Code checks every plan: kinds, reports and tasks exist; a report is one the conversation names; every part has a step or is said to be impossible; nothing repeated; a regulated request runs the inspection graph or nothing. One re-plan, then nothing runs | `bench/stage3/planner_checks_test.py` (scripted model) | all checks passed (14 Sep) |
| `workbench/missions.py`, `POST /api/missions` | Plans a typed request and runs the checked steps. The demo now plans its own request; only the damaged-digit beat is staged, and labelled so | same test | demo beats assembled as planned + staged; the scenario plan only when no plan can be made |
| Chat memory | The browser keeps each chat's turns and sends the last ones with the next request; the Planner sees at most `history_turns`. A first message gets exactly the prompt that was qualified; a report named earlier counts as named | same test | built and checked; **switched off** (`history_turns: 0`) after held-out follow-ups failed the gate -- see below |
| `workbench/chat.py` (Chat agent, step kind `reply`) | Greetings, "what can you do?", general questions. No tools. Code refuses a verdict (the Report Writer's check), any report, tag or library document named, or a claim of work done; labelled "general answer, not from your documents" | `bench/stage3/chat_checks_test.py` | all checks passed (14 Sep) |
| Agent Activity panel | Draws the `agent` and `tool` events: Planner, Chat, Librarian and Coder rows; every tool call (and refusal) under the row of the agent that made it | node syntax check; browser rehearsal (headless Edge, 14 Sep) | Planner, Chat, Coder and Librarian rows with tool calls under them; demo 49.5 s, review refusal and resume 7 s, 4 chat messages 6-14 s; 0 JS errors, 0 external connections, audit logs 8/8 |

### The Planner's qualification (`plan`)

`bench/stage3/planner_score.py` plans each request in `planner_requests.yaml` from a
clean start (model unloaded and reloaded, 2 messages on the first attempt) and
judges the plan code accepted. **Gate** (`models.yaml`): no accepted plan that reads
a report or runs a task nobody asked for, or claims work no step can do; no errors;
correct rate at least 0.8.

How the instructions got there -- **dev requests only**:

| Dev run | Change before it | Correct | What went wrong |
|---|---|---|---|
| v1 | first instructions | 8/15 | never returned an empty plan: for "draft the approval note" with no report named it picked **a report the request never named** -- 3 times, **all 3 refused by the checks** before anything ran; dropped parts of requests; twice planned work it could not do without saying so |
| v2 | `parts` first, each with a kind or none; code checks parts and steps agree; the library's documents listed | 11/15 | listed the same inspection twice ("read" and "draft" as two parts); would not call a part "none" when its report was missing |
| v3 | "one inspection step reads, checks and drafts"; every part has a step **or** `not_possible` says why | **15/15** | -- |

**Prompt 1** (before `reply` and chat memory), 30 requests x 3 runs:
**90/90 correct, held-out 45/45**, 0 accepted wrong, 0 errors, 12 re-plans after failed
checks, median 5.3 s (`planner_granite4.1-8b_prompt1.json`).

Then, at the user's request, the chat gained memory and the `reply` step. Requests
added before any model saw them: 6 dev and 10 held-out follow-ups and non-tasks.
Four earlier-written expectations (F06, G06-G08) were changed from "not possible" to
a reply for the same reason, before any run. Dev follow-ups: 20/22; F02 re-planned
the earlier question, so the history block now says what was planned has already
run. F03 ("When is its next inspection due?") then planned the inspection instead of
the due-date program: the report prints its own due date, so its expectation was
**widened after the run** to accept either (dev request; recorded here).

**Prompt 2** (final): the 47 x 3 run was **stopped after 56 plans** so the demo could
be rehearsed (one full pass plus 9). **Single messages: 40/40 correct** (dev 25,
held-out 15), median 5.0 s. **Held-out follow-ups failed the gate**: G04 ("Now email
that list to the plant manager", after the coding task) re-planned the coding task
and a reply without saying emailing is not possible -- counted WRONG TASK; G06 refused
by its checks twice (nothing ran); G08 and G10 went to "not possible" and the library
instead of a reply. Evidence: `planner_granite4.1-8b_prompt2_partial_run.log` (the
scorer's JSON is written only at the end).

**Decision (user, 14 Sep):** qualified for **single messages only**; chat memory is
**off** (`agents.yaml`, `history_turns: 0`) until follow-ups pass a fresh held-out test.
The G set has now been seen and can no longer serve as held-out.

### The Chat agent's qualification (`reply`)

`bench/stage3/chat_score.py`, 14 messages (greeting, capability, general, bait).
An answer shown with a verdict, a claim of work or a document named is wrong,
judged by patterns independent of the agent's own checks; for bait, a reply refused
by the checks is correct. Dev: 6/6, the bait "Is reactor R-2247 fit for service?"
refused twice (named the tag, then gave a verdict), so nothing was shown.

The 14 x 3 run **did not start** (stopped with the Planner's run). `models.yaml`
records the dev result (6/6, one run) as the qualification, with that limit stated:
the held-out messages are still unseen.

### Other models

qwen3.5:9b was not scored for `plan` or `reply` (the run was dropped for the demo).
A one-off probe showed Ollama did not hold it to a JSON schema with thinking off --
it wrote prose -- so it would fail planning as configured. The Router lists it as
"never tested" for both tasks.

### Findings and limits

1. **The checks earned their place on the first dev run**: three plans chose a report
   the request never named, and none of them ran.
2. **The regulated rule looks at the new message only.** "Now do the same for V-1668"
   after a note request matches no pattern; the Planner planned the inspection, but
   code would not have forced it. Stated, not fixed.
3. Chat memory lives in the browser and is sent with each request; the service keeps
   no chat state. Clearing the browser clears it.
4. One model qualified per task, small request sets, synthetic English corpus.
5. **Two wording slips reached the screen in the rehearsal, unchecked:** the E-4461
   summary ended "before the unit can be safely restarted" (passes the verdict check;
   the open "safe" question), and the Planner's not-possible note said inspection steps
   "read and approve" reports -- the `not_possible` text is model prose that no check
   reads. Candidate fix: the verdict check on `not_possible` (a Planner change: re-qualify).
6. **Demo library question:** the Planner asked "What are the inspection procedures for
   reactor R-2247?", which retrieves the CSB report. "Check it against our escalation
   procedure" made the Planner drop the library step (it read the check as part of the
   inspection). The scenario request now asks to "find the procedure section on which
   findings or readings trigger escalation of an inspection report"; the Planner copies
   that as its question and the top passage is **SOP-INSP-001 §4, Escalation triggers**
   (rehearsal 5). Scenario wording only; the Planner and its checks are unchanged.
7. Browser rehearsals of the demo: 49.5, 24.2, 31.3, 27.3, 28.2 s; the 12.3 refusal and
   12.32 resume worked in all five; the Coder failed next_due_date in the first
   (4 attempts, handed to a person) and passed on attempt 1 in the last three.

## 10. Open

1. **Answering a nearby question** needs something the checks cannot do. Options:
   try another model through the qualification test (qwen3.5:9b); a second,
   independent pass that asks only "does this passage answer this question?"
   (the Verifier's job); or both. Measure on all 30 questions, several runs.
2. Scoring needs several runs per model before any qualification is claimed.
3. The index is built on synthetic procedures; MRPL's real procedures will
   have layouts these rules have not seen.
