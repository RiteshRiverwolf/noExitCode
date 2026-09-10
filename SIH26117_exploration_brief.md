# SIH26117 — Exploration & Benchmarking Brief for Claude Code

## Context

We're building a **sovereign, air-gapped, agentic AI workbench** for MRPL (Mangalore Refinery and Petrochemicals Limited) — SIH 2026 problem statement 26117, doubling as a B.Tech final-year project. Full requirement text and architecture rationale live in `docs/PS26117.md` and `docs/architecture_assessment.md` (paste in the research report if not present).

Core requirements the system must eventually satisfy:
- 100% on-premise, zero external network calls, provable via logs/network monitor
- Multiple open-weight models, auto-selected by task type (coding / summarization / multimodal), swappable without redesign
- True agentic behavior: multi-step planning, tool use (file r/w, sandboxed code exec, spreadsheet, internal doc search), iteration
- Multimodal input: scanned PDFs, handwritten notes, engineering drawings/photos — OCR + vision
- Real deliverables as output: Word/PPT/Excel files, working code, calculations with steps — not just chat text
- Grounded in an internal knowledge base (SOPs, manuals, correspondence)
- Demo on a single mid-range-GPU workstation (assume 24GB VRAM unless told otherwise)

**We are not committing to a single stack yet.** This brief exists to systematically test candidate libraries/techniques for each subsystem, measure them against real criteria, and let the evidence pick the winner — not hype, not whichever one we read about first. Time is not a constraint for this phase; thoroughness is the priority.

## How to work through this

