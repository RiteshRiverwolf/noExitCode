# SIH26117 — Model & Library Inventory

Candidate open-weight models and libraries, with benchmark evidence and the
multi-agent topology they plug into.

**Revision 2 — 2026-09-10.** Sections 3.7–3.13 revised after Ritesh's review
and the decision to build on AnythingLLM. **Part 1 is no longer the
architecture description** — that is [`ARCHITECTURE.md`](ARCHITECTURE.md) rev 2.
Part 1 is kept for the Fugu/TRINITY research and routing options it records.

Compiled from published benchmarks and vendor claims, not yet from our own
testing. Everything here is a **candidate**; the benchmarks in `results/`
decide winners. Sources listed at the end.

> **Health warning on every number below.** Vendor-published scores are marked
> *(vendor)*. Leaderboard scores reflect the leaderboard's conditions, not our
> workload — a document-parsing score on clean PDFs says nothing about a smudged
> refinery log sheet. These numbers are for **shortlisting candidates**, never
> for choosing a winner. That's what Subsystems 1–6 are for.

---

## Part 0 — Hardware tiers

| Tier | VRAM | Role |
|---|---|---|
| **A** | ~12GB | **This bench (RTX 4070).** Baseline validation — prove the workflow end to end. |
| **B** | 24–32GB | Expected MRPL demo/deployment class. The realistic target. |
| **C** | 48GB+ / multi-GPU | Headroom. Design must not preclude it; we won't run it here. |

12GB is the **floor we validate on, not a ceiling we design to**. The brief
requires models be "swappable without redesign", so model choice is
configuration. If it works at Tier A it works better at B and C.

---

## Part 1 — Architecture: multi-agent topology and routing

### 1.1 Inspiration: Sakana Fugu (and why we can't use it)

Sakana AI (Japan) released **Fugu** on 2026-06-22 — a multi-agent orchestration
system that presents as a single model behind one OpenAI-compatible endpoint. It
handles model selection, role assignment, coordination, verification and
synthesis internally, and can recursively re-read its own output to pick a better
coordination strategy without retraining.

**Fugu itself is disqualified for this project:** closed managed API, no released
weights, no self-hosting, and Sakana states the routing is "proprietary… not
exposed by design." For an air-gapped sovereign deployment that is a
non-starter on all three counts.

**But the research beneath it is public and directly applicable.** Two ICLR 2026
papers:

| Paper | What it is | Why it matters to us |
|---|---|---|
| **TRINITY** | A **~0.6B** coordinator, evolved with CMA-ES, that assigns **Thinker / Worker / Verifier** roles across a pool of much larger models over multiple turns | A 0.6B router is small enough to stay **permanently resident even at Tier A** while 7–14B workers swap around it. This is the shape our VRAM budget wants. |
| **Conductor** | A **7B** model trained with RL to discover *natural-language* coordination strategies for a diverse model pool; can call itself recursively | Coordination strategy in natural language is **auditable** — a huge win for the MRPL security-review requirement, vs. an opaque learned policy |

Sakana's own framing is the useful lesson: **orchestration is a scaling axis**.
A well-coordinated pool of small models can rival a much larger single model.
That is precisely the bet SIH26117 forces us to make on one workstation, and it
means our multi-agent design is a *capability strategy*, not just tidy
engineering.

**Adopt the pattern, not the product:** Thinker/Worker/Verifier roles, a small
resident coordinator, explicit verification passes, natural-language (loggable)
coordination.

> **Caution — do not overclaim.** TRINITY and Conductor are *learned* coordinators
> (CMA-ES / RL). We are not training a coordinator in this timeframe. What we can
> realistically build is a **hand-designed Thinker/Worker/Verifier topology with
> a deterministic router**, informed by these papers. Training our own TRINITY-
> style coordinator is a stretch goal to attempt only if the base system works
> first, and it should be described that way — an honest "inspired by" beats a
> claim that collapses under a judge's question.

### 1.2 Agent roles

| Agent | Job | Model class | Fugu-role analogue |
|---|---|---|---|
| **Orchestrator** | Decompose, plan, dispatch, decide completion | Strong reasoning, long context | Thinker |
| **Retrieval** | Query SOP/manual KB, return grounded passages + citations | Small general + embedding + reranker | Worker |
| **Vision/Doc** | Scanned PDFs, handwritten sheets, drawings → structured data | VLM + OCR stack | Worker |
| **Coder** | Calculations, data wrangling, sandboxed execution | Code-specialised | Worker |
| **Deliverable** | Emit real .docx/.pptx/.xlsx | General, strong schema-following | Worker |
| **Verifier** | Render artefact → VLM inspects; recompute formulas; check citations | VLM + general | **Verifier** |

The **Verifier is not optional**. "Real deliverables" fail silently — a .docx
that opens with a mangled table looks like success to every automated check.
Round-trip verification is what makes the deliverable claim survive a demo.

### 1.3 Routing — two layers

The requirement "multiple models auto-selected by task type" is really two
decisions:

