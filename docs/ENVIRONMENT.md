# Test Bench — Ground Truth

Everything measured in `results/` was produced on this machine unless a file says
otherwise. Recorded 2026-09-04.

## Hardware

| | |
|---|---|
| GPU | NVIDIA GeForce RTX 4070, **12282 MiB (12GB) VRAM**, driver 610.88 |
| RAM | 31.7 GB |
| Disk | C: 124 GB free, D: 117 GB free |
| OS | Windows 11 Pro 10.0.26200 |

## Toolchain

| | |
|---|---|
| Python | 3.13.x (default), 3.12.4 also present |
| uv | 0.10.11 |
| CUDA toolkit | 13.0 (nvcc V13.0.88) |
| Docker | 29.4.0 |
| Node | 22.17.0 |
| git | 2.44.0 |
| WSL | `docker-desktop` distro only (stopped). No Ubuntu installed. |
| Ollama | 0.30.3 — models present: `llama3.1:8b`, `nomic-embed-text` |

## Deviations from the exploration brief

The brief was written against assumptions that do not hold here. These are
decisions of record, not oversights.

### 1. VRAM is 12GB — this is the baseline bench, not a design ceiling

The brief says "assume 24GB VRAM unless told otherwise". This box has 12GB.

**Decision: 12GB is the validation floor, not the target.** The architecture is
designed model-agnostic and hardware-tiered — the brief's own requirement is that
models be "swappable without redesign", so the model choice is *configuration*,
not architecture. We prove the system works end-to-end on 12GB; a deployment with
more VRAM runs strictly better models through the same routing spine with no code
change.

Concretely this means:

- No candidate is dropped from the inventory for being too big to run here.
  `docs/STACK_INVENTORY.md` tiers models A/B/C by VRAM class.
- Benchmarks measured on Tier A (12GB) models are reported as **baseline**
  numbers, and every `VERDICT.md` states what changes at 24GB and 48GB.
- Anything that *only* works because the model is small (e.g. a routing trick
  that a 7B needs but a 32B would not) gets flagged as a baseline artefact, so we
  don't bake a 12GB workaround into the permanent design.

### 2. Windows host, Linux deferred

Subsystems 1, 3, 4 and 5 run natively on Windows. Linux is required only for:

- **vLLM, TGI** (Subsystem 2) — no native Windows build
- **nftables, network namespaces, OpenSnitch** (Subsystem 6) — Linux kernel features
- FAISS-GPU (FAISS-CPU is fine on Windows)

WSL2 Ubuntu gets installed when Subsystem 2 reaches vLLM, not before.

**Open question for the team, before Subsystem 6:** what OS is MRPL's actual
deployment target? If it is a Linux server — likely, but unconfirmed — then an
air-gap proof produced on Windows demonstrates the wrong platform, and Subsystem
6 must run under WSL2 or a Linux box to be worth anything to a security
reviewer.

### 3. No prior research report

`docs/architecture_assessment.md` does not exist and is not forthcoming, so the
brief's step 5 ("flag anything that contradicts the prior research report") is
**dropped**; these results are the primary record, not a check on an earlier
one.

**Updated 2026-09-10:** the problem statement text itself was supplied by the
team on 2026-09-04 and is in [`PS26117.md`](PS26117.md). Requirements are read
from there (see [`PS_ANALYSIS.md`](PS_ANALYSIS.md)), not from the brief's
Context section.