1. Work subsystem by subsystem, in the order listed below (each is roughly independent).
2. For each subsystem, set up an isolated test environment (`uv venv` or similar per subsystem — don't let dependency conflicts between candidates block progress), install every candidate, and run the **same test cases** against all of them.
3. Log everything to `results/<subsystem>/` as you go — raw outputs, timing, VRAM usage, and your own qualitative notes. Don't just report a final verdict; keep the evidence.
4. At the end of each subsystem, write a short `results/<subsystem>/VERDICT.md`: a comparison table + a recommendation + what would change the recommendation (e.g., "if VRAM budget rises to 48GB, reconsider X").
5. Flag anything that contradicts what's in the prior research report (`docs/architecture_assessment.md`) — that report was compiled from secondary sources and needs empirical checking, not blind trust.
6. If a candidate fails to even install/run offline, don't skip it silently — log the failure and why. That's useful information too (e.g., "requires telemetry endpoint even in local mode" is a disqualifying finding worth recording).

Ask before installing anything that requires payment, an account, or a cloud API key — the point is sovereignty, so cloud-dependent tools should be flagged, not silently used for convenience during testing.

---

## Subsystem 1 — Agent Runtime / Orchestration Spine

**Candidates to test:**
- **LangGraph** (baseline — team's existing skill)
- **Hermes Agent** (`NousResearch/hermes-agent`) — pin a specific tagged release, disable all gateway adapters (Telegram/Slack/Discord/WhatsApp/Signal/SMS) and the autonomous skill-learning/GEPA loop before testing
- **DeepSeek Harness (dsh)** — pin a specific rc, point at a local OpenAI-compatible endpoint with no DeepSeek API key present
- **smolagents** (Hugging Face) — lightweight comparison point
- Optional if time allows: raw ReAct loop hand-rolled in Python, as a "what do we lose without a framework" control

**Test cases (run identically against every candidate):**
1. A 5-step task requiring file read → tool call → reasoning → file write, with one intentionally-failing tool call the agent must recover from (tests error recovery / retry).
2. A task requiring the agent to call two different "models" (mock with two different local endpoints) based on task type — measure routing correctness.
3. A task that should exceed a normal context window, to see how/whether context compression or truncation is handled.
4. A subagent/delegation task — parent spawns a child agent with a restricted tool set, verify the child can't exceed its grant.
5. Force a network call attempt (point one tool at a real external URL) — verify what evidence each framework produces about the attempt (this doubles as your air-gap audit-trail test).

**What to measure per candidate:**
- Setup friction (time to first successful run, offline)
- Does it run fully offline against a local model with zero telemetry — verify with `tcpdump`/`OpenSnitch`, don't take documentation's word for it
- Quality of the audit/session log (can you reconstruct exactly what happened from it after the fact?)
- Error recovery behavior on the failing-tool-call test
- Iteration/budget control — does it loop forever, get stuck, or cleanly stop?
- Language/dependency footprint (Python vs Node, install size, dependency conflicts with the rest of the stack)
- License

---

## Subsystem 2 — Local Model Serving

**Candidates to test:**
- **vLLM**
- **llama.cpp** (server mode)
- **Ollama**
- Optional: **TGI (Text Generation Inference)**

**Test cases:**
1. Serve a ~30B-class text model (Q4 quantization) and a ~8B vision-language model. Measure cold-start time, VRAM footprint, tokens/sec at a realistic context length.
2. Hot-swap between two models on one GPU — measure swap latency. This matters directly for the "automatic model selection" requirement.
3. Concurrent requests — does the server handle 2+ simultaneous sessions without falling over (relevant if MRPL ever goes multi-user)?
4. Confirm OpenAI-compatible endpoint actually works cleanly with whichever agent runtime wins Subsystem 1 (no silent format mismatches).
5. Vision input: send a scanned document image, verify the server correctly passes it through to a VLM (this has reportedly been flaky in some Ollama + Qwen-VL combos — verify directly rather than trusting that report).

**What to measure:** VRAM usage per model at rest and under load, tokens/sec, swap latency, ease of running fully offline (no model-hub phone-home on startup), and how painful multi-model config actually is in practice.

---

## Subsystem 3 — Vision / OCR for Scanned Documents & Handwriting

**Candidates to test:**
- **PaddleOCR-VL**
- **Surya** (note: check license terms — flagged as possibly GPL/Rail-M restricted, confirm before committing)
- **docling** (PDF → structured text/tables)
- **TrOCR** (base and large) — printed text baseline
- A general VLM (whichever vision model wins Subsystem 2) used directly for OCR-via-prompting, as a comparison point

**Test cases:**
1. A clean scanned printed document (e.g., a generated PDF page) — baseline accuracy check.
2. A real or realistic handwritten form/log sheet — this is the hard case; measure character error rate (CER) if you can build/find a small labeled sample, otherwise qualitative accuracy.
3. A table-heavy scanned document — does structure survive extraction, or does it collapse into unstructured text?
4. Timing per page/image — this affects whether OCR can run inline in an agent's tool-call loop or needs to be an async/background step.

**What to measure:** accuracy (CER/WER if labelable), speed, VRAM/CPU footprint, license, and whether output format is directly usable downstream (structured JSON vs raw text dump).

---

## Subsystem 4 — Retrieval / Knowledge Grounding

**Candidates to test:**
- **Neo4j** hybrid (vector index + graph traversal) — team's existing strength, baseline
- **LightRAG**
- Plain flat vector RAG (e.g., a simple FAISS/Chroma setup) as a control — to demonstrate concretely *why* hybrid retrieval beats flat RAG, not just assert it
- Optional: Microsoft **GraphRAG** if time allows, as a heavier comparison point

**Test cases:**
1. Build a small synthetic SOP/manual corpus (10-20 documents, some with genuine cross-references between them — e.g., a procedure that references an equipment spec) so relationship-based retrieval has something real to exploit.
2. Ask retrieval questions that (a) a flat vector search should answer fine, and (b) require multi-hop reasoning across documents (flat RAG should struggle, graph traversal should help) — this is your actual evidence for the hybrid-retrieval design decision.
3. Measure retrieval precision/recall on a small hand-labeled question set (even 20-30 questions is enough for a first signal).
4. Test incremental updates — add a new/revised document, verify you don't have to re-ingest everything from scratch.

**What to measure:** retrieval precision/recall by question type (single-hop vs multi-hop), latency, ingestion/update friction, and whether the graph structure is something the team can realistically build and maintain for the actual demo corpus in the time available.

---

## Subsystem 5 — Document Generation (Real Deliverables)

**Candidates to test:**
- **python-docx** + **docxtpl** (templating)
- **python-pptx**
- **openpyxl** (+ a LibreOffice headless recalculation step to validate formulas actually compute)
- Compare direct library calls vs wrapping them as MCP tools vs wrapping them as agent-native tool functions (Subsystem 1 framework's own tool interface)

**Test cases:**
1. Agent-driven generation of a Word approval note from a template, with dynamically inserted findings and a citation back to a specific SOP clause.
2. Agent-driven generation of an Excel calculation sheet with actual formulas (not hardcoded values) — verify with LibreOffice headless recalc that formulas evaluate correctly, not just that cells contain formula-looking strings.
3. A round-trip self-check: render the generated document to PDF/image and have a VLM verify it looks correct (catches silent formatting failures).

**What to measure:** reliability (does the agent successfully produce valid, openable Office files on the first attempt, or does it need multiple retries?), whether templating vs raw generation is more robust, and how well this integrates as a tool call in whichever agent runtime wins Subsystem 1.

---

## Subsystem 6 — Air-Gap / Sovereignty Verification

**Candidates to test:**
- **nftables** (default-drop egress + logging)
- **OpenSnitch** (per-process outbound firewall)
- **Linux network namespaces** (full isolation)
- **tcpdump/Wireshark** (passive capture as independent verification)

**Test cases:**
1. Run the full assembled stack (whatever wins Subsystems 1-5) inside a no-route network namespace — confirm it still functions using only local models/tools.
2. Deliberately try to make something call out (e.g., temporarily point one tool at a real URL) — confirm nftables/OpenSnitch actually catches and logs the attempt.
3. Produce a clean artifact bundle (firewall ruleset + egress log + packet capture) that would be convincing to a skeptical judge or an MRPL security reviewer.

**What to measure:** whether any component (model server, agent runtime, a Python package with an accidental phone-home default) attempts an external call you didn't expect — this is as much a discovery exercise as a benchmark.

---

## Final Output

Once all six subsystems have a `VERDICT.md`, write a top-level `results/RECOMMENDATION.md` that:
- Names the winning combination per subsystem, with one-line justification each
- Flags any two winners that don't actually integrate cleanly together (e.g., a runtime that only speaks Node-style tool schemas paired with a Python-only serving stack) so we catch integration mismatches before committing
- Lists the 2-3 riskiest findings from testing (things that surprised you, contradicted assumptions, or are likely to bite us later)
- Proposes the actual first end-to-end vertical slice to build next, based on what testing showed actually works — not what the earlier research report assumed would work

Don't optimize for matching what the prior research report predicted. The whole point of this exercise is to find out where reality disagrees with it.
