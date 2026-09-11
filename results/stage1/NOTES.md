# Stage 1 notes — reading the scan (step ①) and choosing models

12 September 2026. Bench: RTX 4070 12 GB, 32 GB RAM, Windows 11.
Corpus: the 12 synthetic MRPL-style reports in `data/corpus`, four scan
qualities each (clean, light, medium, heavy). The corpus is machine-made in a
clean font, so good results here do not prove good results on real MRPL scans.

Scripts used are in the session scratchpad for now; they move into
`workbench/` once the design settles.

---

## 1. qwen3.5:9b reading the whole page (vision model)

The model reads every page image and returns the report as JSON. Code compares
every field with the ground truth. "Critical" = CML ids, all four thickness
numbers per row, severities, finding ids, and the locations of readings and
findings.

| Scan quality | Critical fields wrong | All fields wrong | Reports with a critical error |
|---|---|---|---|
| Clean  | 1 / 456 | 1 / 722 | insp_1002 (CML-01 location misread) |
| Light  | 0 / 456 | 0 / 722 | — |
| Medium | 0 / 456 | 2 / 722 | — |
| Heavy  | 4 / 456 | 9 / 722 | insp_1000 (decimal points read as commas: "12,66") |

About 23 s per report. The scorer was itself tested: it catches a changed
digit, rounding, swapped columns, a dropped or invented row and a wrong
severity.

- On the clean insp_1002 scan qwen misread CML-01's location in 4 of 4 runs,
  each time differently ("Shell head — crown", "Shell head 2 — 180°" …). It
  read the same row correctly on the noisier medium scan. Cleaner is not
  always easier for a model.
- Ollama did not enforce the JSON schema for this model (it wrapped values as
  `{"value": …}` inside a markdown fence). The exact keys are now in the prompt.

## 2. Does the reader guess? (damaged-cell tests)

**Whited-out cells** (CML-03 current, CML-01 minimum, F-02 severity), 3 runs
each on clean and medium: qwen answered null in 18 of 18 reads. Good.

**A partly unreadable number** — the last digit of CML-03's current thickness
"12.32" (the breached reading) erased, or blurred. 18 reads in total:

| What qwen returned | Reads | Caught by code checks? |
|---|---|---|
| "12.3" — clean-looking, truncated | 13 (including temperature 0 on the blurred digit) | No: status still BELOW MIN, 12.3 still below 12.7 |
| A garbled table (row duplicated, columns shifted) | 2 | Yes: missing values, repeated CML |
| Another cell's value (19.28, 18.75, 19.67) | 3 | Not recorded — and each would have turned ESCALATE into NO TRIGGER |
| "Unreadable" for the damaged cell alone | 0 | — |

**Conclusion:** a model reading the whole page never reports a smudged digit
as unreadable. It writes a plausible number, and damage to one cell can spread
to the whole table.

## 3. OCR first: PP-StructureV3 (PaddleOCR 3.7.0, CPU)

Team suggestion (Rudraansh): parse the document with OCR tools first, then give
models clean text — the parsed text also feeds the knowledge base.

- **Text reading is excellent.** All 16 thickness numbers read correctly on
  clean, medium and heavy, confidence 0.94–1.00, each with its box on the page.
  On heavy it had no comma problem.
- **Its table structure is not trustworthy.** Even on the clean scan the HTML
  table merged the header with CML-01's row and shifted CML-01's values into the
  next row. The cell boxes show the same merge.
- **So code places the text, by position:** columns from the header words, rows
  from the CML ids, corrected for the scan's tilt (heavy is rotated ~1.5°).
  With the tilt correction all 16 numbers land in the right cells on all
  scans. Without it, 4 heavy values were placed in the wrong row.
- **It also read the blurred "12.32" as "12.3", at confidence 1.000.** OCR
  confidence did not flag the damage, and qwen gave the same "12.3" — two
  readers agreeing on a wrong value. Agreement between readers is not proof.
- OCR's mistakes stay local: it never copied another cell's value or shifted a
  row the way qwen did.
- **Leftover-ink check** (dark pixels in a number cell not covered by any read
  text): the smudged cell scores 76 px against at most 26 for the other cells
  on that page — but an undamaged cell on the heavy scan reaches 46 from
  speckle. Promising, not yet trustworthy; needs calibration on many damaged
  examples (ARCHITECTURE §7.1).
