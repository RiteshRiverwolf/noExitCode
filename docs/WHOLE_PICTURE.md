# The whole picture — the workbench, the agent team, and who starts on what

Written 2026-09-12 so everyone can work in parallel. This is the one document
that says what we are building, how the pieces fit, what the demo is, and how
it maps to the way SIH actually scores. Detail lives in
`docs/ARCHITECTURE.md` (design of record), `docs/HARNESS_AND_ROADMAP.md`
(scaling) and `docs/PS_ANALYSIS.md` (requirements R1–R6).

**The rule:** every claim is marked **Proven** (we ran it, evidence in the
repo), **Built** (code runs, not measured at scale) or **Proposed**
(designed, backed by published work, not built). Nothing is presented as
finished when it is not. Where a piece is unfinished, we show the measurement
that says the approach works and the published result that says it scales.

---

## 1. What we are building

**A sovereign AI workbench: the organisation's own team of AI specialists,
running entirely inside the building.**

MRPL and units like it generate enormous volumes of sensitive knowledge work —
approval notes, board decks, engineering calculations, internal tooling code,
scanned drawings and inspection reports. None of it can go to Claude or Codex,
because the data is confidential. So the work is done by hand, or quietly
pasted into a public tool anyway.

We are not building a chatbot with documents attached, and not one
inspection-report script. We are building **a team of agents that does the
work**: it plans multi-step jobs, uses real tools on the machine, **writes and
runs code whenever that is the fastest way to an answer**, reads scans and
photographs, tests its own output, and returns finished Word, Excel and
PowerPoint files — grounded in the organisation's own manuals and SOPs, with
every number traceable to its source, and live proof that nothing left the
premises.

The difference from what already exists is not the feature list. AnythingLLM
already routes models and generates documents; Onyx already runs code in a
sandbox. **What nobody ships is the evidence spine:** every critical value
carrying its source page and a picture of the cell it was read from,
deterministic rules a model cannot overrule, every deliverable verified by
reading the finished file back, and the machine stopping to ask a person when
it is unsure. In a refinery, a confidently wrong assistant is worse than no
assistant. That is the product.

---

## 2. How SIH scores, and what we lead with

Published weighting for the idea submission: **Innovation and uniqueness 25%,
problem understanding and clarity 20%, technical feasibility 20%, impact and
scalability 20%, presentation quality 15%.** The finale is a live pitch —
roughly 15 minutes plus 5 minutes of questions — and the consistent advice from
past rounds is that **a stable working prototype beats an ambitious
half-finished build.** The official deck runs about ten slides: problem,
solution, technical architecture, innovation, feasibility, impact, prototype,
timeline, team and references.

What that means for us, concretely:

| Criterion | What we show |
|---|---|
| **Innovation 25%** | The evidence spine and the self-checking loop — not "we used an LLM". The damaged-digit catch (§4) is the single most original thing we have: a code check that catches what two independent readers and a 1.000 confidence score all missed. |
| **Problem understanding 20%** | We can state exactly why the naive build fails: a whole-page vision model never reports a damaged digit as unreadable — it writes a plausible number, and in 3 of 18 runs copied a *neighbouring cell's value*, which flips ESCALATE to NO TRIGGER. We measured that. |
| **Technical feasibility 20%** | It runs now, on a 12 GB RTX 4070, offline. Every number in the deck comes from a script in the repo that a judge can re-run. |
| **Impact & scalability 20%** | Same harness, bigger server: models are plug-ins admitted by a qualification test. Connectors (§8) put it where people already work. |
| **Presentation 15%** | Live demo of the break-it-on-purpose loop (§5 step 7). Thirty seconds, and it proves the whole thesis. |

**Judging implication we should act on:** the prototype must not be fragile.
Anything that only works on one file, or needs a network, is a liability on
stage — which is why vendoring Tailwind (§9) is a demo-blocker, not a chore.

---

## 3. The three layers, and the agent team

**1. The floor — a pool of models, not one model.** Open-weight models are
plug-ins; each is admitted to a job only by passing a qualification test on our
harness, and new ones drop in without redesign.

