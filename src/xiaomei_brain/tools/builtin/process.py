"""Bounded background-process management for one Agent process."""

from __future__ import annotations

import locale
import os
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..base import Tool

MAX_OUTPUT_BYTES = 1024 * 1024
MAX_FINISHED_PROCESSES = 30


def _decode(data: bytes) -> str:
    for encoding in dict.fromkeys(("utf-8", locale.getpreferredencoding(False))):
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


@dataclass
class ProcessRecord:
    id: str
    command: str
    shell_name: str
    cwd: str
    process: subprocess.Popen[bytes]
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    exit_code: int | None = None
    _output: bytearray = field(default_factory=bytearray, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def status(self) -> str:
        code = self.process.poll()
        if code is None:
            return "running"
        if self.exit_code is None:
            self.exit_code = code
            self.finished_at = self.finished_at or time.time()
        return "completed" if code == 0 else "failed"

    def append(self, data: bytes) -> None:
        with self._lock:
            self._output.extend(data)
            overflow = len(self._output) - MAX_OUTPUT_BYTES
            if overflow > 0:
                del self._output[:overflow]

    def output(self) -> str:
        with self._lock:
            return _decode(bytes(self._output))

    def snapshot(self, *, include_output: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "process_id": self.id,
            "pid": self.process.pid,
            "status": self.status,
            "command": self.command,
            "shell": self.shell_name,
            "cwd": self.cwd,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }
        if include_output:
            result["output"] = self.output()
        return result


class ProcessRegistry:
    def __init__(self) -> None:
        self._records: dict[str, ProcessRecord] = {}
        self._lock = threading.RLock()

    def add(
        self,
        *,
        command: str,
        shell_name: str,
        cwd: str,
        process: subprocess.Popen[bytes],
    ) -> ProcessRecord:
        record = ProcessRecord(
            id=f"process_{uuid.uuid4().hex[:12]}",
            command=command,
            shell_name=shell_name,
            cwd=cwd,
            process=process,
        )
        with self._lock:
            self._records[record.id] = record
            self._prune()
        threading.Thread(
            target=self._read_output,
            args=(record,),
            name=f"xiaomei-{record.id}",
            daemon=True,
        ).start()
        return record

    @staticmethod
    def _read_output(record: ProcessRecord) -> None:
        stream = record.process.stdout
        if stream is not None:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    break
                record.append(chunk)
        record.exit_code = record.process.wait()
        record.finished_at = time.time()

    def _prune(self) -> None:
        finished = [
            item for item in self._records.values()
            if item.process.poll() is not None
        ]
        if len(finished) <= MAX_FINISHED_PROCESSES:
            return
        finished.sort(key=lambda item: item.finished_at or item.started_at)
        for item in finished[:-MAX_FINISHED_PROCESSES]:
            self._records.pop(item.id, None)

    def get(self, process_id: str) -> ProcessRecord | None:
        with self._lock:
            return self._records.get(process_id)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            records = list(self._records.values())
        records.sort(key=lambda item: item.started_at, reverse=True)
        return [item.snapshot() for item in records]


process_registry = ProcessRegistry()


def terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
            timeout=10,
        )
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)


def manage_process(
    action: str,
    process_id: str = "",
    timeout: float = 30,
) -> dict[str, Any]:
    action = str(action or "").strip().lower()
    if action == "list":
        return {"processes": process_registry.list()}
    record = process_registry.get(process_id)
    if record is None:
        return {"error": f"Error: unknown process_id: {process_id}"}
    if action in {"poll", "log"}:
        return record.snapshot(include_output=True)
    if action == "wait":
        try:
            record.process.wait(timeout=max(0.1, min(float(timeout or 30), 600)))
        except subprocess.TimeoutExpired:
            result = record.snapshot(include_output=True)
            result["timed_out"] = True
            return result
        return record.snapshot(include_output=True)
    if action == "kill":
        terminate_process_tree(record.process)
        return record.snapshot(include_output=True)
    return {"error": "Error: action must be list, poll, log, wait, or kill"}


process_tool = Tool(
    name="process",
    description=(
        "Manage commands started in the background: list them, read output, "
        "wait for completion, or stop one process tree."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "poll", "log", "wait", "kill"],
            },
            "process_id": {"type": "string", "default": ""},
            "timeout": {
                "type": "number",
                "minimum": 0,
                "maximum": 600,
                "default": 30,
            },
        },
        "required": ["action"],
    },
    func=manage_process,
    category="process",
)
