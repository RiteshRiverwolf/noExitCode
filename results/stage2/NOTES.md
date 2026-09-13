# Stage 2 notes — the real reader, and a correction to stage 1

12 September 2026. Bench: RTX 4070 12 GB, 32 GB RAM, Windows 11.
Corpus: the 12 synthetic MRPL-style reports in `data/corpus` (born-digital
PDFs, plus four scan qualities each). The corpus is machine-made in a clean
font, so good results here do not prove good results on real MRPL scans.

---

## 1. What was built

The pipeline used to read the ground-truth answer key. It now reads the
document.

| Module | Job |
|---|---|
| `workbench/pagesource.py` | A PDF of any length or a page image → per page, every piece of text with its box. A born-digital page is read from its own characters; an image page goes to OCR. Both end up in the same shape and the same pixel frame, so one set of code handles either. |
| `workbench/ocr_worker.py` | PP-StructureV3, run as a subprocess of `.venv-ocr`. Results cached by image hash — a page costs 130–200 s on the CPU build. |
| `workbench/tablemap.py` | Places values into table cells by position, tilt-corrected, and checks them. Knows nothing about inspection reports. |
| `workbench/scan_reader.py` | The MRPL report's shape: which sections, tables and labels → evidence records with page, box, crop and the text each value was read from. |
| `bench/stage2/reader_score.py` | Scores a reading against ground truth. |
| `bench/stage2/damaged_cell_test.py` | The safety test: does a damaged digit get caught? |

## 2. Results

`bench/stage2/reader_score.py`, against the ground-truth sidecars:

| Source | Critical fields right | Accepted wrong | Time |
|---|---|---|---|
| 12 born-digital PDFs (all reports) | **395 / 395** | **0** | 0.1 s each |
| insp_1002, clean scan (OCR) | 30 / 30 | 0 | 0.1 s |
| insp_1002, medium scan (OCR) | 30 / 30 | 0 | 0.1 s |
| insp_1002, heavy scan (OCR) | 29 right, 1 flagged | 0 | 0.1 s |

"Critical" = CML ids, all four thickness numbers per row, finding ids and
severities. **"Accepted wrong" is the number that matters**: a value that is
wrong and that nothing flagged, which would reach an approval note. It is zero
in every run. Non-critical prose read from a *scan* does carry OCR noise
(character-level errors in descriptions and locations); read from the PDF it is
exact.

For comparison, stage 1's whole-page vision model took 23 s per report and made
4 critical errors on heavy scans. Reading a born-digital PDF is ~230× faster
and exact — which is the case for deciding per page rather than sending
everything to a model.

## 3. Correction to stage 1: leftover ink does not work

Stage 1 proposed a "leftover ink" check — dark pixels in a cell that no
recognised text box covers — and measured 76 px on the smudged cell against
≤ 26 px elsewhere. Implemented against the page-level OCR boxes and measured
again, it does not hold:

| Case | Dark px in cell not covered by a text box |
|---|---|
| undamaged | 0 at threshold 140; 193 at threshold 180 |
| blurred last digit | 0 at threshold 140; 193 at 180; 243 at 210 |
| erased last digit | 0 at threshold 140; 193 at 180 — identical to undamaged |

An erased digit leaves a white gap: there are no pixels to count, and no
threshold can find it. The blurred case only separates at a brightness where
the table's own grid lines also count. Stage 1's numbers came from per-cell OCR
boxes, which are tighter than the page-level ones. **The check is not
presented.**

## 4. What does work: column precision

A survey column is printed to a fixed number of decimals. The breached reading
`12.32` with its last digit damaged is read as a clean `12.3` — by
PP-StructureV3 at confidence 1.000, and by qwen in 13 of 18 stage-1 attempts —
but `12.3` carries one decimal where every other value in that column carries
two.

`bench/stage2/damaged_cell_test.py`:

| Case | Read as | Outcome |
|---|---|---|
| undamaged | `12.32` | correct, not flagged |
| last digit blurred | `12.3` | **wrong, raised for review** with the crop |
| last digit erased | `12.3` | **wrong, raised for review** with the crop |

