# SIH26117 — Problem Statement Analysis

What the PS actually demands, what it merely mentions, and what that means for
scope. Source text: [`PS26117.md`](PS26117.md). Revision 1, 2026-09-04.

---

## 1. The demo rubric, decoded

The Expected Solution paragraph is effectively the grading checklist. Extracted
literally:

| # | Requirement | Verbatim trigger |
|---|---|---|
| **R1** | Working local deployment on a single workstation/server, mid-range GPU | "demonstrable on a single workstation or server with a mid range GPU" |
| **R2** | Model auto-selection across **≥2 task types** | "shows model auto selection across at least two different task types" |
| **R3** | Agentic task end-to-end: **scanned inspection report → findings → Word approval note** | "for example reading a scanned inspection report…" |
| **R4** | Coding task **run and verified in a sandbox** | "A coding task run and verified in a sandbox" |
| **R5** | Multimodal task: image or scanned document understanding | "A multimodal task involving image or scanned document understanding" |
| **R6** | **Visible proof** of zero external calls via logs or network monitor | "through logs or a visible network monitor" |

Six items. That is the whole test. Everything else in the PS is context that
justifies these six.

---

## 2. The most important observation: described ≠ demonstrated

**The Description names hard capabilities that the Expected Solution does not
require us to demonstrate.** This is the single highest-leverage scoping insight
available, so it's worth being precise:

| Capability | Named in Description | Required by Expected Solution |
|---|---|---|
| Scanned PDFs | ✅ | ✅ (R3, R5) |
| **Handwritten notes** | ✅ | ❌ **not in the rubric** |
| **Engineering drawings (P&ID)** | ✅ | ❌ **not in the rubric** |
| Photographs | ✅ | ❌ (covered generically by R5) |
| Word / PPT / Excel output | ✅ | ⚠️ only **Word** is named (R3) |
| Spreadsheet tool | ✅ | ❌ not separately demoed |
| Local KB grounding | ✅ | ❌ not separately demoed |

The worked example in R3 is a **scanned inspection report** — printed, not
handwritten. R5 asks for "image or scanned document understanding", not
handwriting recognition and not diagram digitisation.

### Why this matters enormously

Two of our three biggest technical risks are **capability claims, not demo
requirements**:

- **Handwriting OCR** — [F002](../results/findings/F002-handwriting-ocr-gap.md)
  establishes that the best model on earth manages ~28.5% CER on realistic
  handwritten documents, and it's closed-weight. Unsolved problem, and we are
  air-gapped away from even the mediocre option.
- **P&ID digitisation** — active research (F1 ~0.96 on symbol-text detection in
  published work), but **no mature open-source tool exists**. It is a research
  project, not an integration.

**Strategy: build the winnable subset properly, support the hard cases
best-effort and honestly.**

- Demo on printed scans and photographs, where open models are genuinely strong.
- Support handwriting through a confidence-gated path that surfaces uncertainty
  and asks for human confirmation instead of silently guessing.
- Treat P&ID as a documented stretch goal, not a promise.

This is not scope-dodging — it's the difference between a demo that works and a
demo that fails live on the one input nobody could have made work. **Claiming
handwriting and having it fail in front of judges is far worse than scoping it
explicitly and explaining why.** An honest "here is the confidence gate, here is
where a human confirms" is a *better* engineering answer for a refinery than a
confident wrong number, and it should be presented that way.

---

## 3. What "120B class hardware" tells us

> "use a smaller open weight model if 120B class hardware isn't available at the
> venue"

Two things follow:

1. **The reference deployment is ~80GB VRAM.** 120B-class open models
   (gpt-oss-120b, Sarvam 105B) target a single 80GB accelerator — an H100/A100
   server. That is what "the organization's own GPU server" means in the PS
   author's head. It confirms our **Tier C** exists and is the real deployment
   target.
2. **The PS explicitly sanctions demoing on smaller models.** Our 12GB RTX 4070
   bench isn't a compromise we have to apologise for — the PS pre-authorises it.

