# SIH26117 — Datasets & Test Corpus

What we test on, where it comes from, and what we are legally allowed to do with
it. Revision 1, 2026-09-04.

---

## The headline findings

### Correction to revision 0

An earlier pass concluded "there is no public corpus of refinery inspection
reports, therefore everything must be synthetic." **That was based on too narrow
a search** — looking for *inspection report templates* rather than for the places
industrial documents actually get published: regulatory bodies, accident
investigators, and public procurement portals.

Two genuinely good real sources exist. Both are downloaded and verified.

### 1. US CSB investigation reports — public domain, real refinery engineering ✅

`data/external/CSB_chevron_richmond_final_report.pdf` — verified:

- **132 pages, born-digital with a full text layer** (avg 2,426 chars/page)
- **US federal agency work → public domain.** The cleanest license possible
- Real content: wall-thickness values on the 4-sidecut piping, 2007 and 2011
  Crude Unit turnaround inspection records and their recommendations,
  mechanical-integrity program findings, equipment tags (C-1100 crude unit
  atmospheric column), process schematics, sulfidation-corrosion damage-mechanism
  analysis, API 570 deficiencies

This is real refinery inspection and integrity content written by investigators
with full access to the operator's records. It is not a form-shaped inspection
report, but as **domain-authentic technical corpus** it is far better than
anything we could invent. The CSB has published many more of these.

### 2. MRPL's own public tender documents — authentic corporate documents ✅

`data/external/MRPL_tender_3200000346.pdf` — verified:

- **486 pages, born-digital with a text layer**
- Genuine MRPL letterhead, registered office, ONGC subsidiary framing, refinery
  capacity figures (15.25 MMTPA, 900,000 TPA paraxylene)
- Real internal document structure: Master Index, NIT, Instructions to Bidders,
  GCC, SCC, annexures covering time schedule, measurement of work, payment terms,
  **quality management system specification**, **calibration** requirements
- Published by MRPL themselves at mrpl.co.in and eprocure.gov.in

**This is the single most on-target corpus material available** — actual MRPL
documents, in MRPL's own formatting and language, for a demo aimed at MRPL.

⚠️ **Two caveats.** *(a)* This particular tender is for civil construction (a
rest room and parking yard), so its technical content is not process
engineering. Worth hunting MRPL tenders for **turnaround, inspection or
mechanical services** to get real inspection specifications. *(b)* **It contains
real employees' names, direct phone numbers and email addresses.** Published
publicly, but propagating named individuals' contact details into a demo corpus
is needlessly careless — **strip or pseudonymise PII before any document goes
into the KB or on a slide.**

### 3. The method that falls out of this: born-digital PDFs are self-labelling OCR benchmarks

Both documents have a **text layer**. That means:

```
render page at high fidelity  →  apply scan degradation  →  OCR
                                                             ↓
                          compare against the PDF's own embedded text
                                    = free ground truth
```

**Real documents with zero manual labelling.** This is a much better OCR
benchmark than either synthetic documents or hand-labelled scans, and it works
at whatever scale we want — 132 + 486 pages of real industrial text, gradeable
across the full degradation curve. Subsystem 3 should be built on this.

### What synthetic generation is still for

Not obsolete — **retargeted**. Real documents give us OCR ground truth but not
*structured field-level* ground truth: no public source gives a completed
inspection report with a known equipment tag, known severity per finding, and a
known correct escalation decision. That is exactly what R3's extraction step must
be scored against.

| Job | Source |
|---|---|
| **OCR / CER benchmarking** | **Real docs** (CSB, MRPL, DocLayNet) degraded, scored vs. their own text layer |
| **KB grounding corpus** | **Real docs** (CSB, MRPL tenders) + our own OISD-style SOPs for cross-references |
| **Structured extraction + approval-note decision** | **Synthetic** — the only way to have field-level ground truth |
| **Non-synthetic control** | DocLayNet |

So the generator in `bench/corpus/` stays, with its scope narrowed to the
structured-extraction task — and its vocabulary now calibrated against the real
CSB language rather than invented.

---

## Part 1 — Datasets we will actually use

### 1.1 Demo corpus — authored by us ✅ primary

Synthetic but domain-authentic. Generated from templates, rendered to PDF, then
degraded to simulate scanning (skew, noise, JPEG artefacts, mild blur).