No false alarms across the 12-report corpus. This catches the erased case that
stage 1 concluded only a person could catch. It is pure code: no model, no
threshold to tune, and it rests on a property of the printed form.

The check is deliberately conservative — it needs at least three other values
in the column agreeing with each other, and it raises the cell for review
rather than editing the number. A lost digit still cannot be recovered by
anyone; the only safe outcome is that a person sees the cell and its picture.

## 5. Two layout problems worth remembering

Both were caught by scoring, not by reading the output:

- **"Observation" is both a column header and a severity grade.** On the clean
  scan OCR misread the real heading as "Obseryation", so matching header words
  one at a time latched onto a *severity cell two rows down*, and the first two
  findings fell outside the table. Fix: the header must be one printed line —
  candidates are fitted to a line and the line carrying the most columns wins.
  A horizontal band is not enough, because a heavy scan is tilted ~1.5°, which
  lifts one end of the header row by about 30 px — more than a row's height.
- **The last row of a table swallows whatever is printed below it** (the
  corrosion-rate block), because it has no next row to stop it. White space does
  not separate them: the gap is 1.4 row pitches, well inside what a wrapped cell
  can leave. Alignment does: every line of a table sits on its columns' edges,
  and the block below misses them by 8–131 px.

## 6. Tolerance for OCR damage — where the line is

OCR writes `Eguipment Tag`, `Obseryation`, `INSPECTIONFINDINGS`, `380℃`.
Template words — the section headings, column headers and field labels — are a
small closed set fixed by the form, so they are matched with tolerance, and
every near match is recorded in the evidence set's `notes` ("read
'obseryation' as 'observation' (0.91 alike)"). **Values are never matched this
way.** `l2.32` stays unreadable and goes to review. Accepting a damaged
template word cannot change a number; accepting a damaged value can.

## 7. The sandbox and the Coder agent (R4)

`workbench/sandbox.py` runs untrusted code in Docker with `--network none`, a
read-only root filesystem, one writable working directory, a memory cap, a
process cap and a wall-clock limit. `--self-test` demonstrates the isolation
rather than asserting it:

| Probe | Result |
|---|---|
| TCP to 8.8.8.8:53 | refused (OSError) |
| DNS lookup | failed (gaierror) |
| HTTP to example.com | failed (URLError) |
| write to `/etc` | refused (OSError); the working directory is writable |
| `while True: pass` | killed at the time limit |

Each probe takes under a second. `--network none` gives the container no
interface at all — not a blocked one, an absent one — which is a stronger and
much simpler claim than a firewall rule. Without Docker the runner falls back
to a plain subprocess and labels the result
`subprocess (NO ISOLATION -- development fallback, not evidence)`; the label
travels with every result so a run can never be mistaken for evidence.

**The rule that makes "verified" mean something:** the model's own tests do not
count. A task is accepted only when the acceptance tests *we* wrote pass, and
the model never sees their source — only the failure messages, the way a
developer sees CI output. Same shape as the summary writer: the model
produces, code decides.

Results with granite4.1:8b (`workbench/coding_tasks.py`, full records in
`results/stage2/coder_*.json`):

| Task | Attempts | Time |
|---|---|---|
| `cml_report` — every CML below its minimum across many reports, ordered by shortfall | passed 1st | 7.2 s |
| `remaining_life` — corrosion rate and remaining life, with the grew-since-last-reading case | passed 1st | 3.9 s |
| `next_due_date` — API 510 half-life interval, rounded down, with 29 February | **failed, then passed on the 2nd** | 49.6 s |

The third task is the demo. The first attempt **hung and was killed by the
sandbox's time limit**; the model was told only "your program did not finish
within the time limit — it is probably waiting or looping forever", and its
next attempt passed all the tests. That is the self-healing loop and the
isolation working together, on camera, in under a minute.

The acceptance tests were themselves checked before any model saw them: a
reference solution passes each, and a deliberately wrong one (`<=` instead of
`<`, missing values treated as zero, rounding to nearest instead of down,
`date.replace` on 29 February) fails each, for the stated reason. Tests that
have not been shown to fail are not tests.

