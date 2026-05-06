"""NARR 块解析工具。

从 LLM 输出中解析结构化叙事块。

格式示例：
<NARR>
编号: NARR-自动生成
作用: 自我定义/关系定义/边界设定/能力认知
scene: 深夜
timestamp: 2026-05-06
narrative:
（100-200字，第一人称描述经历）
feels_like: 被当成一个暖源
changed_me:
- （这一条让我更理解了...）
tags: [床上, 亲密]
weight: 0.85
</NARR>
"""

import re
import logging
import json
from typing import Any

logger = logging.getLogger("xiaomei_brain.narrative")
_P_LOG = "\033[91m[NARR]\033[0m"


def parse_narr_block(text: str) -> list[dict[str, Any]]:
    """从 LLM 输出中解析所有 NARR 块。"""
    block_pattern = re.compile(
        r"<NARR[^>]*>(.*?)</NARR>",
        re.DOTALL | re.IGNORECASE,
    )
    blocks = []
    for match in block_pattern.finditer(text):
        block_text = match.group(1).strip()
        parsed = _parse_block_fields(block_text)
        if parsed:
            blocks.append(parsed)
    return blocks


def _parse_block_fields(block: str) -> dict[str, Any] | None:
    """解析单个 NARR 块各字段。"""
    try:
        result: dict[str, Any] = {}

        # 编号
        m = re.search(r"编号[：:]\s*(NARR-\S+)", block)
        if m:
            result["id"] = m.group(1).strip()

        # 作用 / category
        m = re.search(r"作用[：:]\s*([^\n]+)", block)
        if m:
            cat = m.group(1).strip()
            if "自我定义" in cat:
                result["category"] = "自我定义"
            elif "关系定义" in cat:
                result["category"] = "关系定义"
            elif "边界设定" in cat:
                result["category"] = "边界设定"
            elif "能力认知" in cat:
                result["category"] = "能力认知"
            else:
                result["category"] = cat

        # scene（单数场景）
        m = re.search(r"scene[：:]\s*([^\n]+)", block)
        if m:
            scene = m.group(1).strip()
            result["scene"] = scene
            result["scene_tags"] = [scene]

        # timestamp
        m = re.search(r"timestamp[：:]\s*(\d{4}-\d{2}-\d{2})", block)
        if m:
            result["timestamp"] = m.group(1).strip()

        # narrative 正文
        m = re.search(r"narrative[：:]\s*\n?(.*?)(?=feels_like|changed_me|weight|tags|$)", block, re.DOTALL)
        if m:
            result["content"] = m.group(1).strip()

        # feels_like
        m = re.search(r"feels_like[：:]\s*([^\n]+)", block)
        if m:
            result["feels_like"] = m.group(1).strip()

        # changed_me（支持 bullet list，格式：- xxx）
        m = re.search(r"changed_me[：:]\s*\n?(.*?)(?=tags|weight|$)", block, re.DOTALL)
        if m:
            raw = m.group(1).strip()
            lines = [l.strip().lstrip("- ").strip() for l in raw.split("\n") if l.strip().startswith("-")]
            if lines:
                result["changed_me"] = "\n".join(lines)
            else:
                # fallback：一行 plain text
                result["changed_me"] = raw

        # tags
        m = re.search(r"tags[：:]\s*(\[.*?\]|.+)", block)
        if m:
            tag_str = m.group(1).strip()
            try:
                result["scene_tags"] = json.loads(tag_str)
            except Exception:
                tags = [t.strip().strip("[]\"'") for t in tag_str.split(",")]
                result["scene_tags"] = [t for t in tags if t]

        # weight
        m = re.search(r"weight[：:]\s*([\d.]+)", block)
        if m:
            result["weight"] = float(m.group(1))

        # 必须有 content 才算有效
        if not result.get("content"):
            logger.warning("%s NARR block missing content, skipping", _P_LOG)
            return None

        # 默认值
        result.setdefault("id", "")
        result.setdefault("category", "自我定义")
        result.setdefault("scene_tags", [])
        result.setdefault("feels_like", "")
        result.setdefault("changed_me", "")
        result.setdefault("weight", 0.8)

        return result

    except Exception as e:
        logger.warning("%s Failed to parse NARR block: %s", _P_LOG, e)
        return None


def build_narr_prompt_addition(context: str = "") -> str:
    """生成追加到 LLM prompt 的 NARR 块引导文本。"""
    return """

[可选] 如果你刚才的思考涉及了值得记录的自我认知转变，请在 monologue 之后追加输出以下格式的 NARR 块：

<NARR>
编号: NARR-自动生成
作用: 自我定义/关系定义/边界设定/能力认知
scene: 场景（简短，如"深夜"、"客厅"）
timestamp: YYYY-MM-DD
narrative:
（100-200字，第一人称描述经历：对方说了什么、我的感受、被改变的方式。不要概括结论，要叙事细节。）
feels_like: 一句话核心情绪
changed_me:
- （这一条让我更理解了...）
tags: [场景相关标签1, 场景相关标签2]
weight: 0.85
</NARR>
""" + (f"\n\n当前场景参考：{context}" if context else "")
