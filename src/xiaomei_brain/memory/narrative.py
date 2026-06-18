"""NARR 块解析 + 叙事记忆学习。

从 LLM 输出中解析结构化叙事块，以及从对话记录中检测和生成新的叙事记忆。

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

learn_narratives() 是对话驱动的叙事记忆学习入口：
- 从 RoundScheduler 每 20 轮触发（via ConversationDriver）
- 增量查询对话记录，独立 LLM 调用生成 NARR 块
- 替代原来 L2 tick_emergence() 尾部定时器驱动的 NARR 生成
"""

from __future__ import annotations

import re
import logging
import json
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from xiaomei_brain.llm.client import LLMClient

logger = logging.getLogger("xiaomei_brain.narrative")
_P_LOG = "\033[91m[NARR]\033[0m"


def learn_narratives(
    conversation_db: Any,
    llm: LLMClient,
    longterm_memory: Any,
    since: float | None = None,
    user_id: str = "global",
    agent_name: str = "我",
    consciousness_context: str = "",
) -> list[str]:
    """从对话记录中检测并生成新的叙事记忆。

    增量查询对话记录，独立 LLM 调用生成 NARR 块，
    解析后存入 narrative_memories 表。

    Args:
        conversation_db: ConversationDB 实例
        llm: LLM 客户端
        longterm_memory: LongTermMemory 实例
        since: 增量查询起始时间戳（UNIX 秒），不传则取最近 50 条
        user_id: 用户标识
        agent_name: Agent 名称（用于 prompt）
        consciousness_context: 意识上下文（来自 build_simple_context）

    Returns:
        新生成的 NARR ID 列表
    """
    # 1. 取增量对话
    recent = conversation_db.get_recent(50, since=since, user_id=user_id)
    if not recent:
        logger.debug("%s 无增量对话，跳过", _P_LOG)
        return []

    # 2. 格式化对话
    lines: list[str] = []
    for m in recent:
        role = m.get("role", "")
        content = m.get("content", "")[:500]
        if role == "user":
            lines.append(f"[对方] {content}")
        elif role == "assistant":
            lines.append(f"[{agent_name}] {content}")
    recent_dialogue = "\n".join(lines)

    if len(recent_dialogue) < 100:
        logger.debug("%s 对话太短 (%d 字)，跳过", _P_LOG, len(recent_dialogue))
        return []

    logger.info("%s 检测对话 (%d 条, %d 字)...", _P_LOG, len(recent), len(recent_dialogue))

    # 3. 构建 prompt + LLM 调用
    from ..prompts.templates_v2 import NARR_LEARN_PROMPT

    prompt = NARR_LEARN_PROMPT.format(
        agent_name=agent_name,
        consciousness_context=consciousness_context,
        recent_dialogue=recent_dialogue,
    )

    try:
        response = llm.chat(
            messages=[{"role": "user", "content": prompt}],
            tools=None,
        )
    except Exception as e:
        logger.warning("%s LLM 调用失败: %s", _P_LOG, e)
        return []

    narr_text = response.content or ""
    if not narr_text or "NARR" not in narr_text:
        logger.debug("%s 无 NARR 块生成", _P_LOG)
        return []

    # 4. 解析并存储
    narr_blocks = parse_narr_block(narr_text)
    if not narr_blocks:
        logger.debug("%s 未解析到有效 NARR 块", _P_LOG)
        return []

    new_ids: list[str] = []
    for nb in narr_blocks:
        try:
            nm_id = longterm_memory.store_narrative_memory(
                category=nb.get("category", "自我定义"),
                content=nb.get("content", ""),
                scene_tags=nb.get("scene_tags", []),
                feels_like=nb.get("feels_like", ""),
                changed_me=nb.get("changed_me", ""),
                weight=nb.get("weight", 0.8),
                related_narrative_id=None,
                source="round",
                timestamp=nb.get("timestamp"),
                user_id=user_id,
            )
            new_ids.append(nm_id)
            logger.info("%s 学到新叙事: %s [%s]", _P_LOG, nm_id, nb.get("category", ""))
        except Exception as e:
            logger.warning("%s 存储失败: %s", _P_LOG, e)

    return new_ids


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
    # NARR_BLOCK_INSTRUCTION moved to prompts/prompts_bak.py (zero-call)
    return ""