This validates the tiered approach in
[`STACK_INVENTORY.md`](STACK_INVENTORY.md) and gives us the language to present
it: *the architecture targets 120B-class; the demo runs Tier A weights; nothing
but a config file changes between them.* **R2 (model auto-selection) is what
proves that claim** — swappability is demonstrated, not asserted.

---

## 4. Prior art — the PS's central premise is contestable

> "But nothing deployable exists today that industrial users can actually work
> with the way they use Claude or Codex."

**This is not quite true, and a sharp judge may know it.** We need an answer
ready.

### Onyx (formerly Danswer)

- **MIT licensed**, self-hosted, **fully air-gapped deployment supported**
- Enterprise search across **40+ connectors**, permission-aware retrieval
- Multi-model chat, deep research, custom agents
- Runs local inference via **Ollama, vLLM, or SGLang**
- **Already deployed in ITAR, FedRAMP, CMMC and FERPA environments**
- SOC 2 Type II, audit trails, RBAC

Onyx is a real, mature, air-gapped, MIT-licensed AI platform for exactly this
class of organisation. Pretending otherwise is a losing position.

### But look at what Onyx does *not* do

Checked directly against our rubric:

| Rubric item | Onyx |
|---|---|
| R2 — automatic multi-model routing **by task type** | ❌ absent |
| R3 — **document generation** (Word/PPT/Excel) | ❌ absent |
| R4 — **sandboxed code execution** | ❌ absent |
| R5 — **multimodal / OCR** document understanding | ❌ absent |
| R6 — visible egress proof | partial (audit trails) |
| Retrieval / KB / connectors / permissions / UI | ✅ strong |

**The four things Onyx lacks are precisely the four things the PS demo
requires.** Onyx is a retrieval-and-chat application layer; SIH26117 asks for an
*agentic production workbench*. That is a clean, defensible differentiation —
and it is also, conveniently, the honest one.

### Decision: we build standalone. Onyx is prior art, not a dependency.

**Decided 2026-09-04.** We are not using or forking Onyx. Its only role in this
project is as a **related-work answer** if a judge challenges the PS's "nothing
deployable exists today" premise. The answer is two sentences:

> Onyx is the closest existing system — MIT, air-gapped, strong on retrieval and
> connectors. It does not do task-type model routing, deliverable generation,
> sandboxed execution, or multimodal document understanding, which are exactly
> the four capabilities SIH26117 asks for.

**One idea worth stealing anyway: permission-aware retrieval.** MRPL has vendor
negotiations, financials and unreleased designs sitting in one corpus. A
retrieval layer with no access control is a confidentiality breach waiting to
happen, and the PS's own framing ("confidential", "policy keeps this data on
premises") invites the question. Not required by the rubric, cheap to add at the
retrieval layer, and probably the most credible unprompted addition available.
Flagged for the team as a scope call.

---

## 5. Architecture implications from this round of research

### 5.1 Routing — use `vllm-project/semantic-router` (R2)

The single best find for R2. An **Apache-2.0, official vLLM project**: "a
programmable Mixture-of-Models router for heterogeneous LLM inference," routing
on model specialisation, compute type and deployment location. v0.3 shipped June
2026. Related published work includes *When to Reason: Semantic Router for vLLM*
(reasoning-mode selection) and the Workload-Router-Pool architecture paper.

This is purpose-built for "automatically pick the right model for a given task"
and is far more defensible than a hand-rolled classifier — a named upstream
project with papers behind it. **Still needs verification: whether it runs fully
offline, and its hardware footprint.** Its install script is a `curl`, which is
an air-gap smell worth checking early.

Keep the deterministic rule-router as the **fallback and the audit story**; the
semantic router earns its place only if it beats rules on our task mix.

### 5.2 Don't build the UI (R1, and the "like Claude or Codex" bar)

The PS explicitly benchmarks UX against Claude and Codex. Building that from
scratch is months we do not have, and it is not what is being graded.

| Option | License | Fit |
|---|---|---|
| **Open WebUI** | ⚠️ **custom "Open WebUI License"** | ~140k stars, best all-rounder, one Docker command, Ollama/llama.cpp native, RAG + Python function calling |
| **LibreChat** | MIT | Most ChatGPT-like, team auth, **MCP agents**, multi-model switching in one conversation |
| **AnythingLLM** | MIT | RAG-first, workspace-centric, no-code agent builder, desktop app |