**Layer 1 — Agent routing:** which agent handles a subtask. Owned by the
Orchestrator's plan. Semantic, LLM-driven.

**Layer 2 — Model routing:** which weights serve a call. **Should be
deterministic wherever possible** — an auditable rule table is worth more to an
MRPL security reviewer than a clever classifier, and costs zero VRAM.

| Approach | Mechanism | Cost | Auditable |
|---|---|---|---|
| **Rule / modality** | Image present → VLM. Tool is `exec_python` → coder. Else general. | Zero | Fully |
| **Embedding similarity** | Nearest task exemplar via already-loaded embedding model | Negligible | Yes — log the score |
| **TRINITY-style small coordinator** | ~0.6B resident model emits role + route | ~1GB resident | Partly |
| **LLM-as-router** | Orchestrator picks explicitly | A full turn | Yes, but non-deterministic |
| **`semantic-router` library** | Off-the-shelf embedding router | Negligible | Yes |

**Hypothesis to test, not assume:** rule + embedding covers most routing
decisions; LLM-as-router is needed only for genuinely ambiguous requests.
Subsystem 1 test case 2 settles this.

### 1.4 The VRAM-swap consequence

At Tier A a 14B text model (~9GB) and a 7B VLM (~6GB) **cannot co-reside** in
12GB. So model swapping is mandatory at baseline and swap latency sits in the
user-facing critical path.

Three consequences:

1. Subsystem 2's **hot-swap test is the most load-bearing measurement** there, not a footnote.
2. The router gets a second objective: **minimise swaps** by batching same-model work rather than ping-ponging.
3. **SGLang serves multiple models from one process** (vLLM cannot) — see §3.2. That capability is unusually valuable here and the brief didn't list it.

At Tier B/C models co-reside and this problem evaporates — which is exactly why
swap policy must be **configuration, not hardcoded**.

---

## Part 2 — Model inventory

### 2.1 Sarvam — the sovereignty play 🇮🇳

Added at team request, and it turns out to matter more than a box-tick.

**Sarvam 30B and 105B** were announced at the India AI Impact Summit 2026 and
open-sourced under **Apache 2.0**. Both are MoE, **trained entirely in India on
IndiaAI Mission compute**, supporting all 22 scheduled Indian languages
including native script, romanised Latin, and code-mixed (Hinglish) input.

| | Sarvam 30B | Sarvam 105B | Sarvam-M (older) |
|---|---|---|---|
| Total / active params | 32B / **~2.4B** | 105B | 23.6B (dense) |
| Context | 65K | — | — |
| License | Apache 2.0 | Apache 2.0 | — |
| AA Intelligence Index | 12 | 18 | 8 |
| Math500 *(vendor)* | 97.0 | 98.6 | — |
| HumanEval *(vendor)* | 92.1 | — | — |
| MBPP *(vendor)* | 92.7 | — | — |
| AIME 25 *(vendor)* | 88.3 (96.7 w/ tools) | — | — |
| Indic pairwise wins *(vendor)* | 89% | 90% | — |
| Base | from scratch | from scratch | Mistral Small |

Architecture (30B): 19 layers, dense FFN 8192, MoE intermediate 1024, top-6
routing, `num_key_value_heads=4`, `rope_theta=8e6` for long-context stability
without RoPE scaling.

**Why this is strategically strong for SIH specifically:**

- **~2.4B active params** on a 32B MoE means near-3B inference speed with 30B-class quality. For single-workstation deployment that is the single most interesting architecture in this document.
- **Apache 2.0** — cleanest possible license for PSU procurement.
- **"Sovereign AI" becomes literal.** An air-gapped refinery workbench running an Indian-made, Indian-trained, Apache-2.0 model on Indian government compute is a materially stronger story to an SIH panel than the same system running Qwen. That is a real evaluation criterion, not just optics.
- Indic + code-mixed support may be a hard requirement for MRPL correspondence — **needs confirming with the team**.

**Caveats to test, not trust:** every Sarvam benchmark above is vendor-published.
The AA Intelligence Index (12 / 18) is third-party and more sober than the
headline scores suggest — it places Sarvam 30B below the top open models on
general capability. **Our read: strong Indic + efficient MoE, general capability
to be verified independently.** VRAM at Q4 unconfirmed (source blocked); a 32B
MoE at Q4 is likely ~18–20GB → **Tier B, not Tier A**.

### 2.1b K2 Horizon (IFM) — released 2026-09-03, watch closely

⚠️ **Name collision.** "K2" also refers to Moonshot's **Kimi K2** family (K2.6,
K2.7, K3). Those are 1T-parameter MoE models needing **~633GB VRAM at Q4** —
irrelevant to us at any tier, including the PS's own 120B-class reference. Even
the distilled K2.6-Mini needs ~150GB. **Different organisation, different model,
not a candidate.** The one below is from the Institute of Foundation Models.

Six models, **Apache 2.0** (weights *and* code), published together with
**training data (or its construction recipe), training code, configs,
intermediate checkpoints throughout training, and fine-grained training logs**.

