"""Register the controlled Desktop browser as an Agent tool."""

from __future__ import annotations

import base64
import mimetypes
import re
from pathlib import Path
from typing import Any

from xiaomei_brain.body.embodiment.commands import get_default_command_broker
from xiaomei_brain.tools.base import Tool
from xiaomei_brain.tools.builtin.file_ops import resolve_readable_path
from xiaomei_brain.tools.execution_context import (
    current_tool_execution,
    resolve_current_attachment,
    resolve_current_workspace_asset,
)


_MAX_TRANSFER_BYTES = 10 * 1024 * 1024


_ACTIONS = {
    "open": "browser.open",
    "navigate": "browser.navigate",
    "snapshot": "browser.snapshot",
    "click": "browser.click",
    "type": "browser.type",
    "select": "browser.select",
    "press": "browser.press",
    "scroll": "browser.scroll",
    "download": "browser.download",
    "upload": "browser.upload",
    "wait_for": "browser.wait_for",
    "back": "browser.back",
    "forward": "browser.forward",
    "reload": "browser.reload",
    "get_state": "browser.state.get",
    "close": "browser.close",
}


def browser_control(
    action: str,
    url: str = "",
    ref: str = "",
    text: str = "",
    value: str = "",
    clear: bool = True,
    direction: str = "down",
    amount: int = 700,
    interactive_only: bool = False,
    max_elements: int = 200,
    key: str = "Enter",
    file_path: str = "",
    attachment_id: str = "",
    asset_id: str = "",
    workspace_id: str = "",
    condition: str = "load",
    timeout_ms: int = 5000,
) -> dict[str, Any]:
    """Execute one allowlisted action in the Desktop embedded browser."""
    # OpenAI-compatible providers occasionally emit scalar values with the
    # wrong JSON type (for example a six-digit verification code as a number).
    # Normalize at the tool boundary so a valid user value is never silently
    # dropped by the typed Desktop bridge.
    action = str(action or "")
    url = str(url or "")
    ref = str(ref or "")
    text = str(text if text is not None else "")
    value = str(value if value is not None else "")
    clear = _as_bool(clear, default=True)
    interactive_only = _as_bool(interactive_only, default=False)
    command = _ACTIONS.get(action)
    if command is None:
        return {"error": f"不支持的网页操作：{action}"}
    broker = get_default_command_broker()
    if broker is None:
        return {"error": "Desktop 网页控制服务尚未初始化"}
    context = current_tool_execution()
    if context is None or not context.session_id or not context.turn_id:
        return {"error": "当前工具调用没有可路由的 Desktop 对话现场"}

    arguments: dict[str, Any] = {}
    if url:
        arguments["url"] = url
    if ref:
        arguments["ref"] = ref
    if action == "type":
        arguments.update({"text": text, "clear": clear})
    if action == "select":
        arguments["value"] = value
    if action == "press":
        arguments["key"] = key
    if action == "scroll":
        arguments.update({"direction": direction, "amount": amount})
    if action == "snapshot":
        arguments.update({
            "interactive_only": interactive_only,
            "max_elements": max_elements,
        })
    if action == "wait_for":
        arguments.update({
            "condition": str(condition or "load"),
            "timeout_ms": max(100, min(30_000, int(timeout_ms or 5000))),
        })
        if text:
            arguments["text"] = text
    if action == "upload":
        try:
            upload = _resolve_upload(
                file_path=file_path,
                attachment_id=attachment_id,
                asset_id=asset_id,
                workspace_id=workspace_id,
            )
        except (OSError, ValueError) as exc:
            return {"error": str(exc)}
        arguments.update(upload)

    response = broker.request(
        turn_id=context.turn_id,
        session_id=context.session_id,
        command=command,
        arguments=arguments,
        cancel_check=context.cancel_check,
        timeout=(max(100, min(30_000, int(timeout_ms or 5000))) / 1000 + 5.0)
        if action == "wait_for"
        else 180.0 if action == "download"
        else 45.0 if action == "upload"
        else 25.0,
    )
    if response.get("status") != "completed":
        failed = {"error": response.get("error") or "Desktop 未能执行网页操作"}
        result = response.get("result")
        if isinstance(result, dict):
            failed.update(result)
        return failed
    result = response.get("result")
    if not isinstance(result, dict):
        return {"status": "completed"}
    if action != "download":
        return result
    try:
        return _store_download(result)
    except (OSError, ValueError) as exc:
        return {"error": str(exc)}


def _as_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value or "").strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    return default


def _resolve_upload(
    *,
    file_path: str,
    attachment_id: str,
    asset_id: str,
    workspace_id: str,
) -> dict[str, Any]:
    if attachment_id:
        item = resolve_current_attachment(attachment_id)
        resolved = Path(str(item.get("local_path") or "")).resolve(strict=True)
        name = str(item.get("name") or resolved.name)
        mime_type = str(item.get("mime_type") or "")
    elif asset_id:
        item = resolve_current_workspace_asset(asset_id, workspace_id=workspace_id)
        resolved = Path(str(item.get("local_path") or "")).resolve(strict=True)
        name = str(item.get("name") or resolved.name)
        mime_type = str(item.get("mime_type") or "")
    elif file_path:
        resolved, error = resolve_readable_path(file_path, exists=True)
        if error or resolved is None:
            raise ValueError(error or "无法解析待上传文件")
        name = resolved.name
        mime_type = ""
    else:
        raise ValueError("upload 需要 file_path、attachment_id 或 asset_id")
    if not resolved.is_file():
        raise ValueError("只能上传当前 Agent 有权读取的文件")
    size = resolved.stat().st_size
    if size <= 0 or size > _MAX_TRANSFER_BYTES:
        raise ValueError("待上传文件为空或超过 10 MB")
    data = resolved.read_bytes()
    return {
        "name": Path(name).name,
        "mime_type": mime_type or mimetypes.guess_type(name)[0] or "application/octet-stream",
        "data_base64": base64.b64encode(data).decode("ascii"),
    }


