# F001 — Ollama's Windows desktop app runs an update check at startup, by default

**Severity:** Medium — sovereignty-relevant, easily avoided
**Found:** 2026-09-04, incidentally, while probing the environment
**Corrected:** 2026-09-10 — see "Correction" below
**Observed on:** Ollama 0.30.3, Windows 11 Pro
**Relevant to:** model serving, network proof

## What we observed

Running `ollama list` with no server running caused the Windows desktop app to
start (`source=app_windows.go`). Its log:

```
17:26:21.673 level=INFO source=app_windows.go:282 msg="starting Ollama" version=0.30.3
17:26:24.682 level=INFO source=updater.go:355 msg="beginning update checker" interval=1h0m0s
17:26:25.991 level=INFO source=updater.go:133 msg="New update available at
  https://github.com/ollama/ollama/releases/download/v0.33.3/OllamaSetup.exe"
```

Established by this log:

- An update check ran automatically and reported a result **about 4.3 seconds**
  after the app started, with no user action.
- It is scheduled to repeat **every hour**.
- It is the **Windows desktop app** doing this (`app_windows.go`, `updater.go`).

## Correction

Revision 1 of this finding, and the first team brief, said Ollama "contacted
GitHub". **The log does not show that.** The GitHub address is the *download
link the check returned*, not necessarily the server the check contacted.

Ritesh's review reports that the desktop updater's source defines a 3-second
initial delay, an hourly interval and an **ollama.com** update URL. That is
consistent with our timing (a 3-second delay plus a network round trip). We
have not confirmed the destination ourselves.

Also not established: whether `ollama serve` on its own, or Ollama on Linux,
does this. Our observation covers only the Windows desktop app, version 0.30.3.

## Why it matters

The PS asks us to show that no external calls are made. A component that
attempts an outbound connection hourly fills the egress log with denied
attempts that a security reviewer will ask about, even though outbound blocking
stops them. The same check is needed for every component in the stack —
including AnythingLLM, which documents its own telemetry controls.

## Mitigation

Use llama.cpp as the first-choice server (ARCHITECTURE §5.2), or run the Ollama
server without the desktop app. Outbound blocking catches the attempt either
way; the point is a clean, explainable log.

## Status

- [ ] Confirm the check's destination under packet capture, with version recorded
- [ ] Confirm whether `ollama serve` alone makes any outbound attempt
- [ ] Audit AnythingLLM the same way with `DISABLE_TELEMETRY=true`
