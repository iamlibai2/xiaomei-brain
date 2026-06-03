"""Project Mental Model — 项目认知地图。

不是代码索引，不是 RAG。是她脑子里的一张项目地图——活的、会更新、会自己长。

五维认知：结构、约定、历史、当前状态、质量标准。
基于 LLM diff-merge 更新——有意义的观察发生时立即修订对应维度。
持久化到 brain.db project_map 表，按 (agent_id, project_id) 隔离。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from ..base.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
PENDING_THRESHOLD = 3  # 积累 N 条有意义的观察 → 触发 LLM 更新


# ── ProjectMapData ────────────────────────────────────────────────────

@dataclass
class ProjectMapData:
    """五维认知地图。"""
    structure: str = ""         # 模块/层次/依赖关系
    conventions: str = ""       # 命名模式、代码风格、测试习惯
    history: str = ""           # 设计决策、踩过的坑
    current_state: str = ""     # 当前进度、阻塞点、下一步
    quality_standards: str = "" # 质量标准
    updated_at: float = 0.0
    version: int = 0

    def to_dict(self) -> dict:
        return {
            "structure": self.structure,
            "conventions": self.conventions,
            "history": self.history,
            "current_state": self.current_state,
            "quality_standards": self.quality_standards,
            "updated_at": self.updated_at,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectMapData":
        return cls(
            structure=data.get("structure", ""),
            conventions=data.get("conventions", ""),
            history=data.get("history", ""),
            current_state=data.get("current_state", ""),
            quality_standards=data.get("quality_standards", ""),
            updated_at=data.get("updated_at", 0.0),
            version=data.get("version", 0),
        )

    def is_empty(self) -> bool:
        return not any([
            self.structure, self.conventions, self.history,
            self.current_state, self.quality_standards,
        ])


# ── ProjectMentalModelStorage ─────────────────────────────────────────

class ProjectMentalModelStorage(SQLiteStore):
    """brain.db project_map 表持久化。"""

    def __init__(self, db_path: str) -> None:
        super().__init__(db_path)
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        conn = self._get_conn()
        version = self._get_schema_version("project_map")
        if version >= SCHEMA_VERSION:
            return
        conn.execute("""
            CREATE TABLE IF NOT EXISTS project_map (
                agent_id          TEXT NOT NULL,
                project_id        TEXT NOT NULL,
                structure         TEXT NOT NULL DEFAULT '',
                conventions       TEXT NOT NULL DEFAULT '',
                history           TEXT NOT NULL DEFAULT '',
                current_state     TEXT NOT NULL DEFAULT '',
                quality_standards TEXT NOT NULL DEFAULT '',
                updated_at        REAL NOT NULL DEFAULT 0.0,
                version           INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (agent_id, project_id)
            )
        """)
        conn.commit()
        self._set_schema_version("project_map", SCHEMA_VERSION)
        logger.info("[ProjectMentalModelStorage] 表已创建 (version=%d)", SCHEMA_VERSION)

    def load(self, agent_id: str, project_id: str) -> ProjectMapData:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM project_map WHERE agent_id = ? AND project_id = ?",
            (agent_id, project_id),
        ).fetchone()
        if row is None:
            return ProjectMapData()
        return ProjectMapData.from_dict(dict(row))

    def save(self, agent_id: str, project_id: str, data: ProjectMapData) -> None:
        data.updated_at = time.time()
        data.version += 1
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO project_map (
                agent_id, project_id, structure, conventions, history,
                current_state, quality_standards, updated_at, version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            agent_id, project_id,
            data.structure, data.conventions, data.history,
            data.current_state, data.quality_standards,
            data.updated_at, data.version,
        ))
        conn.commit()
        logger.info(
            "[ProjectMentalModelStorage] 已保存: agent=%s project=%s v%d",
            agent_id, project_id, data.version,
        )

    def list_projects(self, agent_id: str) -> list[dict]:
        """列出该 agent 的所有已知项目（用于推断当前任务属于哪个项目）。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT project_id, structure, updated_at FROM project_map "
            "WHERE agent_id = ? ORDER BY updated_at DESC",
            (agent_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# ── ProjectMentalModel ────────────────────────────────────────────────

class ProjectMentalModel:
    """项目心智模型 — 五维认知 + LLM diff-merge。

    用法:
        pmm = ProjectMentalModel(storage, agent_id="jiaojiao")
        pmm.set_project("car-repair")  # 加载该项目的认知地图

        # 每步有意义的观察
        pmm.record(event_type="surprise", content="TOOL_LOOP ...")
        pmm.record(event_type="block", content="文件权限不足")

        # 触发更新
        pmm.maybe_update(llm)  # pending >= 3 时调用 LLM

        # 注入 system prompt
        ctx = pmm.get_context()
    """

    def __init__(self, storage: ProjectMentalModelStorage, agent_id: str = "") -> None:
        self._storage = storage
        self._agent_id = agent_id
        self._project_id: str = ""
        self._data: ProjectMapData = ProjectMapData()
        self._pending: list[dict] = []

    # ── 项目管理 ──────────────────────────────────────────────────

    def set_project(self, project_id: str) -> None:
        """切换到指定项目，从 DB 加载认知地图。"""
        if project_id == self._project_id:
            return
        self._project_id = project_id
        self._data = self._storage.load(self._agent_id, project_id)
        self._pending = []
        if not self._data.is_empty():
            logger.info(
                "[ProjectMentalModel] 加载项目 %s v%d", project_id, self._data.version,
            )
        else:
            logger.info("[ProjectMentalModel] 新项目 %s", project_id)

    @property
    def project_id(self) -> str:
        return self._project_id

    def list_known_projects(self) -> list[dict]:
        """列出该 agent 的所有已知项目。"""
        return self._storage.list_projects(self._agent_id)

    # ── 观察记录 ──────────────────────────────────────────────────

    def record(
        self,
        event_type: str = "",
        content: str = "",
        goal_context: str = "",
        files: list[str] | None = None,
    ) -> None:
        """队列一条有意义的观察。常规 CONTINUE 步骤不需要调用。

        Args:
            event_type: surprise / block / completion / discovery / pitfall
            content: 观察内容描述
            goal_context: 当前目标上下文
            files: 涉及的文件路径
        """
        if not self._project_id:
            logger.debug("[ProjectMentalModel] project_id 未设置，跳过 record")
            return
        self._pending.append({
            "event_type": event_type,
            "content": content,
            "goal_context": goal_context,
            "files": files or [],
            "time": time.time(),
        })
        logger.debug(
            "[ProjectMentalModel] pending=%d event=%s: %s",
            len(self._pending), event_type, content[:80],
        )

    # ── LLM 更新 ──────────────────────────────────────────────────

    def maybe_update(self, llm: Any = None) -> bool:
        """如果 pending >= 阈值，调用 LLM diff-merge 更新认知地图。

        Returns:
            True 如果更新被执行
        """
        if len(self._pending) < PENDING_THRESHOLD or not llm:
            return False
        if not self._project_id:
            return False
        return self._do_update(llm)

    def force_update(self, llm: Any, observations: list[dict] | None = None) -> bool:
        """立即调用 LLM 更新（如 post_review 之后），无视 pending 阈值。

        Args:
            llm: LLM 客户端
            observations: 额外的观察（如 post_review findings），会被合并到 pending
        """
        if observations:
            self._pending.extend(observations)
        if not self._pending or not llm:
            return False
        if not self._project_id:
            return False
        return self._do_update(llm)

    def _do_update(self, llm: Any) -> bool:
        """执行 LLM diff-merge 更新。"""
        new_data = self._call_diff_merge(llm)
        if new_data is None:
            logger.warning("[ProjectMentalModel] LLM 更新失败，保留现状")
            return False

        self._storage.save(self._agent_id, self._project_id, new_data)
        self._data = new_data
        self._pending = []
        logger.info(
            "[ProjectMentalModel] 更新完成: project=%s v%d",
            self._project_id, new_data.version,
        )
        return True

    def _call_diff_merge(self, llm: Any) -> ProjectMapData | None:
        """调用 LLM 做 diff-merge。返回更新后的 ProjectMapData 或 None。"""
        current = self._data
        observations_text = "\n".join(
            f"- [{obs['event_type']}] {obs['content'][:200]}"
            for obs in self._pending[-10:]
        )

        prompt = f"""你正在维护一个项目的认知地图。只修改与新观察相关的部分，其他部分保持不变。

【当前地图】
结构认知: {current.structure or '（空）'}
约定认知: {current.conventions or '（空）'}
历史认知: {current.history or '（空）'}
当前状态: {current.current_state or '（空）'}
质量标准: {current.quality_standards or '（空）'}

【最近观察】（请据此更新地图）
{observations_text}

请用 JSON 格式回复完整的更新后地图：
```json
{{
    "structure": "...",
    "conventions": "...",
    "history": "...",
    "current_state": "...",
    "quality_standards": "..."
}}
```

规则：
1. 每个字段最多 200 字，用中文
2. 只修改与新观察相关的字段，未涉及的字段原样保留
3. structure: 项目由哪几部分组成，它们之间的关系
4. conventions: 命名/风格/习惯/测试方式
5. history: 重要设计决策、踩过的坑、为什么这么做
6. current_state: 做到哪了、卡在哪了、下一步做什么
7. quality_standards: 这个项目"好"的标准是什么"""

        try:
            messages = [{"role": "user", "content": prompt}]
            response = llm.chat(messages)
            if not response or not hasattr(response, "content"):
                return None
            text = (response.content or "").strip()
            return self._parse_response(text)
        except Exception as e:
            logger.warning("[ProjectMentalModel] LLM 调用失败: %s", e)
            return None

    def _parse_response(self, text: str) -> ProjectMapData | None:
        """从 LLM 响应中解析 JSON。"""
        # 提取 JSON 块
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start) if "```" in text[start:] else len(text)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start) if "```" in text[start:] else len(text)
            text = text[start:end].strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 尝试修复：找第一个 { 和最后一个 }
            try:
                start = text.index("{")
                end = text.rindex("}") + 1
                data = json.loads(text[start:end])
            except (ValueError, json.JSONDecodeError):
                logger.warning("[ProjectMentalModel] JSON 解析失败: %s...", text[:100])
                return None

        current = self._data
        return ProjectMapData(
            structure=data.get("structure", current.structure),
            conventions=data.get("conventions", current.conventions),
            history=data.get("history", current.history),
            current_state=data.get("current_state", current.current_state),
            quality_standards=data.get("quality_standards", current.quality_standards),
            updated_at=current.updated_at,  # save() 会更新
            version=current.version,        # save() 会递增
        )

    # ── 上下文获取 ──────────────────────────────────────────────────

    def get_context(self, module_filter: str = "") -> str:
        """获取当前项目认知地图文本，用于注入 system prompt。

        兼容旧接口（module_filter 参数保留但无实际过滤效果）。
        """
        if not self._data or self._data.is_empty():
            return ""

        d = self._data
        parts = []
        if d.structure:
            parts.append(f"结构: {d.structure}")
        if d.conventions:
            parts.append(f"约定: {d.conventions}")
        if d.history:
            parts.append(f"历史: {d.history}")
        if d.current_state:
            parts.append(f"当前: {d.current_state}")
        if d.quality_standards:
            parts.append(f"质量标准: {d.quality_standards}")

        if not parts:
            return ""

        hours_ago = ""
        if d.updated_at:
            elapsed = time.time() - d.updated_at
            if elapsed > 3600:
                hours_ago = f"（{elapsed / 3600:.0f}小时前更新）"
            elif elapsed > 60:
                hours_ago = f"（{elapsed / 60:.0f}分钟前更新）"

        lines = [f"【项目认知地图 — {self._project_id}{hours_ago}】"]
        lines.extend(parts)
        return "\n".join(lines)

    # ── 工具方法 ────────────────────────────────────────────────────

    @staticmethod
    def slugify(description: str, max_len: int = 40) -> str:
        """从描述生成稳定的 project_id slug。"""
        h = hashlib.md5(description.encode()).hexdigest()[:8]
        # 取前几个有意义的词
        words = description.replace("！", "").replace("，", " ").replace("。", " ").split()
        prefix = "-".join(w for w in words[:3] if len(w) <= 10)
        if prefix:
            return f"{prefix[:max_len - 9]}-{h}"
        return h

    @property
    def pending_count(self) -> int:
        return len(self._pending)