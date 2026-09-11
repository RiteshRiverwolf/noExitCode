# F003 — AnythingLLM reaches out to the internet in four places; one of them crashes it offline

**Severity:** High — a fresh air-gapped install goes down on its first scanned upload
**Found:** 2026-09-10 to 2026-09-11, during stage 0
**Observed on:** `mintplexlabs/anythingllm@sha256:5fb4a84c…d7e0b7` (created 2026-09-09), Docker Desktop, Windows 11 Pro
**Relevant to:** network proof, installation, OCR, agent configuration
**Evidence:** `results/stage0/offline_summary.txt`, `results/stage0/pcap/*_dropped.pcap`,
`results/stage0/run_offline-nocache_20260911-133219.json`, `results/stage0/NOTES.md`

## What we observed

| # | What | Destination | When | Offline behaviour |
|---|---|---|---|---|
| 1 | OCR language data (`eng.traineddata`, 5 MB) | `cdn.jsdelivr.net` | First OCR of an image, if not cached | **Crashes the whole container** (tested twice) |
| 2 | Model context windows | `raw.githubusercontent.com` (BerriAI/litellm) | Startup, when the 3-day cache is stale | Not tested offline; source says it fails gracefully |
| 3 | Model pricing | `models.dev` | Startup, when the 3-day cache is stale | Not tested offline; source says it fails gracefully |
| 4 | Agent `web-scraping` and `web-browsing` skills | Any URL the model picks; with no provider configured, web search uses **You.com's keyless API, falling back to DuckDuckGo** | Attached to every agent run by default; **neither asks for approval** | Not triggered in our tests |

### 1. The OCR crash

With outbound traffic blocked and `storage/models/tesseract/eng.traineddata`
moved aside, uploading one scanned PNG:

- dropped the HTTP connection after 0.26 s (`RemoteDisconnected`);
- stopped the container (`exit=1`, `oom=false`, restart policy none);
- left this in the log:

```
[collector] info: [OCRLoader] Starting OCR of insp_1002_p1.png
Error: TypeError: fetch failed
    at Worker.<anonymous> (/app/collector/node_modules/tesseract.js/src/createWorker.js:217:15)
Node.js v18.20.8
```

The dropped-packet capture shows a DNS query for `cdn.jsdelivr.net` at that
moment. The error is thrown from a worker event and never caught, so the
collector process dies and takes the container with it.

With the file pre-seeded, the same upload works offline (window B2: OCR finds
`R-2247`, 6.9 s).

### Source check: no switches

- `collector/utils/OCRLoader/index.js` passes tesseract.js only `cachePath`
  (`STORAGE_DIR/models/tesseract`), never `langPath`, and reads no
  environment variable for it.
- `server/utils/AiProviders/modelMap/index.js:30` and
  `server/utils/helpers/modelPricing/index.js:70` read no environment variable
  except `NODE_ENV === "test"`, which is not a production setting.

## Why it matters

The problem statement needs a system that works with no network and can show
that it makes no external calls. Item 1 means an install that looks complete
fails on the first real document, and fails by crashing rather than with an
error message. Items 2–4 put denied attempts in the egress log that a
reviewer will ask about.

## Mitigation

1. **Ship `eng.traineddata` pre-seeded** in `storage/models/tesseract/`, and
   check it's there at install time. (We use PaddleOCR for the inspection
   workflow anyway; this covers AnythingLLM's own upload path.)
2. **Pre-seed the context-window and pricing caches** and refresh
   `.cached_at`, or patch the two URLs out of our pinned image. Decide once
   the cold-start test below is done.
3. **Disable the agent web skills** in the sovereign build.
4. Keep outbound blocking on regardless; it caught every attempt in our tests.

## Status

- [x] Offline crash reproduced twice, with packet capture (2026-09-11, 12:59 and 13:32)
- [x] Pre-seeded language data confirmed to fix it (window B2)
- [ ] Cold offline start: boot the container with egress already blocked and stale caches; confirm items 2–3 fail gracefully
- [ ] Find the setting that disables the web skills, and confirm it
- [ ] Consider reporting the uncaught tesseract.js error upstream
