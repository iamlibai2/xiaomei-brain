"""
消息处理公用工具
"""

from typing import Any


def scrub_tool_calls_incomplete(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    清理消息列表中不完整的 tool_calls。

    DeepSeek 等 API 要求：如果 assistant 有 tool_calls，
    则必须有对应数量的 tool 响应消息。
    streaming 中途失败会导致 tool_calls 残缺，引发 400。

    处理逻辑：
    1. 收集所有 assistant 的 tool_call_ids
    2. 收集所有有对应 tool 响应的 tool_call_ids
    3. 如果 assistant 的 tool_calls 中任何一个缺失响应，剥离整个 tool_calls 字段

    Args:
        messages: OpenAI 格式消息列表

    Returns:
        清理后的消息列表（原列表不变，返回新列表）
    """
    if not messages:
        return messages

    # 第一遍：收集 assistant 的 tool_call_ids
    assistant_tc_ids: set[str] = set()
    for m in messages:
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls", []):
                tc_id = tc.get("id", "")
                if tc_id:
                    assistant_tc_ids.add(tc_id)

    # 第二遍：收集有对应 tool 响应的 tool_call_ids
    tool_response_ids: set[str] = set()
    for m in messages:
        if m.get("role") == "tool":
            tc_id = m.get("tool_call_id", "")
            if tc_id and tc_id in assistant_tc_ids:
                tool_response_ids.add(tc_id)

    # 第三遍：重建消息列表，剥离不完整的 tool_calls
    result: list[dict[str, Any]] = []
    for m in messages:
        msg = dict(m)
        if msg.get("role") == "assistant":
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                missing = [tc for tc in tool_calls if tc.get("id") not in tool_response_ids]
                if missing:
                    del msg["tool_calls"]
        result.append(msg)

    return result
