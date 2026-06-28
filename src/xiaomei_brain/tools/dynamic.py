"""动态工具加载 — 按用户意图 embedding 召回相关工具。

每步 embed 当前上下文，只把 top-K 相关工具 + 核心工具发给 LLM，
避免工具膨胀导致 prompt token 爆炸。

用法::

    loader = DynamicToolLoader(registry)
    loader.build_index()
    tools = loader.select_openai_tools("帮我搜百度")

    # 工具变更后
    loader.rebuild()
"""

from __future__ import annotations

import logging
import math
from typing import Any

from .base import Tool
from .registry import ToolRegistry

logger = logging.getLogger(__name__)

# 核心工具：无论 query 是什么都始终保留
_CORE_TOOL_NAMES = frozenset({
    "shell",
    "read_file",
    "write_file",
    "edit_file",
    "send_message",
    "check_inbox",
    "memory_search",
    "memory_add",
    "memory_list",
    "dag",
})

DEFAULT_TOP_K = 10
STEP_GROWTH = 3       # 每步增加动态工具名额
MAX_DYNAMIC = 50       # 动态工具上限

# 全局活跃的 loader，供 MCP/Plugin 热重载后通知重建索引
_active_loader: DynamicToolLoader | None = None


def set_active_loader(loader: DynamicToolLoader) -> None:
    """注册当前活跃的 DynamicToolLoader（agent 初始化时调用）。"""
    global _active_loader
    _active_loader = loader


def notify_tools_changed() -> None:
    """工具变更后调用（MCP 热重载、Plugin reload），重建 embedding 索引。"""
    if _active_loader:
        _active_loader.rebuild()


class DynamicToolLoader:
    """按用户意图动态召回相关工具。

    - 为所有工具建 embedding 索引
    - 每次 select_tools() 计算 query embedding，召回 top-K 动态工具
    - 核心工具（文件/内存/消息）始终保留，不受 embedding 影响
    """

    def __init__(self, registry: ToolRegistry, top_k: int = DEFAULT_TOP_K) -> None:
        self._registry = registry
        self._top_k = top_k
        self._embedder: Any = None
        self._tool_names: list[str] = []       # 索引中的工具名（按顺序）
        self._tool_embeddings: list = []        # 对应的 embedding 向量（list[float]）
        self._built = False

    def _get_embedder(self):
        """懒加载 embedding 模型。"""
        if self._embedder is None:
            from xiaomei_brain.memory.search import Embedder
            self._embedder = Embedder(model_name="BAAI/bge-m3")
        return self._embedder

    def _tool_embedding_text(self, tool: Tool) -> str:
        """构造每个工具的 embedding 文本。"""
        return f"{tool.name}: {tool.description} {tool.category}"

    def build_index(self) -> None:
        """为 registry 中所有工具建 embedding 索引。"""
        tools = self._registry.list_tools()
        if not tools:
            logger.warning("DynamicToolLoader: no tools registered, skip index build")
            self._built = True
            return

        texts = [self._tool_embedding_text(t) for t in tools]
        try:
            embedder = self._get_embedder()
            vectors = embedder.embed_batch(texts)
        except Exception:
            logger.warning("DynamicToolLoader: embedding failed, disabled")
            self._built = True  # 标记已构建但空索引，fallback 到全量
            return

        self._tool_names = [t.name for t in tools]
        self._tool_embeddings = vectors
        self._built = True
        logger.info("DynamicToolLoader: built index for %d tools", len(tools))

    def rebuild(self) -> None:
        """重建索引（工具变更后调用）。"""
        self._tool_names = []
        self._tool_embeddings = []
        self._built = False
        self.build_index()

    def select_tools(self, query: str, top_k: int | None = None, step: int = 0) -> list[Tool]:
        """根据 query 召回相关工具。

        返回：核心工具 + top_k 个最相关的动态工具。
        动态工具数量随 step 增长：base + step * STEP_GROWTH，上限 MAX_DYNAMIC。

        Args:
            query: 用户意图文本（原始任务 + 工具返回摘要）
            top_k: 基础动态工具数量，None 使用构造时的默认值
            step: 当前 ReAct 步数，每步增长 STEP_GROWTH 个名额

        Returns:
            选中的工具列表，去重，保持 core 在前
        """
        base = top_k if top_k is not None else self._top_k
        k = min(base + step * STEP_GROWTH, MAX_DYNAMIC)
        all_tools = self._registry.list_tools()
        if not all_tools:
            return []

        # 分离核心工具和候选工具
        core_tools: list[Tool] = []
        candidates: list[tuple[Tool, int]] = []  # (tool, index_in_embeddings)

        for t in all_tools:
            if t.name in _CORE_TOOL_NAMES:
                core_tools.append(t)
            else:
                idx = self._tool_names.index(t.name) if t.name in self._tool_names else -1
                candidates.append((t, idx))

        if not candidates or not self._tool_embeddings:
            return core_tools + [t for t, _ in candidates]

        # Embed query → 计算相似度
        try:
            embedder = self._get_embedder()
            query_vec = embedder.embed(query)
        except Exception:
            logger.debug("DynamicToolLoader: embed query failed, fallback to all tools")
            return core_tools + [t for t, _ in candidates]

        scored: list[tuple[Tool, float]] = []
        for tool, idx in candidates:
            if idx >= 0 and idx < len(self._tool_embeddings):
                sim = self._dot_similarity(query_vec, self._tool_embeddings[idx])
            else:
                sim = 0.0
            scored.append((tool, sim))

        # 取 top-K
        scored.sort(key=lambda x: x[1], reverse=True)
        selected = [t for t, _ in scored[:k]]
        logger.warning("DynamicToolLoader: step growth → %d core + %d dynamic = %d tools (top_k=%d, step=%d)",
                       len(core_tools), len(selected), len(core_tools) + len(selected), k, step)
        return core_tools + selected

    def select_openai_tools(self, query: str, top_k: int | None = None, step: int = 0) -> list[dict[str, Any]]:
        """和 select_tools 一样，但返回 OpenAI function calling 格式。"""
        tools = self.select_tools(query, top_k, step)
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    @staticmethod
    def _dot_similarity(a: list[float], b: list[float]) -> float:
        """向量已 normalize 过，dot product = cosine similarity。"""
        return sum(x * y for x, y in zip(a, b))