- A fully erased digit leaves no trace: no reader can catch it. Only a person
  with the original image can — which is why every value links to its crop.
- Speed on CPU: 130–200 s per page (oneDNN had to be disabled:
  paddlepaddle 3.3.0 CPU on Windows fails in layout detection with it). The GPU
  build should be much faster.
- Offline note: the first run downloads 10 models into
  `C:\Users\user\.paddlex\official_models`. For the air-gapped build these must
  be copied in beforehand and `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True` set
  (same class of problem as finding F003).

## 4. Direction for step ①

1. **OCR (PP-StructureV3) reads the page** → text, confidence and box for
   every value; also the text for the knowledge base, with page positions.
2. **Code places values in cells by position** (tilt-corrected), demands
   exactly one value per cell, exact numbers, and confidence above a
   calibrated threshold. Anything else → NEEDS REVIEW with the cell crop.
3. **qwen3.5:9b reads independently as a second reader.** Disagreement →
   review. Agreement is not treated as proof.
4. **Cheap consistency checks:** the report's own Status column against the
   rules' result; thickness that grew since the previous reading.
5. **Every critical value shows its crop to the engineer.** This is the only
   defence against a physically lost digit.

## 5. Models as the summary writer

**Sarvam 30B** (official `sarvamai/sarvam-30b-gguf`, Q4_K_M, architecture
`bailingmoe2`, 6 shards, 19.6 GB):

- The first download (DevQuasar GGUF) could not load: it used an architecture
  name (`sarvam_moe`) from an unmerged llama.cpp branch. Deleted.
- Served with Ollama's bundled `llama-server.exe`. **Started on its own, it
  ran on the CPU only** — it cannot find Ollama's CUDA backend. Fix:
  `GGML_BACKEND_PATH=…\lib\ollama\cuda_v12\ggml-cuda.dll` and that folder on
  `PATH`. Early speed and quality results were therefore unfair to the model.
- On GPU with `--n-cpu-moe 12`: 52.7 tokens/s generation, ~8.8 GB VRAM.
- Its tokenizer matches the official one for English and Hindi; one Kannada
  word splits differently.
- It would not switch thinking off (template setting, `<|nothink|>`,
  `--reasoning-budget 0` all failed or leaked). Forcing it off tested it in a
  mode it was not built for. Thinking is harmless for safety — the checker
  reads only the final summary — so the fair test runs with thinking on, its
  own recommended settings (temperature 0.7, top_p 0.8, top_k 20) and a
  6,000-token budget.
- Its own model card shows it behind same-size models at writing (Writing
  Bench 78.7 vs 85.0 Qwen3-30B-Thinking, 83.7 Nemotron-3-Nano); its strength is
  22 Indian languages.
**Like-for-like result** — same facts, same checker, same one-repair rule,
3 runs × 12 reports each:

| | Granite 4.1 8B | Sarvam 30B (GPU, thinking on) |
|---|---|---|
| Clean on first try | 28 / 36 | 26 / 36 |
| Repaired on second try | 6 (3 of them only too long) | 7 |
| Accepted long but accurate | 2 | 0 |
| Code fallback (model failed twice) | **0** | **3** |
| Attempts with a safety problem caught | **4** | **13** |
| Median time per summary | **2.6 s** | **49 s** |

Safety problems Sarvam made: not naming the CML below its minimum (most
often), miscounting severities, one invented breach (insp_1009), and once an
empty reply after thinking through its whole budget. Granite's: not naming a
breached CML (2), saying 3 Major findings where there were 2 (2).

**Conclusion:** on this task and this hardware the larger model is not
better — it made three times as many safety errors and was about 19× slower.
Every summary that reached a note, from either model, passed the checker.
The code-side safety net, not model size, is what makes the note safe.

**Caveat:** the facts given to the model and the checker were developed
against Granite's mistakes, which may favour it; Sarvam's strength (Indian
languages) is not tested by an English corpus.

**What this means for the pitch:** bigger models stay on the roadmap as
*candidates*, each admitted only by passing the same qualification test. The
test harness — not an assumption that bigger is better — decides.