`cml_report` is also the answer to the "code as a tool" question: no single
inspection report says which readings across a whole set are worst, and that is
miserable for a language model to work out in its head. Ten lines of Python,
run in the sandbox, produce the answer and can be shown, re-run and checked.

## 8. All 12 medium scans, through OCR

Added 2026-09-13, once the background OCR run had read every medium page.

**Reader** (`results/stage2/reader_scan_medium.json`):

| | Right | Caught | Accepted wrong |
|---|---|---|---|
| Critical fields | 393 | 2 | **0** |
| Other fields | 200 | 83 | 150 |

Both catches were checked to be flagged *on the field itself*, not merely
somewhere in the report (the damaged-cell test once passed for exactly that
wrong reason): insp_1010's F-03 severity came out empty, and insp_1011's CML-01
current thickness was split into "12.62" and "." at confidence 0.196.

The 150 wrong non-critical fields, broken down:

- **111 are only lost spaces or dashes** — "Shell course 2-180°" for
  "Shell course 2 — 180°".
- **39 are real misreads.** 28 are clause references with "Cl." read as "CI."
  or "C1." ("OISD-STD-118CI.6.5"); 6 plant names drop a Roman numeral
  ("Phase II" → "Phase"); 5 are descriptions. The clause errors will matter
  when the Librarian looks clauses up — "CI. 6.5" will not match a clause.
  They are not repaired: values are never repaired, and the PDF path reads
  them exactly.

**Through the whole pipeline** (`--no-model`): 9 of 12 reach a verified note;
3 stop at `build_evidence` and go to a person.

| Report | Stopped for | Right to stop? |
|---|---|---|
| insp_1010 | F-03 severity unreadable | Yes — it was "Major" |
| insp_1011 | CML-01 current thickness unreadable | Yes |
| insp_1003 | CML-05 current thickness at OCR confidence 0.894, under the 0.90 limit | **No** — 13.49 was read correctly |

The one false alarm came from the confidence threshold, not from the
column-precision check, which flagged nothing wrongly on any medium scan. A
false stop costs a person a look at a correct value; that is the threshold's
intended trade-off, and it is not being tuned on one example.

### The 12 heavy scans — the worst quality

**Reader** (`results/stage2/reader_scan_heavy.json`): critical fields 355 right,
15 caught, **0 accepted wrong**.

Scorer caveat, stated so it is not mistaken for a result: the non-critical
line for heavy ("0 accepted wrong, 249 caught") flatters the reader. Every
heavy report carried at least one flag, and the scorer counts a report-level
flag as catching that report's prose errors. The critical figures are checked
per field and are sound.

**Through the whole pipeline** (`--no-model`): 4 reach a verified note, 8 stop
for a person. `bench/stage2/pipeline_stops.py --quality heavy` re-runs this.

- **All 4 notes have the right outcome**, checked against `index.json` rather
  than reasoned: insp_1004 ESCALATE, insp_1005 NO TRIGGER, insp_1006 ESCALATE,
  insp_1011 NO TRIGGER.
- **All 8 stops are right**: each had at least one critical value genuinely
  wrong or missing. None was a false alarm.

Stops worth naming:

| Report | What was wrong | Why it matters |
|---|---|---|
| insp_1000 | CML-05 minimum read as **82** for **8.2** — a dropped decimal point | exactly the misread that flips a verdict; caught |
| insp_1003 | F-05 severity read as "OISD-STD-118 CI. 8.4" — the clause cell landed in the severity column | caught only by the unreadable-grade gate added today (section 9) |
| insp_1008 | the thickness table was not found at all | no readings is not "no breach"; stopped |

The rest: severities left empty (insp_1002, 1007, 1009) and thickness values
unreadable (insp_1001, 1009, 1010).

**Three of the eight stops exist only because of today's fix** (insp_1002, 1003
and 1007 — their only problem was an unreadable grade). The grades lost there
were Observation and Minor, so the notes those runs would have produced were
right by luck. The same misread on a Major grade is the NO TRIGGER case in
section 9.

| Quality | Reach a note | Stop | Right stops | False alarms |
|---|---|---|---|---|
| medium | 9 | 3 | 2 | 1 (confidence 0.894) |
| heavy | 4 | 8 | 8 | 0 |

