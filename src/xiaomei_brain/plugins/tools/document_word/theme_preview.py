"""Expose the bundled, Word-rendered theme preview to an Agent turn."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from xiaomei_brain.tools.base import Tool
from xiaomei_brain.tools.execution_context import current_tool_execution

from .theme import WORD_THEME_PRESETS


_ASSET_NAME = "theme-showcase.png"
_DISPLAY_NAME = "Word主题预览.png"


def preview_word_themes() -> dict[str, Any]:
    """Copy the immutable theme showcase into the current Agent workspace."""
    context = current_tool_execution()
    if context is None:
        return {"error": "preview_word_themes 只能在 Agent 工具调用期间使用"}

    root_value = context.output_root or context.workspace_root
    if not root_value:
        return {"error": "当前执行现场没有可用的输出目录"}

    source = Path(__file__).parent / "assets" / _ASSET_NAME
    if not source.is_file():
        return {"error": "Word 主题预览资源缺失，请重新安装 document_word 插件"}

    # Separate sessions avoid overwriting a preview that another concurrent
    # conversation is about to present, while retaining a friendly file name.
    session_key = hashlib.sha256(
        (context.session_id or context.tool_call_id).encode("utf-8"),
    ).hexdigest()[:12]
    output_dir = Path(root_value).resolve() / "theme-previews" / session_key
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / _DISPLAY_NAME
    shutil.copyfile(source, output)

    return {
        "success": True,
        "type": "word_theme_preview",
        "output_path": str(output),
        "themes": list(WORD_THEME_PRESETS),
        "next_action": (
            "先调用 present_artifacts 展示此预览图，再调用 clarify 让用户选择主题"
        ),
    }


def create_preview_word_themes_tool() -> Tool:
    return Tool(
        name="preview_word_themes",
        description=(
            "Show one real Microsoft Word-rendered comparison image for the built-in "
            "Word themes. Use it only when a new Word document needs a meaningful visual "
            "style choice and the person has not already specified a theme. After this "
            "tool, present its output_path, then use clarify with the four returned themes."
        ),
        parameters={"type": "object", "properties": {}, "required": []},
        func=preview_word_themes,
        category="document",
    )
