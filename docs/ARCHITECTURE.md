# SIH26117 — System Architecture

**Revision 2 — 2026-09-10.** Replaces revision 1 (2026-09-05). §12 lists what
changed and why. In short: Ritesh's adversarial review
(`air-gapped-workbench-critical-review.pdf`, 6 Sep 2026) found real errors in
rev 1, and the team decided to build on existing products instead of
standalone.

Related: [`PS_ANALYSIS`](PS_ANALYSIS.md) (what the problem statement asks),
[`STACK_INVENTORY`](STACK_INVENTORY.md) (candidate models and libraries),
[`DATASETS`](DATASETS.md) (test data), [`PID_APPROACH`](PID_APPROACH.md)
(drawings).

---

## 1. What we are building

An offline workbench for confidential refinery work, running on the
organisation's own hardware. It plans multi-step work across a team of
specialist agents, uses local tools, and returns real files.

Its flagship workflow reads a scanned inspection report and drafts an approval
note in which **every critical reading links back to the exact table cell it
came from**, uncertain readings are sent to a person rather than guessed, and
the draft carries a record of the checks it passed.

**Positioning.** Existing open-source products already do model routing, file
generation and sandboxed code (§11). We do not compete on having those
features. We compete on **evidence and reliability**:

> An offline inspection workbench that links every critical reading and
> recommendation to visible source evidence, handles uncertainty explicitly,
> and produces a verified approval-note draft on a 12GB workstation.

That wording comes from the review. It is a promise we have to earn through
the tests in §10, not a claim we can make today.

### Principles

1. **Use existing products; build only what is specific to us.**
2. **The model explains, code decides.** Safety-relevant decisions are
   deterministic rules over checked data, never model judgement.
3. **Every number has a source.** No critical value appears in an output
   without a link to its document, page and cell.
4. **Uncertainty is a result, not an error.** Missing or ambiguous evidence
   produces "needs review", never "safe".
5. **Every handoff is a file a person can open.**
6. **Models are configuration** — and any model change must pass a
   compatibility test before use (§5.3).

---

## 2. Components

```
┌──────────────────────────────────────────────────────────────────────┐
│ SOVEREIGNTY BOUNDARY — outbound traffic blocked and logged (§8)     │
│                                                                      │
│  OUR FRONTEND                                                        │
│  chat · upload · agent timeline · evidence viewer · network panel    │
│        │                                                             │
│  GATEWAY (Python) — records every run, sends each request to:        │
│        ├── inspection / coding / intake ──► AGENT TEAM   (§3)        │
│        └── general chat / document Q&A ───► ANYTHINGLLM  (§4)        │
│                                                                      │
│  AGENT TEAM                         ANYTHINGLLM (Docker, MIT)        │
│  ICM stage folders                  chat · Model Router · LanceDB    │
│  + procedural graph                 · its own MCP-capable agents     │
│  + state machine                          │                          │
│        │                                  │                          │
│        └────────────┬─────────────────────┘                          │
│             MCP TOOL SERVERS (Python, MCP SDK, localhost)            │
│             ocr · docgen · sandbox · library lookup                  │
│                     │                                                │
│             DOCUMENT LIBRARY + INTAKE   (§6)                         │
│                     │                                                │
│             MODEL SERVING — llama.cpp · PaddleOCR-VL runtime (§5)    │
└──────────────────────────────────────────────────────────────────────┘
```

| Component | Built or reused | Role |
|---|---|---|
| Frontend | **Built** | The views judges and users need that no stock UI has: live agent timeline, evidence viewer, network panel |
| Gateway | **Built** (thin) | Routes each request; writes the run record |
| Agent team | **Built** | The evidence-first workflows — the part that is actually ours |
| MCP tool servers | **Built** (small) | OCR, Word generation, sandbox, library lookup — usable by both our agents and AnythingLLM |
| Document library + intake | **Built** | Revision-controlled knowledge base |
| AnythingLLM | **Reused** | General chat, model router, embeddings + vector search, ad-hoc agents |
| Models, OCR, serving | **Reused** | Qwen, PaddleOCR-VL, llama.cpp |

---

## 3. The agent team

