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

    @property
    def has_tool_calls(self) -> bool:
        """是否有工具调用。"""
        return len(self.tool_calls) > 0


class LLMError(Exception):
    """LLM 调用异常。

    Attributes:
        retryable: 本次错误是否可重试。429/5xx/网络错误为 True，
                   认证失败 / 参数错误为 False。
    """

    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable

# endregion


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

    # 默认重试次数和超时时间
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_TIMEOUT = 60

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str,
        provider: str | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        """初始化 LLM 客户端。

        Args:
            model: 模型名称，如 "glm-5"、"doubao-pro-32k"。
            api_key: API 密钥。
            base_url: API 端点基础地址。
            provider: Provider 名称（zhipu / volcengine / openai），用于日志标识。
            max_retries: 最大重试次数，默认 3 次。
            timeout: 请求超时时间（秒），默认 60 秒。
        """
        self.provider = provider
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.max_retries = max_retries
        self.timeout = timeout

        # 参数校验
        if not self.api_key:
            raise ValueError("API key 不能为空")
        if not self.base_url:
            raise ValueError("base_url 不能为空")
        if not self.model:
            raise ValueError("model 不能为空")

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
        return resp

    # endregion

    # region 私有方法

    def _build_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """将内部消息格式转换为 API 格式，并合并相邻同角色消息。

        为什么需要合并：
        - MiniMax 等平台要求消息角色交替（user → assistant → user），
          连续相同角色的消息会导致 400 错误。
        - 合并规则：连续同 role、无 tool_calls 的消息，内容拼接。

        保留的字段：
        - tool_calls（assistant 消息）：多轮工具调用必需
        - tool_call_id（tool 消息）：关联工具调用结果必需
        - name（function 角色）：函数调用者标识

        Args:
            messages: 内部格式消息列表。

        Returns:
            API 格式消息列表。
        """
        result = []
        for msg in messages:
            api_msg: dict[str, Any] = {"role": msg["role"]}

            # 内容字段
            if msg.get("content") is not None:
                api_msg["content"] = msg["content"]

            # 工具调用（assistant 消息携带）
            if msg.get("tool_calls"):
                api_msg["tool_calls"] = msg["tool_calls"]

            # 工具结果（tool 消息携带）
            if msg.get("tool_call_id"):
                api_msg["tool_call_id"] = msg["tool_call_id"]

            # 函数调用者名字
            if msg.get("name"):
                api_msg["name"] = msg["name"]

            # 合并相邻的同角色消息（跳过有 tool_calls 的消息，它们不能合并）
            if (
                result
                and result[-1]["role"] == api_msg["role"]
                and not api_msg.get("tool_calls")
            ):
                prev = result[-1].get("content", "")
                new = api_msg.get("content", "")
                if prev and new:
                    result[-1]["content"] = prev + "\n" + new
                elif new:
                    result[-1]["content"] = new
            else:
                result.append(api_msg)

        return result

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
        msg_preview = (payload.get("messages", [{}])[0].get("content") or "")[:40]
        has_tools = "tools" in payload

        def log_request(success: bool, detail: str = ""):
            """记录单次 LLM 调用结果。"""
            elapsed = time.time() - t0
            status = "OK" if success else "ERR"
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            level = log_level if log_level is not None else logging.INFO
            logger.log(
                level,
                "[LLM %s] %s model=%s msgs=%d tools=%s elapsed=%.2fs %s %s",
                status, ts, self.model, len(payload.get("messages", [])),
                has_tools, elapsed, msg_preview, detail,
            )

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

                # 非 200 状态码直接抛异常
                if response.status_code >= 400:
                    logger.warning("[LLM] HTTP %d response body: %s", response.status_code, response.text[:500])
                response.raise_for_status()
                data = response.json()
                logger.debug("API 响应: %s", json.dumps(data, ensure_ascii=False, indent=2)[:500])

                # 响应格式校验
                if "choices" not in data or not data["choices"]:
                    raise LLMError("API 响应缺少 choices 字段", retryable=True)

                log_request(True)
                return self._parse_response(data)

            except requests.Timeout:
                last_error = LLMError(f"请求超时（{self.timeout}s）", retryable=True)
                if attempt < self.max_retries:
                    backoff = 2 ** attempt
                    logger.warning("超时，%.1fs 后重试（第 %d/%d 次）", backoff, attempt + 1, self.max_retries)
                    time.sleep(backoff)
                    continue
                log_request(False, f"timeout({self.timeout}s)")
                raise last_error

            except requests.ConnectionError as e:
                last_error = LLMError(f"连接错误：{e}", retryable=True)
                if attempt < self.max_retries:
                    backoff = 2 ** attempt
                    logger.warning("连接失败，%.1fs 后重试（第 %d/%d 次）", backoff, attempt + 1, self.max_retries)
                    time.sleep(backoff)
                    continue
                log_request(False, "conn_err")
                raise last_error

            except requests.RequestException as e:
                # 其他请求异常（如 401/403/422）不重试
                log_request(False, f"req_err:{e}")
                raise LLMError(f"请求失败：{e}", retryable=False)

        # 重试次数耗尽（理论上 above for loop 总会 return 或 raise，
        # 这里是为了穷尽所有路径）
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
        if "tool_calls" in message:
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
        )

    # endregion