| Model | Params | Tier | Note |
|---|---|---|---|
| **K2-Horizon-0.9B** | 0.9B | **A** | **Claimed SOTA at scale**; reportedly >48 on AIME 2026 |
| K2-Horizon-3.7B | 3.7B | **A** | Claimed SOTA at scale |
| **K2-Horizon-7B** | 7B | **A** | Claimed SOTA at scale |
| K2-Horizon-32B | 32B | B | "among the top models" |
| K2-Horizon-MoVA-36B-A4B | 36B / **4B active** | B | Sparse |
| K2-Horizon-375B-A23B | 375B / 23B active | C | #11 of 112 on AA Index |

375B benchmarks: Terminal-Bench 2.1 **66.9%** *(corrected down from 70.2 after
audit)*, SWE-Bench Pro 42.6%, GPQA Diamond 87.3%, Humanity's Last Exam 32.0%,
Toolathlon Verified 65.3%.

**Native 512K context. Text-only** — it does not cover R5, so a VLM is still
required regardless.

**Why this is interesting for us specifically:**

1. **The 0.9B is a strong candidate for the resident coordinator** the
   architecture wants (§1.1). TRINITY's coordinator is ~0.6B; a 0.9B claiming
   SOTA at its scale is the right size to stay permanently resident at Tier A
   while workers swap around it.
2. **A SOTA 7B at Tier A** could co-reside with a 6GB VLM inside 12GB —
   eliminating the swap problem at baseline entirely.
3. **Published training data and logs = auditable provenance.** For a
   defence-linked PSU, "what was this model trained on?" is a real procurement
   question, and no other open family answers it this completely. This is a
   genuinely differentiated sovereignty argument, distinct from Sarvam's
   made-in-India one — and the two are complementary, not competing.

⚠️ **Practical blocker, verified:** llama.cpp has **no `k2-horizon` registered
architecture and no support PR open**. IFM publishes official GGUFs, but they
need a build from the **MBZUAI-IFM fork**. vLLM and SGLang require unreleased PR
branches. **Ollama is llama.cpp-based, so it almost certainly cannot load these
today.**

**Verdict: watch, do not build on it yet.** Two days old, zero community track
record, novel attention mechanism (MoVA — expert routing inside attention
layers), and the corrected Terminal-Bench number is a small reminder to wait for
third-party replication. Re-check before Subsystem 2 concludes; if upstream
llama.cpp support lands, the 0.9B and 7B become serious Tier A candidates.

### 2.2 General reasoning / orchestration

| Model | Params | ~Q4 | Tier | License | Evidence |
|---|---|---|---|---|---|
| Gemma 4 E4B | ~4B eff. | 6–7GB | A | Gemma ToU ⚠️ | Apr 2026 release |
| Phi-4 | 14B | ~9GB | A | MIT | 25–32 tok/s on RTX 4070 |
| Qwen3-14B | 14B | ~9GB | A | Apache 2.0 | "all-rounder" for 12GB |
| Llama 4 Scout | MoE (~17B act.) | fits 12GB Q4 | A | Llama Community ⚠️ | MoE — 17B speed, larger-model quality |
| DeepSeek-R1-Distill-14B | 14B | ~9GB | A | MIT | Visible reasoning traces |
| **Sarvam 30B** | 32B / 2.4B act. | ~18–20GB *est* | B | Apache 2.0 | §2.1 |
| **Qwen3.6-27B** | 27B dense | ~17GB | B | Apache 2.0 | **77.2% SWE-bench Verified**, 262K ctx |
| **Qwen3.8-27B** | 27B dense **+VL** | ~18GB | B | Apache 2.0 | Aug 2026; SWE-MM 25.7→38.6 |
| gpt-oss-20b | 20B MoE | ~12–13GB | B | Apache 2.0 | Agentic-focused, 128K ctx |
| Sarvam 105B | 105B MoE | ~60GB *est* | C | Apache 2.0 | AA Index 18 |
| gpt-oss-120b | 120B MoE | ~63GB | C | Apache 2.0 | Built for single 80GB GPU |

**Qwen3.8-27B is the standout Tier B candidate:** dense 27B, Apache 2.0,
**vision-language *and* strongest local coding agent in one model**, ~18GB. One
model covering orchestration + coding + vision would collapse three swap targets
into one resident model at Tier B. If that holds up under testing it
significantly simplifies the whole design.

Note the Qwen3.6-27B "90.0% SWE-bench" figure circulating: it used **12× RTX 4090
across two workstations** with an engineered agent stack. Irrelevant to us —
cite 77.2%, not 90%, or a judge who checks will find the asterisk.

### 2.3 Coding

| Model | Params | ~Q4 | Tier | License |
|---|---|---|---|---|
| Qwen2.5-Coder-7B | 7B | ~4.7GB | A | Apache 2.0 |
| Qwen2.5-Coder-14B | 14B | ~9GB | A | Apache 2.0 |
| Qwen3.6-27B / Qwen3.8-27B | 27B | 17–18GB | B | Apache 2.0 |
| Qwen3-Coder-30B-A3B | 30B MoE | ~18GB | B | Apache 2.0 |