| Artefact | Purpose | Rubric |
|---|---|---|
| Equipment inspection reports (printed) | The R3 input | R3, R5 |
| SOP / standard-operating documents with **cross-references between them** | KB grounding + multi-hop retrieval | R3 |
| Approval-note templates | Deliverable target | R3 |
| Calculation sheets | Excel + coding path | R4 |
| Handwritten annotation overlays | Confidence-gating path | *(capability, not rubric)* |

**Ground truth is emitted alongside every document** — a JSON sidecar with every
field value. That is what makes accuracy measurable rather than vibes-based.

Content modelled on **OISD standards** (Oil Industry Safety Directorate, Ministry
of Petroleum & Natural Gas — the body Indian refineries actually answer to) and
**API 510** for structure and vocabulary. ⚠️ **Modelled on, not copied from** —
see §2.3.

### 1.2 DocLayNet ✅ permissive

- **License: CDLA-Permissive-1.0** — worldwide, non-exclusive, irrevocable right to use and publish. **The cleanest license of any document dataset we found.**
- 81K human-annotated pages, 11 region classes, scanned images **and** native PDFs
- IBM Research (Deep Search); underpins `docling`
- **Use:** layout-analysis evaluation, and a realistic non-synthetic control so we can show our OCR results aren't an artefact of our own generator

### 1.3 Handwriting evaluation — research use only

| Dataset | Scale | Note |
|---|---|---|
| **IAM** | 1,539 forms, 657 writers, 115K words | The standard HTR benchmark. Comparable to the F002 CER figures |
| **IMGUR5K** | 8,094 images, ~5,305 writers | In-the-wild, harder, closer to real conditions |
| **IIIT-INDIC-HW-WORDS** | **872K instances, 135 writers, 8 Indic scripts** | IIIT Hyderabad. **The one that matters if MRPL's corpus is Indic** |
| IIIT-HW-Dev | 95K Devanagari words | Devanagari-specific |

**Use:** measuring the F002 handwriting gap on our own hardware, and as
fine-tuning data for TrOCR if we pursue that. ⚠️ Research/educational terms —
fine for SIH, **must be re-checked before any commercial MRPL deployment.**

### 1.4 P&ID — stretch goal only

| Resource | Note |
|---|---|
| **Dataset-P&ID / Digitize-PID** | 500 synthetic P&IDs with noise + complex symbols. On HF as `hamzas/digitize-pid-yolo` |
| **Roboflow "P&ID Symbols" (PID Connect)** | 1,065 images + pretrained model + API |
| `mgupta70/PID_Symbol_Detection` | GitHub, research-paper derived |
| **`Azure-Samples/digitization-of-piping-and-instrument-diagrams`** | **MIT licensed** — see correction below |

**Correction to [PS_ANALYSIS §2](PS_ANALYSIS.md):** I previously wrote that P&ID
digitisation has "no mature open-source tool". That was too strong. Microsoft
publishes an **MIT-licensed** reference implementation doing symbol detection,
text detection, line and arrow-direction detection, and **graph construction** —
P&ID in, graph out.

The catch: it is **built on Azure ML, AKS, Azure storage and SQL Graph**. The
code is readable and the license is permissive, but it is cloud-coupled and
would need real rework to run air-gapped. So the corrected statement is: *an
MIT reference implementation exists, but no air-gapped-ready open tool does.*
Still a stretch goal, still out of the rubric — but the **P&ID → graph** output
design is a genuinely good idea worth borrowing if we ever reach it, because it
feeds straight into the Subsystem 4 knowledge graph.

---

## Part 2 — Datasets we are deliberately NOT using

### 2.1 FUNSD ⚠️ non-commercial

Noisy scanned forms with key-value annotations — a natural fit for the
form-extraction task, and **excluded on license**. Terms restrict use to
"non-commercial, research and educational purposes."

SIH is arguably educational, but the PS's whole point is a system MRPL actually
deploys. Anything FUNSD touches — especially a fine-tuned model — inherits that
restriction. **Not worth the contamination for a dataset we can substitute.**

### 2.2 RVL-CDIP ⚠️ murky license, wrong domain

400K scanned pages in 16 categories (form, invoice, specification) — superficially
attractive. Two problems:

