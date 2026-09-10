# SIH26117 — System Architecture

The consolidated picture: what we are building, why each piece is shaped the way
it is, and what is actually built so far.

Revision 1, 2026-09-05. Supersedes nothing — it ties together
[`PS_ANALYSIS`](PS_ANALYSIS.md), [`STACK_INVENTORY`](STACK_INVENTORY.md),
[`DATASETS`](DATASETS.md), [`PID_APPROACH`](PID_APPROACH.md) and
[`ENVIRONMENT`](ENVIRONMENT.md).

---

## 1. What we are building, in one paragraph

An **air-gapped multi-agent AI workbench** that runs entirely on an
organisation's own GPU server. A user hands it confidential industrial work — a
scanned inspection report, an engineering calculation, an internal tool to write
— and it plans the work across multiple open-weight models, picks the right
model per subtask automatically, uses local tools (file I/O, sandboxed code
execution, document search, spreadsheets), grounds itself in the organisation's
own SOPs and correspondence, and returns a **real deliverable** — a Word
approval note, an Excel calculation sheet, working code — not a chat reply.
Nothing leaves the building, and the system proves that continuously with a live
egress monitor rather than asserting it in a slide.

---

## 2. The six things that actually get graded

Everything below traces to one of these. From
[`PS_ANALYSIS §1`](PS_ANALYSIS.md):

| | Requirement |
|---|---|
| **R1** | Working local deployment, single workstation, mid-range GPU |
| **R2** | Model auto-selection across ≥2 task types |
| **R3** | Agentic end-to-end: scanned inspection report → findings → **Word approval note** |
| **R4** | Coding task run and verified **in a sandbox** |
| **R5** | Multimodal: image or scanned-document understanding |
| **R6** | **Visible proof** of zero external calls |

Two demos cover all six. R3 is the spine; R4 is a second, smaller flow.

---

## 3. System diagram