### 2.4 Vision / document understanding

| Model | Params | ~Q4 | Tier | License | Notes |
|---|---|---|---|---|---|
| Qwen2.5-VL-7B | 7B | ~6GB | A | Apache 2.0 *verify* | Doc/OCR baseline |
| Qwen3-VL | varies | varies | A/B | Apache 2.0 *verify* | "competitive but lags" on handwriting |
| Gemma 4 (multimodal) | ~4B eff. | 6–7GB | A | Gemma ToU ⚠️ | Text+vision in one — saves a swap |
| **Qwen3.8-27B** | 27B | ~18GB | B | Apache 2.0 | VL + coding + general |

### 2.5 OCR / document parsing — OmniDocBench v1.6

Real leaderboard numbers, and the headline is striking: **the best document
parser is 0.9B and Apache 2.0.**

| Model | Size | Overall | Text edit dist. ↓ | TEDS (tables) | CDM (formulas) | License |
|---|---|---|---|---|---|---|
| **PaddleOCR-VL-1.6** | **0.9B** | **96.34** | **0.0326** | **94.76** | **97.53** | **Apache 2.0** |
| MinerU2.5-Pro | 1.2B | 95.75 | 0.036 | — | 97.45 | open |
| GLM-OCR | 0.9B | 95.22 | 0.044 | — | 97.18 | open |
| Youtu-Parsing | 2.5B | — | — | 92.02 | — | — |
| HunyuanOCR | — | — | — | 91.01 | — | — |
| Marker | pipeline | 78.44 | — | — | — | — |

**PaddleOCR-VL-1.6 leads on all three sub-metrics at 0.9B under Apache 2.0** —
small enough to stay resident alongside everything else even at Tier A. Strong
default for printed/tabular documents.

⚠️ **But see [F002](../results/findings/F002-handwriting-ocr-gap.md).**
MinerU2.5-Pro handles **only Latin and CJK print**, and OmniDocBench is
print-dominated. A 96.34 here does **not** mean handwriting works.

### 2.6 Handwriting — the hard case

| Model | CER (IAM, clean lines) | Open? |
|---|---|---|
| GPT-5 / Claude Opus 4.7 / Gemini 3 | 1.22 / 1.31 / 1.44% | ❌ unusable (air-gap) |
| **DTrOCR** | **2.38%** | ✅ |
| **TrOCR-Large** | **2.89%** | ✅ MIT |

On **realistic handwritten documents**, the best measured model (Gemini 3 Pro,
closed) gets **28.5% CER**, and open models degrade further. EasyOCR ~62%
accuracy. **This is the project's biggest technical risk — read F002 before
designing anything that depends on handwriting.** TrOCR-Large is the practical
open baseline *for fine-tuning on domain data*, which is likely the highest-
leverage work available to us.

### 2.7 Embeddings & reranking

| Model | Params | Tier | License | Evidence |
|---|---|---|---|---|
| nomic-embed-text | 137M | A | Apache 2.0 | **Already local** |
| BGE-M3 | 568M | A | MIT | Dense+sparse+multi-vector in one pass |
| **Qwen3-Embedding-8B** | 8B | A/B | Apache 2.0 | **MTEB Multilingual 70.58 — #1**, 32K ctx, 100+ langs |
| Qwen3-Embedding-0.6B / 4B | 0.6B / 4B | A | Apache 2.0 | Smaller siblings |
| **Qwen3-VL-Embedding-8B** | 8B | B | Apache 2.0 *verify* | **MMEB-V2 77.8 — SOTA**; MTEB-multi 67.9 |
| bge-reranker-v2-m3 | 568M | A | MIT | |
| Qwen3-Reranker-0.6B / 4B | 0.6B / 4B | A | Apache 2.0 | |

Two notes. **BGE-M3** emits dense + sparse + ColBERT vectors in one pass, which
maps directly onto Subsystem 4's hybrid design — lexical and semantic matching
without two models. **Qwen3-VL-Embedding** allows retrieving over *page images*
rather than extracted text, which sidesteps OCR error entirely for some queries
— genuinely interesting given F002, and worth a Subsystem 4 test axis.

**A reranker is not in the brief's Subsystem 4 list — adding it.** It's cheap and
usually the biggest retrieval-quality win; "hybrid + rerank beats both" is a more
useful finding than "hybrid beats flat".

---

## Part 3 — Library inventory

### 3.1 Subsystem 1 — Agent runtime

| Library | Lang | License | Notes |
|---|---|---|---|
| **LangGraph** | Py | MIT | Baseline; team's skill. Cyclical graphs, explicit nodes/edges — control and auditability suit us |
| smolagents | Py | Apache 2.0 | Lightweight comparison |
| **Pydantic AI** | Py | MIT | **Added.** Type-safe validated agent logic — directly serves deliverable-schema reliability |
| Hermes Agent | Py | *verify* | Pin a tag; disable all gateway adapters + GEPA loop |
| DeepSeek Harness (dsh) | *verify* | *verify* | Pin an rc; local endpoint, no API key |
| CrewAI | Py | MIT | Role-based multi-agent — maps to Thinker/Worker/Verifier |
| Hand-rolled ReAct | Py | — | Control |

