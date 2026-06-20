"""LLMClient — 从 PluginRegistry 获取 provider，按 api_mode 分发到 transport。

迁移自 base/llm.py，核心逻辑保留：
- 重试/退避/fallback
- JSONL 日志
- Token 估算
- Interoception 回调
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import time
from typing import Any, Generator

import requests

from xiaomei_brain.llm.types import ProviderProfile, ModelDefinition, NormalizedResponse, ToolCall
from xiaomei_brain.llm.transport import get_transport

logger = logging.getLogger(__name__)

# ── Per-agent LLM 日志目录 ──
_log_agent_id: str | None = None


def set_log_agent(agent_id: str) -> None:
    global _log_agent_id
    _log_agent_id = agent_id


class LLMError(Exception):
    """LLM 调用异常。"""
    def __init__(self, message: str, retryable: bool = False, status_code: int = 0) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class FatalLLMError(BaseException):
    """LLM 致命错误 — 继承 BaseException 穿透 except Exception 块。"""
    def __init__(self, message: str, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code


class LLMClient:
    """LLM API 客户端 — 从 registry 获取 profile，分发到 transport。

    Usage:
        client = LLMClient(provider="deepseek", model="deepseek-v4-flash", registry=registry)
        response = client.chat(messages=[...], tools=[...])
        for chunk in client.chat_stream(messages=[...], tools=[...]):
            ...
    """

    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
    FATAL_STATUS_CODES = {401, 402, 403}
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_TIMEOUT = 60
    MAX_CONSECUTIVE_FAILURES = 10

    def __init__(
        self,
        provider: str,
        model: str,
        registry,  # PluginRegistry
        api_key: str = "",
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: int = DEFAULT_TIMEOUT,
        fallback_configs: list[dict[str, str]] | None = None,
        interoception: Any = None,
    ) -> None:
        self._registry = registry
        self._profile = registry.get_provider(provider)
        if self._profile is None:
            raise ValueError(f"Unknown provider: {provider}")

        self._model_id = model
        self._model_def = self._profile.resolve_model(model)
        if self._model_def is None:
            self._model_def = ModelDefinition(id=model, name=model,
                                              context_window=128000, max_tokens=8192)
            logger.debug("Model '%s' not in provider '%s' catalog, using defaults", model, provider)

        self._transport = get_transport(self._profile.api_mode)
        self._max_retries = max_retries
        self._timeout = timeout

        # API key: 参数 → 环境变量
        self._api_key = api_key or self._resolve_api_key()

        # Fallback
        self._fallback_configs = fallback_configs or []
        self._fallback_index = -1
        self._interoception = interoception

        # Token callback
        self._token_callback: Any = None

        # Tracking
        self._last_call_latency_ms: float = 0.0
        self._last_call_error: bool = False
        self._backoff_until: float = 0.0
        self._consecutive_failures: int = 0
        self._reasoning_end_yielded: bool = False
        self._last_stream_response: NormalizedResponse | None = None

    def _resolve_api_key(self) -> str:
        for env_var in self._profile.env_vars:
            val = os.getenv(env_var)
            if val:
                return val
        return ""

    @property
    def provider(self) -> str:
        return self._profile.provider_id

    @property
    def model(self) -> str:
        return self._model_id

    @property
    def base_url(self) -> str:
        return self._profile.base_url

    @property
    def api_key(self) -> str:
        return self._api_key

    # ── Public API ──────────────────────────────────────────

    def set_model(self, model: str, base_url: str | None = None, api_key: str | None = None) -> None:
        self._model_id = model
        self._model_def = self._profile.resolve_model(model)
        if self._model_def is None:
            self._model_def = ModelDefinition(id=model, name=model,
                                              context_window=128000, max_tokens=8192)
        if base_url:
            self._profile.base_url = base_url
        if api_key:
            self._api_key = api_key

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        log_level: int | None = None,
    ) -> NormalizedResponse:
        """非流式对话。"""
        api_messages = self._transport.convert_messages(messages, self._model_def, self._profile)
        api_tools = self._transport.convert_tools(tools or [], self._model_def, self._profile) if tools else None

        payload = self._transport.build_kwargs(
            api_messages, api_tools, self._model_def, self._profile, stream=False,
        )

        headers = self._transport.get_headers(self._api_key)
        headers["Content-Type"] = "application/json"

        resp = self._request_with_retry(payload, headers, log_level)

        # Token 估算
        tokens = self._estimate_call_tokens(api_messages, resp.content)
        self._record_call(self._last_call_latency_ms, False, tokens)
        self._log_call(len(api_messages), bool(api_tools), self._last_call_latency_ms,
                       "", success=True, stream=False)

        self._save_llm_log(payload, resp)
        return resp

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Generator[str, None, None]:
        """流式对话 — 逐个 yield chunk。生成器结束后 _last_stream_response 可用。"""
        from xiaomei_brain.llm.transport.chat_completions import ChatCompletionsTransport

        api_messages = self._transport.convert_messages(messages, self._model_def, self._profile)
        api_tools = self._transport.convert_tools(tools or [], self._model_def, self._profile) if tools else None

        payload = self._transport.build_kwargs(
            api_messages, api_tools, self._model_def, self._profile, stream=True,
        )

        headers = self._transport.get_headers(self._api_key)
        headers["Content-Type"] = "application/json"

        self._save_llm_log(payload)

        t0 = time.time()
        content_parts: list[str] = []
        reasoning_text = ""
        tool_calls_raw: list[dict] | None = None
        finish_reason = ""

        response = requests.post(
            self._transport.get_endpoint(self._profile.base_url),
            headers=headers,
            json=payload,
            timeout=self._timeout,
            stream=True,
        )

        if response.status_code in self.FATAL_STATUS_CODES:
            raise FatalLLMError(
                f"LLM API 致命错误 (HTTP {response.status_code}): {response.text[:200]}",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            logger.warning(
                "[LLM DEBUG] HTTP %d | msgs=%d roles=%s | body=%s",
                response.status_code,
                len(api_messages),
                [m.get("role") for m in api_messages],
                response.text[:500],
            )
        response.raise_for_status()

        try:
            for text, extra in self._transport.stream_iter(response, self._model_def, self._profile):
                if text:
                    content_parts.append(text)
                    yield text
                if extra:
                    if extra.get("finish_reason"):
                        finish_reason = extra["finish_reason"]
                    if extra.get("tool_calls"):
                        tool_calls_raw = extra["tool_calls"]
                    if extra.get("reasoning"):
                        reasoning_text = extra["reasoning"]
        except Exception as e:
            logger.warning("[LLM] Streaming failed: %s", e)
            raise

        # 构建最终响应 — content 由 content_parts 累积（过滤 ANSI 控制字符）
        content = "".join(c for c in content_parts
                          if c not in ("\n", "\033[0m", "\033[0m\n\n", "\033[2m"))
        content = ChatCompletionsTransport._strip_thinking(content)

        try:
            content = content.encode("utf-8", "surrogatepass").decode("utf-8", "replace") if content else content
        except Exception as e:
            logger.debug("Content surrogate cleanup failed: %s", e)

        tool_calls: list[ToolCall] = []
        if tool_calls_raw:
            for tc in tool_calls_raw:
                try:
                    args = json.loads(tc["arguments"]) if tc.get("arguments") else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(
                    id=tc.get("id", ""),
                    name=tc.get("name", ""),
                    arguments=json.dumps(args, ensure_ascii=False),
                ))

        self._last_stream_response = NormalizedResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            reasoning=reasoning_text or None,
        )

        elapsed = (time.time() - t0) * 1000
        tokens = self._estimate_call_tokens(api_messages, content)
        self._record_call(elapsed, False, tokens)
        self._log_call(len(api_messages), bool(api_tools), elapsed,
                       "", success=True, stream=True)
        self._save_llm_log(payload, self._last_stream_response)

    # ── Retry logic ────────────────────────────────────────

    def _request_with_retry(self, payload: dict, headers: dict,
                            log_level: int | None = None) -> NormalizedResponse:
        url = self._transport.get_endpoint(self._profile.base_url)
        t0 = time.time()

        if self._interoception:
            backoff = getattr(self._interoception, 'backoff_seconds', 0.0)
            if backoff > 0:
                logger.warning("[LLM] Interoception 退避 %.1fs", backoff)
                time.sleep(backoff)

        last_error = None
        for attempt in range(self._max_retries + 1):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=self._timeout)

                if response.status_code in self.RETRYABLE_STATUS_CODES:
                    retry_after = self._calc_retry_after(response)
                    if attempt < self._max_retries:
                        logger.warning("API 返回 %d，%.1fs 后重试（第 %d/%d 次）",
                                       response.status_code, retry_after, attempt + 1, self._max_retries)
                        time.sleep(retry_after)
                        continue
                    raise LLMError(f"API 返回 {response.status_code}，重试耗尽", retryable=False)

                if response.status_code in self.FATAL_STATUS_CODES:
                    raise FatalLLMError(
                        f"LLM API 致命错误 (HTTP {response.status_code}): {response.text[:200]}",
                        status_code=response.status_code,
                    )

                if response.status_code >= 400:
                    logger.warning("[LLM] HTTP %d: %s", response.status_code, response.text[:500])
                response.raise_for_status()

                data = response.json()
                try:
                    self._transport.validate_raw_response(data)
                except ValueError as e:
                    raise LLMError(str(e), retryable=True)

                elapsed = (time.time() - t0) * 1000
                self._last_call_latency_ms = elapsed
                return self._transport.normalize_response(data, self._model_def, self._profile)

            except requests.Timeout:
                last_error = LLMError(f"请求超时（{self._timeout}s）", retryable=True)
                if attempt < self._max_retries:
                    time.sleep(2 ** attempt)
                    continue
                self._record_call((time.time() - t0) * 1000, True)
                raise last_error

            except requests.ConnectionError as e:
                last_error = LLMError(f"连接错误：{e}", retryable=True)
                if attempt < self._max_retries:
                    time.sleep(2 ** attempt)
                    continue
                self._record_call((time.time() - t0) * 1000, True)
                raise last_error

            except (FatalLLMError, LLMError):
                raise
            except requests.RequestException as e:
                http_status = e.response.status_code if hasattr(e, 'response') and e.response else 0
                self._record_call((time.time() - t0) * 1000, True, status_code=http_status)
                raise LLMError(f"请求失败：{e}", retryable=False, status_code=http_status)

        self._record_call((time.time() - t0) * 1000, True)
        raise last_error or LLMError("未知错误", retryable=False)

    def _calc_retry_after(self, response) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
        if response.status_code == 429:
            return 2.0
        return min(4.0, 2.0)

    # ── Helpers ────────────────────────────────────────────

    def _estimate_call_tokens(self, messages: list[dict], response_content: str | None) -> int:
        from xiaomei_brain.base.message_utils import estimate_tokens
        total = 0
        for m in messages:
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

    def _log_call(self, n_msgs: int, has_tools: bool, elapsed_ms: float,
                  detail: str, *, success: bool, stream: bool) -> None:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        detail_clean = detail.replace("\n", "\\n")[:80] if detail else ""
        tag = "LLM OK STREAM" if stream else "LLM OK"
        if not success:
            tag = "LLM ERR STREAM" if stream else "LLM ERR"
        msg = "%s model=%s msgs=%d tools=%s elapsed=%.2fs %s" % (
            ts, self._model_id, n_msgs, has_tools, elapsed_ms / 1000, detail_clean,
        )
        logger.info("\033[91m[%s] %s\033[0m" if success else "[%s] %s", tag, msg)

    def _record_call(self, latency_ms: float, is_error: bool, tokens: int = 0,
                     status_code: int = 0) -> None:
        self._last_call_latency_ms = latency_ms
        self._last_call_error = is_error
        if is_error and status_code >= 400:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                raise FatalLLMError(
                    f"LLM 连续 {self._consecutive_failures} 次 HTTP {status_code} 错误，程序终止",
                    status_code=status_code,
                )
        else:
            self._consecutive_failures = 0

        if self._interoception:
            try:
                self._interoception.record_llm_call(latency_ms, is_error)
            except Exception as e:
                logger.warning("Interoception failed: %s", e)
        if self._token_callback and tokens > 0:
            try:
                self._token_callback(tokens)
            except Exception as e:
                logger.warning("Token callback failed: %s", e)

    def _save_llm_log(self, payload: dict, response: NormalizedResponse | None = None) -> None:
        log_dir = os.path.expanduser(
            f"~/.xiaomei-brain/{_log_agent_id}/logs/llm" if _log_agent_id
            else "~/.xiaomei-brain/global/logs"
        )
        os.makedirs(log_dir, exist_ok=True)
        now = datetime.datetime.now()
        log_file = os.path.join(log_dir, f"{now.strftime('%Y%m%d')}.jsonl")
        try:
            resp_data = None
            if response:
                resp_data = {
                    "content": response.content,
                    "tool_calls": [{"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                                   for tc in (response.tool_calls or [])],
                    "finish_reason": response.finish_reason,
                    "reasoning_content": response.reasoning,
                }
            entry = {
                "timestamp": now.isoformat(),
                "model": self._model_id,
                "payload": {"messages": payload.get("messages", []), "tools": payload.get("tools")},
                "response": resp_data,
            }
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("[LLM] Failed to save log: %s", e)

    # ── Fallback ───────────────────────────────────────────

    def add_fallback(self, spec: str) -> None:
        """添加备用 provider。格式: 'provider_id/model_id' e.g. 'volcengine/doubao-pro-32k'。"""
        parts = spec.split("/", 1)
        self._fallback_configs.append({
            "provider": parts[0],
            "model": parts[1] if len(parts) > 1 else "",
        })

    def switch_to_fallback(self) -> bool:
        self._fallback_index += 1
        if self._fallback_index >= len(self._fallback_configs):
            return False
        cfg = self._fallback_configs[self._fallback_index]
        logger.warning("[LLM] 切换到备用: %s", cfg.get("provider", "unknown"))
        return True

    def reset_to_primary(self) -> None:
        self._fallback_index = -1

    def apply_backoff(self, seconds: float) -> None:
        if seconds > 0:
            self._backoff_until = time.time() + seconds
            logger.warning("[LLM] 退避 %.1fs", seconds)
            time.sleep(seconds)

    def set_provider(self, provider: str, model: str | None = None) -> None:
        """切换 provider（运行时更换）。"""
        self._profile = self._registry.get_provider(provider)
        if self._profile is None:
            raise ValueError(f"Unknown provider: {provider}")
        self._transport = get_transport(self._profile.api_mode)
        resolved = self._resolve_api_key()
        if resolved:
            self._api_key = resolved
        if model:
            self._model_id = model
            self._model_def = self._profile.resolve_model(model)
            if self._model_def is None:
                self._model_def = ModelDefinition(id=model, name=model,
                                                  context_window=128000, max_tokens=8192)
