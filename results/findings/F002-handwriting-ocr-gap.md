# F002 — Open-source handwriting OCR is the weakest link in the whole PS

**Severity:** High — this is a stated hard requirement with no strong open solution
**Found:** 2026-09-04, during benchmark research (before any local testing)
**Relevant to:** Subsystem 3, and the feasibility of the PS as written

## The requirement

SIH26117 requires multimodal input over "scanned PDFs, **handwritten notes**,
engineering drawings/photos". Handwriting is called out explicitly.

## What the benchmarks actually say

Two very different numbers get quoted for handwriting OCR, and conflating them
is how a team walks into a demo-day failure.

**On IAM (clean, single-line, English handwriting):**

| Model | CER | Open? |
|---|---|---|
| GPT-5 | ~1.22% | ❌ |
| Claude Opus 4.7 | ~1.31% | ❌ |
| Gemini 3 | ~1.44% | ❌ |
| Azure Document Intelligence v4.0 | ~1.8% | ❌ |
| **DTrOCR** | **2.38%** | ✅ (WACV 2024) |
| **TrOCR-Large** | **2.89%** | ✅ MIT |

**On realistic handwritten *documents* (not clean lines):**

| Model | CER | Open? |
|---|---|---|
| Gemini 3 Pro — best measured | **28.5%** | ❌ |
| LightOnOCR-2, DeepSeek-OCR | "substantial degradation" | ✅ |
| EasyOCR | ~62% accuracy (i.e. ~38% error) | ✅ |

The gap between 1.4% and 28.5% is the gap between a benchmark line-crop and a
real form. **The best model on the planet gets roughly one character in four
wrong on realistic handwritten documents**, and it's a closed cloud model we are
forbidden from using.

## Why this is the project's central risk

1. **The ceiling is low even for closed models.** This isn't "open source is
   behind" — it's an unsolved problem. We cannot fix it by buying our way out,
   and air-gap forbids that anyway.
2. **Open models degrade worse than closed ones** on exactly this task.
3. **MinerU2.5-Pro, the #2 on OmniDocBench, handles only Latin and CJK *print*.**
   The document-parsing leaderboard leaders are largely print-optimised — a high
   OmniDocBench score does **not** transfer to handwriting.
4. A refinery log sheet is the hard case, not the easy one: mixed print+
   handwriting, domain vocabulary, tabular structure, variable scan quality,
   possibly Indic script or code-mixed annotation.

## What this changes about the plan

**Do not architect as if handwriting OCR will work.** Design assuming it is
lossy and needs a human in the loop:

- **Confidence-gated extraction** — surface per-field confidence, route anything
  low-confidence to human confirmation rather than silently ingesting a wrong
  number into a calculation. An agent that confidently computes on a misread
  digit is worse than one that asks.
- **Constrain the field space.** Free-form handwriting recognition is brutal;
  recognising a date, a numeric reading, or one of eight known equipment tags is
  far easier. Structured forms with known schemas are a genuinely winnable
  subset.
- **Fine-tune on domain data.** TrOCR-Large is explicitly noted as "the most
  practical open-weight baseline **for fine-tuning on domain data**". A few
  hundred labelled MRPL log-sheet crops would likely beat any zero-shot VLM.
  This is probably the single highest-leverage piece of work available.
- **Scope the demo honestly.** Print + structured forms working reliably beats
  free-form cursive working occasionally.

## Actions

- [ ] **Spike this early — before Subsystem 3's full matrix.** Get real
      handwritten samples (or realistic proxies) and measure CER for
      TrOCR-Large, Qwen3-VL, PaddleOCR-VL, DTrOCR. If CER is unusable, the
      product design must change, and it's better to know in week 1.
- [ ] Ask MRPL/team what handwritten documents actually look like and how much
      of the corpus they are. If it's 2%, this de-risks to a footnote. If it's
      40%, it's the project.
- [ ] Check whether handwritten content is English, Indic script, or code-mixed
      — decides whether Sarvam/Indic-capable VLMs enter the OCR path.
- [ ] Confirm DTrOCR's license and whether usable weights are actually released.