```
┌───────────────────────────────────────────────────────────────────────────┐
│  SOVEREIGNTY BOUNDARY — default-drop egress (nftables), no route out      │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │ L6  UI SHELL           LibreChat / AnythingLLM (MIT)                │ │
│  │                        + EGRESS MONITOR PANEL  ← R6 proof, on screen│ │
│  └──────────────────────────────┬──────────────────────────────────────┘ │
│                                 │ OpenAI-compatible                       │
│  ┌──────────────────────────────▼──────────────────────────────────────┐ │
│  │ L3  AGENT RUNTIME — Thinker / Worker / Verifier   (LangGraph)       │ │
│  │                                                                     │ │
│  │        ┌──────────────────────────────────────────┐                 │ │
│  │        │  ORCHESTRATOR  (Thinker)                 │                 │ │
│  │        │  decompose → plan → dispatch → iterate   │                 │ │
│  │        └───┬─────────┬─────────┬─────────┬────────┘                 │ │
│  │            │         │         │         │                          │ │
│  │      ┌─────▼───┐ ┌───▼────┐ ┌──▼─────┐ ┌─▼──────────┐               │ │
│  │      │ VISION  │ │RETRIEVE│ │ CODER  │ │DELIVERABLE │  (Workers)    │ │
│  │      │ /DOC    │ │        │ │        │ │            │               │ │
│  │      └─────┬───┘ └───┬────┘ └──┬─────┘ └─┬──────────┘               │ │
│  │            └─────────┴────┬────┴─────────┘                          │ │
│  │                     ┌─────▼──────┐                                  │ │
│  │                     │  VERIFIER  │  render → VLM checks → pass/fail │ │
│  │                     └─────┬──────┘  recompute formulas, check cites │ │
│  │                           │ fail → back to Orchestrator             │ │
│  └───────────────────────────┼─────────────────────────────────────────┘ │
│                              │                                           │
│  ┌───────────────────────────▼─────────┐  ┌────────────────────────────┐ │
│  │ L4  TOOLS                           │  │ L5  KNOWLEDGE GROUNDING    │ │
│  │  file r/w · sandboxed exec (Docker) │  │  hybrid retrieval:         │ │
│  │  docx/pptx/xlsx · spreadsheet       │◄─┤  vector + BM25 + graph     │ │
│  │  KB search                          │  │  → rerank → cited passages │ │
│  └─────────────────────────────────────┘  └────────────────────────────┘ │
│                              │                                           │
│  ┌───────────────────────────▼─────────────────────────────────────────┐ │
│  │ L2  ROUTER  ← R2.  deterministic first, escalate only if needed     │ │
│  │     modality rule → embedding similarity → semantic-router → LLM    │ │
│  │     swap-aware: batches same-model work to avoid VRAM thrash        │ │
│  └───────────────────────────┬─────────────────────────────────────────┘ │
│                              │                                           │
│  ┌───────────────────────────▼─────────────────────────────────────────┐ │
│  │ L1  MODEL SERVING   OpenAI-compatible endpoint                      │ │
│  │     Ollama / llama.cpp  ·  SGLang (multi-model, 1 process)  · vLLM  │ │
│  │     ┌────────┬────────┬────────┬────────┬──────────┬─────────────┐  │ │
│  │     │general │ coder  │ VLM    │ OCR    │ embedding│  reranker   │  │ │
│  │     └────────┴────────┴────────┴────────┴──────────┴─────────────┘  │ │
│  │     model registry = config file. swap tier A→B→C, no code change   │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │ L0  HOST — single GPU workstation. nftables · pcap · audit log      │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## 4. The layers, and why each is shaped this way

### L0 — Sovereignty boundary (R6)

Default-drop egress with logging, packet capture as independent verification,
and an **audit log that can reconstruct exactly what happened after the fact**.

The design point most teams miss: **a monitor that only ever reads zero is
indistinguishable from a broken monitor.** So the demo includes a *scripted,
deliberate* outbound call that gets caught and logged on screen. Proving the
detector works is what makes the zero meaningful.

Already found one real offender before writing a line of code —
[F001](../results/findings/F001-ollama-update-check.md): Ollama contacts GitHub
within 4 seconds of startup and rechecks hourly, by default.

### L1 — Model serving

One OpenAI-compatible endpoint in front of a **pool of specialised models**.
Models are declared in a config file, never referenced by name in code — that is
the entire mechanism behind "new models addable without redesign".

Serving candidates and why: **Ollama / llama.cpp** run natively on Windows and
are the Tier A baseline. **SGLang** matters more than it looks — it serves
*multiple models from one process*, which vLLM cannot, and that directly attacks
our VRAM problem. **vLLM** is the throughput answer at Tier B/C.

**Hardware tiers** ([`ENVIRONMENT`](ENVIRONMENT.md)): Tier A = 12GB (this bench,
validation floor), Tier B = 24–32GB (realistic MRPL target), Tier C = 80GB+ (the
PS's own "120B class" reference). The architecture is identical across all three;
only the config differs. **R2 is what proves that claim** — swappability is
demonstrated, not asserted.

### L2 — Router (R2)

Two distinct decisions people conflate:

- **Agent routing** — which agent handles a subtask. The Orchestrator's plan. Semantic.
- **Model routing** — which weights serve a call. **Deterministic wherever possible.**

The escalation ladder: **modality rule** (image present → VLM; tool is
`exec_python` → coder) → **embedding similarity** to task exemplars →
[`vllm-project/semantic-router`](https://github.com/vllm-project/semantic-router)
(Apache 2.0, official vLLM project) → LLM-as-router only for genuine ambiguity.

**Why deterministic-first:** an auditable rule table is worth more to an MRPL
security reviewer than a clever classifier, and it costs zero VRAM. A judge can
be shown the routing table. The semantic router has to *earn* its place by
beating rules on our task mix — that's a Subsystem 1 measurement, not an
assumption.

The router has a second, non-obvious job at Tier A: **minimise model swaps.** At
12GB a 14B text model and a 7B VLM cannot co-reside, so swap latency sits in the
user-facing path. The router batches same-model work rather than ping-ponging.
At Tier B/C this evaporates — which is exactly why swap policy is configuration,
not hardcoded.

### L3 — Agent runtime

**Thinker / Worker / Verifier**, borrowed from Sakana's TRINITY paper. We cannot
use Fugu itself (closed API, weights unreleased, routing "proprietary by
design") but the *pattern* is published and directly applicable, and Sakana's
framing is the useful lesson: **orchestration is a scaling axis** — a
well-coordinated pool of small models can rival a much larger single one. That is
precisely the bet a single workstation forces.

> **Honesty guardrail.** TRINITY and Conductor are *learned* coordinators
> (CMA-ES / RL). We are building a **hand-designed** T/W/V topology with a
> deterministic router, *informed by* those papers. Training our own coordinator
> is a stretch goal, and we describe it that way. An honest "inspired by" beats a
> claim that collapses under one follow-up question.

**The Verifier is not optional.** "Real deliverables" fail *silently* — a .docx
that opens with a mangled table passes every automated check and fails in front
of a judge. So every artefact gets a round trip: render to image, VLM inspects
it, formulas get recomputed via LibreOffice headless, citations get checked
against the retrieved source. Failure routes back to the Orchestrator.

Framework: **LangGraph** is the leading candidate — explicit nodes and edges mean
the execution graph *is* the audit trail, which is exactly what a security
reviewer wants.

### L4 — Tools

File read/write, **sandboxed code execution**, document generation
(`python-docx` / `python-pptx` / `openpyxl`), spreadsheet operations, KB search.

**Sandbox (R4) — scoped by threat model, not by blog consensus.** 2026 guidance
says shared-kernel Docker is inadequate for untrusted AI code, and recommends
gVisor or Firecracker microVMs. But that guidance assumes multi-tenant SaaS
running third-party code. Ours is generated by *our own local model*, for *one
trusted internal user*, on an *air-gapped host where egress is already
default-drop*. The realistic threats are accidental — a runaway loop, a stray
`rm` — not hypervisor escape. **Docker with dropped capabilities, read-only
mounts, `--network none` and CPU/memory/PID limits is very likely sufficient**,
with gVisor named as the hardening step and Firecracker as the production upgrade
path. Reasoning from the real threat model is itself the defensible engineering
answer.

### L5 — Knowledge grounding

**Hybrid retrieval**: dense vectors + BM25 lexical + graph traversal, then a
reranker. BGE-M3 is interesting because it emits dense, sparse and multi-vector
representations in a single pass. A reranker is not in the original brief's
candidate list — **we added it**, because it is cheap and usually the largest
single quality win; "hybrid + rerank beats both" is a more useful finding than
"hybrid beats flat".

**Every claim in a deliverable carries a citation** back to a specific clause.
For a refinery approval note this is not a nicety — it is the difference between
a document an engineer can sign and one they cannot.

### L6 — UI

**Buy, don't build.** The PS explicitly benchmarks UX against "the way they use
Claude or Codex", which is months of frontend work that is not what gets graded.
LibreChat or AnythingLLM (both MIT) as the shell, our agent backend behind an
OpenAI-compatible endpoint. Open WebUI is the most popular option but
**relicensed in April 2025** — deployments over 50 users must retain its
branding, which is awkward for a sovereignty pitch.

Plus the **egress monitor panel**, which is a deliberate build item, not a
by-product.

---

## 5. The R3 flow, concretely

The PS hands us the vertical slice. This is the spine of the whole demo:

```
scanned inspection report (PDF/image)
   │
   ├─► ROUTER: image present → VLM/OCR path
   │
   ├─► VISION/DOC AGENT      PaddleOCR-VL-1.6 (0.9B, Apache 2.0, tops
   │                          OmniDocBench) → structured text + tables
   │
   ├─► ROUTER: text reasoning → general model
   ├─► ORCHESTRATOR          extract findings, severities, thickness readings
   │                          decide: does this warrant escalation?
   │
   ├─► RETRIEVAL AGENT       ground each finding in the SOP corpus,
   │                          return clause citations (OISD / API 510)
   │
   ├─► DELIVERABLE AGENT     python-docx + template → approval note
   │                          with findings, recommendations, citations
   │
   ├─► VERIFIER              render .docx → VLM inspects layout,
   │                          check every citation resolves,
   │                          confirm severity logic
   │                          ✗ → back to Orchestrator
   │
   └─► EGRESS PANEL          zero external calls, live, throughout
