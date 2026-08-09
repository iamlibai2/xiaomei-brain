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
from pathlib import Path
from typing import Any

from .base import Tool
from .registry import ToolRegistry

logger = logging.getLogger(__name__)

# 核心工具：无论 query 是什么都始终保留
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
    "present_artifacts",
    "send_message",
    "check_inbox",
    "memory_search",
    "memory_add",
    "memory_list",
    "dag",
    "skills_list",
    "skill_view",
    # Direct control of the current Desktop body must not depend on semantic
    # Top-K retrieval; short phrases such as "打开右侧栏" are common.
    "embodiment_control",
    # A Person may refer to earlier work with a short phrase such as
    # "continue that report".  Semantic tool retrieval cannot reliably infer
    # the Assignment lifecycle from those words alone, so keep the two small
    # lookup/revision tools available in every conversation turn.
    "list_assignments",
    "revise_assignment",
    "start_assignment",
    # Project confirmation often arrives as a context-dependent short reply
    # such as "可以了".  Keep the small reflection tool available so the Agent
    # can reconcile its plan without turning Project into a fixed workflow.
    "review_project",
    # Short follow-up requests such as "把华东放前面" still need access to the
    # currently discussed workspace even when semantic retrieval is ambiguous.
    "list_workspaces",
    "get_workspace",
    "create_workspace",
    "update_workspace",
})

DEFAULT_TOP_K = 10
STEP_GROWTH = 3       # 每步增加动态工具名额
MAX_DYNAMIC = 50       # 动态工具上限
TOOL_CONTEXT_USER_MESSAGES = 3
TOOL_CONTEXT_MAX_CHARS = 2400
TOOL_PROGRESS_MAX_CHARS = 1200

_WORKSPACE_AUTHORING_TOOLS = frozenset({
    "get_current_workspace",
    "define_collection",
    "add_collection_fields",
    "record_business_context",
    "configure_context_execution",
    "correct_business_context",
    "list_business_context",
    "create_surface",
    "update_surface",
    "list_business_actions",
    "establish_business_action",
})


def _contextual_required_tool_names(query: str) -> set[str]:
    """Select small deterministic dependencies for unmistakable task shapes.

    Semantic retrieval remains the default.  This only covers cases where the
    attachment type and the user's destination together identify one platform
    operation; omitting that operation would force the model to rebuild it row
    by row with lower-level tools.
    """
    text = str(query or "").casefold()
    has_tabular_attachment = any(marker in text for marker in (
        ".csv", ".tsv", ".xlsx",
        "text/csv", "tab-separated-values", "spreadsheetml",
    ))
    has_import_intent = any(marker in text for marker in (
        "导入", "写入", "放进", "放入", "存入", "import",
    ))
    has_workspace_destination = any(marker in text for marker in (
        "workspace", "工作空间", "经营数据", "业务数据", "经营看板",
    ))
    required: set[str] = set()
    # A focused Workspace is durable runtime state, not something semantic
    # retrieval should have to rediscover from a short follow-up.  When the
    # user asks to build or continue shaping that Workspace, expose the small
    # authoring kit deterministically.  This only makes the tools available;
    # it does not prescribe a workflow or force the Agent to call them.
    has_focused_workspace = "<focused_workspace>" in text
    has_workspace_authoring_intent = any(marker in text for marker in (
        "搭建", "建设", "创建结构", "业务结构", "初始化", "完善", "补齐",
        "定义字段", "定义集合", "创建集合", "创建看板", "创建界面",
        "按你理解", "按你的理解", "按你自己理解", "你自己看着", "继续",
        "继续推进", "继续建设", "继续完善", "build out", "set up",
        "initialize", "schema",
        "collection", "surface", "use your judgment", "continue building",
        "规则", "约束", "默认值", "计算规则", "business rule",
    ))
    if has_focused_workspace:
        required.add("get_current_workspace")
    if has_focused_workspace and has_workspace_authoring_intent:
        required.update(_WORKSPACE_AUTHORING_TOOLS)
    if has_tabular_attachment and has_import_intent and has_workspace_destination:
        required.add("import_tabular_data")
    has_business_object = any(marker in text for marker in (
        "客户", "报价", "合同", "订单", "回款", "应收", "经营",
        "customer", "quote", "contract", "order", "payment", "receivable",
    ))
    has_business_change = any(marker in text for marker in (
        "推进", "更新", "登记", "修改", "记下", "记录", "录入", "保存",
        "确认", "反馈", "收到", "已经", "预计", "承诺", "签了", "付款", "到账",
        "advance", "update", "register", "change", "record", "save",
        "confirmed", "reported", "received", "paid",
    ))
    has_business_query = any(marker in text for marker in (
        "查询", "统计", "汇总", "多少", "哪些",
        "query", "summarize", "count",
    ))
    if has_business_object and (has_business_change or has_business_query):
        required.update({
            "get_current_workspace",
            "query_business_records",
            "upsert_business_record",
        })
    if has_business_object and has_business_change:
        required.update({
            "record_observation",
            "list_business_actions",
            "execute_business_action",
        })
    has_business_crystallization = any(marker in text for marker in (
        "业务做法", "候选做法", "稳定下来", "固定下来", "结晶", "形成动作",
        "business practice", "action candidate", "crystallize", "establish action",
    ))
    if has_business_crystallization:
        required.update({
            "get_current_workspace",
            "list_business_actions",
            "establish_business_action",
        })
    has_business_action_validation = any(marker in text for marker in (
        "只读验证", "历史验证", "历史案例", "验证这个动作", "验证业务动作",
        "为什么被认为是稳定", "为什么是稳定", "稳定 action",
        "validate action", "historical validation", "why is this action stable",
    ))
    if has_business_action_validation:
        required.update({
            "get_current_workspace",
            "list_business_actions",
            "validate_business_action_candidate",
        })
    return required