1. Derived from the Legacy Tobacco Document Library via IIT-CDIP; HF marks it "other". Not a license we can rely on for a deployed system.
2. **It's 1990s tobacco-litigation paperwork.** Structurally document-like, semantically nothing like a refinery inspection report. It would make our OCR numbers look real while measuring the wrong thing.

### 2.3 OISD standards ⚠️ redistribution prohibited

OISD publishes 200+ standards governing Indian petroleum installations — exactly
the SOP corpus MRPL grounds against, and the most authentic possible content.

**But:** OISD publications "are the property of the Ministry and shall not be
reproduced or copied without written consent from OISD."

**So:** read them for structure, vocabulary and clause-numbering conventions;
**author our own SOP documents in that style**; never commit an OISD PDF to the
repo or ship one in a demo bundle. Citing *"per OISD-STD-116 §7.3"* in a
generated approval note is a reference, not reproduction — that's fine and it is
exactly what makes the demo feel authentic to a refinery audience.

---

## Part 3 — License summary

| Dataset | License | Commercial | Verdict |
|---|---|---|---|
| **Our synthetic corpus** | Ours | ✅ | **Primary** |
| **DocLayNet** | CDLA-Permissive-1.0 | ✅ | **Use freely** |
| Dataset-P&ID | check at download | ? | Stretch goal |
| Azure P&ID sample | MIT (code) | ✅ | Reference only — Azure-coupled |
| IAM / IMGUR5K / IIIT-INDIC-HW | research/educational | ⚠️ | Evaluation only; re-check before deployment |
| FUNSD | non-commercial | ❌ | **Excluded** |
| RVL-CDIP | custom / "other" | ⚠️ | **Excluded** — wrong domain anyway |
| OISD standards | Ministry property | ❌ redistribution | Model on, never ship |
| API 510 | API copyright | ❌ | Reference only |

**Rule of thumb: if it can't be committed to the repo and shipped in a demo
bundle, it doesn't go in the demo corpus.** Evaluation-only datasets stay out of
version control, in a gitignored `data/external/`.

---

## Part 4 — Build order

1. **Inspection report generator** — templates → PDF → scan degradation → image + JSON ground truth. Unblocks the entire R3 slice.
2. **SOP corpus generator** — 10–20 documents with genuine cross-references, so multi-hop retrieval has something real to exploit.
3. **Scan-degradation module** — skew, noise, JPEG, blur, at controllable severity, so OCR can be scored against a difficulty curve rather than one arbitrary quality level.
4. **DocLayNet sample** — pulled as the non-synthetic control.
5. *(later)* IAM / IIIT-INDIC for the handwriting spike.

---

## Sources

- [DocLayNet | GitHub (DS4SD)](https://github.com/DS4SD/DocLayNet) · [license](https://github.com/DS4SD/DocLayNet/blob/main/LICENSE) · [arXiv 2206.01062](https://arxiv.org/abs/2206.01062)
- [FUNSD License and Terms of Use](https://guillaumejaume.github.io/FUNSD/work/)
- [RVL-CDIP on Hugging Face](https://huggingface.co/datasets/aharley/rvl_cdip)
- [IIIT-INDIC-HW-WORDS | CVIT, IIIT Hyderabad](https://cvit.iiit.ac.in/research/projects/cvit-projects/iiit-indic-hw-words)
- [Word-level Handwritten Datasets for Indic Scripts | CVIT](https://cvit.iiit.ac.in/research/projects/cvit-projects/indic-hw-data)
- [IMGUR5K Handwriting Dataset | Meta Research](https://github.com/facebookresearch/IMGUR5K-Handwriting-Dataset)
- [Dataset-P&ID / digitize-pid-yolo | Hugging Face](https://huggingface.co/datasets/hamzas/digitize-pid-yolo)
- [P&ID Symbols Object Detection | Roboflow Universe](https://universe.roboflow.com/pid-connect/p-id-symbols)
- [Azure-Samples/digitization-of-piping-and-instrument-diagrams](https://github.com/Azure-Samples/digitization-of-piping-and-instrument-diagrams)
- [Oil Industry Safety Directorate — Standards List](https://www.oisd.gov.in/en-in/oisd-standards-list)
- [OISD | Ministry of Petroleum and Natural Gas](https://mopng.gov.in/en/refining/oil-industry-safety-directorate)
- [API 510: Pressure Vessel Inspection Code (public copy)](https://law.resource.org/pub/us/cfr/ibr/002/api.510.2006.pdf)