**2. The team — specialist agents with defined powers.** Each agent is a small
definition: its purpose, the tools it may call, the models it may use, and what
it must prove before its output is accepted. An agent cannot reach a tool
outside its allow-list. That is what makes the multi-agent design real rather
than decorative — the agents differ in *authority*, not just in prompt.

**3. The rails.** Evidence spine, verification, hash-chained audit log,
human-in-the-loop gates, and the Sentinel proving nothing left the machine.

| Agent | What it does | Powers | Status |
|---|---|---|---|
| **Planner** | Breaks a request into a plan, picks the mission type and the agents, re-plans when a step fails | delegates only | Proposed |
| **Router** | Picks the model per step from task type and measured qualification results, logs the reason (R2) | model registry | **Built** — wired into the pipeline and the Coder |
| **Reader** | Scans, PDFs, drawings, photos → evidence records with page, box and crop (R5) | OCR, vision, file read | **Proven** (§4) |
| **Librarian** | Searches manuals, SOPs, past correspondence; answers with citations or says it doesn't know | knowledge base, file read | Proposed (§7) |
| **Analyst** | Engineering calculations with steps shown — **and writes throwaway code to compute an answer when that is the right tool** | sandbox, spreadsheet, evidence store | Proposed (§6) |
| **Coder** | Writes code, runs it in the sandbox, reads the test output, fixes, repeats (R4) | sandbox only — no network, no host filesystem | **Proven** (§5a) |
| **Author** | Real deliverables: Word notes, Excel workbooks, PowerPoint decks | docgen MCP, file write | **Built** for Word |
| **Verifier** | Independently checks each deliverable against the evidence, reads the finished file back, returns failed work | file read, evidence store | **Built** |
| **Sentinel** | Watches every tool call and outbound packet, produces the R6 proof, holds the approval gates | audit log, network monitor | Partly proven |

### Two ways of working, and the Planner chooses

- **Regulated missions** — an approval note, a calculation feeding a decision.
  Fixed procedural graph: defined steps, rules in code, verified output, full
  trace. A model may *write*, never *decide*.
- **Open missions** — "summarise these vendor replies", "build a deck from this
  month's inspections", "find which units are closest to their limit". A real
  agent loop: plan, call tools, look at results, iterate.

Same rails underneath both, and the choice is logged, so a regulated task can
never be quietly downgraded into a free-running loop.

---

## 4. The Reader — finished today (Proven, 2026-09-12)

Until this morning the pipeline read the answer key instead of the document.
Now it reads the document.

```
pagesource.py   PDF or scan -> per page, every piece of text with its box
                  - born-digital PDF: its own characters, exact and instant
                  - a scan: OCR (PP-StructureV3), page text with boxes
tablemap.py     code places each value in its cell (tilt-corrected) and checks it
scan_reader.py  the report's shape -> evidence records with page, box and crop
```

Measured by `bench/stage2/reader_score.py` against ground truth:

| Source | Critical fields right | Accepted wrong | Time |
|---|---|---|---|
| 12 born-digital PDFs (whole corpus) | **395 / 395** | **0** | 0.1 s each |
| insp_1002 clean scan (OCR) | 30 / 30 | 0 | 0.1 s |
| insp_1002 medium scan (OCR) | 30 / 30 | 0 | 0.1 s |
| insp_1002 heavy scan (OCR) | 29 right, 1 flagged | 0 | 0.1 s |
| **all 12 clean scans (OCR)** | **386 right, 9 flagged** | **0** | 0.1 s each |
| **all 12 light scans (OCR)** | **392 right, 3 flagged** | **0** | 0.1 s each |
| **all 12 medium scans (OCR)** | **393 right, 2 flagged** | **0** | 0.1 s each |
| **all 12 heavy scans (OCR)** | **380 right, 15 flagged** | **0** | 0.1 s each |

Through the whole pipeline, 48 scan runs: **28 approval notes, every one with
the correct outcome; 19 stops for a person that were right to stop; 1 false
alarm; 0 wrong outcomes** (`bench/stage2/pipeline_stops.py`). Worse scans send
more work to people rather than more errors to paper.

"Accepted wrong" — a wrong value nothing flagged, which would reach a signed
note — is the only number that matters. It is zero everywhere. The whole-page
vision model tested in stage 1 took 23 s per report and made 4 critical errors
on heavy scans.

### The damaged-digit result — our strongest slide

