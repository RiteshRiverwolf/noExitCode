"""Tamper-evident log of tool calls, shared by our MCP servers.

Every tool call becomes one JSON line in logs/<server>_tool_calls.jsonl.
Each line carries the SHA-256 of the line before it, so editing or deleting
an earlier entry breaks the chain, and `verify` reports where.

This proves the log was not edited *in the middle*. Someone who rewrites the
whole file can rebuild the chain, so the latest hash should also be recorded
somewhere else (a run record, the frontend) to anchor it.

One file per server: two processes appending to one file would interleave
their chains.

    .venv\\Scripts\\python -m mcp_servers.audit logs\\web_access_tool_calls.jsonl
"""

from __future__ import annotations

import hashlib
import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
GENESIS = "0" * 64


def _sha256(line: bytes) -> str:
    return hashlib.sha256(line).hexdigest()


class AuditLog:
    """Append-only, hash-chained JSONL log for one server."""

    def __init__(self, server: str, path: Path | None = None):
        self.server = server
        self.path = Path(path) if path else LOG_DIR / f"{server}_tool_calls.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._prev = self._last_hash()

    def _last_hash(self) -> str:
        if not self.path.exists():
            return GENESIS
        last = b""
        with self.path.open("rb") as f:
            for raw in f:
                if raw.strip():
                    last = raw.rstrip(b"\r\n")
        return _sha256(last) if last else GENESIS

    @property
    def head(self) -> str:
        """Hash of the latest entry -- record it elsewhere to anchor the chain."""
        return self._prev

    def write(self, event: dict) -> dict:
        with self._lock:
            record = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "server": self.server,
                **event,
                "prev_sha256": self._prev,
            }
            line = json.dumps(record, ensure_ascii=False)
            with self.path.open("a", encoding="utf-8", newline="\n") as f:
                f.write(line + "\n")
            self._prev = _sha256(line.encode("utf-8"))
            return record


def verify(path: Path) -> tuple[bool, int, str]:
    """Check the hash chain. Returns (ok, entries checked, message)."""
    prev, n = GENESIS, 0
    with Path(path).open("rb") as f:
        for raw in f:
            if not raw.strip():
                continue
            n += 1
            line = raw.rstrip(b"\r\n")
            try:
                record = json.loads(line)
            except ValueError:
                return False, n, f"entry {n}: not valid JSON"
            if record.get("prev_sha256") != prev:
                return False, n, f"entry {n}: chain broken -- an earlier entry was changed or removed"
            prev = _sha256(line)
    return True, n, f"chain intact; latest hash {prev}"


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else LOG_DIR / "web_access_tool_calls.jsonl"
    ok, count, message = verify(target)
    print(f"{'OK' if ok else 'BROKEN'}: {count} entries. {message}")
    raise SystemExit(0 if ok else 1)
