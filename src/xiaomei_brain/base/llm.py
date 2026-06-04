"""LLM 客户端封装，支持多 Provider、重试逻辑、流式与非流式调用。"""

from __future__ import annotations

import datetime
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ── Per-agent LLM 日志目录 ──────────────────────────────────
_log_agent_id: str | None = None


def set_log_agent(agent_id: str) -> None:
    """设置当前 agent ID，LLM 日志写入 {agent_id}/logs/llm/。"""
    global _log_agent_id
    _log_agent_id = agent_id


def _get_llm_log_dir() -> str:
    if _log_agent_id:
        return f"~/.xiaomei-brain/{_log_agent_id}/logs/llm"
    return "~/.xiaomei-brain/global/logs"


# region 数据结构

@dataclass
class ToolCall:
    """LLM 生成的工具调用请求。

    Attributes:
        id: 工具调用的唯一标识，用于关联 tool_call_id。
        name: 要调用的工具名称（函数名）。
        arguments: 工具函数的参数，dict 格式。
    """

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatResponse:
    """LLM 响应结果。

    Attributes:
        content: 文本回复内容（可能为 None）。
        tool_calls: 工具调用列表（若无工具调用则为空列表）。
        finish_reason: 结束原因，如 "stop" / "tool_calls" / "length"。
    """

    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""
    reasoning_content: str | None = None  # DeepSeek thinking mode 推理过程

    @property
    def has_tool_calls(self) -> bool:
        """是否有工具调用。"""
        return len(self.tool_calls) > 0


