"""Transport ABC — 每种 wire 协议一个子类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generator

from xiaomei_brain.llm.types import ModelDefinition, ProviderProfile, NormalizedResponse


class Transport(ABC):
    """一种 API 协议的传输实现。

    所有方法接收 model 和 profile，per-model 能力字段决定传输层行为。
    """

    # ── Concrete methods（子类按需 override）──

    def get_endpoint(self, base_url: str) -> str:
        """API 端点 URL。默认 /chat/completions。"""
        return f"{base_url}/chat/completions"

    def get_headers(self, api_key: str) -> dict[str, str]:
        """认证请求头。默认 Bearer token。"""
        return {"Authorization": f"Bearer {api_key}"}

    def validate_raw_response(self, data: dict) -> None:
        """校验原始响应是否合法。默认检查 choices 字段。"""
        if "choices" not in data or not data["choices"]:
            raise ValueError("API response missing 'choices' field")

    @abstractmethod
    def convert_messages(self, messages: list[dict],
                         model: ModelDefinition, profile: ProviderProfile) -> list[dict]:
        """将内部消息格式转换为本协议的请求格式。"""
        ...

    @abstractmethod
    def convert_tools(self, tools: list[dict],
                      model: ModelDefinition, profile: ProviderProfile) -> list[dict]:
        """将内部工具定义转换为本协议的请求格式。"""
        ...

    @abstractmethod
    def build_kwargs(self, messages: list[dict], tools: list[dict] | None,
                     model: ModelDefinition, profile: ProviderProfile,
                     stream: bool, **context) -> dict:
        """构建完整的 API 请求参数。"""
        ...

    @abstractmethod
    def normalize_response(self, raw: Any,
                           model: ModelDefinition, profile: ProviderProfile) -> NormalizedResponse:
        """将 API 原始响应归一化为 NormalizedResponse。"""
        ...

    @abstractmethod
    def stream_iter(self, response,
                    model: ModelDefinition, profile: ProviderProfile
                    ) -> Generator[tuple[str, dict | None], None, None]:
        """迭代 SSE 流，产出 (delta_content, extra_info | None) 元组。

        delta_content: 本次 chunk 的文本增量（可能为空字符串 ""）
        extra_info:   附加信息 dict，None 表示本次 chunk 无额外信息。
                       chat_completions: {"finish_reason": str, "tool_calls": [...], "reasoning": str}
        """
        ...
