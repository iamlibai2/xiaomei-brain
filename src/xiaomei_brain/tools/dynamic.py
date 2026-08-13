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

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from .base import Tool, tool
from .registry import ToolRegistry

logger = logging.getLogger(__name__)

# Core tools are the Agent's universal execution floor. Domain tools must be
# discovered from the current task, activated by a Skill, or requested through
# ``discover``. Keeping this set deliberately small prevents every repaired
# retrieval miss from becoming permanent prompt cost.
_CORE_TOOL_NAMES = frozenset({
    "powershell",
    "bash",
    "process",
    "read",
    "write",
    "edit",
    "glob",
    "grep",
    # Historical tool names can still occur in persisted skills/tests. They
    # remain selectable if explicitly registered, but AgentManager no longer
    # registers them for new runtimes.
    "shell",
    "read_file",
    "write_file",
    "edit_file",
    "memory_search",
    "skill_view",
    "discover",
})

DEFAULT_TOP_K = 3
# Prefetch is a latency optimization, not the only discovery path. It must not
# grow on every ReAct step; the model can call discover when something is
# missing.
STEP_GROWTH = 0
MAX_DYNAMIC = 3
MAX_TOOL_SEARCH_RESULTS = 8
TOOL_CONTEXT_USER_MESSAGES = 3
TOOL_CONTEXT_MAX_CHARS = 2400
TOOL_PROGRESS_MAX_CHARS = 1200
# Tool embeddings are normalized before they are stored. LanceDB's default L2
# distance is therefore comparable across the supported embedding models. A
# result above this distance is merely the nearest tool, not necessarily a
# relevant one. Lexical matches remain eligible independently of this gate.
MAX_SEMANTIC_L2_DISTANCE = 0.82
_DISCOVERY_TOOL_NAMES = frozenset({"discover", "tool_search"})

_MESSAGE_TRANSPORT_PREFIXES = (
    re.compile(r"^\s*距上条消息\s+\S+\s*"),
    re.compile(r"^\s*\[\d{2}-\d{2}\s+\d{2}:\d{2}\]\s*"),
)

# 全局活跃的 loader，供 MCP/Plugin 热重载后通知重建索引
_active_loader: DynamicToolLoader | None = None


def _message_text_for_tool_selection(content: Any) -> str:
    """Extract searchable text without copying image data into the query."""
    if isinstance(content, str):
        text = content.strip()
        for pattern in _MESSAGE_TRANSPORT_PREFIXES:
            text = pattern.sub("", text, count=1)
        return text.strip()
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type", ""))
        if item_type == "text":
            text = str(item.get("text", "")).strip()
            if text:
                parts.append(text)
        elif item_type in {"image", "image_url", "input_image"}:
            parts.append("[image attachment]")
        elif item_type:
            parts.append(f"[{item_type} attachment]")
    return "\n".join(parts)


def build_tool_selection_context(
    messages: list[dict[str, Any]],
    attachments: list[dict[str, Any]] | None = None,
    *,
    max_user_messages: int = TOOL_CONTEXT_USER_MESSAGES,
    max_chars: int = TOOL_CONTEXT_MAX_CHARS,
) -> str:
    """Build a bounded, user-led query for semantic tool retrieval.

    The current request remains primary. Only recent user messages are used as
    conversational context; ordinary assistant replies are deliberately
    excluded so a mistaken capability claim cannot reinforce itself.
    """
    user_texts = [
        text
        for message in messages
        if message.get("role") == "user"
        if (text := _message_text_for_tool_selection(message.get("content")))
    ][-max(1, max_user_messages):]

    current = user_texts[-1] if user_texts else ""
    recent = user_texts[:-1]

    attachment_lines: list[str] = []
    for attachment in attachments or []:
        if not isinstance(attachment, dict):
            continue
        name = str(attachment.get("name", "")).strip()
        mime_type = str(attachment.get("mime_type", "")).strip()
        kind = str(attachment.get("kind", "")).strip()
        details = ", ".join(value for value in (kind, mime_type, name) if value)
        if details:
            attachment_lines.append(f"- {details}")

    protected_parts: list[str] = []
    if current:
        protected_parts.append(f"Current user request:\n{current}")
    if attachment_lines:
        protected_parts.append(
            "Current attachments:\n" + "\n".join(attachment_lines)
        )
    protected = "\n\n".join(protected_parts)

    if len(protected) >= max_chars:
        return protected[:max_chars]
    if not recent:
        return protected

    recent_text = "\n".join(f"- {text}" for text in reversed(recent))
    heading = "\n\nRecent user context:\n"
    remaining = max_chars - len(protected) - len(heading)
    if remaining <= 0:
        return protected
    # Preserve the beginnings of the most recent messages: they usually hold
    # the task verb and object omitted by short follow-ups such as "use this".
    return f"{protected}{heading}{recent_text[:remaining]}".strip()