def _store_download(result: dict[str, Any]) -> dict[str, Any]:
    context = current_tool_execution()
    if context is None or not context.workspace_root:
        raise ValueError("当前 Agent Workspace 不可用")
    encoded = str(result.get("data_base64") or "")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Desktop 返回了无效的下载文件") from exc
    if not data or len(data) > _MAX_TRANSFER_BYTES:
        raise ValueError("网页下载文件为空或超过 10 MB")
    raw_name = Path(str(result.get("name") or "download")).name
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw_name).strip()[:180] or "download"
    root = Path(context.workspace_root).expanduser().resolve()
    downloads = root / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    target = _available_path(downloads, safe_name)
    target.write_bytes(data)
    relative = target.relative_to(root).as_posix()
    return {
        "downloaded": True,
        "name": target.name,
        "mime_type": str(result.get("mime_type") or "application/octet-stream"),
        "size": len(data),
        "path": str(target),
        "workspace_path": relative,
    }


def _available_path(directory: Path, name: str) -> Path:
    candidate = directory / name
    if not candidate.exists():
        return candidate
    source = Path(name)
    for index in range(2, 10_000):
        candidate = directory / f"{source.stem} ({index}){source.suffix}"
        if not candidate.exists():
            return candidate
    raise ValueError("下载目录中同名文件过多")


def register(ctx: Any) -> None:
    ctx.register_agent_tool(Tool(
        name="browser_control",
        description=(
            "在当前对话来源的 Desktop 内嵌浏览器中打开、阅读和操作网页。"
            "先用 open 打开网页，再用 snapshot 读取页面并获得 e1、e2 等元素引用；"
            "点击、输入或选择前应使用最近一次 snapshot 返回的 ref。页面跳转后旧 ref 会失效。"
            "适合搜索资料、查看网页、填写表单以及在已登录网站中执行用户明确要求的操作。"
            "下载前先 snapshot，再对下载链接使用 download；文件会保存到当前 Agent 的 workspace/downloads。"
            "上传时优先直接调用 upload，并把网页上的‘上传/选择文件’按钮 ref 一并传入；upload 会执行真实点击、"
            "拦截文件选择器并注入文件，不要先单独 click 该按钮。若快照直接返回 role=file 控件，也可把该 ref 传给 upload；"
            "页面只有一个现成文件控件时可省略 ref。upload 还需提供当前 Workspace 路径、当前附件或 Workspace Asset。"
            "异步加载时使用 wait_for 等待加载完成、URL、文本或元素状态；操作结果会附带页面变化和新快照。"
            "若 ref 已失效，错误结果会直接附带 recovery_snapshot，应从中选择新 ref 继续。"
            "只能执行受控网页动作，不能执行任意 JavaScript，也不能控制其他桌面软件。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": list(_ACTIONS),
                    "description": "要执行的网页动作",
                },
                "url": {"type": "string", "description": "open 或 navigate 使用的 HTTP/HTTPS 地址"},
                "ref": {
                    "type": "string",
                    "description": "最近一次 snapshot 返回的元素引用，例如 e3；upload 可传上传按钮或 role=file 控件",
                },
                "text": {
                    "type": "string",
                    "description": "type 动作输入的文字；默认替换原内容，追加输入时必须设置 clear=false；结果会返回 observed_value 和 verified",
                },
                "value": {"type": "string", "description": "select 动作选择的值"},
                "key": {"type": "string", "enum": ["Enter", "Tab", "Escape"], "default": "Enter", "description": "press 动作发送的按键"},
                "file_path": {"type": "string", "description": "upload 使用的当前 Agent Workspace 文件路径"},
                "attachment_id": {"type": "string", "description": "upload 使用的当前消息附件 ID 或文件名"},
                "asset_id": {"type": "string", "description": "upload 使用的 Workspace Asset ID"},
                "workspace_id": {"type": "string", "description": "asset_id 所属 Workspace ID"},
                "clear": {"type": "boolean", "default": True, "description": "true 替换原内容，false 在当前内容末尾追加"},
                "direction": {"type": "string", "enum": ["up", "down"], "default": "down"},
                "amount": {"type": "integer", "minimum": 100, "maximum": 4000, "default": 700},
                "interactive_only": {"type": "boolean", "default": False, "description": "snapshot 是否只返回可操作元素"},
                "max_elements": {"type": "integer", "minimum": 20, "maximum": 500, "default": 200},
                "condition": {
                    "type": "string",
                    "enum": ["load", "url", "text", "element", "hidden"],
                    "default": "load",
                    "description": "wait_for 的等待条件：加载完成、URL 包含、文本出现、元素可见或元素隐藏",
                },
                "timeout_ms": {
                    "type": "integer",
                    "minimum": 100,
                    "maximum": 30000,
                    "default": 5000,
                    "description": "wait_for 最长等待毫秒数",
                },
            },
            "required": ["action"],
        },
        func=browser_control,
        source="plugin:browser_control",
        optional=True,
        category="browser",
    ))
