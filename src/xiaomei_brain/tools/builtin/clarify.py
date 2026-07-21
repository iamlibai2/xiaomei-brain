"""Clarify tool — LLM 在不确定时向用户提问。

模式：
  1. 选择题：提供最多 4 个选项，用户选一个或自填
  2. 开放式：不提供选项，用户自由输入

设计参考 Hermes Agent 的 clarify_tool.py，交互逻辑委托给平台注入的回调。

线程安全：
  CLI 模式下 clarify 回调在 Living 线程（非主线程）执行。
  直接 input() 会和主线程的 CLI read loop 竞争 stdin。
  使用双 Event 手递手：Living 线程发请求 → 主线程读输入 → 返回。
"""

from __future__ import annotations

import json
import threading
from typing import Any, Callable

from ..base import tool, Tool

MAX_CHOICES = 4

# 平台注入的回调：callback(question, choices) -> str
# CLI 模式下 set_clarify_callback(_cli_callback)
_clarify_callback: Callable | None = None


def set_clarify_callback(callback: Callable | None) -> None:
    """设置平台的 clarify 交互回调。CLI/渠道各自注入。"""
    global _clarify_callback
    _clarify_callback = callback


# ── 线程安全 clarify 交互（主线程 ↔ Living 线程手递手） ──

_clarify_lock = threading.Lock()
_clarify_request: dict[str, Any] = {}
_clarify_response: list[str] = []

# request_ready: Living 线程 set，主线程 wait/clear
_clarify_request_ready = threading.Event()
# response_ready: 主线程 set，Living 线程 wait/clear
_clarify_response_ready = threading.Event()


def poll_clarify_request() -> dict[str, Any] | None:
    """主线程轮询：取出正在等待的 clarify 请求。无请求时返回 None。"""
    with _clarify_lock:
        if not _clarify_request_ready.is_set():
            return None
        req = dict(_clarify_request)
        _clarify_request.clear()
        _clarify_request_ready.clear()
        _clarify_response.clear()
        return req


def answer_clarify_request(response: str) -> None:
    """主线程回写：设置响应并唤醒 Living 线程。"""
    with _clarify_lock:
        _clarify_response.append(response)
        _clarify_response_ready.set()


def _normalize_choices(choices: Any) -> list[str] | None:
    """规范化 choices 参数（可能来自 LLM 的 JSON 字符串或数组）。

    LLM 传入的 choices 可能是：
    - None
    - list[str]（正常流程）
    - JSON 字符串 '["a", "b"]'（schema 退化时）
    - | 分隔字符串 "a|b|c"（schema 退化为 string 时 LLM 自创格式）
    """
    if choices is None:
        return None
    if isinstance(choices, str):
        try:
            parsed = json.loads(choices)
            if isinstance(parsed, list):
                choices = parsed
            else:
                choices = [choices]
        except (json.JSONDecodeError, TypeError):
            if "|" in choices:
                choices = [c.strip() for c in choices.split("|") if c.strip()]
            else:
                choices = [choices]
    if not isinstance(choices, list):
        return None
    result = [str(c).strip() for c in choices if str(c).strip()]
    if len(result) > MAX_CHOICES:
        result = result[:MAX_CHOICES]
    return result or None


@tool(
    name="clarify",
    description=(
        "当你不确定用户意图、需要用户做出选择或确认时，向用户提问。\n"
        "支持两种模式：\n"
        "  1. 选择题：提供最多 4 个选项（choices 参数），用户选一个或自填「其他」\n"
        "  2. 开放式：不提供 choices 参数，用户自由输入\n"
        "调用后会等待用户回答，返回用户的回复文本。"
    ),
)
def clarify(question: str, choices: list[str] | None = None) -> str:
    """向用户提问，等待回答。

    Args:
        question: 提问内容
        choices: 最多 4 个选项。省略 → 开放式提问
    """
    if not question or not question.strip():
        return json.dumps({"error": "问题不能为空"}, ensure_ascii=False)

    question = question.strip()
    normalized = _normalize_choices(choices)

    if _clarify_callback is None:
        return json.dumps(
            {"error": "clarify 工具在当前环境不可用（未注入交互回调）"},
            ensure_ascii=False,
        )

    try:
        user_response = _clarify_callback(question, normalized)
    except Exception as exc:
        return json.dumps({"error": f"获取用户输入失败: {exc}"}, ensure_ascii=False)

    return json.dumps({
        "question": question,
        "choices_offered": normalized,
        "user_response": str(user_response).strip(),
    }, ensure_ascii=False)


clarify_tool: Tool = clarify


def create_clarify_tool(agent_instance: Any) -> Tool:
    """Create a clarify tool bound to one Agent instance.

    WebSocket conversations use the Agent's InteractionBroker. CLI keeps the
    existing callback implementation for backwards compatibility.
    """

    @tool(name="clarify", description=clarify.description)
    def bound_clarify(question: str, choices: list[str] | None = None) -> str:
        if not question or not question.strip():
            return json.dumps({"error": "问题不能为空"}, ensure_ascii=False)

        question_text = question.strip()
        normalized = _normalize_choices(choices)
        core = agent_instance._get_agent()
        session_id = getattr(core, "session_id", "") or ""
        turn_id = getattr(core, "turn_id", "") or ""
        user_id = getattr(core, "user_id", "") or ""
        living = getattr(agent_instance, "_living", None)
        broker = getattr(living, "_interaction_broker", None)

        if broker is not None and session_id not in ("", "main") and not session_id.startswith("cli-"):
            try:
                user_response = broker.request(
                    question=question_text,
                    choices=normalized,
                    session_id=session_id,
                    user_id=user_id,
                    turn_id=turn_id,
                )
            except TimeoutError as exc:
                return json.dumps({"error": str(exc)}, ensure_ascii=False)
            return json.dumps({
                "question": question_text,
                "choices_offered": normalized,
                "user_response": user_response,
            }, ensure_ascii=False)

        return clarify.execute(question=question_text, choices=normalized)

    return bound_clarify


# ── CLI 回调（线程安全） ─────────────────────────────────

def _cli_callback(question: str, choices: list[str] | None) -> str:
    """CLI 交互 — Living 线程发送请求，主线程读 stdin。

    流程：
      Living 线程: set request_ready → wait response_ready → 返回
      主线程:      poll request → print + input() → answer response
    """
    # 优先使用 cli_selector（箭头键选择，curses 独立于 stdin，无竞争）
    try:
        from .cli_selector import pick_one
        return pick_one(question, choices)
    except ImportError:
        pass

    # Fallback：双 Event 手递手
    global _clarify_request, _clarify_response
    with _clarify_lock:
        _clarify_request["question"] = question
        _clarify_request["choices"] = choices
        _clarify_response.clear()
        _clarify_request_ready.set()

    # 等待主线程处理（超时 60s）
    if not _clarify_response_ready.wait(timeout=60):
        _clarify_request_ready.clear()
        return json.dumps({"error": "clarify 超时：主线程未响应"}, ensure_ascii=False)

    _clarify_response_ready.clear()
    with _clarify_lock:
        if _clarify_response:
            return _clarify_response[0]
    return json.dumps({"error": "clarify 未收到回复"}, ensure_ascii=False)