⚠️ **Open WebUI relicensed from BSD-3 to a custom license (v0.6.6+, April 2025)
with a CLA.** Deployments exceeding **50 users in a rolling 30-day window must
retain Open WebUI branding** — name, logo and identifiers cannot be removed or
replaced. Under 50 users is exempt.

For MRPL that is probably survivable; for a *sovereign, this-is-our-system*
pitch it is awkward, and for an SIH presentation where we claim authorship it is
worse. **Lean LibreChat or AnythingLLM (both MIT).** LibreChat's native MCP agent
support also aligns with tool-calling. *Licenses to be verified at install, not
trusted from a comparison blog.*

### 5.3 Sandbox — get the threat model right first (R4)

2026 consensus is that shared-kernel Docker/runc "isn't cutting it" for
untrusted AI-generated code; gVisor (user-space kernel, syscall interception) or
Firecracker microVMs (100–125ms boot, hardware-enforced, **snapshot-restore in
5–30ms** — genuinely useful for multi-turn agents) are the recommended tiers.

**But that consensus is written for a different threat model than ours.** Those
guides assume multi-tenant SaaS running code from untrusted third parties. Our
code is generated by *our own local model*, for *one trusted internal user*, on
an *air-gapped host where egress is already default-drop*. The realistic threats
are **accidental** — a runaway loop, a fork bomb, an `rm` in the wrong directory
— not a determined attacker escaping a hypervisor.

So: **Docker with dropped capabilities, read-only mounts, no network, and CPU/
memory/PID limits is very likely adequate for R4**, with gVisor as the credible
hardening step if a judge pushes. Firecracker is almost certainly
over-engineering for this project — worth *naming* as the production upgrade
path, not building. Deciding this on threat model rather than on what a blog
called state-of-the-art is itself the defensible engineering answer.

⚠️ **All three options need Linux (KVM/gVisor).** This is now the **third**
independent driver toward WSL2, alongside vLLM/SGLang and Subsystem 6.

### 5.4 R6 is a *demo artifact*, not just a test

"through logs or a **visible network monitor**" — the proof has to be **on
screen, live, during the demo**. That is a deliberate build item, not a
by-product of Subsystem 6:

- A live panel showing egress attempts (target: zero) with a running packet
  count and the active firewall ruleset
- A deliberate, scripted **failed** call-out to prove the monitor actually
  detects something — a monitor that only ever shows zero proves nothing about
  the monitor
- An exportable bundle (ruleset + egress log + pcap) for a security reviewer

The second bullet is the one teams forget. A dashboard reading zero all demo is
indistinguishable from a dashboard that is broken. **Show it catching something.**

---

## 6. The first vertical slice

**The PS hands it to us in R3.** Build exactly this, thin, end to end, before
adding any depth:

```
scanned inspection report (printed PDF)
  → OCR/VLM extraction         [PaddleOCR-VL-1.6 / Qwen2.5-VL]
  → findings extraction         [routed: summarization model]
  → KB grounding + citation     [retrieval over SOP corpus]
  → Word approval note          [python-docx + template]
  → Verifier round-trip         [render → VLM checks it looks right]
  → egress monitor shows zero   [live panel]
```

That single flow exercises **R1, R2, R3, R5 and R6**. Adding one coding task
through the sandbox completes **R4** and the entire rubric is covered by two
demos.

Depth — better models, hybrid graph retrieval, PPT/Excel, handwriting, P&ID —
gets added *after* the skeleton is provably end-to-end. **Build the full path
before improving any single stage.**

---

