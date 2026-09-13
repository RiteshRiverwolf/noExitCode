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

## 9. Open

1. **Answering a nearby question** needs something the checks cannot do. Options:
   try another model through the qualification test (qwen3.5:9b); a second,
   independent pass that asks only "does this passage answer this question?"
   (the Verifier's job); or both. Measure on all 30 questions, several runs.
2. Scoring needs several runs per model before any qualification is claimed.
3. The index is built on synthetic procedures; MRPL's real procedures will
   have layouts these rules have not seen.