**Deliberately excluded:** OpenAI Agents SDK, Google ADK, Mastra, Microsoft Agent
Framework — cloud-oriented or JS-runtime-targeted, poor fit for air-gapped
Python. **Sakana Fugu — closed API, disqualified (§1.1).**

Supporting: `pydantic`, `outlines` / `xgrammar` / `instructor` (constrained
decoding — structured-output reliability is a hard requirement), `semantic-router`.

### 3.2 Subsystem 2 — Serving

| Library | License | Windows | Notes |
|---|---|---|---|
| Ollama | MIT | ✅ native | **Installed.** See F001 — phones home by default |
| llama.cpp (server) | MIT | ✅ native | GGUF, best CPU-offload and swap story |
| **SGLang** | Apache 2.0 | ❌ Linux | **Added — not in brief.** **Multi-model serving from one process (vLLM cannot)**; native JSON-schema/function-calling; ~29% throughput over vLLM (H100); 80–120ms TTFT; ~6× on RAG |
| vLLM | Apache 2.0 | ❌ WSL2/Docker | Throughput leader at scale |
| TGI | Apache 2.0 | ❌ Docker | Optional |
| LM Studio | proprietary | ✅ | ⚠️ **Not open source — local convenience only, never shipped** |

**SGLang remains a strong candidate** if multi-model serving or throughput
becomes the bottleneck: multi-model from one process attacks the swap problem,
and native structured output helps deliverable reliability. **Revised
2026-09-10:** the baseline starts on llama.cpp (ARCHITECTURE §5.2) and moves to
SGLang or vLLM only when a measured bottleneck justifies it.

### 3.3 Subsystem 3 — Vision / OCR

`paddleocr` / PaddleOCR-VL (Apache 2.0 — current leader), `rapidocr-onnxruntime`
(Apache 2.0, no Paddle dep), MinerU (print-only), `docling` (MIT),
`transformers` for TrOCR/DTrOCR (MIT), `surya-ocr` (**GPL-3.0 ⚠️**),
`pypdfium2` (Apache/BSD — **prefer over `pymupdf`, which is AGPL-3.0 ⚠️**),
`opencv-python`, `pdf2image` + Poppler.

### 3.4 Subsystem 4 — Retrieval

| Library | License | Notes |
|---|---|---|
| Neo4j Community | **GPLv3** ⚠️ | Baseline hybrid; team strength |
| LightRAG | MIT | |
| Microsoft GraphRAG | MIT | Optional heavier comparison |
| Qdrant | Apache 2.0 | Strong hybrid control; GPLv3-free alternative |
| Chroma | Apache 2.0 | Simplest control |
| FAISS | MIT | CPU on Windows; GPU Linux-only |
| `rank_bm25` / Tantivy | Apache 2.0 | Lexical half of hybrid |
| Memgraph | BSL ⚠️ | Neo4j alternative if GPLv3 bites |

### 3.5 Subsystem 5 — Document generation

`python-docx` (MIT), `docxtpl` (LGPL-2.1), `python-pptx` (MIT), `openpyxl`
(MIT), `xlsxwriter` (BSD), **LibreOffice headless** (MPL-2.0 — formula recalc +
render-to-PDF, the backbone of the Verifier round-trip).

### 3.6 Subsystem 6 — Air-gap

`nftables`, Linux netns, OpenSnitch (GPLv3), `tcpdump`/Wireshark (GPLv2),
`mitmproxy` (MIT). Windows: `pktmon`, Firewall outbound-block. **Linux-only bar
the last — deferred until WSL2 goes in.**

### 3.7 Routing — revised 2026-09-10

Two levels, both logged with the rule that fired and the model chosen:

- **Gateway rules (ours):** inspection, coding and intake requests go to the
  agent team; general chat and document questions go to AnythingLLM. Inside
  the team, the router chooses by workflow stage, required capability,
  available memory and previous failures — not just "an image exists".
  Running code needs no model at all; only writing or repairing code does.
- **AnythingLLM's Model Router** for general chat: rule-based (keywords, token
  count, message count, image attached), first match wins, optional LLM
  classifier. MIT, built in.

`vllm-project/semantic-router` (Apache 2.0) and RouteLLM are **dropped from the
first build** — the built-in router plus our rules cover R2. Revisit only if
testing shows routing errors.

### 3.8 Platform and frontend — AnythingLLM underneath, our interface on top