# 全局活跃的 loader，供 MCP/Plugin 热重载后通知重建索引
_active_loader: DynamicToolLoader | None = None


def _message_text_for_tool_selection(content: Any) -> str:
    """Extract searchable text without copying image data into the query."""
    if isinstance(content, str):
        return content.strip()
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
        # Tools explicitly required by Skills are scoped by conversation. This
        # lets a follow-up turn reuse a loaded Skill without leaking its tools
        # into another Desktop/channel session.
        self._required_tools_by_scope: dict[str, set[str]] = {}
        self._active_required_tools: set[str] = set()
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

    def begin_run(self, scope_id: str = "main") -> None:
        """Select the conversation-scoped Skill bindings for a ReAct run."""
        normalized_scope = str(scope_id or "main")
        self._active_required_tools = self._required_tools_by_scope.setdefault(
            normalized_scope,
            set(),
        )

    def set_disabled_names(self, names: set[str] | list[str]) -> None:
        """Hide capability-owned tools from future selections immediately."""
        self._disabled_names = {str(name).strip() for name in names if str(name).strip()}
        for required in self._required_tools_by_scope.values():
            required.difference_update(self._disabled_names)
        self._active_required_tools.difference_update(self._disabled_names)

    def activate_required_tools(self, names: list[str]) -> tuple[list[str], list[str]]:
        """Pin declared Skill dependencies for the remainder of this run."""
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
                self._active_required_tools.add(normalized)
                activated.append(normalized)
            else:
                missing.append(normalized)
        if activated:
            logger.info(
                "DynamicToolLoader: activated Skill dependencies: %s",
                ", ".join(activated),
            )
        if missing:
            logger.warning(
                "DynamicToolLoader: Skill dependencies are not registered: %s",
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
        all_tools = [
            tool for tool in self._registry.list_tools()
            if tool.name not in self._disabled_names
        ]
        if not all_tools:
            return []

        name_to_tool = {t.name: t for t in all_tools}

        # 分离核心工具
        core_tools = [t for t in all_tools if t.name in _CORE_TOOL_NAMES]
        contextual_required = _contextual_required_tool_names(query)
        required_names = self._active_required_tools | contextual_required
        required_tools = [
            t for t in all_tools
            if t.name in required_names
            and t.name not in _CORE_TOOL_NAMES
        ]
        always_included = _CORE_TOOL_NAMES | required_names

        # LanceDB 搜索
        table = self._get_lance_table()
        if table is None or table.count_rows() == 0:
            return core_tools + required_tools + [
                t for t in all_tools if t.name not in always_included
            ]

        try:
            embedder = self._get_embedder()
            query_vec = embedder.embed(query)
        except Exception:
            logger.debug("DynamicToolLoader: embed query failed, fallback to all tools")
            return core_tools + required_tools + [
                t for t in all_tools if t.name not in always_included
            ]

        try:
            results = table.search(query_vec).limit(k + len(self._disabled_names)).to_list()
        except Exception:
            logger.debug("DynamicToolLoader: LanceDB search failed, fallback to all tools")
            return core_tools + required_tools + [
                t for t in all_tools if t.name not in always_included
            ]

        # 映射回 Tool 对象（排除已包含的核心工具）
        selected = []
        seen = set()
        for r in results:
            name = r["id"]
            if name in seen or name in always_included:
                continue
            tool = name_to_tool.get(name)
            if tool:
                selected.append(tool)
                seen.add(name)

        # 规则兜底：query 中明确出现工具名 → 强制入选
        # 避免用户说 "generate_music" 时 embedding 没把它排在 top-K
        forced: list[Tool] = []
        for name, tool in name_to_tool.items():
            if name in seen or name in always_included:
                continue
            # 支持原始名 (generate_music) 和 normalize 名 (generate music)
            normalized = name.replace("_", " ").replace("-", " ")
            if name in query or normalized in query:
                forced.append(tool)
                seen.add(name)

        # Explicitly named tools have priority over semantic results.  The old
        # append-then-truncate order could silently discard the forced tool
        # whenever embedding had already filled all K slots.
        if forced:
            selected = forced[:k] + selected[:max(0, k - len(forced))]
        else:
            selected = selected[:k]

        logger.info(
            "DynamicToolLoader: step growth → %d core + %d dynamic = %d tools (top_k=%d, step=%d)",
            len(core_tools) + len(required_tools),
            len(selected),
            len(core_tools) + len(required_tools) + len(selected),
            k,
            step,
        )
        return core_tools + required_tools + selected

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