## 7. Updated risk register

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| **F002** | Handwriting OCR unsolved even for closed frontier models (~28.5% CER on real documents) | **High → Medium** | **Downgraded**: not in the demo rubric (§2). Confidence-gated + human confirm; demo on printed |
| **New** | P&ID digitisation has no mature open tool | Medium | Not in rubric. Explicit stretch goal. Park it |
| **New** | Onyx already does much of this, MIT, air-gapped, in ITAR/FedRAMP use | **Medium** | §4 — differentiate on the four gaps, and have the answer rehearsed |
| **New** | Open WebUI license forces branding retention >50 users | Low–Med | Prefer LibreChat / AnythingLLM (MIT) |
| **New** | Three independent requirements now need Linux (vLLM/SGLang, sandbox, nftables) | **Medium** | **Install WSL2 Ubuntu earlier than planned** |
| **New** | `semantic-router` installs via `curl` — offline-hostile smell | Low | Verify air-gapped install path early |
| **F001** | Ollama phones home hourly by default | Medium | Verify `ollama serve` alone is silent; default-drop egress regardless |
| **New** | Live network monitor could read zero because it's broken | Low | Scripted failed call-out during demo (§5.4) |

---

## 8. What changed as a result of this analysis

1. **Handwriting risk downgraded** from High to Medium — outside the demo rubric.
2. **The first vertical slice is now specified**, taken verbatim from R3.
3. **`vllm-project/semantic-router` becomes the leading R2 candidate**, displacing a hand-rolled router.
4. **UI is a buy-not-build decision**, leaning LibreChat/AnythingLLM on license grounds.
5. **Sandbox scoped to Docker+hardening** on threat-model reasoning, not blog consensus.
6. **Linux moved earlier** — three independent drivers, not one.
7. **Onyx identified as prior art** requiring a rehearsed answer, and possibly a source of borrowed ideas (permission-aware retrieval).

---

## 9. Open questions for the team

1. **Build on Onyx, or standalone?** (§4) — the biggest scope decision available, and it should be made deliberately.
2. **Do we add permission-aware retrieval?** Not required by the PS; arguably the most credible unprompted addition for a corpus mixing vendor negotiations with SOPs.
3. **Is the corpus English, Indic, or code-mixed?** Decides whether Sarvam is strategic bonus or hard requirement.
4. **What GPU will actually be at the SIH venue?** Determines the demo tier. The PS's "if 120B class hardware isn't available" implies we should be ready for either.
5. **PPT and Excel — build or claim?** R3 names only Word. Both are cheap with `python-pptx`/`openpyxl`, but each needs its own Verifier path.

---

## Sources

- [vLLM Semantic Router | GitHub](https://github.com/vllm-project/semantic-router)
- [The Workload-Router-Pool Architecture for LLM Inference (arXiv 2603.21354)](https://arxiv.org/pdf/2603.21354)
- [When to Reason: Semantic Router for vLLM (arXiv 2510.08731)](https://arxiv.org/pdf/2510.08731)
- [RouterArena: Comparison of LLM Routers (arXiv 2510.00202)](https://arxiv.org/pdf/2510.00202)
- [Sovereign AI: Definition, Why It Matters, Top Platforms | Onyx](https://onyx.app/insights/sovereign-ai)
- [Best Self-Hosted Enterprise AI Platforms in 2026 | ibl.ai](https://ibl.ai/blog/best-self-hosted-enterprise-ai-platforms-2026)
- [Open WebUI License](https://docs.openwebui.com/license/)
- [Open WebUI moves to BSD 3-Clause (later superseded) | GitHub Discussion](https://github.com/open-webui/open-webui/discussions/8467)
- [AnythingLLM vs Open WebUI vs LibreChat 2026 | DEV](https://dev.to/jovan_chan_9500711396d4e6/anythingllm-vs-open-webui-vs-librechat-in-2026-which-self-hosted-ai-interface-should-you-use-24cl)
- [How to sandbox AI agents in 2026: Firecracker, gVisor, runtimes](https://manveerc.substack.com/p/ai-agent-sandboxing-guide)
- [How to Sandbox LLMs & AI Shell Tools | CodeAnt](https://www.codeant.ai/blogs/agentic-rag-shell-sandboxing)
- [From Engineering Diagrams to Graphs: Digitizing P&IDs with Transformers (arXiv 2411.13929)](https://arxiv.org/pdf/2411.13929)
- [Automated inspection of P&ID object recognition using deep learning | Scientific Reports](https://www.nature.com/articles/s41598-025-25506-2)
- [Optimizing image format P&ID recognition | J. Computational Design and Engineering](https://academic.oup.com/jcde/article/12/6/55/8156798)