| Item | Decision | Evidence |
|---|---|---|
| **AnythingLLM** | Base platform, run in Docker | MIT; offline; `DISABLE_TELEMETRY=true`; developer API (workspaces, upload, chat with threads and streaming, API keys) |
| Agents through the API | Confirmed | `server/utils/chats/apiChatHandler.js` checks `EphemeralAgentHandler.isAgentInvocation` in both sync and streaming chat and runs `startAgentCluster()` |
| Search without chat | Available | `/v1/workspace/{slug}/vector-search` |
| **Our frontend** | Build it | The panels judges need — agent timeline, evidence viewer, network monitor — don't exist in any stock UI |
| **Stage 0 (2026-09-11)** | **Passed for Q&A and API-driven tool calls, offline** | Scan OCR, document Q&A with source, agent → our MCP tool → Word file, all with outbound traffic blocked and no internet connections ([VERDICT](../results/stage0/VERDICT.md)) |
| Built-in agent writing reports | **Not used** | With llama3.1:8b it skipped the document search and wrote a false approval in 3 of 3 clean runs |
| Offline install requirements | Pre-seed `eng.traineddata` (else the first scan **crashes the container**); pre-seed or patch the startup fetches; disable agent web skills; set `AUTH_TOKEN`; MCP allowed hosts; fixed host address | [F003](../results/findings/F003-anythingllm-outbound-dependencies.md) |

