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
from pathlib import Path
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
    "skills_list",
    "skill_view",
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

    - 为所有工具建 embedding 索引，缓存到 LanceDB
    - 每次 select_tools() embed query，LanceDB 原生搜索 top-K
    - 核心工具（文件/内存/消息）始终保留，不受 embedding 影响
    """

    def __init__(
        self,
        registry: ToolRegistry,
        top_k: int = DEFAULT_TOP_K,
        lance_db_path: str | Path | None = None,
    ) -> None:
        self._registry = registry
        self._top_k = top_k
        self._lance_db_path = Path(lance_db_path) if lance_db_path else None
        self._built = False

        # 共享全局 embedding 单例
        from xiaomei_brain.base.shared_embedder import SharedEmbedder
        self._shared = SharedEmbedder.get_or_create()

        # LanceDB 实例
        self._lance_db: Any = None
        self._lance_table: Any = None

    def _get_embedder(self):
        """返回全局共享的 embedding 单例。"""
        return self._shared

    def _tool_embedding_text(self, tool: Tool) -> str:
        """构造每个工具的 embedding 文本。"""
        return f"{tool.name}: {tool.description} {tool.category}"

    # ── LanceDB 缓存 ──────────────────────────────────────────

    def _get_lance_table(self):
        """懒打开 LanceDB tool_embeddings 表。"""
        if self._lance_table is not None:
            return self._lance_table

        if self._lance_db_path is None:
            return None

        import lancedb
        import pyarrow as pa

        self._lance_db_path.mkdir(parents=True, exist_ok=True)
        self._lance_db = lancedb.connect(str(self._lance_db_path))

        # 尝试直接打开（list_tables() 有时不返回已存在的表）
        try:
            self._lance_table = self._lance_db.open_table("tool_embeddings")
            logger.info("DynamicToolLoader: LanceDB cache opened (%s)", self._lance_db_path)
            return self._lance_table
        except Exception:
            pass

        # 不存在 → 新建
        embedder = self._get_embedder()
        sample_vec = embedder.embed("dim check")
        expected_dim = len(sample_vec)

        schema = pa.schema([
            pa.field("id", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), expected_dim)),
        ])
        self._lance_table = self._lance_db.create_table("tool_embeddings", schema=schema)
        logger.info("DynamicToolLoader: LanceDB cache created (%s)", self._lance_db_path)
        return self._lance_table

    def _get_cached_names(self) -> set[str]:
        """LanceDB 中已缓存的工具名集合。"""
        table = self._get_lance_table()
        if table is None:
            return set()
        try:
            n = table.count_rows()
            if n == 0:
                return set()
            names = set(table.to_pandas()["id"].tolist())
            logger.debug("DynamicToolLoader: read %d cached names from LanceDB", len(names))
            return names
        except Exception:
            logger.warning("DynamicToolLoader: failed to read cached names", exc_info=True)
            return set()

    # ── 索引构建 ──────────────────────────────────────────

    def build_index(self) -> None:
        """为 registry 中所有工具建 embedding 索引（优先缓存）。"""
        tools = self._registry.list_tools()
        if not tools:
            logger.warning("DynamicToolLoader: no tools registered, skip index build")
            self._built = True
            return

        # 按名称排序，确保 texts 和 names 对齐
        tools.sort(key=lambda t: t.name)
        current_names = [t.name for t in tools]
        name_to_tool = {t.name: t for t in tools}
        cached_names = self._get_cached_names()

        if cached_names:
            if sorted(cached_names) == current_names:
                self._built = True
                logger.info("DynamicToolLoader: cache hit, %d tools (skipped embed)", len(tools))
                return

            # 增量更新
            added = set(current_names) - cached_names
            removed = cached_names - set(current_names)
            logger.info(
                "DynamicToolLoader: cache stale — added=%d removed=%d",
                len(added), len(removed),
            )

            table = self._get_lance_table()
            if removed and table:
                for name in removed:
                    try:
                        table.delete(f"id = '{name}'")
                    except Exception:
                        pass

            if added and table:
                new_tools = [name_to_tool[n] for n in current_names if n in added]
                embedder = self._get_embedder()
                try:
                    texts = [self._tool_embedding_text(t) for t in new_tools]
                    vectors = embedder.embed_batch(texts)
                except Exception:
                    logger.warning("DynamicToolLoader: incremental embed failed")
                    self._built = True
                    return

                import pyarrow as pa
                data = pa.table({
                    "id": [t.name for t in new_tools],
                    "vector": vectors,
                })
                table.add(data)

            self._built = True
            logger.info("DynamicToolLoader: incremental update done, %d tools", len(current_names))
            return

        # 缓存未命中 → 全量构建
        self._full_build(tools, current_names)

    def _full_build(self, tools: list[Tool], current_names: list[str]) -> None:
        """全量 embed + 写入 LanceDB。"""
        texts = [self._tool_embedding_text(t) for t in tools]
        total_chars = sum(len(t) for t in texts)
        logger.info("DynamicToolLoader: embedding %d tools (%d KB)...", len(texts), total_chars // 1024)
        try:
            embedder = self._get_embedder()
            vectors = embedder.embed_batch(texts)
        except Exception as e:
            logger.warning("DynamicToolLoader: embedding failed, disabled: %s", e)
            self._built = True
            return

        table = self._get_lance_table()
        if table is not None:
            # 先清理旧数据（drop + recreate 比 delete 更可靠，避免 LanceDB 残留）
            try:
                self._lance_db.drop_table("tool_embeddings", ignore_missing=True)
            except Exception:
                pass
            self._lance_table = None
            table = self._get_lance_table()
            if table is None:
                self._built = True
                return

            import pyarrow as pa
            data = pa.table({"id": current_names, "vector": vectors})
            table.add(data)
            logger.info("DynamicToolLoader: saved %d tool embeddings to cache", len(current_names))

        self._built = True
        logger.info("DynamicToolLoader: built index for %d tools", len(tools))

    def rebuild(self) -> None:
        """重建索引（工具变更后调用）。"""
        self._built = False
        self.build_index()

    # ── 搜索 ──────────────────────────────────────────────

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

        name_to_tool = {t.name: t for t in all_tools}

        # 分离核心工具
        core_tools = [t for t in all_tools if t.name in _CORE_TOOL_NAMES]

        # LanceDB 搜索
        table = self._get_lance_table()
        if table is None or table.count_rows() == 0:
            return core_tools + [t for t in all_tools if t.name not in _CORE_TOOL_NAMES]

        try:
            embedder = self._get_embedder()
            query_vec = embedder.embed(query)
        except Exception:
            logger.debug("DynamicToolLoader: embed query failed, fallback to all tools")
            return core_tools + [t for t in all_tools if t.name not in _CORE_TOOL_NAMES]

        try:
            results = table.search(query_vec).limit(k).to_list()
        except Exception:
            logger.debug("DynamicToolLoader: LanceDB search failed, fallback to all tools")
            return core_tools + [t for t in all_tools if t.name not in _CORE_TOOL_NAMES]

        # 映射回 Tool 对象（排除已包含的核心工具）
        selected = []
        seen = set()
        for r in results:
            name = r["id"]
            if name in seen or name in _CORE_TOOL_NAMES:
                continue
            tool = name_to_tool.get(name)
            if tool:
                selected.append(tool)
                seen.add(name)

        # 规则兜底：query 中明确出现工具名 → 强制入选
        # 避免用户说 "generate_music" 时 embedding 没把它排在 top-K
        for name, tool in name_to_tool.items():
            if name in seen or name in _CORE_TOOL_NAMES:
                continue
            # 支持原始名 (generate_music) 和 normalize 名 (generate music)
            normalized = name.replace("_", " ").replace("-", " ")
            if name in query or normalized in query:
                selected.append(tool)
                seen.add(name)

        # 兜底过多时截断（embedding 结果优先，兜底补到末尾）
        if len(selected) > k:
            selected = selected[:k]

        logger.info(
            "DynamicToolLoader: step growth → %d core + %d dynamic = %d tools (top_k=%d, step=%d)",
            len(core_tools), len(selected), len(core_tools) + len(selected), k, step,
        )
        return core_tools + selected

    def select_openai_tools(self, query: str, top_k: int | None = None, step: int = 0) -> list[dict[str, Any]]:
        """和 select_tools 一样，但返回 OpenAI function calling 格式。"""
        tools = self.select_tools(query, top_k, step)
        result = []
        seen = set()
        for t in tools:
            if t.name in seen:
                logger.warning("DynamicToolLoader: duplicate tool '%s', skipping", t.name)
                continue
            seen.add(t.name)
            result.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            })
        return result