def build_step_tool_selection_context(
    original_intent: str,
    progress: list[str],
    *,
    max_progress_chars: int = TOOL_PROGRESS_MAX_CHARS,
) -> str:
    """Keep the original request dominant while adding bounded execution facts."""
    if not progress:
        return original_intent
    recent_progress = "\n".join(reversed(progress))[:max_progress_chars]
    return (
        f"{original_intent}\n\nRecent execution progress:\n{recent_progress}"
    ).strip()


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
        # Deterministic dependencies and tools found by active discovery share
        # one run lifetime, but retain separate provenance for tracing.
        self._required_tools_by_scope: dict[str, set[str]] = {}
        self._discovered_tools_by_scope: dict[str, set[str]] = {}
        self._active_required_tools: set[str] = set()
        self._active_discovered_tools: set[str] = set()
        self._disabled_names: set[str] = set()

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
        parameters = json.dumps(
            tool.parameters or {},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return (
            f"Tool: {tool.name}\n"
            f"Category: {tool.category}\n"
            f"Purpose: {tool.description}\n"
            f"Inputs: {parameters}"
        )

    def _tool_fingerprint(self, tool: Tool) -> str:
        return hashlib.sha256(
            self._tool_embedding_text(tool).encode("utf-8")
        ).hexdigest()

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

        # 获取当前模型的 embedding 维度
        dim = self._shared.dim
        if dim is None:
            dim = len(self._get_embedder().embed("dim check"))
        expected_dim = dim

        # 尝试直接打开（list_tables() 有时不返回已存在的表）
        try:
            tbl = self._lance_db.open_table("tool_embeddings")
            table_schema = tbl.to_arrow().schema
            actual = table_schema.field("vector").type.list_size
            if actual != expected_dim:
                logger.warning(
                    "DynamicToolLoader: dim mismatch (table=%d vs model=%d), dropping and rebuilding",
                    actual, expected_dim,
                )
                self._lance_db.drop_table("tool_embeddings")
            elif "fingerprint" not in table_schema.names:
                logger.info(
                    "DynamicToolLoader: legacy cache schema detected, rebuilding"
                )
                self._lance_db.drop_table("tool_embeddings")
            else:
                self._lance_table = tbl
                logger.info("DynamicToolLoader: LanceDB cache opened (%s)", self._lance_db_path)
                return self._lance_table
        except Exception:
            pass

        # 不存在或维度不匹配 → 新建

        schema = pa.schema([
            pa.field("id", pa.string()),
            pa.field("fingerprint", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), expected_dim)),
        ])
        self._lance_table = self._lance_db.create_table("tool_embeddings", schema=schema)
        logger.info("DynamicToolLoader: LanceDB cache created (%s)", self._lance_db_path)
        return self._lance_table

    def _get_cached_fingerprints(self) -> dict[str, str]:
        """Return cached tool fingerprints keyed by tool name."""
        table = self._get_lance_table()
        if table is None:
            return {}
        try:
            n = table.count_rows()
            if n == 0:
                return {}
            # Reading cached metadata does not require pandas.  Keeping this on
            # Arrow also lets the Agent run in the minimal runtime environment
            # used by the CLI and packaged Desktop.
            rows = table.to_arrow().select(["id", "fingerprint"]).to_pylist()
            cached = {
                str(row["id"]): str(row["fingerprint"])
                for row in rows
                if row.get("id") is not None and row.get("fingerprint") is not None
            }
            logger.debug(
                "DynamicToolLoader: read %d cached fingerprints from LanceDB",
                len(cached),
            )
            return cached
        except Exception:
            logger.warning("DynamicToolLoader: failed to read cached fingerprints", exc_info=True)
            return {}

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
        current_fingerprints = {
            tool.name: self._tool_fingerprint(tool) for tool in tools
        }
        cached_fingerprints = self._get_cached_fingerprints()
        cached_names = set(cached_fingerprints)

        if cached_names:
            if cached_fingerprints == current_fingerprints:
                self._built = True
                logger.info("DynamicToolLoader: cache hit, %d tools (skipped embed)", len(tools))
                return

            # 增量更新
            added = set(current_names) - cached_names
            removed = cached_names - set(current_names)
            changed = {
                name for name in set(current_names) & cached_names
                if cached_fingerprints.get(name) != current_fingerprints[name]
            }
            logger.info(
                "DynamicToolLoader: cache stale — added=%d changed=%d removed=%d",
                len(added), len(changed), len(removed),
            )

            table = self._get_lance_table()
            if (removed or changed) and table:
                for name in removed | changed:
                    try:
                        table.delete(f"id = '{name}'")
                    except Exception:
                        logger.debug("DynamicToolLoader: delete stale embedding failed for '%s'", name, exc_info=True)

            pending = added | changed
            if pending and table:
                new_tools = [name_to_tool[n] for n in current_names if n in pending]
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
                    "fingerprint": [current_fingerprints[t.name] for t in new_tools],
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
                logger.debug("DynamicToolLoader: drop_table failed, will retry with recreate", exc_info=True)
            self._lance_table = None
            table = self._get_lance_table()
            if table is None:
                self._built = True
                return

            import pyarrow as pa
            data = pa.table({
                "id": current_names,
                "fingerprint": [self._tool_fingerprint(tool) for tool in tools],
                "vector": vectors,
            })
            table.add(data)
            logger.info("DynamicToolLoader: saved %d tool embeddings to cache", len(current_names))

        self._built = True
        logger.info("DynamicToolLoader: built index for %d tools", len(tools))

    def rebuild(self) -> None:
        """重建索引（工具变更后调用）。"""
        self._built = False
        self.build_index()

    def begin_run(self, scope_id: str = "main", *, reset: bool = False) -> None:
        """Select the turn-scoped explicit bindings for a ReAct run.

        A session can contain many user turns.  Tools discovered for an older
        turn must not accumulate forever, so the first preparation call resets
        the scope.  Skill and Capability bindings are then pinned again from
        the current request and remain active for the whole ReAct loop.
        """
        normalized_scope = str(scope_id or "main")
        if reset:
            self._required_tools_by_scope[normalized_scope] = set()
            self._discovered_tools_by_scope[normalized_scope] = set()
        self._active_required_tools = self._required_tools_by_scope.setdefault(
            normalized_scope,
            set(),
        )
        self._active_discovered_tools = self._discovered_tools_by_scope.setdefault(
            normalized_scope,
            set(),
        )

    def set_disabled_names(self, names: set[str] | list[str]) -> None:
        """Hide capability-owned tools from future selections immediately."""
        self._disabled_names = {str(name).strip() for name in names if str(name).strip()}
        for required in self._required_tools_by_scope.values():
            required.difference_update(self._disabled_names)
        for discovered in self._discovered_tools_by_scope.values():
            discovered.difference_update(self._disabled_names)
        self._active_required_tools.difference_update(self._disabled_names)
        self._active_discovered_tools.difference_update(self._disabled_names)

    def activate_required_tools(self, names: list[str]) -> tuple[list[str], list[str]]:
        """Pin explicitly declared dependencies for the remainder of this run."""
        return self._activate_tools(names, self._active_required_tools, "declared dependencies")

    def activate_discovered_tools(self, names: list[str]) -> tuple[list[str], list[str]]:
        """Pin tools found by explicit discovery for the remainder of this run."""
        return self._activate_tools(names, self._active_discovered_tools, "discovered tools")

    def _activate_tools(
        self,
        names: list[str],
        target: set[str],
        source: str,
    ) -> tuple[list[str], list[str]]:
        registered = {
            tool.name for tool in self._registry.list_tools()
            if tool.name not in self._disabled_names
        }
        activated: list[str] = []
        missing: list[str] = []
        for name in names:
            normalized = str(name).strip()
            if not normalized:
                continue
            if normalized in registered:
                target.add(normalized)
                activated.append(normalized)
            else:
                missing.append(normalized)
        if activated:
            logger.info(
                "DynamicToolLoader: activated %s: %s",
                source,
                ", ".join(activated),
            )
        if missing:
            logger.warning(
                "DynamicToolLoader: %s are not registered: %s",
                source,
                ", ".join(missing),
            )
        return activated, missing

    def pin_required_tools(
        self,
        scope_id: str,
        names: list[str],
    ) -> tuple[list[str], list[str]]:
        """Pin deterministic dependencies without changing the active run."""
        normalized_scope = str(scope_id or "main")
        target = self._required_tools_by_scope.setdefault(normalized_scope, set())
        registered = {
            tool.name for tool in self._registry.list_tools()
            if tool.name not in self._disabled_names
        }
        activated: list[str] = []
        missing: list[str] = []
        for name in names:
            normalized = str(name).strip()
            if not normalized:
                continue
            if normalized in registered:
                target.add(normalized)
                activated.append(normalized)
            else:
                missing.append(normalized)
        return activated, missing

    @staticmethod
    def _search_terms(value: str) -> set[str]:
        """Return lightweight multilingual lexical terms for hybrid search."""
        text = str(value or "").casefold().replace("_", " ").replace("-", " ")
        ascii_terms = {
            token for token in re.findall(r"[a-z0-9]+", text)
            if len(token) > 1 and token not in {
                "the", "and", "for", "with", "from", "into", "this", "that",
                "tool", "please", "use", "need", "want", "current", "user",
                "request", "message", "messages",
            }
        }
        chinese_runs = re.findall(r"[\u4e00-\u9fff]+", text)
        chinese_terms = {
            run[index:index + 2]
            for run in chinese_runs
            for index in range(max(0, len(run) - 1))
        }
        return ascii_terms | chinese_terms

    def _rank_candidates(
        self,
        query: str,
        *,
        limit: int,
        excluded_names: set[str] | frozenset[str],
    ) -> list[Tool]:
        """Hybrid-rank non-core tools without ever falling back to all tools."""
        all_tools = [
            item for item in self._registry.list_tools()
            if item.name not in self._disabled_names
            and item.name not in excluded_names
            and item.name not in _DISCOVERY_TOOL_NAMES
        ]
        if not all_tools or limit <= 0:
            return []

        name_to_tool = {item.name: item for item in all_tools}
        query_text = str(query or "").casefold().strip()
        query_terms = self._search_terms(query_text)
        scores: dict[str, float] = {}

        # Lexical matching protects exact tool names and domain vocabulary from
        # being displaced by semantically similar neighbours.
        for item in all_tools:
            normalized_name = item.name.casefold().replace("_", " ").replace("-", " ")
            searchable = (
                f"{item.name} {item.category} {item.description}"
            ).casefold().replace("_", " ").replace("-", " ")
            item_terms = self._search_terms(searchable)
            overlap = len(query_terms & item_terms)
            score = float(overlap * 3)
            if query_text and query_text in searchable:
                score += 8.0
            if normalized_name and normalized_name in query_text:
                score += 20.0
            if item.name.casefold() in query_text:
                score += 24.0
            if score > 0:
                scores[item.name] = score

        # Semantic retrieval supplies recall when user language describes a
        # business goal rather than a technical tool name.
        table = self._get_lance_table()
        if table is not None:
            try:
                if table.count_rows() > 0:
                    query_vec = self._get_embedder().embed(query)
                    rows = table.search(query_vec).limit(
                        min(
                            len(all_tools) + len(excluded_names),
                            max(limit * 4 + len(excluded_names), 12),
                        )
                    ).to_list()
                    semantic_rank = 0
                    for row in rows:
                        name = str(row.get("id") or "")
                        if name not in name_to_tool:
                            continue
                        try:
                            distance = float(row["_distance"])
                        except (KeyError, TypeError, ValueError):
                            # A semantic result without an absolute score cannot
                            # establish relevance. It may still survive through
                            # the independent lexical score above.
                            continue
                        if distance > MAX_SEMANTIC_L2_DISTANCE:
                            continue
                        # Reciprocal rank is stable across LanceDB distance
                        # ordering and combines cleanly with lexical evidence.
                        scores[name] = scores.get(name, 0.0) + 6.0 / (semantic_rank + 1)
                        semantic_rank += 1
            except Exception:
                logger.debug(
                    "DynamicToolLoader: semantic tool search failed; using lexical results",
                    exc_info=True,
                )

        ranked = sorted(
            scores.items(),
            key=lambda item: (-item[1], item[0]),
        )
        return [name_to_tool[name] for name, _score in ranked[:limit]]

    def search_and_activate(self, query: str, limit: int = 5) -> dict[str, Any]:
        """Discover tools after model reasoning and expose them next step."""
        bounded_limit = max(1, min(int(limit or 5), MAX_TOOL_SEARCH_RESULTS))
        excluded = _CORE_TOOL_NAMES | self._active_required_tools | self._active_discovered_tools
        candidates = self._rank_candidates(
            query,
            limit=bounded_limit,
            excluded_names=excluded,
        )
        activated, missing = self.activate_discovered_tools(
            [item.name for item in candidates]
        )
        return {
            "query": str(query),
            "activated": [
                {
                    "name": item.name,
                    "category": item.category,
                    "description": item.description[:300],
                }
                for item in candidates
                if item.name in activated
            ],
            "missing": missing,
            "instruction": (
                "Activated tool schemas will be available in the next reasoning step. "
                "Use a more specific search query if the required tool is not listed."
            ),
        }

    # ── 搜索 ──────────────────────────────────────────────

    def select_tools(self, query: str, top_k: int | None = None, step: int = 0) -> list[Tool]:
        """根据 query 召回相关工具。

        返回：核心工具 + top_k 个最相关的动态工具。
        预取数量始终受 MAX_DYNAMIC 限制，不会随 ReAct 步数自动增长。
        如果缺少工具，模型应调用 discover 主动发现。

        Args:
            query: 用户意图文本（原始任务 + 工具返回摘要）
            top_k: 基础动态工具数量，None 使用构造时的默认值
            step: 当前 ReAct 步数，仅用于日志和兼容现有调用签名

        Returns:
            选中的工具列表，去重，保持 core 在前
        """
        base = top_k if top_k is not None else self._top_k
        k = min(max(0, int(base)), MAX_DYNAMIC)
        all_tools = [
            tool for tool in self._registry.list_tools()
            if tool.name not in self._disabled_names
        ]
        if not all_tools:
            return []

        # 分离核心工具
        core_tools = [t for t in all_tools if t.name in _CORE_TOOL_NAMES]
        required_names = set(self._active_required_tools)
        discovered_names = set(self._active_discovered_tools)
        required_tools = [
            t for t in all_tools
            if t.name in required_names
            and t.name not in _CORE_TOOL_NAMES
        ]
        discovered_tools = [
            t for t in all_tools
            if t.name in discovered_names
            and t.name not in _CORE_TOOL_NAMES
            and t.name not in required_names
        ]
        always_included = _CORE_TOOL_NAMES | required_names | discovered_names

        selected = self._rank_candidates(
            query,
            limit=k,
            excluded_names=always_included,
        )

        logger.info(
            "DynamicToolLoader: %d fixed + %d prefetched = %d tools (top_k=%d, step=%d)",
            len(core_tools) + len(required_tools) + len(discovered_tools),
            len(selected),
            len(core_tools) + len(required_tools) + len(discovered_tools) + len(selected),
            k,
            step,
        )
        return core_tools + required_tools + discovered_tools + selected

    def select_openai_tools(self, query: str, top_k: int | None = None, step: int = 0) -> list[dict[str, Any]]:
        """和 select_tools 一样，但返回 OpenAI function calling 格式。"""
        schemas, _selection = self.select_openai_tools_with_selection(query, top_k, step)
        return schemas

    def select_openai_tools_with_selection(
        self,
        query: str,
        top_k: int | None = None,
        step: int = 0,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Return schemas together with their stable selection provenance."""
        tools = self.select_tools(query, top_k, step)
        core = [tool.name for tool in tools if tool.name in _CORE_TOOL_NAMES]
        required = [
            tool.name for tool in tools
            if tool.name in self._active_required_tools and tool.name not in _CORE_TOOL_NAMES
        ]
        discovered = [
            tool.name for tool in tools
            if tool.name in self._active_discovered_tools
            and tool.name not in _CORE_TOOL_NAMES
            and tool.name not in self._active_required_tools
        ]
        fixed = set(core) | set(required) | set(discovered)
        schemas = []
        seen: set[str] = set()
        for item in tools:
            if item.name in seen:
                continue
            seen.add(item.name)
            schemas.append({
                "type": "function",
                "function": {
                    "name": item.name,
                    "description": item.description,
                    "parameters": item.parameters,
                },
            })
        return schemas, {
            "step": int(step),
            "query": str(query),
            "core": core,
            "required": required,
            "discovered": discovered,
            "semantic": [item.name for item in tools if item.name not in fixed],
        }


def create_tool_search_tool(loader: DynamicToolLoader) -> Tool:
    """Create the model-driven discovery entry for deferred tools."""

    @tool(
        name="tool_search",
        description=(
            "Search the Agent's deferred tool catalog when the currently visible tools "
            "cannot complete the task. Call this after understanding the missing action, "
            "using a specific capability query such as 'query Workspace customer records' "
            "or 'send a file through Feishu'. Matching tool schemas are activated for the "
            "next reasoning step; do not guess an unavailable tool name."
        ),
    )
    def tool_search(query: str, limit: int = 5) -> dict[str, Any]:
        return loader.search_and_activate(query, limit)

    tool_search.category = "internal"
    return tool_search
