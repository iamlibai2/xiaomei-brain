"""Lifecycle manager for AI model services shared on one host."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import psutil

from .catalog import (
    SERVICE_SPECS,
    cached_model_bytes,
    cached_model_path,
    get_model_spec,
    get_service_spec,
    list_model_specs,
    missing_dependencies,
)
from .selection import ModelSelectionStore, base_dir_for_runtime


class LocalAIRuntimeError(RuntimeError):
    pass


class LocalAIRuntimeManager:
    """Start, observe, and stop host services without owning Agent data."""

    def __init__(self, runtime_dir: str | Path | None = None) -> None:
        self.runtime_dir = Path(runtime_dir or Path.home() / ".xiaomei-brain" / "runtime" / "ai-services")
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.selections = ModelSelectionStore(base_dir_for_runtime(self.runtime_dir))

    def list_services(self) -> list[dict[str, Any]]:
        service_ids = [spec.service_id for spec in SERVICE_SPECS]
        with ThreadPoolExecutor(max_workers=len(service_ids)) as executor:
            return list(executor.map(self.status, service_ids))

    def system_status(self) -> dict[str, Any]:
        memory = psutil.virtual_memory()
        return {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_percent": memory.percent,
            "memory_used_bytes": memory.used,
            "memory_total_bytes": memory.total,
            "gpus": self._gpu_status(),
        }

    def status(self, service_id: str) -> dict[str, Any]:
        spec = get_service_spec(service_id)
        selected_model_id = self.selections.selected(service_id)
        model_spec = get_model_spec(service_id, selected_model_id)
        selected_device = self.selections.selected_device(service_id, selected_model_id)
        missing = missing_dependencies(model_spec)
        model_path = cached_model_path(model_spec) or self._completed_model_path(service_id, selected_model_id)
        process = self._tracked_process(service_id)
        download_process = self._tracked_download(service_id)
        health = self._health(spec.endpoint) if spec.endpoint else None
        metadata = self._read_metadata(service_id)
        download_metadata = self._read_download_metadata(service_id)
        downloaded_bytes = cached_model_bytes(model_spec)
        model_present = bool(model_path) or not spec.downloadable
        download_progress = (
            100
            if model_present
            else min(99, round(downloaded_bytes * 100 / model_spec.expected_size_bytes))
            if model_spec.expected_size_bytes
            else 0
        )
        if download_process is not None and not model_present:
            reported_progress = self._download_log_progress(service_id, selected_model_id)
            if reported_progress is not None:
                download_progress = max(download_progress, reported_progress)
                downloaded_bytes = max(
                    downloaded_bytes,
                    round(model_spec.expected_size_bytes * reported_progress / 100),
                )
        memory_bytes = int((health or {}).get("memory_bytes") or self._process_memory(process))
        system_memory_total_bytes = int((health or {}).get("system_memory_total_bytes") or 0)
        gpu_memory_bytes = int((health or {}).get("gpu_memory_bytes") or 0)
        gpu_memory_total_bytes = int((health or {}).get("gpu_memory_total_bytes") or 0)

        if health is not None:
            state = "online"
            error = ""
        elif process is not None:
            state = "starting"
            error = "模型正在加载" if model_path else "模型正在下载或加载"
        elif download_process is not None:
            state = "downloading"
            error = ""
        elif metadata.get("pid"):
            state = "error"
            error = self._last_log_line(service_id) or "服务进程已意外退出"
        elif download_metadata.get("pid") and not model_present:
            state = "download_error"
            error = self._last_download_log_line(service_id) or "模型下载进程已意外退出"
        elif missing:
            state = "unavailable"
            error = f"缺少运行库：{', '.join(missing)}"
        elif spec.downloadable and not model_present:
            state = "not_installed"
            error = ""
        elif not spec.controllable:
            state = "available"
            error = "等待接入共享推理服务"
        else:
            state = "stopped"
            error = ""

        return {
            "id": spec.service_id,
            "name": spec.name,
            "description": spec.description,
            "model": model_spec.name,
            "selected_model_id": selected_model_id,
            "models": [self._model_status(item) for item in list_model_specs(service_id)],
            "selection_locked": bool(self.selections.lock_info(service_id)),
            "selection_lock_reason": str(self.selections.lock_info(service_id).get("reason") or ""),
            "selected_device": selected_device,
            "supported_devices": list(model_spec.supported_devices),
            "expected_size": model_spec.expected_size,
            "endpoint": spec.endpoint,
            "required": spec.required,
            "controllable": spec.controllable,
            "downloadable": spec.downloadable,
            "installed": not missing,
            "missing_dependencies": missing,
            "model_present": model_present,
            "model_path": model_path,
            "expected_size_bytes": model_spec.expected_size_bytes,
            "downloaded_bytes": downloaded_bytes,
            "download_progress": download_progress,
            "state": state,
            "pid": (
                (process or download_process).pid
                if (process or download_process) is not None
                else (health or {}).get("pid")
            ),
            "started_at": (
                metadata.get("started_at", "")
                if process is not None
                else download_metadata.get("started_at", "")
            ),
            "device": str((health or {}).get("device") or metadata.get("device") or spec.device_default),
            "health": health or {},
            "memory_bytes": memory_bytes,
            "system_memory_total_bytes": system_memory_total_bytes,
            "gpu_memory_bytes": gpu_memory_bytes,
            "gpu_memory_total_bytes": gpu_memory_total_bytes,
            "error": error,
            "log_path": str(self._log_path(service_id)),
            "download_log_path": str(self._download_log_path(service_id)),
        }

    def start(self, service_id: str, *, device: str | None = None) -> dict[str, Any]:
        spec = get_service_spec(service_id)
        if not spec.controllable:
            raise LocalAIRuntimeError(f"{spec.name} 尚未接入独立共享服务")
        current = self.status(service_id)
        if current["state"] in {"online", "starting"}:
            return current
        if current["missing_dependencies"]:
            raise LocalAIRuntimeError(current["error"])
        if spec.downloadable and not current["model_present"]:
            raise LocalAIRuntimeError(f"请先下载 {spec.name} 模型")
        launch_device = device or str(current["selected_device"])
        if launch_device not in current["supported_devices"]:
            raise LocalAIRuntimeError(f"{current['model']} 不支持使用 {launch_device} 运行")

        log_path = self._log_path(service_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = open(log_path, "ab", buffering=0)
        command = [
            sys.executable,
            "-m",
            "xiaomei_brain.runtime_services.worker",
            service_id,
            "--model",
            str(current["selected_model_id"]),
            "--model-path",
            str(current["model_path"]),
            "--runtime-dir",
            str(self.runtime_dir),
            "--device",
            launch_device,
        ]
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": log_file,
            "stderr": subprocess.STDOUT,
            "cwd": str(Path.home()),
            "env": {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"},
            "close_fds": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
            )
        else:
            kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(command, **kwargs)
        finally:
            log_file.close()
        self._write_metadata(service_id, {
            "pid": process.pid,
            "create_time": psutil.Process(process.pid).create_time(),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "device": launch_device,
            "model": current["selected_model_id"],
            "command": command,
        })
        time.sleep(0.2)
        if process.poll() is not None:
            raise LocalAIRuntimeError(self._last_log_line(service_id) or f"{spec.name} 启动失败")
        return self.status(service_id)

    def download(self, service_id: str) -> dict[str, Any]:
        spec = get_service_spec(service_id)
        if not spec.downloadable:
            raise LocalAIRuntimeError(f"{spec.name} 不需要单独下载模型")
        current = self.status(service_id)
        if current["model_present"] or current["state"] == "downloading":
            return current
        remaining = max(0, int(current["expected_size_bytes"]) - int(current["downloaded_bytes"]))
        free = shutil.disk_usage(Path.home()).free
        if remaining and free < int(remaining * 1.1):
            raise LocalAIRuntimeError(
                f"磁盘可用空间不足：至少还需要 {remaining / 1024 ** 3:.1f} GB"
            )

        log_path = self._download_log_path(service_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # A download log describes one attempt. Truncating it prevents a new
        # progress observer from mistaking an earlier completion for this run.
        log_file = open(log_path, "wb", buffering=0)
        command = [
            sys.executable,
            "-m",
            "xiaomei_brain.runtime_services.downloader",
            service_id,
            "--model",
            str(current["selected_model_id"]),
            "--completion-file",
            str(self._model_record_path(service_id, str(current["selected_model_id"]))),
        ]
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": log_file,
            "stderr": subprocess.STDOUT,
            "cwd": str(Path.home()),
            "env": {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"},
            "close_fds": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
            )
        else:
            kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(command, **kwargs)
        finally:
            log_file.close()
        self._write_download_metadata(service_id, {
            "pid": process.pid,
            "create_time": psutil.Process(process.pid).create_time(),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "command": command,
            "model": current["selected_model_id"],
        })
        time.sleep(0.2)
        if process.poll() is not None:
            raise LocalAIRuntimeError(self._last_download_log_line(service_id) or f"{spec.name} 下载启动失败")
        return self.status(service_id)

    def select_model(self, service_id: str, model_id: str) -> dict[str, Any]:
        get_model_spec(service_id, model_id)
        current = self.status(service_id)
        if current["state"] in {"online", "starting", "downloading"}:
            raise LocalAIRuntimeError("请先停止服务或取消下载，再更换模型")
        try:
            self.selections.select(service_id, model_id)
        except ValueError as exc:
            raise LocalAIRuntimeError(str(exc)) from exc
        return self.status(service_id)

    def select_device(self, service_id: str, device: str) -> dict[str, Any]:
        current = self.status(service_id)
        if current["state"] in {"online", "starting", "downloading"}:
            raise LocalAIRuntimeError("请先停止服务或取消下载，再更换运行设备")
        try:
            self.selections.select_device(service_id, str(current["selected_model_id"]), device)
        except ValueError as exc:
            raise LocalAIRuntimeError(str(exc)) from exc
        return self.status(service_id)

    def cancel_download(self, service_id: str) -> dict[str, Any]:
        get_service_spec(service_id)
        process = self._tracked_download(service_id)
        if process is not None:
            self._terminate_process(process)
        self._download_metadata_path(service_id).unlink(missing_ok=True)
        return self.status(service_id)

    def stop(self, service_id: str) -> dict[str, Any]:
        spec = get_service_spec(service_id)
        process = self._tracked_process(service_id)
        if process is None:
            if self._health(spec.endpoint) is not None:
                raise LocalAIRuntimeError("服务不是由小美本机运行管理器启动，不能安全停止")
            self._metadata_path(service_id).unlink(missing_ok=True)
            return self.status(service_id)
        self._terminate_process(process)
        self._metadata_path(service_id).unlink(missing_ok=True)
        return self.status(service_id)

    def restart(self, service_id: str, *, device: str | None = None) -> dict[str, Any]:
        try:
            self.stop(service_id)
        except LocalAIRuntimeError:
            if self._tracked_process(service_id) is not None:
                raise
        return self.start(service_id, device=device)

    def ensure_running(
        self,
        service_id: str,
        *,
        device: str | None = None,
        timeout: float = 180.0,
    ) -> dict[str, Any]:
        """Ensure a required shared service is healthy before a client starts."""
        current = self.status(service_id)
        if current["state"] == "online":
            return current
        if not current["installed"]:
            raise LocalAIRuntimeError(current["error"] or "服务运行依赖尚未安装")
        if current["downloadable"] and not current["model_present"]:
            raise LocalAIRuntimeError(f"请先下载 {current['name']} 的 {current['model']} 模型")
        if current["state"] != "starting":
            current = self.start(service_id, device=device)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if current["state"] == "online":
                return current
            if current["state"] in {"error", "unavailable", "stopped"}:
                raise LocalAIRuntimeError(current["error"] or f"{current['name']} 启动失败")
            time.sleep(0.5)
            current = self.status(service_id)
        raise LocalAIRuntimeError(f"{current['name']} 加载超时，请查看服务日志")

    def read_log(self, service_id: str, max_bytes: int = 64 * 1024) -> str:
        get_service_spec(service_id)
        paths = [self._log_path(service_id), self._download_log_path(service_id)]
        existing = [path for path in paths if path.is_file()]
        if not existing:
            return ""
        path = max(existing, key=lambda item: item.stat().st_mtime)
        if not path.is_file():
            return ""
        with path.open("rb") as stream:
            size = stream.seek(0, os.SEEK_END)
            stream.seek(max(0, size - max_bytes))
            return stream.read().decode("utf-8", errors="replace")

    def _health(self, endpoint: str) -> dict[str, Any] | None:
        if not endpoint:
            return None
        try:
            with urllib.request.urlopen(f"{endpoint.rstrip('/')}/health", timeout=0.8) as response:
                if response.status != 200:
                    return None
                value = json.loads(response.read())
                return value if isinstance(value, dict) else {"status": "ok"}
        except Exception:
            return None

    def _tracked_process(self, service_id: str) -> psutil.Process | None:
        metadata = self._read_metadata(service_id)
        try:
            pid = int(metadata.get("pid", 0))
            if pid <= 0:
                return None
            process = psutil.Process(pid)
            recorded = float(metadata.get("create_time", 0))
            if recorded and abs(process.create_time() - recorded) > 1:
                return None
            if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
                return None
            return process
        except (TypeError, ValueError, psutil.Error):
            return None

    def _tracked_download(self, service_id: str) -> psutil.Process | None:
        return self._process_from_metadata(self._read_download_metadata(service_id))

    @staticmethod
    def _process_from_metadata(metadata: dict[str, Any]) -> psutil.Process | None:
        try:
            pid = int(metadata.get("pid", 0))
            if pid <= 0:
                return None
            process = psutil.Process(pid)
            recorded = float(metadata.get("create_time", 0))
            if recorded and abs(process.create_time() - recorded) > 1:
                return None
            if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
                return None
            return process
        except (TypeError, ValueError, psutil.Error):
            return None

    @staticmethod
    def _terminate_process(process: psutil.Process) -> None:
        children = process.children(recursive=True)
        for child in reversed(children):
            child.terminate()
        process.terminate()
        _, alive = psutil.wait_procs([*children, process], timeout=8)
        for item in alive:
            item.kill()

    @staticmethod
    def _process_memory(process: psutil.Process | None) -> int:
        if process is None:
            return 0
        try:
            return process.memory_info().rss + sum(
                child.memory_info().rss for child in process.children(recursive=True)
            )
        except psutil.Error:
            return 0

    @staticmethod
    def _gpu_status() -> list[dict[str, Any]]:
        command = [
            "nvidia-smi",
            "--query-gpu=name,utilization.gpu,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ]
        kwargs: dict[str, Any] = {
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "timeout": 2,
            "check": False,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            result = subprocess.run(command, **kwargs)
        except (OSError, subprocess.SubprocessError):
            return []
        if result.returncode != 0:
            return []
        gpus: list[dict[str, Any]] = []
        for line in result.stdout.splitlines():
            fields = [field.strip() for field in line.split(",")]
            if len(fields) != 4:
                continue
            try:
                gpus.append({
                    "name": fields[0],
                    "utilization_percent": float(fields[1]),
                    "memory_used_bytes": int(float(fields[2]) * 1024 * 1024),
                    "memory_total_bytes": int(float(fields[3]) * 1024 * 1024),
                })
            except ValueError:
                continue
        return gpus

    def _last_log_line(self, service_id: str) -> str:
        lines = [line.strip() for line in self.read_log(service_id, 8 * 1024).splitlines() if line.strip()]
        return lines[-1] if lines else ""

    def _last_download_log_line(self, service_id: str) -> str:
        path = self._download_log_path(service_id)
        if not path.is_file():
            return ""
        content = path.read_bytes()[-8 * 1024:].decode("utf-8", errors="replace")
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        return lines[-1] if lines else ""

    def _download_log_progress(self, service_id: str, model_id: str) -> int | None:
        """Read subprocess progress without coupling the manager to a Hub SDK."""
        path = self._download_log_path(service_id)
        if not path.is_file():
            return None
        content = path.read_bytes()[-256 * 1024:].decode("utf-8", errors="replace")
        content = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", content)
        if model_id == "whisper-small":
            weight_matches = re.findall(
                r"model\.safetensors:\s*(\d{1,3})%",
                content,
            )
            if weight_matches:
                return min(99, int(weight_matches[-1]))
        aggregate_matches = re.findall(r"Downloading:\s*(\d{1,3})%", content)
        if aggregate_matches:
            return min(99, int(aggregate_matches[-1]))
        return None

    def _metadata_path(self, service_id: str) -> Path:
        return self.runtime_dir / f"{service_id}.json"

    def _log_path(self, service_id: str) -> Path:
        return self.runtime_dir / f"{service_id}.log"

    def _download_metadata_path(self, service_id: str) -> Path:
        return self.runtime_dir / f"{service_id}.download.json"

    def _download_log_path(self, service_id: str) -> Path:
        return self.runtime_dir / f"{service_id}.download.log"

    def _model_record_path(self, service_id: str, model_id: str) -> Path:
        safe_model_id = model_id.replace("/", "_").replace("\\", "_")
        return self.runtime_dir / f"{service_id}.{safe_model_id}.model.json"

    def _completed_model_path(self, service_id: str, model_id: str) -> str:
        try:
            value = json.loads(self._model_record_path(service_id, model_id).read_text(encoding="utf-8"))
            model_path = Path(str(value.get("model_path") or ""))
            return str(model_path) if model_path.is_dir() else ""
        except (OSError, ValueError):
            return ""

    def _model_status(self, model_spec: Any) -> dict[str, Any]:
        model_path = cached_model_path(model_spec) or self._completed_model_path(
            model_spec.service_id,
            model_spec.model_id,
        )
        downloaded_bytes = cached_model_bytes(model_spec)
        return {
            "id": model_spec.model_id,
            "name": model_spec.name,
            "source": model_spec.source,
            "expected_size": model_spec.expected_size,
            "expected_size_bytes": model_spec.expected_size_bytes,
            "downloaded_bytes": downloaded_bytes,
            "model_present": bool(model_path) or not get_service_spec(model_spec.service_id).downloadable,
            "recommended_device": model_spec.recommended_device,
            "supported_devices": list(model_spec.supported_devices),
        }

    def _read_metadata(self, service_id: str) -> dict[str, Any]:
        try:
            value = json.loads(self._metadata_path(service_id).read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write_metadata(self, service_id: str, value: dict[str, Any]) -> None:
        path = self._metadata_path(service_id)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def _read_download_metadata(self, service_id: str) -> dict[str, Any]:
        try:
            value = json.loads(self._download_metadata_path(service_id).read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write_download_metadata(self, service_id: str, value: dict[str, Any]) -> None:
        path = self._download_metadata_path(service_id)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