Stage 1 concluded a physically erased digit "can only be caught by a person".
Re-measuring today showed the check we had planned does not work, and a better
one does:

- **Leftover ink does not work.** An erased digit leaves a white gap — no
  pixels to count. A blurred one only separates at a brightness where the
  table's grid lines also count. We are not presenting this check.
- **Column precision does work, and it is pure code.** A thickness column is
  printed to a fixed number of decimals. The smudged `12.32` reads as a clean
  `12.3` — at confidence 1.000, by two independent readers — but `12.3` carries
  one decimal where the rest of its column carries two. Both the blurred and
  the **erased** case are now caught and sent to a person, with no false alarm
  anywhere in the corpus.

The thesis in one example: safety came from a cheap check on a property of the
printed form, not from a bigger model or a higher confidence score.

---

## 5. The demo

One workbench, several missions, one visible agent timeline.

| # | What the judge sees | Status |
|---|---|---|
| 1 | **The machine is sealed.** Live panel: outbound attempts blocked, packet capture as evidence (R6) | Proven at container level; **panel live** (connection snapshot + audit-log chains, 2026-09-13) |
| 2 | **"Read this inspection report and draft the approval note."** The Planner lays out steps; agents light up as they work | Graph, trace and **live streaming Built** — the frontend shows every stage event; the plan shown is the demo scenario (Planner not built) |
| 3 | **Reader** extracts every finding and reading, each shown with the crop of its cell | **Built** |
| 4 | **One cell is flagged** — the damaged digit. The run *pauses*; the engineer sees the crop and decides | Detection Proven; the run **stops** and the Review tab shows the cell crop (Built); resuming from the engineer's decision is Proposed (§10) |
| 5 | **Rules fire in code** and say why: severity, or a reading below minimum | **Built** |
| 6 | **Author** writes the Word note; **Verifier** reads the finished file back and checks every number | **Built** |
| 7 | **We break it on purpose.** A wrong number is injected; the Verifier catches it; the work is sent back and repaired | **Built** — our best 30 seconds |
| 8 | **"Which clause covers external corrosion?"** The Librarian answers with the clause cited and its page — and refuses when it isn't in the library | **Search with citations Built** (22/22 retrieval); written answers built but **not qualified** — the demo shows the cited passages only |
| 9 | **"Which readings are worst across all these reports?"** No single report says, so the **Coder writes the code on the spot**, runs it sealed, and answers from the result | **Partly built** — the sandboxed Coder passes a *predefined* version of this task, checked by held-out tests. Answering an *arbitrary* question this way needs the evidence store to query and a different kind of check, since an ad-hoc question has no pre-written tests |
| 10 | **"When is the next inspection due?"** The first program hangs; the sandbox kills it at the time limit; the model reads that and fixes it (R4) | **Built** — fails then passes, 50 s |
| 11 | **"Why this model?"** The Router shows the model per step and the reason, logged (R2) | **Built** — "Why this model" tab: every task's choice and every candidate's reason |
| 12 | **"Tell the approvals channel it's ready."** A Teams/Slack notification goes out with *no confidential content* — the Sentinel shows exactly what left (§8) | Not built |

Rows 1–7 and 9–10 are real today: document in, checked deliverable out, with the
machine catching its own mistake — and code written, sealed, run and verified.

### 5a. The sandbox is demonstrable, not asserted

`python -m workbench.sandbox --self-test` shows code inside the sandbox trying
to reach the network and failing three ways (TCP refused, DNS failed, HTTP
failed), failing to write outside its working directory, and being killed when
it loops forever. Each probe takes under a second. `--network none` gives the
container **no interface at all** — not a blocked one, an absent one — which is
both stronger and easier to explain than a firewall rule.

**And the model does not mark its own homework.** A coding task is accepted
only when the acceptance tests *we* wrote pass; the model sees the failure
messages, never the test source. That is the same division as the summary
writer — the model produces, code decides — and it is what makes "verified in a
sandbox" a claim rather than a phrase. The tests themselves were checked by
running a reference solution and a deliberately wrong one against each, so we
know they bite.

---

## 6. Code as a tool, not just a demo item