Worse scans send more work to people. That is the right direction: the system
degrades into asking, not into guessing.

## 9. A safety hole, found by scoring and closed

insp_1010 was the first stop in the table above only *after* this fix. Before
it, that scan ran all the way to `done`.

- The reader flagged F-03's empty severity, but nothing acted on the flag: the
  pipeline stopped only for doubtful *thickness* values.
- The rules treated an empty grade as simply "not Major or Critical" and moved
  on, with no review item.
- insp_1010 still escalated, but only because a thickness reading also
  breached. **On a report whose only trigger is a Major finding, the same
  misread gives NO TRIGGER and a finished note.**

`bench/stage2/unreadable_severity_test.py` was run against the unfixed rules
first, and failed as it should:

| Check (insp_1000, which escalates on severity alone) | Unfixed rules | Fixed |
|---|---|---|
| every escalating grade blanked | **NO TRIGGER** | NEEDS REVIEW |
| a garbled grade, "Majr" | **NO TRIGGER** | NEEDS REVIEW |
| one of two Major grades blanked | ESCALATE, blank one not listed | ESCALATE, blank one listed for review |

Closed in two layers, so neither can be lost to a later change on its own:

1. **Rules** (`workbench/rules.py`): a grade that is not one of Critical,
   Major, Minor or Observation is an EVD-01 review item. The outcome can no
   longer be NO TRIGGER while a grade is missing.
2. **Pipeline** (`workbench/run_inspection.py`): `build_evidence` stops the run
   before the rules are reached.

After the fix: the test passes, all 12 PDFs still reach `done`, and the audit
log's hash chain verifies intact over 955 entries.

The general lesson: a check that *flags* is not a check that *stops*. Every flag
the reader raises on a value a decision depends on has to be wired to
something that halts the run, and tested end to end.

## 10. The Router (R2)

`workbench/router.py` and `workbench/models.yaml`. A model may do a task only if
it has passed a qualification test on our harness; every result names its
evidence file (all 12 paths checked to exist). A safety **gate** decides who is
allowed at all; a **rank** orders the rest. The model must also be running and
fit the GPU. Every decision goes to a hash-chained log with every candidate and
the reason each was or was not chosen.

Decisions on this machine, 2026-09-13:

| Task | Chosen | Why the others were not |
|---|---|---|
| `write_summary` | granite4.1:8b | sarvam-30b qualified but not running; others never tested |
| `tool_agent` | granite4.1:8b | qwen3.5 eligible, ranked second (6/9); **llama3.1 and lfm2.5 fail the safety gate** — 7 and 2 false approval notes |
| `code` | granite4.1:8b | no other model tested |
| `second_read` | qwen3.5:9b | the only vision model — and its record says it is never trusted alone |
| `describe_image` | **nothing** | no model has been tested on photographs or drawings |
| `embed` | nomic-embed-text | the only embedding model |

Different models across task types, which is what R2 asks for — and a refusal
where nothing is qualified, which is what a judge should hear instead of a
guess.

Requests are classified into tasks by plain rules, so the classification is as
auditable as the choice. One rule was wrong on first test: "find last year's
vendor correspondence and summarise it" went to the approval-note summary
writer, which writes from evidence already in hand and would have had nothing
to write from. Summaries now route there only for an approval note; anything
that has to search first is a `tool_agent` job.

The pipeline and the Coder both ask the Router now. `--model` still works, and
is logged as an override.

## 11. Left to do

- The corpus has one two-page report. The reader is built for any length and
  joins rows across pages by CML id, but nothing has tested a table split over
  a page break.
- PaddleOCR-VL-1.6 (0.9B, Apache 2.0, already in `models/`) scores 96.33 on
  OmniDocBench v1.6 against PP-StructureV3's 64.45. It is worth a trial, on the
  condition that it returns per-value boxes and confidence and scores zero
  accepted-wrong here — a generative reader is exactly the kind that invents a
  plausible digit.
- qwen as an independent second reader, with disagreements sent to review, is
  designed and not wired in.