### 3.1 Roster

| Agent | Job | Runs on |
|---|---|---|
| **Supervisor** (planner) | Reads the request, picks the plan, handles retries and handoff to a person | General model |
| **Document Reader** | Scan → text and tables | PaddleOCR-VL |
| **Evidence Builder** | Every table row → a checked evidence record (§7.1); flags dropped rows, orphan values, missing units | Model + validation code |
| **Rules Engine** (checker) | Evaluates approved rules — e.g. is any reading below its minimum? | **Plain code, no model** |
| **Standards Researcher** | Finds the governing clause for each finding | Library lookup + search |
| **Report Writer** | Fills the Word approval-note template | python-docx; model writes prose only |
| **QA Checker** (checker) | The four checks in §7.3 | Code + vision model |
| **Coder** (R4) | Writes and tests code in the sandbox | Coding or general model |

This keeps the planner / workers / checkers structure from Sakana's TRINITY
work (see STACK_INVENTORY §1.1), while fixing each problem the review raised
about free-form coordination:

- **Handoffs have a fixed format**, so evidence cannot be silently dropped.
- **Every stage has a retry limit**, so nothing loops indefinitely.
- **The escalation decision is code**, so it gives the same answer every time.

### 3.2 Stage folders (ICM)

Adapted from the **Interpretable Context Methodology** ([arXiv
2603.16021](https://arxiv.org/abs/2603.16021)). Each agent is a stage folder
whose `CONTEXT.md` declares its inputs, process and output contract. Each job
gets its own run folder, so every handoff is kept for audit.

```
workbench/
  WORKSPACE.md              ← rules that apply everywhere
  CONTEXT.md                ← which stage handles which kind of task
  stages/
    01_read_document/       CONTEXT.md
    02_build_evidence/      CONTEXT.md
    03_apply_rules/         rules.yaml          ← code, no model
    04_find_standards/      CONTEXT.md
    05_write_note/          CONTEXT.md  templates/
    06_qa_check/            CONTEXT.md
  runs/<job-id>/01_read_document/ 02_build_evidence/ ...
```

The paper measured 2,000–8,000 focused tokens per stage against 40,000+ when
everything is loaded at once — important for small models on 12GB.

Two adaptations: **branching lives in code**, because the paper admits
automatic branching is awkward in a pure folder design; and **per-job run
folders**, because ICM assumes one job at a time.

### 3.3 Procedural graph

Adapted from **Procedural Graphs** ([arXiv
2609.09153](https://arxiv.org/abs/2609.09153), Google, Sep 2026). One graph
file per workflow (inspection, coding, intake). Nodes are stages or actions;
links use the paper's relations (`LEADS_TO`, `TRIGGERS`,
`PROVIDES_INPUT_FOR`, `CONVERGES_TO`) and carry three notes: *condition*,
*guidance*, *pitfalls*.

```yaml
- from: read_document
  relation: PROVIDES_INPUT_FOR
  to: build_evidence
  condition: tables extracted from every page
  guidance: one evidence record per table row, including the thickness survey
  pitfalls: a routine-sounding summary does not mean no escalation;
            check every reading against its minimum
```

The same file serves two jobs: the state machine **enforces** which
transitions are allowed, and the notes on the current step's links are
**inserted into the model's instructions**. The frontend draws the graph with
the active step highlighted — the thing judges see is the thing that actually
steers the system.

**Deviation from the paper:** the paper uses an extra model call per step to
turn the graph into guidance (+33–55% tokens). Our graph is hand-written, so we
insert the notes by template instead. Cheaper, but untested by the paper.

**Self-improvement is deferred.** When added, a proposed graph change goes
through validation *and* engineer approval, and every version is kept — the
same Management of Change discipline as document revisions (§6).

### 3.4 State machine

LangGraph or a small plain-Python state machine. **Decide only after the thin
slice works**, using one injected failure: interrupt after extraction, restart
offline, and finish without repeating completed work or losing source links.
Either way, persist input hashes, outputs and transitions, and resume a failed
stage rather than re-running the job. A framework does not make writes
idempotent by itself.

### 3.5 What we say to judges

- The Rules Engine is code, not an LLM. "The model explains, the code decides."
- The inspection workflow follows a known procedure with bounded adaptive
  choices: re-read a disputed cell, search again, redraft, send to a person.
- The Supervisor genuinely plans open-ended requests.
- ICM and procedural graphs are adapted from 2026 papers that were tested only
  on large closed models. We say so.

---

## 4. AnythingLLM — the reused platform

**Role:** general chat and document Q&A, the Model Router for that path,
embeddings and LanceDB vector search, and its own MCP-capable agents for ad-hoc
requests. Our inspection, coding and intake workflows run in our agent team.

**Verified 2026-09-10 (docs and source, not yet on our machine):**

| Fact | Source |
|---|---|
| MIT licensed; local-first | Repository |
| Telemetry off with `DISABLE_TELEMETRY=true` | Docs |
| Developer API: workspaces, document upload, chat with threads and streaming, API keys | Docs |
| **Agents run through the API**, not only the UI | `server/utils/chats/apiChatHandler.js` — `EphemeralAgentHandler.isAgentInvocation` → `startAgentCluster()` in both sync and streaming chat |
| Search without chat: `/v1/workspace/{slug}/vector-search` | Feature issue and docs |
| Model Router: rules on keywords, token count, message count, image attached; optional LLM classifier | Docs |
| MCP: stdio (default), SSE, streamable HTTP; tools only | Docs |
| Custom agent skills are **JavaScript/Node only** | Developer guide |
| Default vector store **LanceDB**, embedded | Docs |

**Caveats**

- **Open bug [#5271](https://github.com/Mintplex-Labs/anything-llm/issues/5271):**
  API uploads on the Windows desktop app are embedded but not added to the
  workspace; not reproduced on Linux. **Run AnythingLLM in Docker.**
- In Docker, AnythingLLM's stdio transport would start our MCP servers inside
  its container. **Run our MCP servers on the host over localhost HTTP.**
- **It must earn its place.** With our own frontend, library and intake, its
  role is narrower than when we chose it. If we end up using only its vector
  search, calling LanceDB directly is simpler.

**Integration test (stage 0, one day):** cold offline start with telemetry off;
a local model; one MCP tool on localhost; upload a scanned report through
the API; trigger an agent through the API; get a Word file back; audit events
recorded. Fallbacks if it fails: Onyx, then LibreChat. Our tools are MCP
servers, so they move with us.

**Stage 0 result (2026-09-11, [VERDICT](../results/stage0/VERDICT.md)): keep
AnythingLLM.** With all outbound traffic blocked, it read a scanned report,
answered the trap question correctly with its source, and ran an agent
through the API that called our MCP tool and wrote a Word file. There were no
internet connections. Its built-in agent with an 8B model wrote a false
approval note in all three clean runs, skipping the document search: that
confirms the inspection workflow belongs in our agent team.

**Requirements from stage 0** (details in
[F003](../results/findings/F003-anythingllm-outbound-dependencies.md)):

1. Pre-seed `eng.traineddata` in `storage/models/tesseract/`. Without it, the
   first scanned upload offline **crashes the container**.
2. Pre-seed or patch out the startup fetches (model context windows from
   GitHub, pricing from models.dev). No switch exists.
3. Disable the agent's web-scraping and web-browsing skills (on by default).
4. Set `AUTH_TOKEN` or use multi-user mode; the internal API is open without it.
5. Our MCP servers allow the `host.docker.internal:*` Host header, with
   DNS-rebinding protection kept on.
6. Give the container a fixed host address (`--add-host` or a user-defined
   network); `host.docker.internal` resolves only through DNS, which the
   network lock blocks.

Still open: a cold offline start, to see how the startup fetches behave on an
offline boot.

---

## 5. Models and serving

### 5.1 Starting plan for the 12GB bench

These are starting candidates, not winners.

| Role | Starting candidate | Notes |
|---|---|---|
| General reasoning, drafting, image follow-up | **Qwen3.5-9B**, smaller fallback if needed | Named by the review; **verify licence and size before use** |
| OCR / layout | **PaddleOCR-VL-1.6** | Own runtime; release GPU memory after its stage |
| Coding control | Qwen2.5-Coder-7B-Instruct | Load on demand; keep only if it beats the general model on our tests |
| Embeddings | `nomic-embed-text` (already local) or Qwen3-Embedding-0.6B | CPU first; precompute the corpus |
| Re-ranker | Optional | Small candidate set only |

**Watch list:** K2 Horizon 0.9B / 7B (upstream llama.cpp support pending);
Sarvam 30B if the corpus is Indic — note 2.4B *active* parameters reduce
compute, not stored weights (~15GB at 4-bit, so not all-GPU on 12GB); Qwen3.8-27B
for 24GB+.

Weight arithmetic is a lower bound: 9B at 4 bits ≈ 4.5GB before runtime
buffers, cache, vision components and display memory.

### 5.2 Serving

**llama.cpp first** for the small quantised models — its server supports model
loading/unloading and schema-constrained output. PaddleOCR-VL runs in its own
supported runtime. Ollama is a usability control (see F001 for its desktop
updater). vLLM or SGLang only if a measured bottleneck warrants it.

**Staged GPU use:** OCR the pages → release OCR → reason and draft → load the
coding model only if needed. Measure warm/cold loads, 8K vs 16K context, peak
VRAM and p95 end-to-end latency.

### 5.3 Model compatibility test

"One config file makes models interchangeable" is incomplete. Pin, per model:
artifact hash, runtime version, tokenizer and chat template, preprocessing,
precision, context limit, tool-call parser and decoding settings. Before any
model goes live, test image input, schema output, tool calls, timeouts,
unload/reload and a cold offline restart.

---

## 6. Document library and intake

A flat pile of chunks cannot tell which revision is current, returns fragments
of procedures, loses cross-document links and misses exact IDs. ICM's paper
explicitly does not cover knowledge bases, so this part is our own design.

### 6.1 Library

```
library/
  INDEX.md                  ← catalogue: one line per document
  registry.json             ← id, type, revision, status, supersedes, file hash, access
  standards/OISD-STD-116/
    CARD.md                 ← scope, revision, key clauses, map of sections
    rev-2008/  source.pdf  sections/7.3.md ...
  equipment/P-1107/
    CARD.md                 ← model, interfaces, limits, alarm codes, map of sections
    manual-rev0/ ...
  sops/ ...
  correspondence/ ...       ← restricted
```

Chunks are clause-aware and carry document ID, title, revision, effective date,
section path, page and permissions. Table headers stay with their rows.

### 6.2 Lookup order

1. **Exact IDs** — clause numbers and equipment tags resolved in the registry by code.
2. **Catalogue** — the agent reads `INDEX.md` and document cards to choose documents.
3. **Sections** — read the chosen sections directly.
4. **Vector search** — LanceDB within the chosen documents, or as a fallback; optional re-ranking.

A study of LLM-maintained markdown wikis ([arXiv
2607.04576](https://arxiv.org/abs/2607.04576)) found targeted access kept
answer quality while cutting cost by a third to over half. It compared ways of
navigating a wiki, not wiki against RAG, and its stronger agents often skipped
the catalogue — our small models will likely rely on it more.

**Permissions are a data-model requirement now,** not a later feature: stored
per document and applied before content enters retrieval, generation or
citation previews.

### 6.3 Intake

```
intake/
  01_receive     fingerprint the file, catch duplicates
  02_extract     text and tables, split by section or clause
  03_classify    document type, equipment tags, revision, effective date
  04_card        draft the CARD.md summary
  05_compare     new document, new revision, or conflict with a current one?
  06_approve     an engineer signs off → status becomes active
  07_publish     update INDEX, registry, and search index for this document only
```

Rules: **nothing is used before sign-off**; **old revisions are marked
superseded, never deleted**; **only the new document is re-indexed**.

Because every output records which document revisions it cited, a revised
manual lets us list every script and approval note that relied on the old one —
**Management of Change**, a standard process-safety practice.

---

## 7. Evidence, decisions and verification

### 7.1 Evidence record

One record per critical reading: document hash; page; table, row and column;
bounding box; equipment / CML identifier; raw OCR text; parsed decimal; unit;
date; applicable minimum **and its source**; extraction model and settings;
review status. The original image is kept. A summary or normalised markdown
table is not sufficient provenance.

**Flow:** page classification → extraction → row association → field
validation → rule evaluation → evidence-grounded drafting → artifact checks →
human disposition.

**Selective re-reading:** if a critical field is missing, two readings
disagree, row linkage is uncertain, or a value is near a configured boundary,
re-read the cell crop through a second path and keep both readings. If still
unresolved, show the crop to the reviewer. **Never silently repair a digit** to
make a report consistent.

OCR confidence, model self-confidence and agreement between readers are
signals, not probabilities of correctness. Calibrate acceptance on held-out
target-like data.

### 7.2 Three outcomes

| Outcome | Meaning |
|---|---|
| **Escalate** | An approved rule triggered |
| **No trigger** | No evaluated rule triggered — not a statement of fitness for service |
| **Needs review** | Evidence missing, ambiguous or conflicting |

Decimal arithmetic and explicit unit conversions. The model never invents a
minimum thickness from general knowledge; the real rule set needs the asset,
the applicable standard edition, the operating context and an authorised
engineering interpretation.

### 7.3 Four checks

| Check | Verifies | On failure |
|---|---|---|
| **Input and decision integrity** | Critical fields match accepted evidence; all required rows covered; rules recompute | Reopen the disputed extraction or rule input |
| **Artifact structure** | File parses; required sections and rows present; no placeholders; values preserved | Repair the template/render stage |
| **Semantics** | Claims supported; units, dates, assets and applicable rules align; citations support the cited claim | Remove or mark unsupported text; seek review |
| **Presentation** | Rendered pages have no clipped content, broken pagination or unreadable tables | Fix layout and render again |

A vision model looking at a render can catch layout problems; it cannot certify
values, formulas or citations. Failures route to their cause, retries are
bounded per stage, and a reviewable incomplete result is returned when the
budget runs out.

**Report Writer rules:** factual fields and measurement tables are filled from
evidence records directly; model prose stays in constrained sections; the model
may only cite retrieved citation IDs; "insufficient evidence" is an allowed
answer; the finished DOCX is read back and its critical values compared with
the records.

**The output is an approval-note draft with a verification record, not an
approval.**

### 7.4 The coding task (R4)

Known expected behaviour, for example: parse a CSV of verified readings, handle
missing or invalid rows, compute a configured comparison, write a summary. Tests
cover normal input, boundary equality, missing values, wrong units and a
malformed row, **including at least one held-out test the model did not write**.
An agent that writes both the code and its own passing tests has not shown
correctness.

---

## 8. Sovereignty boundary and sandbox

### 8.1 Sandbox

**Threat model (corrected):** uploaded documents are untrusted. A vendor file
can carry instructions that steer a tool-using agent (indirect prompt
injection). Even offline, a bad program can corrupt inputs, alter drafts, read
unrelated files or exhaust resources.

**Docker baseline, with explicit controls:** fresh container per task;
non-root; no network; dropped capabilities; `no-new-privileges`; seccomp and a
host MAC policy where available; read-only inputs and root filesystem; one
narrow writable output folder; no host home directory, no Docker socket;
memory, CPU, PID, time and output-size limits; dependencies preloaded; the GPU
model service outside the sandbox. gVisor is the step up; microVMs optional.
These controls reduce risk; they do not make the kernel boundary complete.

### 8.2 Network proof

Separate four categories in the logs: approved local traffic, external
attempts, denied attempts, and observed successful external egress.

**The canary runs in its own window.** The PS asks us to show no external calls
at any point; a deliberate test call to prove the monitor works contradicts
that if mixed into the same run. So: a clearly marked canary window, then a
clean startup window and a clean task window.

**The claim we make:** *"This build completed these tasks with external egress
blocked; the stated monitors observed no successful external egress during the
recorded run."*

**Observation scope:** a firewalled workstation is not automatically physically
air-gapped. WSL packet capture alone does not cover the Windows host; include
Windows, WSL/Hyper-V, IPv4/IPv6 and DNS/proxy paths. Native Linux simplifies
the boundary. Save configuration, process and interface inventory, build
hashes, logs and capture. Include a cold offline start (fonts, model and
tokenizer caches, document renderers, tool dependencies). Treat evidence logs
as confidential.

---

## 9. The demo

The live demo shows:

1. The hidden low-thickness case caught — the summary sounds routine; one reading is below minimum.
2. A genuinely ambiguous reading sent to review with its image crop.
3. Clicking a number in the draft opens its source cell and the rule that used it.
4. A correct Word draft with its verification record.
5. A coding attempt that fails a held-out test, gets repaired, and passes.
6. The separately marked network canary, then the clean run.

Show actions and results — agent handoffs, files, checks — rather than a
decorative stream of model thoughts. Keep a locked known-good build before the
demonstration.

---

## 10. Evaluation

The 12 synthetic reports are a **debugging set, not validation** (DATASETS §4).

**Sets:** development cases for tuning; a frozen test set with held-out report
templates, authors and scan conditions; a separate challenge set; real scans or
photos with independently checked critical fields; counterfactual pairs that
differ in one digit, unit, equipment ID or threshold source.

| Measure | Success means |
|---|---|
| Critical-field accuracy | Exact value **and** unit **and** correct asset/row; missing fields counted |
| Escalation | False negatives, false positives and "needs review" reported separately |
| Selective accuracy | Error rate among accepted fields **and** share sent to review |
| Retrieval | Relevant-clause recall at k, correct edition, evidence completeness, permission filtering |
| Deliverables | First-pass correct files, critical values preserved, time to accepted output |
| Efficiency | p50/p95 latency, cold load, peak VRAM/RAM, retries, review minutes |

Character error rate and table-structure scores are diagnostics, not the
selector: a system that reads boilerplate perfectly but swaps two thickness rows
must not win. A system that sends everything to a person must not win by making
no automatic errors.

**Statistical honesty:** six escalation cases with zero misses still leave a
95% upper bound of about 39% on the miss rate; 300 independent cases with zero
misses bound it at about 1%. Freeze prompts and configuration before testing,
report uncertainty at the source-document level, and call a winner provisional
when intervals are wide.

---

## 11. Prior art (corrected)

| Product | Licence | Already does |
|---|---|---|
| **AnythingLLM** | MIT | Rule-based Model Router; Document Generation Agent (Word, Excel, PowerPoint); agents with MCP — **our base** |
| **Onyx** | MIT core; `ee/` features under a separate licence (SAML SSO, advanced permissions, white-labelling) | Built-in code execution in a Docker sandbox without network; file creation; image handling (per the review); connectors — **fallback base** |
| LibreChat | MIT | Self-hosted code interpreter (per the review); MCP agents |
| Dify / Langflow | Modified Apache 2.0 / MIT | Visual workflow builders — not needed |

**If a judge asks "why not just use X?":** we do use one. What these platforms
don't provide is an evidence-first inspection workflow — per-cell provenance,
deterministic rules with explicit uncertainty, verified drafts, and a
revision-controlled document library. That is what we built.

---

## 12. What changed since revision 1

| Rev 1 said | Rev 2 says | Why |
|---|---|---|
| Onyx lacks all of R2–R5 | Onyx has sandboxed code, file creation, image handling; AnythingLLM has routing and document generation | Rev 1 relied on a marketing page; the review checked product docs, and we confirmed |
| Build standalone | Build on AnythingLLM | Team decision, 2026-09-10 |
| Reuse a stock chat UI | Our own frontend on AnythingLLM's API | Judge-facing panels need custom UI; agents work through the API (confirmed in source) |
| The model decides escalation | Evidence records + deterministic rules, three outcomes | Review's top recommendation; consistent with deterministic-first |
| Free-form planner/workers/checker | Specialist team with fixed handoffs: ICM stages + procedural graph + state machine | Keeps multi-agent; removes uncontrolled loops |
| Verifier = vision model checks a render | Four checks with different evidence | A render check cannot certify values |
| Sandbox safe because our model writes the code | Uploaded documents are untrusted (prompt injection) | Review |
| "No external calls" and a deliberate call-out in one run | Separate canary window; precise claim wording | The two contradicted each other |
| Hybrid + knowledge-graph retrieval | Structured library: exact lookup → catalogue → sections → vector | Review; ICM; wiki study |
| R1–R6 are "the marking scheme" | Our reading; get the official statement | Review |
| Ollama "contacted GitHub" | Update check at ~4s and hourly; destination unconfirmed | F001 corrected |
| Handwriting "unsolved", "not graded" | Hard; restricted-field scope; grading unconfirmed | F002 and PS_ANALYSIS corrected |

---

## 13. Build order

| Stage | Deliverable | Move on when |
|---|---|---|
| **0 — platform check** (1 day) | AnythingLLM integration test (§4) | Passes offline, or we switch base |
| **1 — contract and baseline** | Official PS copy; evidence-record schema; fixed sample; PaddleOCR → rule → templated DOCX | Critical values round-trip; missing evidence gives "needs review" |
| **2 — full thin slice** | Evidence crops, retrieval, render checks, run record, offline dependencies, agent timeline | Cold offline start and full task complete; failures visible and resumable |
| **3 — extraction comparison** | PaddleOCR-VL-1.6 vs GLM-OCR vs cell-based path (PP-StructureV3) with selective re-reading | Winner by critical errors, coverage and review time |
| **4 — bounded intelligence** | General vs coding model; routing log; retry budgets; procedural-graph notes | Routing logged; coding passes independent tests; memory stable |
| **5 — deployment evidence** | Hardened sandbox, canary window, network boundary, frontend | Prohibited actions fail; the legitimate task succeeds; logs explain both |

**First experiments, each changing one thing:** A — model-only escalation vs
rules on the same inputs. B — full-table parsing vs cell-based extraction with
selective re-reading. C — vector-only vs exact lookup + vector (± re-ranking).
D — general model vs coding model under the same repair budget.

**Deferred** until a measured error or confirmed requirement justifies it: full
P&ID topology, free-form handwriting, fine-tuning, a large inferred knowledge
graph, many resident models, automatic procedural-graph self-improvement.

---

## 14. Decided, open, and for the team

**Decided:** build on AnythingLLM with our own frontend; specialist agent team
with fixed handoffs; code decides escalation; tools as MCP servers; LanceDB plus
exact lookup; structured library with approved intake; Docker sandbox with
explicit controls; separate canary window; 12GB is the validation floor.

**Open, decided by testing:** state machine (LangGraph vs plain Python); OCR
pipeline (stage 3); whether a coding model earns its place; whether AnythingLLM
earns its place (stage 0).

**For the team:**

1. The **official problem statement** with its version and judging criteria.
2. Corpus **language**: English, Indic, or mixed?
3. **Handwriting** share of the real corpus, and what it looks like.
4. **Venue** GPU, RAM and OS.
5. **Access policy**: who may see which documents.
6. Do we still run a multi-framework comparison, as the original exploration
   brief asked, or pick one after the slice works?

---

## 15. Status

**Done:** problem statement analysed; model, library, dataset and competitor
research; two real source documents; synthetic report generator with ground
truth; Ritesh's review received and answered; documentation revised.

**Next:** stage 0 (AnythingLLM integration test), then stage 1.

**Not started:** agent team, frontend, gateway, library and intake, MCP tools,
network monitor.

---

## 16. Risks

| Risk | Mitigation |
|---|---|
| Competitors already offer our feature list | Compete on evidence and reliability (§1); rehearsed answer (§11) |
| AnythingLLM doesn't behave as documented | Stage 0 test; Onyx / LibreChat fallback; tools are portable MCP servers |
| ICM and procedural graphs tested only on large closed models | Test with our small models in stages 2 and 4 |
| Handwriting accuracy on real forms unknown | Restricted fields; measure; human review with crops |
| Prompt injection via uploaded documents | Sandbox controls (§8.1); agents act only within their stage contract |
| Components that connect out on their own | F001; audit every component including AnythingLLM |
| Parts of the stack need Linux; WSL capture misses the Windows host | Native Linux for the demo boundary where possible; stated observation scope |
| Small evaluation sets overstate reliability | §10 sets and bounds; winners reported as provisional |