R4 asks for "a coding task run and verified in a sandbox". We should treat that
as the *smallest* use of the capability. **Any agent that can reach the sandbox
can write code to answer a question it cannot answer by reading.**

"Which of these 40 reports has the worst corrosion rate relative to remaining
life?" has no answer in any single document and is miserable for a language
model to do in its head. The right behaviour is: write ten lines of Python over
the evidence store, run it, show the code, the output and the answer. This is
also the honest way to do arithmetic — the numbers come from code, the model
only explains them.

**Why it is safe:** the sandbox has no network and no host filesystem; the code
and its output are logged and shown; and a number produced this way still comes
from evidence records, so it is traceable like every other number. This is
strictly more trustworthy than a model doing mental arithmetic, which is what a
chatbot does today.

---

## 7. The knowledge base — how it should look

We want this and don't have it yet. The key decision: **two stores, not one.**

### 7a. The evidence store — structured and exact

Every reading and finding the Reader has ever extracted, per equipment tag, in
a plain SQL table. Not a vector database.

- **Holds:** report id, tag, CML id, thickness numbers, severities, source page,
  box, file hash — the evidence records we already produce.
- **Answers:** "what was CML-03 last time?", "has this tag ever been below
  minimum?", "every Major finding on R-2247". Also what the Analyst's code runs
  over (§6).
- **Unblocks:** the check "thickness grew since the previous reading", designed
  and unable to run until this exists.
- **Rule:** numbers in a deliverable come from here or from the document in
  hand — never from a retrieved passage.

### 7b. The reference library — search, for wording and citations

What an inspector reasons *with*: standards and codes (the clause behind
`OISD-STD-118 Cl. 6.2`), MRPL procedures and SOPs, past correspondence, the
prose of old reports.

- **Chunking:** by section, each chunk keeping document, page and box — the same
  provenance contract the Reader produces, so a retrieved passage is shown on
  the page it came from. **The Reader is what fills this.**
- **Embeddings:** `nomic-embed-text`, already in Ollama, runs offline.
- **Store: our own SQLite index — Built (2026-09-13).** Chosen over LanceDB
  inside AnythingLLM because each chunk keeps its document, section, page and
  box for the citation, and BM25 keyword search and vectors share one file with
  no new dependency. `workbench/library.py`, settings in `library.yaml`.
- **GraphRAG later, when needed** — the recorded graph first
  (HARNESS_AND_ROADMAP §5), not a graph over everything.
- **Retrieval: hybrid keyword + vector.** Clause identifiers like
  "OISD-STD-118 Cl. 6.2" are exactly what embeddings are worst at and exact
  keyword matching is best at. Vector search alone will miss them.
- **Hard rule:** the library supplies wording, context and citations — never a
  value, and every sentence it contributes carries its source.

### 7c. How we know it works

A retrieval test set in the spirit of the reader scorer: questions with the
passage that should be found (hit@k), **plus questions whose honest answer is
"not in these documents"**, so we measure refusal and not just recall. A
knowledge base that always answers is one that will invent a clause number on
stage.

### 7d. Three kinds of memory — what the agents remember, and who may change it

The two stores above are one kind of memory. Agents need three, plus the
scratchpad of the task in hand. The split is from **CoALA**, *Cognitive
Architectures for Language Agents* (Sumers, Yao, Narasimhan, Griffiths; TMLR
2024), and LangGraph's own memory docs use the same three names.

| Memory | What it is (CoALA) | Ours | Status |
|---|---|---|---|
| **Working** | What the current step needs: inputs, retrieved knowledge, active goals | The mission's LangGraph state, checkpointed so a paused mission resumes where it stopped | Pause and resume tested 30/30, in memory only |
| **Semantic** — facts | The agent's knowledge about the world | Evidence store (§7a, exact numbers); reference library (§7b, wording and citations); recorded knowledge graph (HARNESS_AND_ROADMAP §5.1) | Evidence store **Built**; library **Built**, first score 16/17; graph Proposed |
| **Episodic** — what happened | Experience from earlier runs | Run folders `runs/<job-id>/<stage>/`, the hash-chained audit log, every reviewer decision on a flagged cell. Recalled as "last time": the previous reading for *thickness grew*, a correction an engineer made, a plan that worked, shown to the Planner as an example | Records **Built**; recall Proposed |
| **Procedural** — how the work is done | Model weights plus the agent's code and instructions | The procedural graph (steps, guidance, pitfalls), agent definitions with tool allow-lists, rules in code, the models in `models.yaml` | Graph and rules **Built**; agent definitions Proposed |