class LLMError(Exception):
    """LLM 调用异常。

    Attributes:
        retryable: 本次错误是否可重试。429/5xx/网络错误为 True，
                   认证失败 / 参数错误为 False。
        status_code: HTTP 状态码（0 表示非 HTTP 错误）。
    """

    def __init__(self, message: str, retryable: bool = False, status_code: int = 0) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class FatalLLMError(BaseException):
    """LLM 致命错误 —— 程序不应继续运行。

    继承 BaseException（而非 Exception），自动穿透所有 ``except Exception`` 块，
    类似 SystemExit / KeyboardInterrupt 的行为。

    触发条件：401（认证失败）/ 402（欠费）/ 403（禁止访问）。
    """

    def __init__(self, message: str, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code

# endregion


# ── 流式标签缓冲（模块级，chat_stream 使用）──────────────────────────

# 已知标签前缀（仅真正的 partial，不含完整标签），按长度降序排列
_TAG_PREFIXES = sorted(
    ["</MEMORY", "</MEMOR", "</MEMO", "</MEM", "</ME", "</M", "</", "<",
     "<MEMORY", "<MEMOR", "<MEMO", "<MEM", "<ME", "<M",
     "</think", "</thin", "</thi", "</th", "</t",
     "<think", "<thin", "<thi", "<th", "<t"],
    key=len, reverse=True,
)


def _save_partial_tag(text: str) -> str:
    """检测 text 末尾是否是一个被截断的标签开头，返回应缓冲的部分。

    用于流式 chunk 边界：当标签（如 <MEMORY>）被分割在两个 chunk 中时，
    将第一个 chunk 的尾部缓冲拼接第二个 chunk 的前部，确保标签检测不遗漏。
    """
    for prefix in _TAG_PREFIXES:
        if text.endswith(prefix):
            return prefix
    return ""


def _save_partial_closing_tag(text: str, tag: str) -> str:
    """检测 text 末尾是否是指定闭合标签的被截断前缀，返回应缓冲的部分。

    用于 in_think/in_memory 为 True 时，检测被分割的闭合标签后缀。
    例如 tag="</MEMORY>"，text="... </MEM" → 返回 "</MEM"。
    """
    for n in range(len(tag) - 1, 0, -1):
        prefix = tag[:n]
        if text.endswith(prefix):
            return prefix
    return ""


class LLMClient:
    """LLM API 客户端，支持智谱AI、火山引擎、OpenAI 等 Provider。

    主要能力：
    - 统一的消息格式转换（内部格式 → API 格式）
    - 自动重试：429 / 5xx / 超时 / 网络错误，指数退避
    - 同角色消息合并：防止 MiniMax 等平台连续同角色导致 400
    - 思考块过滤：移除 <think>...</think> 标签内容
    - 日志分级：普通调用记录 INFO，提取等后台调用记录 DEBUG

    Usage:
        client = LLMClient(
            model="glm-5",
            api_key="xxx",
            base_url="https://open.bigmodel.cn/api/paas/v4",
            provider="zhipu",
        )
        response = client.chat(messages=[...], tools=[...])
    """

    # 可重试的 HTTP 状态码
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    # 致命的 HTTP 状态码 —— 程序不应继续运行
    FATAL_STATUS_CODES = {401, 402, 403}

    # 默认重试次数和超时时间
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_TIMEOUT = 60

    # 连续失败阈值 —— 超过此次数视为 API 不可用，触发 FatalLLMError
    MAX_CONSECUTIVE_FAILURES = 10

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str,
        provider: str | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: int = DEFAULT_TIMEOUT,
        # ── 新增：备用 provider + 内感受 ──
        fallback_configs: list[dict[str, str]] | None = None,
        interoception: Any = None,
    ) -> None:
        """初始化 LLM 客户端。

        Args:
            model: 模型名称，如 "glm-5"、"doubao-pro-32k"。
            api_key: API 密钥。
            base_url: API 端点基础地址。
            provider: Provider 名称（zhipu / volcengine / openai），用于日志标识。
            max_retries: 最大重试次数，默认 3 次。
            timeout: 请求超时时间（秒），默认 60 秒。
            fallback_configs: 备用 provider 列表，每项 {"model", "base_url", "api_key", "name"}。
            interoception: Interoception 实例（供退避/切换/错误记录）。
        """
        self.provider = provider
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.max_retries = max_retries
        self.timeout = timeout

        # ── 备用 provider ──
        self._fallback_configs = fallback_configs or []
        self._fallback_index = -1  # -1 = 主配置
        self._interoception = interoception

        # ── Token 回调（供 Drive 层记录累计消耗）──
        self._token_callback: Any = None

        # ── 最近一次调用追踪 ──
        self._last_call_latency_ms: float = 0.0
        self._last_call_error: bool = False

        # ── 退避状态 ──
        self._backoff_until: float = 0.0

        # ── 连续失败计数 ──
        self._consecutive_failures: int = 0

        # 参数校验
        if not self.api_key:
            raise ValueError("API key 不能为空")
        if not self.base_url:
            raise ValueError("base_url 不能为空")
        if not self.model:
            raise ValueError("model 不能为空")

    def set_model(self, model: str, base_url: str | None = None, api_key: str | None = None) -> None:
        """切换模型（无需重启，下次 API 调用生效）。

        Args:
            model: 新模型名称
            base_url: 可选，切换 API 端点
            api_key: 可选，切换 API 密钥
        """
        self.model = model
        if base_url:
            self.base_url = base_url
        if api_key:
            self.api_key = api_key

    # ── 备用 provider ──────────────────────────────────────────

    def _get_active_config(self) -> dict[str, str]:
        """返回当前生效的 base_url/api_key/model。"""
        if self._fallback_index >= 0 and self._fallback_index < len(self._fallback_configs):
            fc = self._fallback_configs[self._fallback_index]
            return {
                "model": fc.get("model", self.model),
                "base_url": fc.get("base_url", self.base_url),
                "api_key": fc.get("api_key", self.api_key),
            }
        return {"model": self.model, "base_url": self.base_url, "api_key": self.api_key}

    def switch_to_fallback(self) -> bool:
        """切换到下一个备用 provider。返回 True 表示切换成功。"""
        self._fallback_index += 1
        if self._fallback_index >= len(self._fallback_configs):
            logger.error("[LLM] 所有备用 provider 已耗尽")
            return False
        cfg = self._fallback_configs[self._fallback_index]
        logger.warning("[LLM] 切换到备用 provider: %s (model=%s)",
                       cfg.get("name", "unknown"), cfg.get("model", "unknown"))
        return True

    def reset_to_primary(self) -> None:
        """切回主 provider。"""
        if self._fallback_index >= 0:
            logger.info("[LLM] 切回主 provider")
            self._fallback_index = -1

    def apply_backoff(self, seconds: float) -> None:
        """执行退避睡眠。"""
        if seconds > 0:
            self._backoff_until = time.time() + seconds
            logger.warning("[LLM] 退避 %.1fs", seconds)
            time.sleep(seconds)

    def _record_call(self, latency_ms: float, is_error: bool, tokens: int = 0,
                     status_code: int = 0) -> None:
        """记录一次调用结果给 Interoception 和 Token 回调。"""
        self._last_call_latency_ms = latency_ms
        self._last_call_error = is_error

        # ── 交给 Interoception 统一管理（返回当前连续失败数）──
        consecutive = 0
        if self._interoception:
            try:
                consecutive = self._interoception.record_llm_call(latency_ms, is_error)
            except Exception as e:
                logger.warning("Interoception record_llm_call failed: %s", e)

        # ── 连续失败检测（仅 HTTP 状态码 >= 400；网络错误由 Interoception SOS 处理）──
        if is_error and status_code >= 400:
            if consecutive >= self.MAX_CONSECUTIVE_FAILURES:
                raise FatalLLMError(
                    f"LLM 连续 {consecutive} 次 HTTP {status_code} 错误，程序终止",
                    status_code=status_code,
                )
        if self._token_callback and tokens > 0:
            try:
                self._token_callback(tokens)
            except Exception as e:
                logger.warning("Token callback failed: %s", e)

    def _estimate_call_tokens(self, api_messages: list[dict], response_content: str | None) -> int:
        """估算一次 LLM 调用的 token 消耗（输入+输出）。"""
        from xiaomei_brain.base.message_utils import estimate_tokens
        total = 0
        for m in api_messages:
            content = m.get("content", "")
            if isinstance(content, str):
                total += estimate_tokens(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        total += estimate_tokens(part.get("text", ""))
        if response_content:
            total += estimate_tokens(response_content)
        return total

    # region 公共接口

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        log_level: int | None = None,
    ) -> ChatResponse:
        """发送对话消息并获取回复（非流式）。

        Args:
            messages: 对话消息列表，每条消息为 {"role": "...", "content": "..."}。
                     工具调用场景会包含 {"role": "assistant", "tool_calls": [...]} 和
                     {"role": "tool", "tool_call_id": "...", "content": "..."}。
            tools: 可选的工具定义列表（OpenAI tools 格式）。
            log_level: 日志级别覆盖，如 logging.DEBUG（记忆提取用），
                     默认 logging.INFO。

        Returns:
            ChatResponse，包含文本内容和/或工具调用列表。

        Raises:
            LLMError: 不可重试的错误（如认证失败）或重试次数耗尽。
        """
        api_messages = self._build_messages(messages)

        # ── Full input/output logging ──────────────────────────────
        import threading
        _call_id = threading.current_thread().name
        _sep = "=" * 80
        logger.debug("\n%s", _sep)
        logger.debug("[LLM CALL %s] model=%s | %d msgs | tools=%s", _call_id, self.model, len(api_messages), bool(tools))
        for i, m in enumerate(api_messages):
            role = m.get("role", "?")
            content = m.get("content", "")
            tc = m.get("tool_calls")
            tc_id = m.get("tool_call_id", "")
            logger.debug("--- msg[%d] role=%s tc=%s tc_id=%s content_len=%d ---", i, role, bool(tc), tc_id[:20] if tc_id else "", len(content) if content else 0)
            logger.debug("%s", (content or "")[:3000])
            if tc:
                logger.debug("tool_calls: %s", json.dumps(tc, ensure_ascii=False, indent=2)[:500])
        if tools:
            logger.debug("--- tools (%d) ---", len(tools))
            logger.debug("%s", json.dumps(tools, ensure_ascii=False, indent=2)[:1000])
        logger.debug(_sep)
        # ── End logging ────────────────────────────────────────────

        payload = {
            "model": self.model,
            "messages": api_messages,
        }
        if tools:
            payload["tools"] = tools

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        resp = self._request_with_retry(
            payload=payload,
            headers=headers,
            log_level=log_level,
        )
        # ── Log response ──────────────────────────────────────────
        logger.debug("[LLM RESPONSE %s] content_len=%d tool_calls=%d finish=%s",
                     _call_id, len(resp.content) if resp.content else 0, len(resp.tool_calls), resp.finish_reason)
        if resp.content:
            logger.debug("%s", resp.content[:1000])
        if resp.tool_calls:
            logger.debug("tool_calls: %s", json.dumps([{"id": tc.id, "name": tc.name, "args": tc.arguments} for tc in resp.tool_calls], ensure_ascii=False, indent=2)[:500])
        logger.debug("=" * 80 + "\n")
        # ── End response ──────────────────────────────────────────

        # Save request + response to JSON log
        self._save_llm_log(payload, {
            "content": resp.content,
            "tool_calls": [{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in resp.tool_calls],
            "finish_reason": resp.finish_reason,
            "reasoning_content": resp.reasoning_content,
        })

        return resp

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Generator[str, None, None]:
        """真流式生成器 — 逐个 yield SSE chunk，不再缓冲。

        生成器结束后，通过 self._last_stream_response 获取 ChatResponse。
        """
        import datetime as _dt
        import os as _os

        api_messages = self._build_messages(messages)

        payload = {
            "model": self.model,
            "messages": api_messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Save payload to JSONL log
        self._save_llm_log(payload)

        _t0 = time.time()
        _msg_preview = (api_messages[0].get("content") or "")[:40] if api_messages else ""
        _has_tools = bool(tools)

        def _log(success: bool, detail: str = ""):
            elapsed = time.time() - _t0
            ts = _dt.datetime.now().strftime("%H:%M:%S")
            detail_clean = detail.replace("\n", "\\n")[:80] if detail else ""
            msg = "%s model=%s msgs=%d tools=%s elapsed=%.2fs %s" % (
                ts, self.model, len(api_messages), _has_tools, elapsed, detail_clean,
            )
            if success:
                logger.info("\033[91m[LLM OK STREAM] %s\033[0m", msg)
            else:
                logger.info("[LLM ERR STREAM] %s", msg)

        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=self.timeout,
            stream=True,
        )
        if response.status_code >= 400:
            logger.warning(
                "[LLM STREAM DEBUG] HTTP %d | msgs=%d roles=%s | msg0_len=%d | tools=%s",
                response.status_code,
                len(api_messages),
                [m.get("role") for m in api_messages],
                len(api_messages[0].get("content", "") if api_messages else ""),
                bool(tools),
            )
        if response.status_code in self.FATAL_STATUS_CODES:
            raise FatalLLMError(
                f"LLM API 致命错误 (HTTP {response.status_code}): {response.text[:200]}",
                status_code=response.status_code,
            )
        response.raise_for_status()

        # Parse SSE stream
        self._reasoning_end_yielded = False
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls_acc: dict[int, dict] = {}
        finish_reason = ""
        in_think = False
        in_memory = False
        reasoning_yielded = False
        _tag_buffer = ""  # 跨 chunk 缓冲：防止标签被分割（如 <MEM 和 ORY>）

        try:
            for line in response.iter_lines():
                if not line:
                    continue
                if isinstance(line, bytes):
                    try:
                        line = line.decode("utf-8")
                    except UnicodeDecodeError:
                        line = line.decode("utf-8", errors="replace")
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break

                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue

                choices = chunk.get("choices")
                if not choices:
                    continue
                choice = choices[0]
                delta = choice.get("delta", {})
                finish_reason = choice.get("finish_reason", "") or finish_reason

                if delta.get("reasoning_content"):
                    rc = delta["reasoning_content"]
                    reasoning_parts.append(rc)
                    if not reasoning_yielded:
                        yield "\n\033[2m"
                        reasoning_yielded = True
                    yield rc

                if "content" in delta and delta["content"] and not delta.get("reasoning_content"):
                    content_parts.append(delta["content"])
                    text = _tag_buffer + delta["content"]
                    _tag_buffer = ""
                    if in_think:
                        end_idx = text.find("</think>")
                        if end_idx != -1:
                            in_think = False
                            text = text[end_idx + 8:]
                        else:
                            # 检测被截断的 </think> 后缀（如 </th、</thi 等）
                            _tag_buffer = _save_partial_closing_tag(text, "</think>")
                            text = "" if not _tag_buffer else text[:-len(_tag_buffer)]
                    if not in_think:
                        start_idx = text.find("<think")
                        if start_idx != -1:
                            end_idx = text.find("</think>", start_idx)
                            if end_idx != -1:
                                text = text[:start_idx] + text[end_idx + 8:]
                            else:
                                text = text[:start_idx]
                                in_think = True
                    # 过滤 <MEMORY> 块（不输出给用户）
                    if in_memory:
                        end_idx = text.find("</MEMORY>")
                        if end_idx != -1:
                            in_memory = False
                            text = text[end_idx + 9:]
                        else:
                            # 检测被截断的 </MEMORY> 后缀（如 </MEM、</ME 等）
                            _tag_buffer = _save_partial_closing_tag(text, "</MEMORY>")
                            text = "" if not _tag_buffer else text[:-len(_tag_buffer)]
                    if not in_memory:
                        start_idx = text.find("<MEMORY>")
                        if start_idx != -1:
                            end_idx = text.find("</MEMORY>", start_idx)
                            if end_idx != -1:
                                text = text[:start_idx] + text[end_idx + 9:]
                            else:
                                text = text[:start_idx]
                                in_memory = True
                    # 保存可能被分割的标签开头（如 <MEM、</M 等），下一 chunk 拼接后再判断
                    if text and not in_think and not in_memory:
                        _tag_buffer = _save_partial_tag(text)
                        if _tag_buffer:
                            text = text[:-len(_tag_buffer)]
                    if text:
                        if reasoning_yielded and not getattr(self, '_reasoning_end_yielded', False):
                            yield "\033[0m\n\n"
                            self._reasoning_end_yielded = True
                        yield text

                if "tool_calls" in delta and delta["tool_calls"]:
                    for tc_delta in delta["tool_calls"]:
                        idx = tc_delta.get("index", 0)
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc_delta.get("id"):
                            tool_calls_acc[idx]["id"] = tc_delta["id"]
                        fn = tc_delta.get("function", {})
                        if fn.get("name"):
                            tool_calls_acc[idx]["name"] = fn["name"]
                        if fn.get("arguments"):
                            tool_calls_acc[idx]["arguments"] += fn["arguments"] or ""
        except Exception as e:
            _log(False, f"stream_err:{e}")
            raise

        # 流结束：冲刷缓冲的截断标签前缀（仅在非抑制状态下）
        if _tag_buffer and not in_think and not in_memory:
            yield _tag_buffer
            _tag_buffer = ""

        # 若推理已开始但从未关闭（模型将所有内容放入 reasoning_content，无 regular content），
        # 补发 ANSI 重置，防止终端持续灰色
        if reasoning_yielded and not getattr(self, '_reasoning_end_yielded', False):
            yield "\033[0m"
            self._reasoning_end_yielded = True

        # 确保流总是以换行结尾，防止后续 logger 输出粘在最后一行
        yield "\n"

        # deepseek-v4-flash 等模型偶尔将回复放在 reasoning_content 中，content 为空
        content = self._strip_thinking("".join(content_parts))
        try:
            content = content.encode("utf-8", "surrogatepass").decode("utf-8", "replace")
        except Exception as e:
            logger.debug("Content surrogate cleanup failed: %s", e)

        tool_calls = []
        for idx in sorted(tool_calls_acc):
            tc = tool_calls_acc[idx]
            try:
                args = json.loads(tc["arguments"]) if tc["arguments"] else {}
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=tc["id"], name=tc["name"], arguments=args))

        chat_response = ChatResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            reasoning_content="".join(reasoning_parts) if reasoning_parts else None,
        )

        self._last_stream_response = chat_response

        _log(True)

        # Token 估算（输入+输出）
        tokens = self._estimate_call_tokens(api_messages, content)
        self._record_call((time.time() - _t0) * 1000, False, tokens)

        # Save response to JSONL log
        self._save_llm_log(payload, {
            "content": content,
            "tool_calls": [{"name": tc.name, "arguments": tc.arguments} for tc in tool_calls],
            "finish_reason": finish_reason,
            "reasoning_content": "".join(reasoning_parts) if reasoning_parts else None,
        })

    # endregion

    # region 私有方法

    def _build_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """将内部消息格式转换为 API 格式（移除内部字段）。"""
        result = []
        for msg in messages:
            api_msg: dict[str, Any] = {"role": msg["role"]}

            # 内容字段
            if msg.get("content") is not None:
                api_msg["content"] = msg["content"]

            # 工具调用（assistant 消息携带）
            if msg.get("tool_calls"):
                api_msg["tool_calls"] = msg["tool_calls"]

            # reasoning_content：仅 GLM 原生支持，其他模型透传可能导致 400
            # DeepSeek 的 reasoning_content 由下方占位逻辑统一处理
            if msg.get("reasoning_content") and "glm" in self.model.lower():
                api_msg["reasoning_content"] = msg["reasoning_content"]

            # 工具结果（tool 消息携带）
            if msg.get("tool_call_id"):
                api_msg["tool_call_id"] = msg["tool_call_id"]

            # 函数调用者名字
            if msg.get("name"):
                api_msg["name"] = msg["name"]

            result.append(api_msg)

        # DeepSeek thinking mode: 所有 assistant 消息必须有 reasoning_content。
        # 跨模型消息（如 MiniMax 产生的）不含此字段，补占位符满足格式要求。
        if "deepseek" in self.model.lower():
            for m in result:
                if m.get("role") == "assistant" and "reasoning_content" not in m:
                    m["reasoning_content"] = " "  # 非空占位，空字符串会被 API 拒绝

        return result

    # ── LLM 日志（JSONL 格式）─────────────────────────────────

    def _save_llm_log(self, payload: dict[str, Any], response: dict[str, Any] | None = None) -> None:
        """保存 LLM 请求/响应为 JSONL 格式日志。

        每条 LLM 调用追加到当天的 JSONL 文件：
        {agent_id}/logs/llm/YYYYMMDD.jsonl（优先）或 global/logs/YYYYMMDD.jsonl（fallback）
        便于回放完整的工具调用链，全天检索方便。
        """
        import os as _os
        import datetime as _dt

        _log_dir = _os.path.expanduser(_get_llm_log_dir())
        _os.makedirs(_log_dir, exist_ok=True)

        now = _dt.datetime.now()
        _log_file = _os.path.join(_log_dir, f"{now.strftime('%Y%m%d')}.jsonl")

        try:
            entry = {
                "timestamp": now.isoformat(),
                "model": payload.get("model", self.model),
                "payload": {
                    "messages": payload.get("messages", []),
                    "tools": payload.get("tools"),
                },
                "response": response,
            }
            with open(_log_file, "a", encoding="utf-8") as _f:
                _f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            logger.debug("[LLM] Logged to %s", _log_file)
        except Exception as _e:
            logger.warning("[LLM] Failed to save log: %s", _e)

    def _request_with_retry(
        self,
        payload: dict[str, Any],
        headers: dict[str, str],
        log_level: int | None,
    ) -> ChatResponse:
        """执行 HTTP 请求，自动重试可恢复的错误。

        重试策略：
        - 429（限流）：使用 Retry-After 头；若无效，指数退避（2/4/8s）
        - 5xx（服务端错误）：指数退避（1/2/4s）
        - 超时 / 网络错误：指数退避（1/2/4s）
        - 认证错误（401/403）等不可重试错误：直接抛出

        日志格式：[LLM OK/ERR] 时间 model=xxx msgs=N tools=T/F elapsed=X.Xs ...

        Args:
            payload: 请求体（已包含 model / messages / tools）。
            headers: HTTP 请求头（已包含 Authorization / Content-Type）。
            log_level: 日志级别，None 则默认 INFO。

        Returns:
            ChatResponse 解析后的响应。

        Raises:
            LLMError: 重试耗尽或不可重试的错误。
        """
        url = f"{self.base_url}/chat/completions"
        t0 = time.time()
        msg_preview = ""
        has_tools = "tools" in payload

        # ── 读取 Interoception 退避信号 ──
        if self._interoception:
            backoff = getattr(self._interoception, 'backoff_seconds', 0.0)
            if backoff > 0:
                logger.warning("[LLM] Interoception 退避 %.1fs，暂停请求", backoff)
                time.sleep(backoff)

        def log_request(success: bool, detail: str = ""):
            """记录单次 LLM 调用结果。"""
            elapsed = time.time() - t0
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            msg = "%s model=%s msgs=%d tools=%s elapsed=%.2fs %s %s" % (
                ts, self.model, len(payload.get("messages", [])),
                has_tools, elapsed, msg_preview, detail,
            )
            if success:
                logger.info("\033[91m[LLM OK] %s\033[0m", msg)
            else:
                logger.info("[LLM ERR] %s", msg)

        last_error: LLMError | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )

                # 可重试的 HTTP 状态码
                # Debug: log full payload on error
                if response.status_code >= 400:
                    msgs = payload.get("messages", [])
                    logger.warning(
                        "[LLM DEBUG] HTTP %d payload: msgs=%d, msg_roles=%s, msg0_len=%d, tools=%s",
                        response.status_code,
                        len(msgs),
                        [m.get("role") for m in msgs],
                        len(msgs[0].get("content", "") if msgs else ""),
                        "tools" in payload,
                    )
                if response.status_code in self.RETRYABLE_STATUS_CODES:
                    retry_after = self._calc_retry_after(response)
                    if attempt < self.max_retries:
                        logger.warning(
                            "API 返回 %d，%.1fs 后重试（第 %d/%d 次）",
                            response.status_code, retry_after, attempt + 1, self.max_retries,
                        )
                        time.sleep(retry_after)
                        continue
                    else:
                        log_request(False, f"http_{response.status_code}_retries_exhausted")
                        raise LLMError(
                            f"API 返回 {response.status_code}，重试 {self.max_retries} 次后放弃：{response.text[:200]}",
                            retryable=False,
                        )

                # 非 200 状态码：致命错误直接终止程序
                if response.status_code in self.FATAL_STATUS_CODES:
                    log_request(False, f"fatal_{response.status_code}")
                    raise FatalLLMError(
                        f"LLM API 致命错误 (HTTP {response.status_code}): {response.text[:200]}",
                        status_code=response.status_code,
                    )
                if response.status_code >= 400:
                    logger.warning("[LLM] HTTP %d response body: %s", response.status_code, response.text[:500])
                response.raise_for_status()
                data = response.json()
                logger.debug("API 响应: %s", json.dumps(data, ensure_ascii=False, indent=2)[:500])

                # 响应格式校验
                if "choices" not in data or not data["choices"]:
                    raise LLMError("API 响应缺少 choices 字段", retryable=True)

                log_request(True)
                resp = self._parse_response(data)
                tokens = self._estimate_call_tokens(
                    payload.get("messages", []), resp.content
                )
                self._record_call((time.time() - t0) * 1000, False, tokens)
                return resp

            except requests.Timeout:
                last_error = LLMError(f"请求超时（{self.timeout}s）", retryable=True)
                if attempt < self.max_retries:
                    backoff = 2 ** attempt
                    logger.warning("超时，%.1fs 后重试（第 %d/%d 次）", backoff, attempt + 1, self.max_retries)
                    time.sleep(backoff)
                    continue
                self._record_call((time.time() - t0) * 1000, True)
                log_request(False, f"timeout({self.timeout}s)")
                raise last_error

            except requests.ConnectionError as e:
                last_error = LLMError(f"连接错误：{e}", retryable=True)
                if attempt < self.max_retries:
                    backoff = 2 ** attempt
                    logger.warning("连接失败，%.1fs 后重试（第 %d/%d 次）", backoff, attempt + 1, self.max_retries)
                    time.sleep(backoff)
                    continue
                self._record_call((time.time() - t0) * 1000, True)
                log_request(False, "conn_err")
                raise last_error

            except requests.RequestException as e:
                # 致命状态码（401/402/403）→ 终止程序
                if isinstance(e, requests.HTTPError) and e.response is not None:
                    if e.response.status_code in self.FATAL_STATUS_CODES:
                        self._record_call((time.time() - t0) * 1000, True,
                                         status_code=e.response.status_code)
                        log_request(False, f"fatal_{e.response.status_code}")
                        raise FatalLLMError(
                            f"LLM API 致命错误 (HTTP {e.response.status_code}): {str(e)[:200]}",
                            status_code=e.response.status_code,
                        )
                # 其他请求异常（如 422）不重试
                http_status = e.response.status_code if isinstance(e, requests.HTTPError) and e.response is not None else 0
                self._record_call((time.time() - t0) * 1000, True, status_code=http_status)
                log_request(False, f"req_err:{e}")
                raise LLMError(f"请求失败：{e}", retryable=False, status_code=http_status)

        # 重试次数耗尽（理论上 above for loop 总会 return 或 raise，
        # 这里是为了穷尽所有路径）
        self._record_call((time.time() - t0) * 1000, True)
        log_request(False, "retries_exhausted")
        raise last_error or LLMError("未知错误", retryable=False)

    def _calc_retry_after(self, response: requests.Response) -> float:
        """计算重试等待时间。

        优先级：
        1. Retry-After 响应头（API 显式指定）
        2. 429 状态码：固定 2s（后端已处理限流）
        3. 其他 5xx：指数退避，上限 4s

        Args:
            response: HTTP 响应对象。

        Returns:
            等待秒数。
        """
        # 1. 优先使用 Retry-After 头
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass

        # 2. 429 限流：固定等待 2s
        if response.status_code == 429:
            return 2.0

        # 3. 5xx 服务端错误：指数退避 2^attempt，上限 4s
        return min(4.0, 2.0)

    @staticmethod
    def _strip_thinking(text: str | None) -> str | None:
        """移除文本中的 <think>...</think> 思考块。

        部分模型（如 GLM）在 content 中嵌入 <think> 标签用于输出推理过程，
        这些内容不应该暴露给用户。

        Args:
            text: 原始文本。

        Returns:
            移除思考块后的文本，若全为空则返回 None。
        """
        if not text:
            return text
        return re.sub(r'<think\b[^>]*>.*?</think\s*>', '', text, flags=re.DOTALL).strip() or None

    def _parse_response(self, data: dict) -> ChatResponse:
        """解析 API 响应数据为 ChatResponse。

        处理逻辑：
        - 提取 message.content，过滤 <think> 标签
        - 提取 tool_calls，解析 arguments JSON
        - 忽略 reasoning_content（模型的内部思考，不暴露给用户）

        Args:
            data: API 返回的 JSON 数据。

        Returns:
            ChatResponse 对象。
        """
        choice = data["choices"][0]
        message = choice.get("message", {})

        # 提取文本内容，移除思考块
        content = message.get("content")
        content = self._strip_thinking(content)

        # 解析工具调用
        tool_calls: list[ToolCall] = []
        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                try:
                    args = json.loads(tc.get("function", {}).get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}
                    logger.warning("解析工具调用参数失败: %s", tc)
                tool_calls.append(
                    ToolCall(
                        id=tc.get("id", ""),
                        name=tc.get("function", {}).get("name", ""),
                        arguments=args,
                    )
                )

        return ChatResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason", ""),
            reasoning_content=message.get("reasoning_content"),
        )

    # endregion