# Harness, scaling and roadmap

How the workbench takes in new models as plug-ins, what gets better on bigger
hardware, and where the knowledge graph and self-evolving procedures fit.
Written 2026-09-11 for the pitch and the team.

**The rule for this document:** every claim is marked **Proven** (we ran it,
the evidence is in the repo), **Built** (code exists and runs, not yet
measured at scale) or **Proposed** (designed and backed by published work, not
built). Judges can check the first two; the third is our roadmap.

---

## 1. The idea in one paragraph

Models are **plug-ins**. The harness around them does the work that has to be
right every time: it reads the evidence, applies the rules in code, checks
everything the model writes, reads the finished file back, and records every
step. A new model plugs in by passing the same qualification tests every
other model took. On today's 12 GB workstation that means 8–9B models; on a
bigger server the same harness qualifies 30B, 100B+ models and switches on
stages that need them. **Safety does not depend on the model**: a weaker
model produces more "needs review" drafts and more fallbacks, never a wrong
approval.

---

## 2. What is proven today (12 GB workstation, RTX 4070)

| Evidence | Result | Where |
|---|---|---|
| Rules engine vs the corpus answer key | **12 of 12** reports get the right outcome (escalate on thickness, on severity, on both; six no-trigger) | `workbench/rules.py`; run logs |
| Tool chaining, same 9-run trap test per model | granite4.1:8b **9/9**, qwen3.5:9b 6/9 (no wrong notes), lfm2.5:8b 0/9, llama3.1:8b 0/9 (7 false approvals) | `results/stage0/NOTES.md` |
| The summary checker catching invented facts | granite, our best model, **invented a thickness breach in 2 of 12 reports** ("undershot minimums" for CMLs that were fine). The checker caught both; the note fell back to a code-written summary. After the harness was changed to hand the model the rules' status for every reading, both passed on the first attempt with correct statements | `workbench/prose.py`, runs `insp_1006`, `insp_1008` |
| Self-healing loop | A deliberately wrong value in the Word file is caught by the read-back check; the procedural graph sends the work back to the renderer; attempt 2 passes | `run_inspection --inject-fault render` |
| Full corpus, final run (after the team's guidelines were applied) | **12/12** model summaries accepted: 9 clean on the first attempt, 1 fixed by its repair attempt, 2 accurate but slightly long (133–135 words) and accepted with that noted in the trace. **12/12** notes pass read-back; run log chain intact. Across all runs the checker also caught a measured value given as a minimum (insp_1011), severity words misused ("two critical findings" where none were graded Critical) and miscounts ("three major" where there were two) | `logs/workbench_runs.jsonl` |
| Read-back of every note | Every value in the Word file is compared with its evidence record before the run ends: 14–18 checks per note, all pass | `workbench/report_writer.py` |
| Air-gap | With all outbound traffic blocked, OCR, document Q&A and agent → tool → Word file all work; no internet connections in the capture | `results/stage0/VERDICT.md` |
| Web access only with permission | 15/15 checks: approve, decline, timeout, refusals, tamper-evident log | `mcp_servers/` |

The lesson we put in front of judges: **model size did not predict
results** (four models of 8–9B scored 0 to 9 out of 9), and even the best one
invents things occasionally. That is why the harness exists.

---

## 3. Models as plug-ins

### 3.1 The model card — **Proposed** (small; next to build)

Each model gets one entry in `models/registry.yaml`:

```yaml
- name: granite4.1:8b
  runtime: ollama            # ollama | llama.cpp | vllm | sglang
  provenance: IBM, official  # official or community conversion
  licence: Apache-2.0
  size_gb: 5.3               # at the quantisation we run
  context: 131072
  capabilities: [tools, text]
  languages: [en]
  status: qualified          # candidate -> qualified -> default -> retired
  roles: [agent, summary_writer]
  results: results/qualification/granite4.1-8b.json
```

### 3.2 Qualification: the gate every model passes — **Built in part**

The same tests for every model, whatever its size or maker. A model earns a
role only by passing the tests for that role.

| Test | Role it qualifies | Status |
|---|---|---|
| Tool-chaining trap test (search → Word note, 9 runs) | agent | **Built** (`stage0/probe_agent_chaining.py`) |
| Summary grounding over all 12 corpus reports (invented numbers, invented breaches, verdict words) | summary writer | **Built** (the checker in `workbench/prose.py`; batch run) |
| Offline run with outbound traffic blocked | any | **Built** (`stage0/offline_phase.ps1`) |
| Image / scanned-document questions | vision | Proposed (R5) |
| Coding tasks verified by hidden tests in the sandbox | coder | Proposed (R4) |
| Speed and memory on the target hardware | all | Measured by hand today |

`qualify <model>` runs the suite, writes the results file and updates the
card. The router only ever picks from qualified models.

### 3.3 Hardware profiles — **Proposed**

One file per hardware class switches roles and optional stages on. **No code
changes between tiers.**

| | Tier A — 12 GB (today) | Tier B — 24–48 GB | Tier C — 80 GB+ (the PS's "120B class") |
|---|---|---|---|
| Models | 8–9B, one resident, swapped per task | 27–32B dense or 30B MoE (e.g. Sarvam 30B, Qwen 27B-class); a vision model resident alongside | 100B+ (Sarvam 105B, gpt-oss-120b) |
| Routing | Rules | Rules + model-assisted for unclear requests | Same |
| Extraction | One reading path | Second reader cross-checks critical cells | Same, faster |
| Knowledge graph | Recorded graph (§5.1) | + model-extracted graph over manuals and SOPs (§5.2) | + associative retrieval (§5.3) |
| Procedural graph | Enforced, fixed | Refiner proposes edits (§4.2) | Same |
| Summaries | Model with checker; fallback to code | Fewer fallbacks expected — **measured by the same checker** | Same |

### 3.4 What a bigger model changes, and what it doesn't

**Changes:** fewer code-written fallbacks and less review time; stages that
need a strong model can switch on (graph extraction, the procedural-graph
refiner, a second extraction reader); more work per stage.

**Does not change:** the rules are code; the minimum thickness comes from the
report, never the model; every number the model writes is checked; every
file is read back; the system never signs; outbound traffic stays blocked.

**How we say it to judges:** "We qualified models on a 12 GB workstation;
the best, an 8B model from IBM, passes 9 out of 9. Bigger hardware gives us
more candidates, like Sarvam 30B or 105B, and each has to pass the same
tests. Safety comes from the harness, so it holds on any model."

---

## 4. Procedural graphs: enforced today, self-evolving next

Adapted from **Procedural Graphs: Self-Evolving Execution Structures for LLM
Agents** (Yuxing Lu, Yicheng Chen, Shanchan Wu, Sercan Ö. Arık; arXiv
[2609.09153](https://arxiv.org/abs/2609.09153), 8 Sep 2026).

### 4.1 What runs today — **Built, demonstrated**

- The inspection workflow is a graph file, `workbench/graphs/inspection.yaml`:
  stages as nodes, the paper's relations (`PROVIDES_INPUT_FOR`, `LEADS_TO`,
  `TRIGGERS`, `CONVERGES_TO`) as edges, each carrying condition, guidance and
  pitfalls.
- The runner **enforces** it: only listed transitions, a retry budget per
  stage, a step budget per run.
- The guidance and pitfalls on a stage's edges are **inserted into the
  model's instructions** for that stage (the paper uses an extra model call
  for this; we insert them by template).
- A failed check follows its `when: fail` edge back to the stage that caused
  it: the **self-healing loop**. Out of budget, the job goes to a person.
- Every note carries the path taken; every step is in a hash-chained log.

### 4.2 Self-evolution — **Proposed**, following the paper

The paper's loop: a refiner model compares failed and successful runs,
proposes edits to the graph, and **commits an edit only if a held-out
validation set scores the same or better**; rejected edits are kept so they
are not proposed again. Ours adds one gate:

1. Every run's trace is already logged (we have them).
2. The refiner proposes an edit, e.g. a new pitfall on an edge.
3. The edit is scored on the validation set: our 12 corpus reports plus the
   trap tests.
4. **An engineer approves it** (Management of Change, like any revision).
5. The graph file is versioned; rejected edits are recorded.

A real example from 2026-09-11: granite invented breaches when it had to
compare readings itself. The fix was to hand it the rules' status for each
reading ("above minimum" or "BELOW MINIMUM, rule THK-01"). We made that edit
by hand after reading the failed runs; it is exactly the kind of edit the
refiner would propose, and exactly the kind the validation set can score.

---

## 5. Knowledge graph: recorded first, inferred later

### Why not "GraphRAG everything"

- **GraphRAG-Bench** (Xiang et al., arXiv
  [2506.05690](https://arxiv.org/abs/2506.05690), revised Feb 2026) reports that
  "GraphRAG frequently underperforms vanilla RAG on many real-world tasks";
  graphs help in specific situations, such as multi-step reasoning.
- **LightRAG** (MIT) says graph extraction needs a strong model — its README
  calls Qwen3-30B-A3B "a reasonable minimum" for local use. That is Tier B, not
  our 12 GB bench.
- A model-built graph can **invent relationships**. In a workflow where every
  number must trace to a source, an invented link is a safety problem.

So the graph comes in three layers, and the pitch is honest about which exist.

### 5.1 Recorded graph — **Proposed, buildable now on 12 GB**

Built by code from the document registry and the evidence records, not by a
model:

```
Equipment --HAS_REPORT--> Report --HAS_FINDING--> Finding --CITES--> Clause --IN--> Standard (revision)
                            |                                                          |
                            +--HAS_READING--> Reading (CML) --TRIGGERED--> Rule        +--SUPERSEDES--> older revision
Approval note --DERIVED_FROM--> Evidence record --FROM--> Page image
```

It answers exact multi-step questions ("which equipment inspected under
OISD-STD-116 had readings below minimum?") with every edge traceable, and the
frontend can draw it. Storage: SQLite plus NetworkX to start.

### 5.2 Extracted graph — **Proposed, Tier B**

[LightRAG](https://github.com/HKUDS/LightRAG) (Guo et al., arXiv
[2410.05779](https://arxiv.org/abs/2410.05779); MIT; runs with Ollama; supports
incremental updates, deletion and citations) over manuals, SOPs and
correspondence. Extracted edges are labelled **inferred**, shown differently,
and never feed a rule or a safety decision without review.

### 5.3 Associative retrieval — **Proposed, Tier B/C**

[HippoRAG 2](https://arxiv.org/abs/2502.14802) (Gutiérrez et al., ICML 2025)
reports "a 7% improvement in associative memory tasks over the
state-of-the-art embedding model" — useful for questions across years of
reports ("has this failure pattern appeared on similar equipment before?").

### 5.4 Where it sits in lookup

Exact IDs → catalogue → **recorded graph** (relationship questions) →
sections → vector search → inferred graph (Tier B, labelled).

---

## 6. The team's guidelines (Ritesh, "counter features", 11 Sep) and where each stands

| Guideline | Status | Where / next step |
|---|---|---|
| Use code for fixed steps and AI for understanding | **Built** | Rules engine, template filling and read-back are code; the model writes one paragraph |
| Let multiple agents share one model | **Design** | Roles map to models in the registry (§3.1); several roles can name the same model with different instructions, so no extra loading. Only a role that needs a different capability (vision, code) swaps model |
| Try Granite as our starting text model | **Built**, test widening | Granite writes the summaries; 9/9 on the trap test and 12/12 reports. Next: unseen documents (below). AnythingLLM's own chat default is still llama3.1:8b — switch it |
| Check every number, unit and decision | **Built** | The checker confirms every number is in the evidence, that a number next to "minimum" is a minimum and next to "current/measured" is a measured value, that units are mm, that severity counts match, and that any "below minimum" claim names a CML the rules flagged |
| Fill important report fields directly from verified data | **Built** | Tables, thickness status and severity counts come from code; the model is handed the rules' decisions instead of re-deriving them |
| Read each document once and reuse the result | **Built in part** | Every stage's output is saved in `runs/<job>/`. Next: key the evidence by the source file's SHA-256 so any agent or later run reuses it |
| Recheck only unclear cells | **Design** | ARCHITECTURE §7.1 selective re-reading; needs cell positions from extraction (stage 3) |
| Search exact IDs before searching by meaning | **Design** | ARCHITECTURE §6.2 lookup order: exact IDs → catalogue → sections → vector |
| Keep AnythingLLM for chat and search | **Decided** | Stage 0 verdict |
| Connect the dashboard to real activity | **Next** | The data exists: `logs/workbench_runs.jsonl` (every stage), `logs/web_access_tool_calls.jsonl` (every web call), both hash-chained. Needs a small local API for the frontend |
| Bundle everything locally and test without internet | **Gap found** | `frontend/index.html` line 7 loads `https://cdn.tailwindcss.com`. Offline, the page loses all styling, and the network monitor would show it as an external call. Fix: build the CSS once with Tailwind's standalone CLI (no Node needed) and link the local file, or at least serve the script from `frontend/vendor/` |
| Test documents the system has not seen before | **Next** | All 12 corpus reports come from one generator and one layout. Needs other layouts and the heavy scans once extraction exists |
| Measure time to a correct report | **Next** | Runs record per-stage seconds; add the reviewer's correction time when the review screen exists (ARCHITECTURE §10 "review minutes") |
| Send uncertain readings for human review | **Built in part** | Missing values give NEEDS REVIEW (rule EVD-01); the image crop needs cell positions from extraction |

---

## 7. Honest limits to state if asked

- Extraction from the scan is not built yet; the note says so in amber in its
  verification record (the evidence is a ground-truth stand-in).
- The rule set is a demonstration set, labelled as such in every note.
- The summary checker reads numbers written as digits. A count written in
  words slips through: for insp_1006 granite wrote "three major and one
  critical findings" where the report has two Major and one Critical.
  Counts should come from code, like the thickness status does.
- Sarvam 30B and Sarvam-M were downloaded but too slow on 12 GB to finish the
  trap test; they are Tier B candidates.
- Self-evolution, the model registry, the extracted graph and associative
  retrieval are proposals with published evidence, not measured by us.