**Rules:**

- **A finished mission may write semantic and episodic memory**: evidence
  ingested, the run recorded. Anything recalled from them is still evidence with
  its source attached, never something the model "remembers".
- **No agent writes procedural memory while it runs.** CoALA says writing to
  it is "riskier than writing to episodic or semantic memory, as it can easily
  introduce bugs or allow an agent to subvert its designers' intentions." Ours
  changes only through the refiner, the validation set and an engineer's
  approval (HARNESS_AND_ROADMAP §4.2), with every version kept.
- **All of it stays on the machine.** The installed LangGraph (checkpoint
  4.2.0) keeps its checkpointer and store in memory only; no SQLite backend is
  installed. Long-term memory goes in our own SQLite files, or a vendored SQLite
  backend tested with the network off, the same way LangGraph itself was.

---

## 8. Connectors — reaching Teams and Slack without leaking

People live in Teams and Slack. A workbench nobody opens is a workbench nobody
uses. But the entire premise is that confidential content does not leave.

**The design that satisfies both: the connector carries notice, never content.**

- **Outbound is a whitelist of message shapes**, not free text: "approval note
  for R-2247 is ready for review", plus a link that only resolves *inside* the
  network. The document itself never crosses.
- **The Sentinel enforces it** — every outbound call passes the same gate that
  produces the R6 evidence, and the panel shows exactly what left, byte for
  byte. A connector does not get an exemption from the network proof; it is the
  proof's hardest test.
- **A person approves each new kind of message**, using the same approval
  callback as any other privileged tool call.
- **Inbound is a request channel:** a message in Teams can *ask* the workbench
  for work; the work and its output stay on the machine.

Presented honestly, this is a strength: most "secure AI" products treat
integration and confidentiality as a trade-off. Ours makes the boundary a piece
of code with a log, so the answer to "what did you send my vendor?" is a file,
not a promise.

---

## 9. Observability and logging — Langfuse, not LangSmith

Currently we have a hash-chained audit log of every stage and tool call. That
is the *compliance* record: tamper-evident, ours, and evidence for R6. What we
do not have is *developer* observability — seeing a mission's agent calls,
prompts, tokens, latencies and failures while building.

**Recommendation: Langfuse, self-hosted.** MIT core, the same codebase as their
cloud, documented on-premises operation with internet access optional, and it
speaks OpenTelemetry. **LangSmith is the wrong choice here on a hard
constraint, not a preference:** it is proprietary, self-hosting is
Enterprise-only, and outside a specific air-gapped licence it requires egress
to `beacon.langchain.com`. A tool that phones home cannot sit inside a system
whose headline claim is that nothing leaves the machine — and a judge who spots
that outbound connection has just won the argument.

**Practical caution for the demo:** Langfuse wants Postgres, ClickHouse, Redis
and blob storage — heavy on a 12 GB demo box. So the order is: keep our audit
log as the record of truth, emit OpenTelemetry spans from the agent graph
(which costs us nothing and is what Langfuse consumes), and stand Langfuse up
on the dev machine where the resources exist. The deck says "OpenTelemetry, with
a self-hosted Langfuse for analysis" — accurate, and it explains why the cloud
option was rejected.

---

## 10. LangGraph — the decision

Today the pipeline runs on our own `workbench/procedural_graph.py`: YAML graph,
retries, trace, hash-chained log. It works and produced the self-healing demo.

**Recommendation: move to LangGraph**, for three things the agent team needs:

1. **`interrupt()` — stopping for a human.** Demo step 4 needs the run to pause
   at a flagged cell, wait for the engineer, and resume exactly there. Our graph
   cannot, and it is the hardest piece to get right by hand.
2. **Checkpointing** — a long mission resumes instead of restarting.
3. **Streamed events** — the live agent timeline and the R6 multi-agent proof
   fall out of the event stream instead of being animated. Also what feeds §9.

