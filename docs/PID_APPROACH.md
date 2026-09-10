# P&ID Digitisation — Approach Note

**Status: stretch goal.** P&IDs appear in the PS Background and Description
but aren't named in the Expected Solution paragraph. That doesn't prove judges
won't ask about drawings (see [PS_ANALYSIS §2](PS_ANALYSIS.md)), so the plan
has two levels:

- **Useful drawing support** (once the core slice works): find the right
  drawing revision in the library, locate an equipment tag on it, and show the
  source region for a person to confirm. This reuses the OCR stack and the
  document library.
- **Full P&ID digitisation** (stretch): symbol detection, line connectivity and
  graph construction, as described below. Never presented as done.

Nothing here starts until the core acceptance tests (R1–R6) pass end to end.

Written 2026-09-04 in response to "are we training a YOLO model?"

---

## Short answer

**Yes, fine-tune YOLO — but understand that symbol detection is one of five
stages, and it's the easy one.**

## The five stages of P&ID digitisation

Decomposition follows the MIT-licensed Azure reference implementation, which is
the most complete public treatment we found:

| # | Stage | Method | Difficulty |
|---|---|---|---|
| 1 | **Symbol detection** — valves, pumps, instruments | **YOLO** ✅ | **Easy.** Solved problem, public datasets, pretrained weights |
| 2 | **Text detection + recognition** — tag numbers (`PT-101`, `V-204`) | Our existing OCR stack (PaddleOCR-VL) | Easy — we get it free from Subsystem 3 |
| 3 | **Line detection** — the pipes | Classical CV (Hough, morphology, line following) | **Hard.** Not a YOLO problem |
| 4 | **Arrow / flow direction** | CV + heuristics | Medium |
| 5 | **Graph construction** — associate symbols + lines + text into connectivity | Spatial reasoning, not ML | **Hard** |

**The trap:** YOLO gets you stage 1, which is the demo-friendly part — coloured
boxes on symbols look impressive immediately. But a model that finds 40 valves
without knowing what connects to what has produced *a bag of symbols, not a
digitised P&ID*. For a refinery the value is entirely in connectivity: trace a
line, find the isolation valves, identify what a relief path ties into. That's
stages 3–5, and they're weeks of work, not days.

**So scope deliberately: stages 1+2 are a credible deliverable. Stages 3–5 are a
research project.** Say so rather than implying full digitisation.

---

## Recommended sequence

### Step 0 — Test a VLM first (30 minutes, do this before any training)

Hand a P&ID to Qwen2.5-VL / Qwen3-VL and ask what equipment it shows. Zero
training cost, and it either works or it doesn't.

**Expectation: it will do poorly.** P&IDs are large, extremely high-density,
symbol-dominated drawings, and VLMs downsample input images — the detail that
distinguishes a gate valve from a globe valve is likely destroyed before the
model sees it. But this is 30 minutes for real information, and if it half-works
on tag extraction it collapses stage 2 into stage 1. Cheap enough that not
running it would be careless.

### Step 1 — Fine-tune YOLO on public data (1–2 days)

- **`hamzas/digitize-pid-yolo`** (HF) — Dataset-P&ID, 500 synthetic P&IDs with noise and complex symbols, **already in YOLO format**
- **Roboflow "P&ID Symbols"** (PID Connect) — 1,065 images plus pretrained weights and an API

Two datasets, one already YOLO-ready, one with pretrained weights to start from.
YOLOv8/v11 fine-tuning on ~1,500 images is a few hours on the RTX 4070 — this is
genuinely tractable, and it's the single most favourable ML task in the project.

**Do not train from scratch.** Fine-tune from COCO-pretrained weights.

### Step 2 — Tag association (cheap, high value)

Pair detected symbols with nearby OCR'd tag text by spatial proximity. Turns
"there is a valve here" into "**V-204** is here", which is the first genuinely
useful output — and it reuses the OCR stack we already need for R3/R5.

### Step 3 — Connectivity (only if time genuinely allows)

Classical line detection + graph construction. **Assume this doesn't get done.**

---

## Why this is worth doing at all

Two reasons beyond "it looks good":

1. **It's the first confidential example the PS names.** "Piping & Instrument Diagrams" leads the list of what can't go to cloud AI. To a judging panel with oil/gas background, showing P&ID understanding lands harder than anything else we could build.
2. **P&ID → graph feeds directly into the Subsystem 4 knowledge graph.** A digitised P&ID stored in Neo4j becomes queryable *alongside* the SOP corpus — "which isolation valves does OISD-STD-116 §7.3 require on this line?" is a question that needs both the drawing and the standard. That's a differentiator no amount of retrieval tuning gets you, and it's the reason the graph output design is worth borrowing from the Azure implementation even though the implementation itself is Azure-coupled.

---

## Honest risk statement

- Public P&ID datasets are largely **synthetic**. A model fine-tuned on them may transfer poorly to MRPL's real drawings, which will have different symbol conventions, scan quality, and vintage. We cannot test that without real drawings we will never be given.
- Symbol conventions vary by standard (ISA, ISO, DIN) and by company. A detector trained on one convention is not general.
- **We should demo on the public synthetic set and say exactly that.** Claiming it works on real refinery drawings is not something we can support.

---

## Sources

- [Dataset-P&ID / digitize-pid-yolo | Hugging Face](https://huggingface.co/datasets/hamzas/digitize-pid-yolo)
- [P&ID Symbols Object Detection | Roboflow Universe](https://universe.roboflow.com/pid-connect/p-id-symbols)
- [Azure-Samples/digitization-of-piping-and-instrument-diagrams (MIT)](https://github.com/Azure-Samples/digitization-of-piping-and-instrument-diagrams)
- [Engineering Document (P&ID) Digitization | Microsoft ISE Blog](https://devblogs.microsoft.com/ise/engineering-document-pid-digitization/)
- [Transforming Engineering Diagrams: P&ID Digitization using Transformers (arXiv 2411.13929)](https://arxiv.org/html/2411.13929v1)
- [mgupta70/PID_Symbol_Detection](https://github.com/mgupta70/PID_Symbol_Detection)
