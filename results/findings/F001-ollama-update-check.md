# F001 — Ollama contacts GitHub on startup, by default

**Severity:** Medium — sovereignty-relevant, trivially fixable
**Found:** 2026-09-04, incidentally, while probing the environment
**Relevant to:** Subsystem 2 (serving), Subsystem 6 (air-gap)

## What happened

Running `ollama list` on a machine with no Ollama server running caused the
client to start one. Its own startup log:

```
level=INFO source=updater.go:355 msg="beginning update checker" interval=1h0m0s
level=INFO source=updater.go:133 msg="New update available at
  https://github.com/ollama/ollama/releases/download/v0.33.3/OllamaSetup.exe"
```

Ollama 0.30.3 reached `github.com` within ~4 seconds of process start, with no
user action, and scheduled itself to repeat **every hour**.

## Why it matters

The core requirement is "100% on-premise, zero external network calls, provable
via logs/network monitor". A model server that beacons hourly to GitHub fails
that on its own, regardless of whether any inference data leaves. On an
air-gapped MRPL network the call fails, but the *attempt* still appears in
egress logs — and a security reviewer looking at a firewall log full of hourly
denied connections to github.com is going to ask why.

This is a discovery worth generalising: the brief's Subsystem 6 asks whether
"a Python package with an accidental phone-home default" attempts an unexpected
call. Here the phone-home was in the *model server*, found before Subsystem 6
started, by reading a log we happened to have on screen. Every component in the
final stack needs this same check.

## Mitigation

Set `OLLAMA_NOPRUNE`/updater env or, per Ollama docs, the update check is
disabled by running the server directly (`ollama serve`) rather than via the
desktop app wrapper — the checker lives in the Windows app shell
(`app_windows.go`), not the server binary. **To be verified empirically in
Subsystem 2, not trusted from this note.**

Air-gap does not depend on this fix; default-drop egress catches it either way.
The point is to make the egress log clean and explainable.

## Status

- [ ] Verify `ollama serve` alone does not contact GitHub (Subsystem 2)
- [ ] Confirm under packet capture, not just by reading Ollama's own log (Subsystem 6)