**Conditions:** pure Python, so the wheels are vendored and verified with the
network physically off — a test, not an assumption. Stage handlers stay plain
functions with no framework imports, so the engine can be swapped and the demo
is never blocked on the migration.

### 10a. What the move must keep

LangGraph is the engine, not the design. Three ideas from earlier in the project
carry over. None of them may be lost in the migration.

**1. The procedural graph stays the source of truth.** From *Procedural Graphs*
(arXiv 2609.09153; ARCHITECTURE §3.3, HARNESS_AND_ROADMAP §4). The YAML file is
compiled into a LangGraph graph rather than rewritten by hand:

- stages become nodes, and the `when: ok / fail / exhausted` edges become
  conditional edges;
- `max_attempts` and `step_budget` stay enforced counters;
- guidance and pitfalls are still inserted into each stage's instructions.

The **self-healing loop** (a failed check sends the work back to the stage that
caused it; out of budget, the job goes to a person) must pass
`run_inspection --inject-fault render` unchanged on the new engine before the
old runner is retired. Self-evolution stays **Proposed**, with an engineer's
approval gate (§7d: procedural memory).

**2. ICM: each stage sees only what it needs.** From the *Interpretable Context
Methodology* (arXiv 2603.16021; ARCHITECTURE §3.2): 2,000–8,000 focused tokens
per stage instead of 40,000+ at once, which matters on 12 GB. Per-job run
folders are **Built**. The per-stage `CONTEXT.md` contracts were **never
built**; the agent definitions (§3) are where they now go: inputs, output
contract, and the context that stage is given.

**3. Ideas from the GitHub Copilot SDK** (MIT; discussed 2026-09-11, recorded
here for the first time):

