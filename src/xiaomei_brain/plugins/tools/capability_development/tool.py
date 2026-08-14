"""Build and optionally activate one capability package owned by this Agent."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any, Callable

import yaml

from xiaomei_brain.capability_packages import (
    CapabilityPackageBuilder,
    CapabilityPackageService,
)
from xiaomei_brain.tools.base import Tool
from xiaomei_brain.tools.execution_context import current_tool_execution


RestartScheduler = Callable[[str, float], None]


def create_build_capability_tool(
    *,
    agent_id: str,
    agent_dir: str | Path,
    restart_scheduler: RestartScheduler | None = None,
) -> Tool:
    """Create the deterministic capability build boundary for one Agent."""
    normalized_agent_id = str(agent_id).strip()
    agent_root = Path(agent_dir).expanduser().resolve()
    package_service = CapabilityPackageService(
        base_dir=agent_root.parent,
        agent_id=normalized_agent_id,
    )
    schedule_restart = restart_scheduler or _schedule_agent_restart

    def build_capability(
        source_dir: str,
        output_name: str = "",
        activate: bool = False,
    ) -> str:
        """Build, inspect and optionally activate an Agent-authored package."""
        context = current_tool_execution()
        if context is None or not context.workspace_root:
            raise RuntimeError("能力包只能在 Agent 的受控 Workspace 中构建")
        workspace_root = Path(context.workspace_root).expanduser().resolve()
        output_root = Path(context.output_root or workspace_root / "outputs").expanduser().resolve()
        source = _resolve_workspace_source(workspace_root, source_dir)
        output_root.relative_to(workspace_root)
        output_root.mkdir(parents=True, exist_ok=True)

        destination = output_root / _output_file_name(source, output_name)
        if context.tool_registry is None:
            raise RuntimeError("当前执行现场缺少工具注册表，无法执行工具契约检查")
        result = CapabilityPackageBuilder(tool_registry=context.tool_registry).pack(
            source,
            output_path=destination,
        )
        package_path = Path(str(result["path"])).resolve()
        relative_output = package_path.relative_to(workspace_root).as_posix()
        response: dict[str, Any] = {
            "success": True,
            "output_path": relative_output,
            "sha256": result["sha256"],
            "size": result["size"],
            "file_count": result["file_count"],
            "package": result["package"],
            "activated": False,
            "restart_required": False,
            "tool_contracts": result.get("tool_contracts") or {},
        }

        if activate:
            installed = package_service.install(
                package_path.read_bytes(),
                file_name=package_path.name,
                expected_sha256=str(result["sha256"]),
            )
            identity = dict(installed["package"])
            activated = package_service.activate(
                str(identity["id"]),
                str(identity["version"]),
                str(identity["sha256"]),
            )
            delay = 8.0
            schedule_restart(normalized_agent_id, delay)
            response.update({
                "activated": True,
                "restart_required": True,
                "restart_scheduled_in_seconds": delay,
                "installed_package": activated,
                "message": "能力包已安装并为当前 Agent 启用；当前回复完成后将自动重启加载。",
            })
        else:
            response["message"] = "能力包已构建并通过完整性与工具契约检查，尚未安装或启用。"
        return json.dumps(response, ensure_ascii=False)

    return Tool(
        name="build_capability",
        description=(
            "将当前 Agent Workspace 内已经准备好的能力源码目录构建为 .xmcap，"
            "自动生成校验清单、复验文件完整性，并用当前 Agent 的真实 Tool Schema 检查 Skill 中"
            "声明的工具名与参数。契约不一致时会返回真实 required/properties 供修订。"
            "source_dir 必须是 Workspace 相对路径；产物写入 outputs/。"
            "只有人物明确要求立即加载或试用时才能设置 activate=true；这会只为当前 Agent 安装启用，"
            "并在当前回复完成后自动重启。普通导出必须保持 activate=false。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "source_dir": {
                    "type": "string",
                    "description": "能力源码的 Workspace 相对目录，例如 work/capabilities/customer-analysis",
                },
                "output_name": {
                    "type": "string",
                    "description": "可选的产物文件名，只能是文件名；省略时使用包 ID 和版本",
                },
                "activate": {
                    "type": "boolean",
                    "default": False,
                    "description": "是否为当前 Agent 安装启用并自动重启；仅在人物明确要求试用时使用",
                },
            },
            "required": ["source_dir"],
        },
        func=build_capability,
        category="capability",
    )


def _resolve_workspace_source(workspace_root: Path, value: str) -> Path:
    raw = Path(str(value or "").strip())
    if not str(raw) or raw.is_absolute():
        raise ValueError("source_dir 必须是 Workspace 相对目录")
    source = (workspace_root / raw).resolve()
    try:
        relative = source.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError("能力源码目录不能越过当前 Agent Workspace") from exc
    if relative.parts and relative.parts[0].casefold() == "inputs":
        raise ValueError("inputs/ 是只读输入区，不能作为能力开发目录")
    if not source.is_dir():
        raise ValueError(f"能力源码目录不存在: {raw.as_posix()}")
    return source


def _output_file_name(source: Path, value: str) -> str:
    requested = str(value or "").strip()
    if requested:
        path = Path(requested)
        if path.name != requested or path.is_absolute():
            raise ValueError("output_name 只能是文件名，不能包含目录")
        return path.with_suffix(".xmcap").name
    try:
        manifest = yaml.safe_load((source / "capability.yaml").read_text(encoding="utf-8"))
        package = manifest["package"]
        return f"{package['id']}-{package['version']}.xmcap"
    except Exception as exc:
        raise ValueError(f"无法从 capability.yaml 确定输出文件名: {exc}") from exc


def _schedule_agent_restart(agent_id: str, delay: float) -> None:
    """Start a detached lifecycle helper after the current response can flush."""
    def launch() -> None:
        command = [sys.executable, "-m", "xiaomei_brain", "restart", agent_id]
        options: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            options["creationflags"] = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            )
        else:
            options["start_new_session"] = True
        subprocess.Popen(command, **options)

    timer = threading.Timer(max(1.0, float(delay)), launch)
    timer.daemon = True
    timer.start()