```

Exercises **R1, R2, R3, R5, R6**. One sandboxed coding task completes **R4**.

**Build the whole path before improving any stage.** A thin ugly end-to-end run
beats a beautiful OCR stage with nothing behind it — it surfaces integration
problems now instead of in month three.

---

## 6. Design principles

1. **Deterministic first, clever only when measured to be necessary.** Auditability beats sophistication for this customer.
2. **Verify every artefact.** Silent failure is the enemy; a document that opens is not a document that is correct.
3. **Never silently guess.** Confidence-gated extraction — low-confidence fields go to a human, they do not flow into a calculation. An agent that confidently computes on a misread digit is worse than one that asks.
4. **Models are configuration.** No model name in application code.
5. **Prove the negative.** The egress monitor must be seen catching something.
6. **Scope honestly.** Demo what works; describe the rest as what it is.

---

## 7. What is decided vs. still open

**Decided:**

- Thinker/Worker/Verifier topology; deterministic-first routing
- Standalone build — Onyx is prior art, not a dependency ([`PS_ANALYSIS §4`](PS_ANALYSIS.md))
- UI is bought, not built; MIT shell preferred
- Sandbox = Docker + hardening, on threat-model grounds
- 12GB is the validation floor, not a design ceiling
- Real documents for OCR benchmarking; synthetic only for structured-extraction ground truth
- Handwriting and P&ID are **capability claims, not demo requirements** — outside the rubric

**Open, and blocking nothing today:**

- Agent framework: LangGraph vs smolagents vs Pydantic AI vs hand-rolled (Subsystem 1 decides)
- Serving: Ollama vs llama.cpp vs SGLang (Subsystem 2 decides)
- Whether `semantic-router` beats a rule table on our task mix
- Whether Qwen3.8-27B collapses orchestrator + coder + VLM into one Tier B model

**Needs the team, not testing:**

- Is MRPL's corpus English, Indic, or code-mixed? Decides whether Sarvam is a strategic bonus or a hard requirement.
- What GPU is at the SIH venue?
- Do we add permission-aware retrieval? Not required, but a corpus mixing vendor negotiations with SOPs invites the question.

---

## 8. Current status — honest

**Built and working:**

- Environment characterised; toolchain verified (RTX 4070 12GB, CUDA 13.0, Ollama with `llama3.1:8b`)
- `bench/inspect_pdf.py` — PDF triage (page count, born-digital vs scanned, text sampling). **Working.**
- Two real source documents downloaded and verified: **CSB Chevron Richmond final report** (132pp, public domain, real refinery integrity content) and an **MRPL public tender** (486pp, authentic MRPL formatting)
- `bench/corpus/` — schema, content generator, PDF renderer, scan-degradation module. **Written, not yet run.**

**Not built yet:** everything in L1–L6. No agent, no router, no retrieval, no
deliverable generation, no egress monitor.

**Immediate next step:** run the corpus generator end to end, then wire the R3
spine thinly — OCR → extract → docx → verify — against the real documents we now
have.

---

## 9. Risks

| Risk | Severity | Status |
|---|---|---|
| Handwriting OCR unsolved even for closed frontier models (~28.5% CER on real docs) | Medium | **Downgraded** — outside the rubric. Confidence-gate it, demo printed |
| Three requirements need Linux (SGLang/vLLM, sandbox, nftables) | Medium | WSL2 install moved earlier |
| P&ID has no air-gapped-ready open tool | Medium | Stretch goal; scoped to symbol+tag detection only |
| Onyx already does the retrieval half, MIT, in ITAR use | Medium | Differentiation rehearsed — it lacks all of R2–R5 |
| Ollama phones home hourly by default | Medium | F001 — verify `ollama serve` alone is silent |
| Live egress monitor could read zero because it's broken | Low | Scripted failed call-out in the demo |
| `semantic-router` installs via `curl` — air-gap smell | Low | Verify offline install path early |