| Idea | Where it lands | Status |
|---|---|---|
| Each agent is a small definition with a list of the only tools it may use | Agent definitions (§3); the allow-list is enforced in code, a refused call is logged | Proposed |
| Lifecycle events per agent (`selected / started / completed / failed`, tagged with the agent's id) | The live agent timeline and the audit log (§9, §11) | Proposed |
| An approval step on every tool call | The Sentinel's approval gate; connectors wait for it (§14 H) | Proposed |
| Packaged skills checked against acceptance criteria | The model qualification test (§3) | Built in part |

**Not copied:** Copilot hands work to an agent by matching the request to
agent descriptions, so the model decides who works next. That is acceptable for
open missions and never for regulated ones, which stay on the graph. Its
built-in shell and file-editing tools would be switched off. **Running the SDK
itself is not planned:** the licence of the Copilot CLI it bundles, and whether
its offline switch works through the SDK, were never checked.

---

## 11. The interface

`frontend/index.html` is a prototype. In order:

1. **Vendor Tailwind.** It loads from a CDN today, which breaks the moment the
   machine is sealed — and being sealed is the point. Demo-blocker.
2. **Connect it to the workbench** — a small local service (uvicorn and
   starlette are already in `.venv`) streams agent events, so the timeline is
   real rather than a cartoon.
3. **The review screen** — flagged cells with crops and an accept/correct
   decision, feeding the paused run (§10).
4. **The Sentinel panel** — reads the real audit log and capture instead of a
   hard-coded zero.

---

## 12. Open fronts, and how we present each

| Req | Where it stands | What we say |
|---|---|---|
| R2 model routing | **Built** — granite for summaries, tools and code; qwen for second readings; nothing for photographs, because nothing is tested; wired into the pipeline and the Coder | The Router applies measured qualification results; a safety gate shuts out the two models that wrote false approvals. See the correction below. |
| R4 sandbox | **Done** — sealed sandbox, three tasks, one of them repairing itself after the time limit killed it | The model does not mark its own homework: our held-out tests decide. §6 makes it a daily tool rather than a demo trick. |
| R5 multimodal | Reader built and measured | Done for printed scans and tables. Engineering drawings stay a stretch goal, never described as finished. |
| R6 network proof | Container-level proof done; panel hard-coded | The capture is real evidence; the panel must read from it. Connectors (§8) are the strongest test of it. |
| Parser upgrade | PP-StructureV3 scores 64.45 on OmniDocBench v1.6; **PaddleOCR-VL-1.6 scores 96.33** at 0.9B, Apache 2.0, already downloaded | Architecture is parser-agnostic — one module changes. Admitted only if it returns per-value boxes and confidence and scores zero accepted-wrong on the damaged-cell test. Benchmark rank earns a trial, not the job. |
| Multi-page reports | Only one corpus report has a second page | An honest gap. The Reader handles any length and joins rows across pages by CML id; the corpus must catch up to prove it. |

### Correction to a claim we were about to make

Stage 1 measured Granite 4.1 8B beating Sarvam 30B at note-writing — fewer
safety errors, 19× faster. **That is not evidence that 8B beats 30B in
general,** and we should not say so. The likely reason is that the task is
mostly instruction-following and tool-shaped work, where Granite is strong, and
the checker was developed against Granite's mistakes, which favours it. Sarvam's
actual strength — 22 Indian languages — was never exercised by an English
corpus. Nothing was tested on the 120B-class hardware the PS describes as the
reference deployment.

What the result *does* support, and what we say: **the qualification test picks
the model per task, and the safety net is code, not model size.** That is a
stronger claim anyway, because it is the one we can defend under questioning.

---

## 13. Settled, and what's still open

**Settled:** the problem statement is known (`docs/PS26117.md`); the corpus is
**English**; there are **no handwritten notes** — so handwriting drops off the
critical path and the F002 caution applies only if a judge raises it.

**Still open, and worth chasing:**

1. The venue's GPU, RAM and OS — decides which models ship in the demo image.
2. Who may see which documents — decides access control on both stores in §7.
3. SIH rules on disclosing AI-assisted development.
4. Whether judges read "model auto-selection across two task types" as two
   task-specific LLMs, or as OCR-plus-reasoning (open point in PS_ANALYSIS §1).

---

## 14. Who starts now — nobody waits for anybody

| Stream | Work | Blocked by |
|---|---|---|
| **A. Interface** | Vendor Tailwind; event-streaming service; review screen with crops; Sentinel panel | nothing |
| **B. Librarian** | Reference library (§7b) and the retrieval test set (§7c) | nothing |
| **C. Evidence store** | The SQL store (§7a), the "thickness grew" check, and the query surface the Analyst's code runs over | nothing |
| **D. Orchestration** | LangGraph behind the same handlers; `interrupt()`; agent definitions with tool allow-lists; OpenTelemetry spans (§9) | nothing |
| **E. Sandbox** | *Done.* Next: let the Analyst call it mid-conversation (§6), and stage the image for the air-gapped build (`docker save`/`docker load`) | nothing |
| **F. Corpus v2** | Multi-page reports, tables split across pages, image-only PDFs | nothing |
| **G. Parser trial** | PaddleOCR-VL-1.6 through the qualification test | nothing — GGUF downloaded |
| **H. Connectors** | Teams/Slack notice-not-content connector behind the Sentinel gate (§8) | needs D's approval callback to land first |
| **I. Deck** | Ten slides to the weighting in §2, every number re-runnable from the repo | reads this document |

---

## Sources

- SIH evaluation weighting and deck structure —
  [SIH 2026 PPT template and scoring](https://reskilll.com/blogs/sih-2026-ppt-template-exact-format-slides-evaluators-score/),
  [Smart India Hackathon](https://sih.gov.in/)
- Parser benchmark — [PaddleOCR-VL-1.6](https://arxiv.org/html/2606.03264v1),
  [OmniDocBench](https://github.com/opendatalab/OmniDocBench)
- Memory — Sumers, Yao, Narasimhan, Griffiths, [Cognitive Architectures for Language Agents](https://arxiv.org/abs/2309.02427) (TMLR 2024), §4.1;
  [LangGraph memory concepts](https://docs.langchain.com/oss/python/concepts/memory)
- Orchestration ideas — [Interpretable Context Methodology](https://arxiv.org/abs/2603.16021),
  [Procedural Graphs](https://arxiv.org/abs/2609.09153),
  [GitHub Copilot SDK](https://github.com/github/copilot-sdk) and its
  [custom agents docs](https://docs.github.com/en/copilot/how-tos/copilot-sdk/features/custom-agents)
- Observability — [Langfuse self-hosting](https://langfuse.com/self-hosting),
  [Langfuse vs LangSmith comparison](https://www.kosmoy.com/resources/blog/langsmith-vs-langfuse/)
