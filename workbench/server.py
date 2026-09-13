"""The local service behind the interface: runs missions and streams what the agents do.

    .venv\\Scripts\\python -m workbench.server              # http://127.0.0.1:<port in workbench/service.yaml>

Loopback only, and there is no option to change that: this service has no
authentication, and stage 0 found the same gap in AnythingLLM's internal API
(results/stage0/NOTES.md). Anything shown on screen is also on disk in the run
folder -- the service adds no facts of its own.

Missions run one at a time. They share the GPU, and every run appends to one
hash-chained audit log, which must have a single writer.

Endpoints
---------
GET  /                                   the interface (frontend/index.html)
GET  /api/health                         Ollama, Docker, sandbox image, OCR environment
GET  /api/corpus                         corpus reports, and which scans are already OCR'd
GET  /api/router                         the Router's decision for every task (display only, not logged)
GET  /api/network                        live connections held by the workbench's own processes
GET  /api/sandbox/self-test              code in the sandbox tries to get out; the result
POST /api/inspections                    start an inspection: JSON {doc_id, source, scan_quality,
                                         no_model, model, inject_fault}, or multipart with `files`
POST /api/code                           start a coding task: JSON {task_id, model}
GET  /api/demo                           the pitch demo's scenario (workbench/demo.yaml)
POST /api/demo                           run the pitch demo: every beat a real run, events streamed
GET  /api/code/tasks                     the coding tasks and their briefs
GET  /api/code/tasks/{id}/acceptance     the held-out tests -- shown to people, never to the model
GET  /api/jobs/{job}                     every event of a job so far
GET  /api/jobs/{job}/events              the same, live, as Server-Sent Events
GET  /api/files/{path}                   a file from runs/ or data/corpus/ (crops, notes, page images)

Events
------
Each SSE message is `data: {json}` with no event name, so EventSource.onmessage
receives all of them. Every event has `seq`, `ts` and `type`. An inspection
emits, in order:

    queued, started, run_start, stage_enter, stage, ... evidence, decision,
    route, summary, ... run_end, stream_end

`evidence` carries every reading and finding with its exact printed value (as
a string), page, box, OCR score and `crop_url`; `stage` carries node, agent,
attempt, status, note, seconds and next -- including a failed qa_check sending
work back to render_note. A coding task emits route, task, attempt_start,
attempt, ... code_result, stream_end. `error` is emitted if a job crashes.
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import ipaddress
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path

import anyio
import httpx
import yaml
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.routing import Route

from mcp_servers.audit import LOG_DIR, verify
from workbench import coder, coding_tasks, demo, pagesource, router, sandbox
from workbench.evidence import CORPUS
from workbench.run_inspection import JobConfig, run_job

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
UPLOADS = RUNS / "_uploads"
FRONTEND = ROOT / "frontend" / "index.html"
SERVED_ROOTS = (RUNS.resolve(), CORPUS.resolve())
HOST = "127.0.0.1"          # loopback only, by design -- not a setting (see the module docstring)

# Port, upload limits, jobs kept, watched processes: workbench/service.yaml.
SETTINGS = yaml.safe_load((Path(__file__).resolve().parent / "service.yaml").read_text(encoding="utf-8"))
PORT = SETTINGS["port"]
MAX_UPLOAD_BYTES = SETTINGS["max_upload_bytes"]
UPLOAD_SUFFIXES = set(SETTINGS["upload_suffixes"])
MAX_JOBS_KEPT = SETTINGS["max_jobs_kept"]
WATCHED_EXES = {p.lower() for p in SETTINGS["watched_processes"]}


# --- replies ---------------------------------------------------------------------

def _clean(v):
    """JSON-safe: no NaN or infinity (the Router ranks a missing figure as +inf)."""
    if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
        return None
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


def reply(data, status: int = 200) -> JSONResponse:
    return JSONResponse(_clean(data), status_code=status)


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", Path(name).name)[:120] or "upload"


def _safe_id(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", text)[:60] or "document"


# --- jobs --------------------------------------------------------------------------

class Job:
    """One mission: its events, kept in order, readable while it runs."""

    def __init__(self, kind: str, label: str):
        self.id = uuid.uuid4().hex[:12]
        self.kind, self.label = kind, label
        self.created = time.time()
        self.events: list[dict] = []
        self.done = False
        self._lock = threading.Lock()

    def emit(self, event: dict) -> None:
        with self._lock:
            self.events.append({"seq": len(self.events), "ts": round(time.time(), 3), **event})

    def finish(self) -> None:
        with self._lock:
            self.done = True

    def since(self, cursor: int) -> tuple[list[dict], bool]:
        with self._lock:
            return list(self.events[cursor:]), self.done


JOBS: dict[str, Job] = {}
_JOBS_LOCK = threading.Lock()
_WORK_LOCK = threading.Lock()          # one mission at a time: one GPU, one audit-log writer


def _start(job: Job, work) -> None:
    def target() -> None:
        job.emit({"type": "queued"})
        with _WORK_LOCK:
            job.emit({"type": "started"})
            try:
                work(job)
            except Exception as e:  # reported to the viewer; the service keeps running
                job.emit({"type": "error", "message": f"{type(e).__name__}: {e}"})
            finally:
                job.finish()

    with _JOBS_LOCK:
        JOBS[job.id] = job
        finished = sorted((j for j in JOBS.values() if j.done), key=lambda j: j.created)
        for old in finished[: max(0, len(JOBS) - MAX_JOBS_KEPT)]:
            JOBS.pop(old.id, None)
    threading.Thread(target=target, daemon=True, name=f"job-{job.id}").start()


def _with_urls(event: dict) -> dict:
    """Turn repo-relative paths into URLs this service will serve."""
    def url(p):
        return f"/api/files/{p}" if p else None
    if event.get("type") == "evidence":
        for item in event.get("readings", []) + event.get("findings", []):
            item["crop_url"] = url(item.get("crop"))
        for page in event.get("pages", []):
            page["image_url"] = url(page.get("image"))
    elif event.get("type") == "run_end":
        event["note_url"] = url(event.get("note"))
    return event


# --- missions ------------------------------------------------------------------------

def _registry_models() -> set[str]:
    return set(router.load_registry()[0]["models"])


async def start_inspection(request: Request) -> JSONResponse:
    index = {e["doc_id"]: e for e in json.loads((CORPUS / "index.json").read_text(encoding="utf-8"))}
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        form = await request.form(max_files=20, max_fields=20)
        uploads = [f for f in form.getlist("files") if hasattr(f, "filename")]
        if not uploads:
            return reply({"error": "put the document in the 'files' field"}, 400)
        folder = UPLOADS / uuid.uuid4().hex[:12]
        folder.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []
        for up in uploads:
            name = _safe_name(up.filename or "upload")
            if Path(name).suffix.lower() not in UPLOAD_SUFFIXES:
                return reply({"error": f"{name}: send a PDF or page images"}, 400)
            data = await up.read()
            if len(data) > MAX_UPLOAD_BYTES:
                return reply({"error": f"{name}: larger than 50 MB"}, 413)
            (folder / name).write_bytes(data)
            saved.append(folder / name)
        if any(p.suffix.lower() == ".pdf" for p in saved) and len(saved) > 1:
            return reply({"error": "send one PDF, or the page images of one report"}, 400)
        model = str(form.get("model") or "") or None
        fault = str(form.get("inject_fault") or "") or None
        cfg = JobConfig(doc_id=_safe_id(str(form.get("doc_id") or saved[0].stem)), image=saved,
                        no_model=_truthy(form.get("no_model")), model=model, inject_fault=fault)
    else:
        try:
            body = await request.json()
        except Exception:
            return reply({"error": "send JSON, or multipart with files"}, 400)
        doc_id = body.get("doc_id")
        if doc_id not in index:
            return reply({"error": f"unknown report {doc_id!r}", "known": sorted(index)}, 400)
        source = body.get("source", "scan")
        quality = body.get("scan_quality", "medium")
        if source not in ("scan", "pdf", "stand-in") or quality not in ("clean", "light", "medium", "heavy"):
            return reply({"error": "source is scan|pdf|stand-in; scan_quality is clean|light|medium|heavy"}, 400)
        model, fault = body.get("model") or None, body.get("inject_fault") or None
        cfg = JobConfig(doc_id=doc_id, source=source, scan_quality=quality,
                        no_model=bool(body.get("no_model")), model=model, inject_fault=fault)

    if cfg.model and cfg.model not in _registry_models():
        return reply({"error": f"{cfg.model!r} is not in the model registry"}, 400)
    if cfg.inject_fault not in (None, "render"):
        return reply({"error": "inject_fault is 'render' or absent"}, 400)

    job = Job("inspection", cfg.doc_id)

    def work(job: Job) -> None:
        pages = [Path(p) for p in cfg.image or []]
        if cfg.source == "scan" and not cfg.image and cfg.doc_id in index:
            pages = [CORPUS / p for p in index[cfg.doc_id]["scans"][cfg.scan_quality]]
        images = [p for p in pages if p.suffix.lower() != ".pdf"]
        fresh = [p for p in images
                 if not (pagesource.OCR_CACHE / f"{pagesource.sha256_file(p)}.json").exists()]
        if fresh:
            job.emit({"type": "notice", "message":
                      f"{len(fresh)} page image(s) not read before: OCR on the CPU takes about "
                      f"80-90 seconds a page"})
        run_job(cfg, emit=lambda e: job.emit(_with_urls(e)))

    _start(job, work)
    return reply({"job": job.id, "events": f"/api/jobs/{job.id}/events"})


async def start_code(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return reply({"error": "send JSON {task_id, model}"}, 400)
    task_id = body.get("task_id")
    if task_id not in coding_tasks.TASKS:
        return reply({"error": f"unknown task {task_id!r}", "known": sorted(coding_tasks.TASKS)}, 400)
    model = body.get("model") or None
    if model and model not in _registry_models():
        return reply({"error": f"{model!r} is not in the model registry"}, 400)

    job = Job("code", task_id)

    def work(job: Job) -> None:
        task = coding_tasks.TASKS[task_id]
        if model:
            chosen, why = model, "set by hand (Router overridden)"
        else:
            decision = router.route("code", {"coding_task": task_id, "via": "server"})
            chosen, why = decision.chosen, decision.reason
        job.emit({"type": "route", "task": "code", "chosen": chosen, "decision": why})
        if chosen is None:
            job.emit({"type": "code_result", "accepted": False, "summary": "no model is qualified to write code"})
            return
        # The service never falls back to running code unsandboxed.
        if not (sandbox.docker_available() and sandbox.image_present()):
            job.emit({"type": "error", "message": "the sandbox is not available: Docker is not "
                                                  "running or its image is missing"})
            return
        job.emit({"type": "task", "task_id": task.task_id, "brief": task.brief,
                  "max_attempts": task.max_attempts})
        result = coder.solve(task, chosen, emit=job.emit)
        record = asdict(result)
        record.pop("attempts")
        job.emit({"type": "code_result", **record, "attempts": len(result.attempts),
                  "summary": result.summary()})

    _start(job, work)
    return reply({"job": job.id, "events": f"/api/jobs/{job.id}/events"})


async def demo_endpoint(request: Request) -> JSONResponse:
    """GET: the scenario. POST: run it -- every beat a real run, as one job (workbench/demo.py)."""
    if request.method == "GET":
        return reply(demo.scenario())
    job = Job("demo", demo.scenario()["title"])
    _start(job, lambda job: demo.run(emit=lambda e: job.emit(_with_urls(e))))
    return reply({"job": job.id, "events": f"/api/jobs/{job.id}/events"})


async def job_snapshot(request: Request) -> JSONResponse:
    job = JOBS.get(request.path_params["job"])
    if job is None:
        return reply({"error": "no such job"}, 404)
    events, done = job.since(0)
    return reply({"job": job.id, "kind": job.kind, "label": job.label, "done": done, "events": events})


async def job_events(request: Request):
    job = JOBS.get(request.path_params["job"])
    if job is None:
        return reply({"error": "no such job"}, 404)
    try:
        cursor = max(0, int(request.query_params.get("from", "0")))
    except ValueError:
        cursor = 0

    async def stream():
        nonlocal cursor
        yield ": connected\n\n"
        while True:
            if await request.is_disconnected():
                return
            new, done = job.since(cursor)
            for event in new:
                yield f"id: {event['seq']}\ndata: {json.dumps(_clean(event), ensure_ascii=False)}\n\n"
            cursor += len(new)
            if done and not new:
                yield 'data: {"type": "stream_end"}\n\n'
                return
            await asyncio.sleep(0.2)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def files(request: Request):
    target = (ROOT / request.path_params["path"]).resolve()
    if not any(target.is_relative_to(r) for r in SERVED_ROOTS) or not target.is_file():
        return reply({"error": "not found"}, 404)
    return FileResponse(target)


# --- the network panel ---------------------------------------------------------------

def _processes() -> dict[int, tuple[int, str]]:
    """pid -> (parent pid, executable), from a Windows process snapshot (stdlib only)."""
    if sys.platform != "win32":
        return {}
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    snap = k32.CreateToolhelp32Snapshot(0x00000002, 0)        # TH32CS_SNAPPROCESS
    if snap in (None, ctypes.c_void_p(-1).value):
        return {}
    procs: dict[int, tuple[int, str]] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            procs[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.szExeFile)
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return procs


def _netstat() -> list[dict]:
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=30).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0] != "TCP" or not parts[4].isdigit():
            continue
        _, local, foreign, state, pid = parts[:5]
        host = foreign.rpartition(":")[0].strip("[]").split("%")[0]
        rows.append({"local": local, "foreign": foreign, "host": host, "state": state, "pid": int(pid)})
    return rows


def network_snapshot() -> dict:
    """Open TCP connections held by the workbench's own processes, right now.

    Watched: this service and every process it started (the OCR worker, the
    docker client), plus Ollama and llama-server and their runners. Each
    connection is sorted by where it goes: loopback, the local network, or
    anywhere else -- "external". Other programs on the same computer (a
    browser, an editor) are deliberately not counted: they are not the
    workbench, and on a sealed machine they would not be there.

    Limits, stated in the reply: a snapshot of open connections is not a packet
    capture -- a connection opened and closed between two snapshots is not
    seen. The packet-capture proof is the stage-0 test.
    """
    procs = _processes()
    watched = {os.getpid()} | {pid for pid, (_, exe) in procs.items() if exe.lower() in WATCHED_EXES}
    grew = True
    while grew:                                      # add children, grandchildren ...
        grew = False
        for pid, (parent, _) in procs.items():
            if parent in watched and pid not in watched:
                watched.add(pid)
                grew = True

    buckets: dict[str, list[dict]] = {"loopback": [], "local_network": [], "external": []}
    for row in _netstat():
        if row["pid"] not in watched or row["state"] == "LISTENING":
            continue
        try:
            ip = ipaddress.ip_address(row["host"])
        except ValueError:
            continue
        if ip.is_unspecified:
            continue
        kind = ("loopback" if ip.is_loopback
                else "local_network" if (ip.is_private or ip.is_link_local) else "external")
        buckets[kind].append({**row, "process": procs.get(row["pid"], (0, "?"))[1]})

    logs = []
    for path in sorted(LOG_DIR.glob("*.jsonl")):
        try:
            ok, n, message = verify(path)
        except Exception as e:
            ok, n, message = False, 0, f"could not verify: {type(e).__name__}"
        logs.append({"log": path.name, "entries": n, "chain_intact": ok, "message": message})

    return {
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "method": "netstat -ano, filtered to the workbench's own processes",
        "watched_processes": sorted({procs.get(p, (0, "?"))[1] for p in watched if p in procs}),
        "external_count": len(buckets["external"]),
        "external": buckets["external"],
        "local_network_count": len(buckets["local_network"]),
        "local_network": buckets["local_network"],
        "loopback_count": len(buckets["loopback"]),
        "audit_logs": logs,
        "limits": "a snapshot of open connections, not a packet capture: a connection opened and "
                  "closed between two snapshots is not seen. See results/stage0 for the capture.",
    }


# --- read-only views --------------------------------------------------------------

def health() -> dict:
    registry, sha = router.load_registry()
    try:
        ollama = httpx.get(f"{registry['servers']['ollama']}/api/tags", timeout=3).status_code == 200
    except Exception:
        ollama = False
    docker = sandbox.docker_available()
    running = router.running_models(registry)
    # "available": on the machine for Ollama (loaded on first use), answering for llama-server
    return {"ollama": ollama, "models_available": sorted(m for m, up in running.items() if up),
            "docker": docker, "sandbox_image": docker and sandbox.image_present(),
            "ocr_environment": pagesource.OCR_PYTHON.exists(), "registry_sha256": sha}


def corpus() -> list[dict]:
    out = []
    for entry in json.loads((CORPUS / "index.json").read_text(encoding="utf-8")):
        scans = {}
        for quality, pages in entry["scans"].items():
            cached = all((pagesource.OCR_CACHE / f"{pagesource.sha256_file(CORPUS / p)}.json").exists()
                         for p in pages)
            scans[quality] = {"pages": len(pages), "ocr_cached": cached}
        out.append({"doc_id": entry["doc_id"], "equipment_tag": entry["equipment_tag"],
                    "pdf": (CORPUS / "pdf" / f"{entry['doc_id']}.pdf").exists(), "scans": scans})
    return out


def router_view() -> dict:
    registry, sha = router.load_registry()
    running = router.running_models(registry)
    return {"registry_sha256": sha, "logged": False,
            "note": "display only; decisions taken for real work are written to the router log",
            "tasks": {t: asdict(router.choose(t, registry, sha, running)) for t in registry["tasks"]}}


def sandbox_self_test() -> dict:
    if not sandbox.docker_available():
        return {"sealed": False, "reason": "Docker is not running"}
    if not sandbox.image_present():
        return {"sealed": False, "reason": f"the image {sandbox.IMAGE} is not on this machine"}
    net = sandbox.run({"main.py": sandbox.NETWORK_PROBE}, timeout=30)
    fs = sandbox.run({"main.py": sandbox.WRITE_PROBE}, timeout=20, collect=("proof.txt",))
    cpu = sandbox.run({"main.py": "while True:\n    pass\n"}, timeout=5)
    try:
        probes = json.loads(net.stdout[: net.stdout.rfind("}") + 1])
    except ValueError:
        probes = {"output": net.stdout.strip() or net.stderr.strip()}
    sealed = "SEALED" in net.stdout and not fs.stdout.startswith("WROTE") and cpu.timed_out
    return {"sealed": sealed, "image": sandbox.IMAGE, "isolation": net.isolation,
            "network": probes, "filesystem": fs.stdout.strip().splitlines(),
            "runaway_code": {"killed_at_time_limit": cpu.timed_out, "seconds": cpu.seconds}}


async def api_health(request: Request) -> JSONResponse:
    return reply(await anyio.to_thread.run_sync(health))


async def api_corpus(request: Request) -> JSONResponse:
    return reply(await anyio.to_thread.run_sync(corpus))


async def api_router(request: Request) -> JSONResponse:
    return reply(await anyio.to_thread.run_sync(router_view))


async def api_network(request: Request) -> JSONResponse:
    return reply(await anyio.to_thread.run_sync(network_snapshot))


async def api_sandbox(request: Request) -> JSONResponse:
    return reply(await anyio.to_thread.run_sync(sandbox_self_test))


async def code_tasks(request: Request) -> JSONResponse:
    return reply([{"task_id": t.task_id, "brief": t.brief, "max_attempts": t.max_attempts}
                  for t in coding_tasks.TASKS.values()])


async def code_acceptance(request: Request) -> JSONResponse:
    task = coding_tasks.TASKS.get(request.path_params["task_id"])
    if task is None:
        return reply({"error": "no such task"}, 404)
    return reply({"task_id": task.task_id, "acceptance_test": task.acceptance,
                  "note": "shown to people; the model never sees this, only its failure messages"})


async def index_page(request: Request):
    if not FRONTEND.exists():
        return reply({"error": "frontend/index.html not found"}, 404)
    return FileResponse(FRONTEND)


app = Starlette(routes=[
    Route("/", index_page),
    Route("/api/health", api_health),
    Route("/api/corpus", api_corpus),
    Route("/api/router", api_router),
    Route("/api/network", api_network),
    Route("/api/sandbox/self-test", api_sandbox),
    Route("/api/inspections", start_inspection, methods=["POST"]),
    Route("/api/code/tasks", code_tasks),
    Route("/api/code/tasks/{task_id}/acceptance", code_acceptance),
    Route("/api/code", start_code, methods=["POST"]),
    Route("/api/demo", demo_endpoint, methods=["GET", "POST"]),
    Route("/api/jobs/{job}", job_snapshot),
    Route("/api/jobs/{job}/events", job_events),
    Route("/api/files/{path:path}", files),
])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()
    import uvicorn
    print(f"workbench service: http://{HOST}:{args.port}  (loopback only; no authentication)",
          flush=True)
    uvicorn.run(app, host=HOST, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
