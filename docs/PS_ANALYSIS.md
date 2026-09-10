# SIH26117 — Problem Statement Analysis

What the problem statement asks for, read carefully. Source text:
[`PS26117.md`](PS26117.md).

**Revision 2 — 2026-09-10.** Corrected after Ritesh's review. The architecture
material that rev 1 carried (routing, UI, sandbox, network proof, vertical
slice) now lives only in [`ARCHITECTURE.md`](ARCHITECTURE.md), so there is one
place to keep current.

---

## 1. Acceptance tests — our reading, not a confirmed rubric

| # | Requirement | Trigger in the text |
|---|---|---|
| **R1** | Working local deployment on a single workstation/server, mid-range GPU | "demonstrable on a single workstation or server with a mid range GPU" |
| **R2** | Model auto-selection across **≥2 task types** | "shows model auto selection across at least two different task types" |
| **R3** | Agentic task end to end, e.g. **scanned inspection report → findings → Word approval note** | "for example reading a scanned inspection report…" |
| **R4** | Coding task **run and verified in a sandbox** | "A coding task run and verified in a sandbox" |
| **R5** | Multimodal: image or scanned document understanding | "A multimodal task involving image or scanned document understanding" |
| **R6** | **Visible proof** of no external calls, via logs or a network monitor | "through logs or a visible network monitor" |

**Status of this list.** Rev 1 called these "effectively the grading
checklist". That was too strong. They are the team's reading of the Expected
Solution paragraph as pasted into `PS26117.md`. We have not seen the official
SIH statement, its version, or its judging criteria, and the review's searches
could not retrieve them either.

**Action:** obtain the official statement and separate mandatory
capabilities, illustrative examples, demo instructions and judging criteria.
Until then, R1–R6 are acceptance tests we set ourselves.

Two open points on R2: confirm whether "OCR model plus general reasoning model"
counts as two task types, or whether judges expect two task-specific LLMs.

---

## 2. Described vs demonstrated

| Capability | Named in the Description | Named in the Expected Solution |
|---|---|---|
| Scanned PDFs | ✅ | ✅ (R3, R5) |
| Handwritten notes | ✅ | ❌ |
| Engineering drawings (P&ID) | ✅ | ❌ |
| Photographs | ✅ | covered generically by R5 |
| Word / PPT / Excel output | ✅ | ⚠️ only Word, in the R3 example |
| Spreadsheet tool | ✅ | ❌ |
| Local knowledge base | ✅ | ❌ not separately |

### Correction to rev 1

Rev 1 concluded handwriting and P&IDs were "not graded" and "optional". The
text doesn't support that. The Expected Solution gives R3 as an *example*
("for example reading a scanned inspection report"), and absence from an
example does not establish what judges will or won't ask about.

### What still holds: the scoping strategy

- **Commit to printed scans and structured forms**, where open models are strong.
- **Handwriting:** test restricted fields — handwritten dates, tags and numbers
  in known form regions — rather than promising free-form handwriting. Compare
  line/cell recognition with human-assisted correction. Make no
  calibrated-confidence claims until measured on target-like samples. See
  [F002](../results/findings/F002-handwriting-ocr-gap.md).
- **Engineering drawings:** a useful smaller feature is finding the right drawing
  revision, locating a tag, and showing its source region for a person to
  confirm. Full P&ID topology reconstruction stays a stretch goal and is never
  described as done. See [`PID_APPROACH`](PID_APPROACH.md).
- **Office formats:** Word first. PowerPoint or Excel only if confirmed
  mandatory, each with its own narrow template and checks.

---

## 3. What "120B class hardware" tells us

> "use a smaller open weight model if 120B class hardware isn't available at the
> venue"

1. **The reference deployment is roughly an 80GB accelerator.** 120B-class open
   models (gpt-oss-120b, Sarvam 105B) target that class of server.
2. **The PS explicitly allows a smaller model at the venue.** Our 12GB RTX 4070
   bench is a sanctioned configuration, not a compromise.

The architecture targets the large tier; the demo runs small weights; only
configuration changes between them — provided each model passes the
compatibility test in ARCHITECTURE §5.3.

---

## 4. Prior art — corrected

Rev 1 said Onyx lacked all four of R2–R5 and that our differentiation was
clean. **Both were wrong.** Rev 1's source was a marketing overview page that
didn't mention the features; the review checked product documentation, and we
confirmed it on 2026-09-10.

- **AnythingLLM** (MIT) documents a rule-based **Model Router** that picks a
  model per message, and a **Document Generation Agent** producing Word, Excel
  and PowerPoint files.
- **Onyx** (MIT core; enterprise features under a separate licence) documents
  built-in **code execution in a Docker sandbox** with no network access, and
  **file creation**; per the review, its release notes also add image handling.

So the PS premise "nothing deployable exists today" is contestable, and a
feature-list differentiation fails.

**Decision (2026-09-10): build on AnythingLLM.** This reverses rev 1's "build
standalone" decision. Differentiation moves from features to **evidence and
reliability** — per-cell provenance, deterministic rules with explicit
uncertainty, verified drafts, and a revision-controlled document library. See
ARCHITECTURE §1 and §11.

### Other framing to keep honest

- **"Staff paste confidential material into public tools."** This is the
  problem statement's own premise. We have no MRPL evidence of how often it
  happens, so present it as the PS's premise or a stakeholder risk, not as our
  finding. A local alternative can improve adoption; its existence alone does
  not stop people using other services.
- **"A chatbot does none of these."** Unhelpful — existing chat products front
  agents, run tools and return files. Describe the concrete work we complete
  instead.

---

## 5. Where the rest went

Routing, the interface, sandbox threat model, network-proof design, the demo
flow, build order and risks are in [`ARCHITECTURE.md`](ARCHITECTURE.md) rev 2.

---

## Sources

- [AnythingLLM — Model Router](https://docs.anythingllm.com/model-router/overview)
- [AnythingLLM — Document Generation Agent](https://docs.anythingllm.com/agent/usage/document-generation-agent)
- [Onyx — Code Execution](https://docs.onyx.app/overview/core_features/code_interpreter)
- [Onyx FOSS repository (MIT)](https://github.com/onyx-dot-app/onyx-foss)
- [Onyx — Enterprise Edition](https://docs.onyx.app/deployment/miscellaneous/enterprise_edition)
- Ritesh's review: `air-gapped-workbench-critical-review.pdf` (repository root, 6 Sep 2026)
