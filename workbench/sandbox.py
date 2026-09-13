"""Run untrusted code with no network and no access to this machine.

    .venv\\Scripts\\python -m workbench.sandbox --self-test

The Coder agent writes code; this is where it runs. Two properties matter, and
both are enforced by the container runtime rather than by our good intentions:

  * **No network.** `--network none` gives the container no interface at all --
    not a blocked one, an absent one. `--self-test` proves it by running code
    that tries to reach the outside and showing the failure. That is the same
    claim R6 makes about the whole workbench, and here it can be demonstrated
    in five seconds rather than argued.
  * **No access to the host.** A read-only root filesystem, one writable
    working directory that holds only the files we put there, a memory cap, a
    process cap and a wall-clock limit. Code that loops forever is killed;
    code that fills memory is killed.

If Docker is not available the runner falls back to a plain subprocess and
**says so in `isolation`**, which every caller records. That fallback is for
development convenience only: it does not isolate anything, and a result
carrying it is not evidence of anything.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGE = os.environ.get("SIH_SANDBOX_IMAGE", "python:3.12-slim")
DOCKER = "docker (no network, read-only root, capped memory and time)"
SUBPROCESS = "subprocess (NO ISOLATION -- development fallback, not evidence)"


@dataclass
class SandboxResult:
    ok: bool                       # the entry point exited 0 within its limits
    exit_code: int
    stdout: str
    stderr: str
    seconds: float
    isolation: str
    timed_out: bool = False
    image: str | None = None
    files_out: dict[str, str] = field(default_factory=dict)   # files the code left behind

    def summary(self) -> str:
        how = "ok" if self.ok else (f"timed out after {self.seconds:.0f}s" if self.timed_out
                                    else f"exit {self.exit_code}")
        return f"{how} in {self.seconds:.1f}s [{self.isolation.split(' (')[0]}]"


def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


def image_present(image: str = IMAGE) -> bool:
    """An air-gapped machine cannot pull, so the image must already be here."""
    try:
        out = subprocess.run(["docker", "image", "inspect", image],
                             capture_output=True, timeout=20)
        return out.returncode == 0
    except Exception:
        return False


def run(files: dict[str, str], entry: str = "main.py", timeout: int = 30,
        memory: str = "512m", collect: tuple[str, ...] = (),
        force_subprocess: bool = False) -> SandboxResult:
    """Write `files` into a fresh directory and run `entry` there.

    `collect` names files to read back out afterwards -- how the code returns
    something bigger than its own output.
    """
    work = Path(tempfile.mkdtemp(prefix="sih-sandbox-"))
    try:
        for name, text in files.items():
            path = work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

        use_docker = not force_subprocess and docker_available() and image_present()
        t0 = time.time()
        if use_docker:
            cmd = [
                "docker", "run", "--rm",
                "--network", "none",              # no interface at all
                "--read-only",                    # the image's filesystem cannot be changed
                "--tmpfs", "/tmp:rw,size=64m",
                "--memory", memory, "--memory-swap", memory,
                "--cpus", "1", "--pids-limit", "128",
                "-v", f"{work}:/work:rw", "-w", "/work",
                "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "PYTHONUNBUFFERED=1",
                IMAGE, "python", entry,
            ]
            isolation, image = DOCKER, IMAGE
        else:
            cmd = [sys.executable, entry]
            isolation, image = SUBPROCESS, None

        timed_out = False
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5,
                                  cwd=None if use_docker else str(work))
            code, out, err = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as e:
            timed_out, code = True, -1
            out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
            err = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")

        collected = {}
        for name in collect:
            path = work / name
            if path.exists():
                collected[name] = path.read_text(encoding="utf-8", errors="replace")

        return SandboxResult(ok=(code == 0 and not timed_out), exit_code=code,
                             stdout=out[-20000:], stderr=err[-20000:],
                             seconds=round(time.time() - t0, 2), isolation=isolation,
                             timed_out=timed_out, image=image, files_out=collected)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# --- proving the isolation ---------------------------------------------------

NETWORK_PROBE = '''
"""Try every ordinary way out of this container. Each one must fail."""
import json, socket, urllib.request

results = {}
try:
    socket.create_connection(("8.8.8.8", 53), timeout=4)
    results["tcp to 8.8.8.8:53"] = "CONNECTED -- isolation is broken"
except Exception as e:
    results["tcp to 8.8.8.8:53"] = f"refused ({type(e).__name__})"
try:
    socket.gethostbyname("example.com")
    results["dns lookup"] = "RESOLVED -- isolation is broken"
except Exception as e:
    results["dns lookup"] = f"failed ({type(e).__name__})"
try:
    urllib.request.urlopen("http://example.com", timeout=4)
    results["http to example.com"] = "FETCHED -- isolation is broken"
except Exception as e:
    results["http to example.com"] = f"failed ({type(e).__name__})"

print(json.dumps(results, indent=2))
print("ESCAPED" if any("broken" in v for v in results.values()) else "SEALED")
'''

WRITE_PROBE = '''
from pathlib import Path
try:
    Path("/etc/sih-was-here").write_text("x")
    print("WROTE to the image filesystem -- isolation is broken")
except Exception as e:
    print(f"could not write outside the working directory ({type(e).__name__})")
Path("proof.txt").write_text("the working directory is writable")
print("working directory: ok")
'''


def self_test() -> int:
    """Show, rather than claim, that code in the sandbox cannot reach out."""
    if not docker_available():
        print("Docker is not running -- start Docker Desktop. Without it the sandbox "
              "falls back to a plain subprocess, which isolates nothing.")
        return 2
    if not image_present():
        print(f"image {IMAGE} is not present locally. On a connected machine:\n"
              f"    docker pull {IMAGE}\n"
              f"On the air-gapped machine it must be loaded from a file:\n"
              f"    docker load -i python-3.12-slim.tar")
        return 2

    print(f"sandbox image: {IMAGE}\n")
    net = run({"main.py": NETWORK_PROBE}, timeout=30)
    print("--- can the code reach the network? ---")
    print(net.stdout.strip() or net.stderr.strip())
    print(f"    {net.summary()}\n")

    fs = run({"main.py": WRITE_PROBE}, timeout=20, collect=("proof.txt",))
    print("--- can the code touch anything else? ---")
    print(fs.stdout.strip() or fs.stderr.strip())
    print(f"    collected back: {list(fs.files_out)}")
    print(f"    {fs.summary()}\n")

    cpu = run({"main.py": "while True:\n    pass\n"}, timeout=5)
    print("--- is runaway code stopped? ---")
    print(f"    {'killed at the time limit' if cpu.timed_out else 'NOT STOPPED -- limit failed'}"
          f" ({cpu.seconds:.1f}s)\n")

    sealed = "SEALED" in net.stdout and not fs.stdout.startswith("WROTE") and cpu.timed_out
    print("RESULT:", "sandbox is sealed" if sealed else "SANDBOX FAILED ITS OWN TEST")
    return 0 if sealed else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    code = sys.stdin.read()
    result = run({"main.py": code})
    print(json.dumps(asdict(result), indent=2))
