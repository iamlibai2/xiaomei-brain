"""Milestone 提取器 — 从经验流提取今日关键节点。

纯规则，不调 LLM。经验流事件类型已有明确标签，直接用关键词匹配即可。
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── 感兴趣的事件类型 ────────────────────────────────────────

_MILESTONE_TYPES = {
    "tool_exec",
    "internal_reflection",
    "internal_action",
    "dream",
    "internal_thought",
    "drive_event",
    "user_msg",
}

# ── 用户消息间隔阈值（秒）──────────────────────────────────
_USER_MSG_GAP = 1800  # 30 分钟：超过此间隔视为新对话起点

# ── 生命周期状态映射 ────────────────────────────────────────
_LIFECYCLE_LABELS: dict[str, tuple[str, str, float]] = {
    # state_value → (中文标签, milestone type, importance)
    "dormant":  ("陷入沉睡", "lifecycle", 0.8),
    "waking":   ("从沉睡中醒来", "lifecycle", 0.8),
    "awake":    ("恢复清醒，开始工作", "lifecycle", 0.7),
    "idle":     ("进入空闲状态", "lifecycle", 0.5),
    "sleeping": ("休息中", "lifecycle", 0.6),
    "dreaming": ("进入梦境", "lifecycle", 0.7),
}

# ── 产出关键词 ──────────────────────────────────────────────
_OUTPUT_KEYWORDS = ["write_file", "创建", "产出", "生成", "保存", "写入"]
_COMPLETION_KEYWORDS = ["完成", "解决", "通过", "成功", "达成"]
_STUCK_KEYWORDS = ["卡住", "失败", "放弃", "阻塞", "困难", "无法"]
_LEARNING_KEYWORDS = ["学到", "理解", "掌握", "发现", "认识到", "学会了"]


def extract_milestones(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从经验流事件中提取今日关键节点。

    Args:
        events: experience_stream.get_recent() 的结果列表

    Returns:
        [{type, content, created_at, importance}, ...]
        按时间升序，最多 15 条。
    """
    if not events:
        return []

    # 按时间升序排列（get_recent 返回的是倒序）
    events = sorted(events, key=lambda e: e.get("created_at", 0))

    milestones: list[dict[str, Any]] = []
    seen: set[str] = set()
    last_user_msg_time: float = 0

    for event in events:
        etype = event.get("type", "")
        if etype not in _MILESTONE_TYPES:
            continue

        content = event.get("content", "").strip()
        if not content:
            continue

        # 用户消息 — 在主循环处理（需要跨事件上下文）
        if etype == "user_msg":
            ts = event.get("created_at", 0)
            if last_user_msg_time > 0 and ts - last_user_msg_time >= _USER_MSG_GAP:
                gap_min = int((ts - last_user_msg_time) / 60)
                who = event.get("user_id", "").strip()
                who_str = f"{who}" if who else "对方"
                milestone = {
                    "type": "social",
                    "content": f"{who_str}来了（沉默{gap_min}分钟后）",
                    "created_at": ts,
                    "importance": 0.6,
                }
                dedup_key = f"social:{ts}"
                if dedup_key not in seen:
                    seen.add(dedup_key)
                    milestones.append(milestone)
            last_user_msg_time = ts
            continue

        milestone = _classify_event(etype, content, event)
        if not milestone:
            continue

        # 去重：相同产出不重复
        dedup_key = f"{milestone['type']}:{milestone['content'][:60]}"
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        milestones.append(milestone)

    # 按重要性排序，取前 15
    milestones.sort(key=lambda m: m.get("importance", 0), reverse=True)
    return milestones[:15]


def _classify_event(
    etype: str,
    content: str,
    event: dict[str, Any],
) -> dict[str, Any] | None:
    """分类单个事件，返回 milestone dict 或 None。"""

    # 梦境 — 直接采纳
    if etype == "dream":
        return {
            "type": "dream",
            "content": f"做了个梦：{content[:150]}",
            "created_at": event.get("created_at", 0),
            "importance": 0.5,
        }

    # 生命周期 — 状态切换
    if etype == "internal_action":
        metadata = _parse_metadata(event.get("metadata", "{}"))
        if isinstance(metadata, dict):
            state_val = metadata.get("new_state", "")
            if state_val in _LIFECYCLE_LABELS:
                label, mtype, imp = _LIFECYCLE_LABELS[state_val]
                return {
                    "type": mtype,
                    "content": label,
                    "created_at": event.get("created_at", 0),
                    "importance": imp,
                }
        return None

    # 内部反思 — 检查完成/卡住
    if etype == "internal_reflection":
        if _any_keyword(content, _COMPLETION_KEYWORDS):
            return {
                "type": "milestone",
                "content": content[:150],
                "created_at": event.get("created_at", 0),
                "importance": 0.7,
            }
        if _any_keyword(content, _STUCK_KEYWORDS):
            return {
                "type": "stuck",
                "content": content[:150],
                "created_at": event.get("created_at", 0),
                "importance": 0.6,
            }
        return None

    # 工具执行 — 只关注产出类
    if etype == "tool_exec":
        metadata = _parse_metadata(event.get("metadata", "{}"))
        action = metadata.get("action", content[:80]) if isinstance(metadata, dict) else content[:80]
        if _any_keyword(action, _OUTPUT_KEYWORDS):
            # 尝试提取文件名
            filename = _extract_filename(action, content)
            summary = f"产出：{filename}" if filename else f"执行了：{content[:120]}"
            return {
                "type": "output",
                "content": summary,
                "created_at": event.get("created_at", 0),
                "importance": 0.4,
            }
        return None

    # 内部思考 — 学习类
    if etype == "internal_thought":
        if _any_keyword(content, _LEARNING_KEYWORDS):
            return {
                "type": "learning",
                "content": content[:150],
                "created_at": event.get("created_at", 0),
                "importance": 0.5,
            }
        return None

    # 驱动事件 — 只看多巴胺峰值
    if etype == "drive_event":
        metadata = _parse_metadata(event.get("metadata", "{}"))
        if isinstance(metadata, dict):
            changes = metadata.get("changes", {})
            dopamine_delta = 0
            if isinstance(changes, dict):
                for k, v in changes.items():
                    if "dopamine" in k:
                        dopamine_delta += abs(float(v)) if isinstance(v, (int, float)) else 0
            if dopamine_delta > 0.2:
                return {
                    "type": "emotional_peak",
                    "content": f"有一阵满足感（多巴胺+{dopamine_delta:.1f}）",
                    "created_at": event.get("created_at", 0),
                    "importance": 0.3,
                }
        return None

    return None


def _parse_metadata(raw) -> dict[str, Any]:
    """解析 experience_stream 的 metadata 字段（可能是 JSON 字符串或 dict）。"""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _any_keyword(text: str, keywords: list[str]) -> bool:
    return any(k in text for k in keywords)


def _extract_filename(action: str, content: str) -> str:
    """尝试从工具调用内容中提取文件名。"""
    import re
    for candidate in [action, content]:
        m = re.search(r"([\w/\-\.]+\.(md|py|json|yaml|txt|toml))", candidate)
        if m:
            return m.group(1)
    return ""
