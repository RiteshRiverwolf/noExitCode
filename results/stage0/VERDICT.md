# Stage 0 verdict — AnythingLLM integration test

**Date:** 2026-09-11
**Question:** can AnythingLLM, driven entirely through its API, take a scanned
report and use our MCP tool to write a Word file, fully offline?

## Answer

**Yes, for the parts AnythingLLM will own in our design. No, for its
built-in agent writing reports.** We keep AnythingLLM as the base platform and
move on to stage 1.

## What works offline

Tested with all outbound traffic from the container blocked (window B2,
`run_offline_20260911-133214.json`):

| Check | Result |
|---|---|
| API key, workspace, agent model set through the API | ✅ |
| Scanned PNG uploaded and read by OCR (finds `R-2247`) | ✅ 6.9 s, with the language data pre-seeded |
| **Test A:** agent calls our MCP tool, Word file lands on the PC | ✅ 9.0 s; matches our tool log and file hash |
| **Test C:** document Q&A answers the trap question | ✅ "CML-03 … 12.32 mm … minimum 12.7 mm", source `insp_1002_p1.png` |
| No connections to the internet | ✅ Only 2 packets dropped in the whole task, both a reverse lookup of the Docker gateway address (`172.17.0.1`), not an internet host. Ollama and the MCP tool made no outside connections. |

The blocking itself was proven first (window A): `example.com` and `1.1.1.1`
were both blocked and appear in the dropped-packet capture, while Ollama and
the MCP tool stayed reachable.

## What doesn't work

**Test B: the built-in agent writes false approval notes.** In 3 clean runs
(online run 3, offline runs 1 and 2) llama3.1:8b skipped the document search
and wrote that "thickness readings meet minimum requirements". The report
says the opposite: CML-03 is 12.32 mm against a 12.7 mm minimum. The search
skill was available every time.

This supports the architecture as written: **the inspection workflow runs in
our own agent team, the numbers come from evidence records, and escalation is
decided by code.** It also tells us the report tool must take structured
fields, not free text (see "Next").

## Requirements for the sovereign build

| # | Requirement | Why |
|---|---|---|
| 1 | Pre-seed `eng.traineddata` in `storage/models/tesseract/` | Without it, the first scanned upload **crashes the container** ([F003](../findings/F003-anythingllm-outbound-dependencies.md)) |
| 2 | Pre-seed or patch out the context-window and pricing fetches | Startup calls to GitHub and models.dev; no switch exists (F003) |
| 3 | Disable the agent's web-scraping and web-browsing skills | On by default (F003) |
| 4 | Set `AUTH_TOKEN` (or multi-user mode) | The internal API is open without it |
| 5 | MCP servers allow the `host.docker.internal:*` Host header | Otherwise HTTP 421 from the MCP SDK |
| 6 | Run Ollama as `ollama serve` with `OLLAMA_NO_CLOUD=1` | Cloud features are on by default; the desktop app checks for updates (F001) |
| 7 | Give the container a fixed address for the host (`--add-host` or a user-defined network) | `host.docker.internal` only resolves through DNS here, which the network lock blocks |

## Not covered yet

- **Cold offline start:** the container was started online and then locked
  down. Whether the startup fetches fail gracefully on an offline boot is
  still to test.
- **The Windows host's own traffic:** captured only for the container; Ollama
  and the MCP tool were sampled once a second.
- **Throughput:** not measured.
- **The gateway reverse lookup:** harmless in itself, but we haven't found
  what triggers it.

## Next

1. Stage 1 (ARCHITECTURE §13): evidence-record schema, then PaddleOCR → rule →
   templated Word note.
2. Replace `create_word_document(title, body)` with a tool that fills the
   template from evidence records, so the model never types a measurement.