⚠️ Open bug [#5271](https://github.com/Mintplex-Labs/anything-llm/issues/5271):
documents uploaded through the API on the **Windows desktop** app (v1.11.2) are
embedded but not added to the workspace; not reproduced on Linux. **Run
AnythingLLM in Docker.**

Alternatives: Onyx (fallback base, §3.12), LibreChat (MIT). Open WebUI's
licence still requires keeping its branding above 50 users.

### 3.9 Sandboxed execution (R4) — threat model corrected

Rev 1 argued Docker was enough because "our own model writes the code for one
trusted user". **That missed indirect prompt injection:** uploaded documents
(vendor files, correspondence) are untrusted and can carry instructions that
steer a tool-using agent. Even offline, a bad program can corrupt inputs, alter
drafts, read unrelated files or exhaust resources.

Docker stays the baseline, justified by explicit controls: a fresh container per
task; non-root; no network; dropped capabilities; `no-new-privileges`; seccomp
and a host MAC policy where available; read-only inputs and root filesystem;
one narrow writable output folder; no host home directory and no Docker socket;
memory, CPU, PID, time and output-size limits; dependencies preloaded; the GPU
model service kept outside the sandbox. gVisor is the step up; microVMs remain
optional. These controls reduce risk; they don't make the kernel boundary
complete.

### 3.10 Tools — MCP servers, not AnythingLLM skills

| Option | Verdict | Why |
|---|---|---|
| **MCP servers written with the official MCP Python SDK** (v2 `MCPServer`; v1 called it FastMCP) | **Use** | Our tools are Python (PaddleOCR, python-docx, sandbox). One implementation serves our agents and AnythingLLM's agents. Local transport, no internet |
| AnythingLLM custom agent skills | Don't use | JavaScript/Node.js only; run only inside AnythingLLM |

AnythingLLM supports MCP over stdio (default), SSE and streamable HTTP — tools
only, not resources or prompts. **When AnythingLLM runs in Docker, run our MCP
servers on the host over localhost HTTP**; otherwise stdio starts them inside
its container, which would then need Python, PaddleOCR and GPU access.
Localhost traffic counts as approved local traffic for the network monitor.

### 3.11 Agent structure — two 2026 papers, adapted

| Source | What we take | Caveats |
|---|---|---|
| **ICM — Interpretable Context Methodology** ([arXiv 2603.16021](https://arxiv.org/abs/2603.16021), Van Clief & McDermott, Mar 2026) | Each agent is a numbered stage folder with a `CONTEXT.md` (inputs, process, output contract); handoffs are files; plain scripts for steps that need no model; 2–8K focused tokens per stage vs 40K+ loading everything | Tested only with Claude Opus/Sonnet; no formal comparison; automatic branching awkward (we keep branching in code); does not cover knowledge bases, many documents or revisions |
| **Procedural Graphs** ([arXiv 2609.09153](https://arxiv.org/abs/2609.09153), Lu, Chen, Wu, Arık — Google, Sep 2026) | A small graph of steps whose links carry *condition / guidance / pitfalls*; the agent sees its current step's neighbourhood. First or joint first in 21 of 24 settings; BFCL v3 58 → 67%; GDPval 71.4 → 78.8 with fewer steps | Only large closed models tested; guidance costs an extra model call per step (+33–55% tokens) — we insert the notes by template instead (untested variant); self-improvement evidence noisy; no public code |
| **State machine** — LangGraph or plain Python | Enforces allowed transitions, retry limits, persistence | Compare only after the slice works: interrupt after extraction, restart offline, finish without repeating work or losing source links |

### 3.12 Prior art — corrected

Rev 1 said Onyx lacked all of R2–R5. **That was wrong** — it rested on a
marketing page that didn't mention the features.

| Product | Licence | Already does |
|---|---|---|
| **AnythingLLM** | MIT | Rule-based [Model Router](https://docs.anythingllm.com/model-router/overview); [Document Generation Agent](https://docs.anythingllm.com/agent/usage/document-generation-agent) (Word, Excel, PowerPoint); agents with MCP |
| **Onyx** | MIT core ([onyx-foss](https://github.com/onyx-dot-app/onyx-foss)); `ee/` features under a separate licence (SAML SSO, advanced permissions, white-labelling) | Built-in [code execution](https://docs.onyx.app/overview/core_features/code_interpreter) in a Docker sandbox with no network; file creation; image handling (per the review); 40+ connectors |
| LibreChat | MIT | Self-hosted code interpreter (per the review); MCP agents |
| Dify | Modified Apache 2.0 (multi-tenant SaaS restricted) | Visual workflows — not needed |
| Langflow | MIT | Visual LangGraph builder — not needed |
| Cognee, ibl.ai, Katonic, Airrived | various | Sovereign-AI positioning |

**Implication:** we don't differentiate on routing, file generation or
sandboxing. We differentiate on evidence — per-cell provenance, deterministic
rules with explicit uncertainty, verified drafts, and a revision-controlled
document library.

### 3.13 Vector store

**LanceDB**, AnythingLLM's default: embedded, local files, one namespace per
workspace; "Accuracy Optimized" adds re-ranking. AnythingLLM's docs describe
similarity search plus re-ranking and nothing on keyword search, which is weak
at exact IDs ("OISD-STD-116 Cl. 7.3", "R-2247"). So clause numbers and
equipment tags are resolved by **registry lookup in code first**, and LanceDB
serves open-ended questions inside the chosen documents.

Local alternatives AnythingLLM supports: Chroma, PGVector, Milvus (one setting,
`VECTOR_DB`). Never the cloud options (Pinecone, AstraDB, Zilliz). Neo4j and
graph retrieval stay parked until a measured cross-document failure justifies
them. Library structure and intake: [ARCHITECTURE §6](ARCHITECTURE.md).

---

## Part 4 — License risk register

For a PSU deployment this is a procurement axis, not paperwork.

| Item | License | Risk | Action |
|---|---|---|---|
| **Surya** | GPL-3.0 + revenue-threshold commercial | **High** | PaddleOCR-VL now leads OmniDocBench under Apache 2.0 — **Surya may be droppable on merit, sidestepping the license entirely** |
| **PyMuPDF** | AGPL-3.0 | **Medium** | Use `pypdfium2` unless decisively better |
| **Neo4j Community** | GPLv3 | **Medium** | Fine internal-use; contaminating if we ship a derivative. Qdrant/Memgraph fallback |
| **Llama 3.x / Llama 4** | Llama Community | **Low** | Not OSI-approved; naming + MAU conditions. Prefer Apache-2.0 Qwen/Sarvam on ties |
| **Gemma 3 / 4** | Gemma ToU | **Low–Med** | Read prohibited-use policy against refinery use cases |
| **LM Studio** | Proprietary | **Disqualifying to ship** | Local convenience only |
| **Sakana Fugu** | Closed API | **Disqualifying** | Inspiration only |

**Working preference: Apache 2.0 / MIT first.** Qwen (Apache 2.0), **Sarvam
(Apache 2.0)**, Phi-4 (MIT), DeepSeek-R1 distills (MIT), PaddleOCR-VL (Apache
2.0) and Qwen3-Embedding (Apache 2.0) cover **every single role** with clean
licenses. That is a strong argument for a Qwen + Sarvam stack independent of
benchmark scores.

---

## Part 5 — Pull list for baseline (Tier A)

~40GB against 124GB free on C:. **Subsystem 1 needs almost none of this** — an
8B plus a second endpoint suffices for orchestration/routing tests, so
**download in parallel with agent-runtime work, don't serialise behind it.**

| Purpose | Model | ~Size |
|---|---|---|
| General *(have)* | `llama3.1:8b` | 4.9GB |
| Embeddings *(have)* | `nomic-embed-text` | 0.3GB |
| General all-rounder | Qwen3-14B | 9.0GB |
| Reasoning | DeepSeek-R1-Distill-14B | 9.0GB |
| Coder | Qwen2.5-Coder-7B | 4.7GB |
| Vision | Qwen2.5-VL-7B | 6.0GB |
| Dual text+vision | Gemma 4 E4B | 6.5GB |
| **Doc parsing** | **PaddleOCR-VL-1.6** | **~1GB** |
| **Handwriting spike** | **TrOCR-Large** | ~1.4GB |
| Embeddings, hybrid | BGE-M3 | 1.2GB |
| Reranker | bge-reranker-v2-m3 | 1.2GB |

Tier B (when hardware allows): **Qwen3.8-27B** (~18GB) and **Sarvam 30B**
(~18–20GB est.) are the two to try first.

---

## Part 6 — Open verifications

Stated here from published sources; must be confirmed by our own testing.

- [ ] **Handwriting CER on realistic samples** — F002. Highest priority.
- [ ] Sarvam 30B actual Q4 size, VRAM under load, and **independent** (non-vendor) general-capability check
- [ ] Whether Sarvam's Indic strength is actually needed — depends on corpus language
- [ ] Qwen3.8-27B: does one model really cover orchestration + coding + vision well enough to kill two swap targets?
- [ ] SGLang multi-model-single-process: real swap/co-residency behaviour at 12GB and 24GB
- [ ] PaddleOCR-VL-1.6 on *our* documents, not OmniDocBench's
- [ ] Licenses: Qwen2.5-VL / Qwen3-VL variants, Qwen3-VL-Embedding, GLM-OCR, MinerU, DTrOCR weights availability
- [ ] Hermes Agent + dsh: license, and whether either runs offline with zero telemetry
- [ ] Does anything pull from HF Hub at **inference** time, not just download?
- [ ] Read TRINITY + Conductor papers properly (arXiv 2606.21228 is the Fugu report) before finalising the routing design

## Part 7 — Questions for the team

1. **Is the MRPL corpus English, Indic, or code-mixed?** Decides whether Sarvam is a strategic bonus or a hard requirement, and whether multilingual embeddings are mandatory.
2. **How much of the corpus is handwritten, and what does it look like?** F002 — if it's 40% the risk profile changes completely.
3. **MRPL deployment OS and GPU class?** Drives Tier B/C and whether Subsystem 6 must be Linux.
4. **Is the system delivered to MRPL or operated for them?** Determines whether GPLv3 (Neo4j, Surya) is a real problem.

---

## Sources

- [Sakana Fugu — Multi-agent System as A Model](https://sakana.ai/fugu/)
- [Sakana Fugu Technical Report (arXiv 2606.21228)](https://arxiv.org/pdf/2606.21228)
- [Sakana Fugu beta announcement](https://sakana.ai/fugu-beta/)
- [Sakana AI Bets on Agent Orchestration Over Frontier Models](https://www.govinfosecurity.com/sakana-ai-bets-on-agent-orchestration-over-frontier-models-a-32043)
- [Open-Sourcing Sarvam 30B and 105B | Sarvam AI](https://www.sarvam.ai/blogs/sarvam-30b-105b)
- [Sarvam 105B and 30B: India enters the open-weights race | Artificial Analysis](https://artificialanalysis.ai/articles/sarvam-105b-Sarvam-30b-everything-you-need-to-know)
- [Sarvam releases 30B and 105B LLMs under Apache 2.0 | Open Source For You](https://www.opensourceforu.com/2026/03/sarvam-releases-30b-and-105b-llms-under-apache-2-0/)
- [sarvamai/sarvam-30b · Hugging Face](https://huggingface.co/sarvamai/sarvam-30b)
- [OmniDocBench | opendatalab](https://github.com/opendatalab/OmniDocBench)
- [OCR Benchmark Leaderboard 2026](https://instavar.com/blog/ai-production-stack/OCR_SOTA_Feb_2026_Open_Document_AI_Leaderboard)
- [Best Handwriting OCR 2026: GPT, Claude, Gemini and TrOCR Compared | CodeSOTA](https://www.codesota.com/ocr/best-for-handwriting)
- [Handwriting Recognition Benchmark with 14 LLMs & OCRs | AIMultiple](https://aimultiple.com/handwriting-recognition)
- [Qwen/Qwen3.6-27B · Hugging Face](https://huggingface.co/Qwen/Qwen3.6-27B)
- [Qwen3.8-27B: Specs, Benchmarks & Verdict | Kingy](https://kingy.ai/blog/qwen3-8-27b-specs-benchmarks-local-hardware/)
- [Qwen3.6-27B-FP8 SWE-bench discussion | QwenLM GitHub](https://github.com/QwenLM/Qwen3/discussions/1846)
- [vLLM vs SGLang in 2026 | Yotta Labs](https://www.yottalabs.ai/post/vllm-vs-sglang-which-inference-engine-should-you-use-in-2026)
- [Complete Guide to Local LLM Inference Tools, July 2026 | DEV](https://dev.to/sreeraj-sreenivasan/the-complete-guide-to-local-llm-inference-tools-in-july-2026-llamacpp-ollama-vllm-sglang-and-4mh1)
- [llama.cpp vs vLLM | Red Hat Developer](https://developers.redhat.com/articles/2026/06/15/llamacpp-vs-vllm-choosing-right-local-llm-inference-engine)
- [Best Embedding Models for RAG 2026 | PremAI](https://www.premai.io/blog/best-embedding-models-for-rag-2026-ranked-by-mteb-score-cost-and-self-hosting/)
- [Qwen3-VL-Embedding and Qwen3-VL-Reranker (arXiv 2601.04720)](https://arxiv.org/pdf/2601.04720)
- [Best Local LLMs by VRAM Tier 2026 | PromptQuorum](https://www.promptquorum.com/local-llms)
- [Best LLM for 12GB VRAM 2026 | Local AI Master](https://localaimaster.com/vram/best-llm-12gb-vram)
- [Berkeley Function Calling Leaderboard (BFCL) V4](https://gorilla.cs.berkeley.edu/leaderboard.html)
- [The best AI agent frameworks in 2026 | LangChain](https://www.langchain.com/resources/ai-agent-frameworks)
