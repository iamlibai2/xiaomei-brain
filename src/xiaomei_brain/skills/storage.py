"""技能存储 — SQLite 元数据 + LanceDB 向量索引。

架构与 LongTermMemory 一致：
- SQLite: 元数据（名称、描述、标签、内容、工具绑定、使用统计）
- LanceDB: 向量索引，语义搜索

用法::

    store = SkillStorage(db_path="~/.xiaomei-brain/{agent_id}/memory/brain.db")
    store.import_from_dir("~/.xiaomei-brain/{agent_id}/skills")

    # 语义搜索
    results = store.list_skills(query="web scraping")

    # 查看详情 + 记录使用
    skill = store.view_skill("web-artifacts-builder")
    store.record_usage("web-artifacts-builder")
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from xiaomei_brain.base.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 3


class SkillStorage(SQLiteStore):
    """技能存储 — SQLite 元数据 + LanceDB 向量索引。"""

    VALID_SOURCES = {"local", "imported", "generated", "hub"}

    def __init__(
        self,
        db_path: str | Path,
        lance_dir: str | Path | None = None,
    ) -> None:
        super().__init__(db_path)
        self._init_tables()

        # LanceDB 目录 — brain.db 已在 memory/ 下，lancedb 同级
        if lance_dir is None:
            lance_dir = self.db_path.parent / "lancedb"
        self._lance_dir = Path(lance_dir)
        self._lance_db: Any = None
        self._lance_table: Any = None

        # Embedding: 共享全局单例
        from xiaomei_brain.base.shared_embedder import SharedEmbedder
        self._shared = SharedEmbedder.get_or_create()

    # ── SQLite ───────────────────────────────────────────────────

    def _init_tables(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                version TEXT DEFAULT '1.0.0',
                tags TEXT DEFAULT '[]',
                content TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'local',
                tool_bindings TEXT DEFAULT '[]',
                usage_count INTEGER DEFAULT 0,
                last_used_at REAL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                content_hash TEXT DEFAULT '',
                source_path TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_skills_name ON skills(name);
            CREATE INDEX IF NOT EXISTS idx_skills_source ON skills(source);
        """)
        conn.commit()

        # 开发中的数据库可能跨过不止一个版本。按实际列迁移，避免版本号
        # 跳跃后漏掉字段。source_path 保存 SKILL.md 的真实位置，使 Skill
        # 自带 scripts/assets/references 不再被误当作 Workspace 相对路径。
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(skills)").fetchall()
        }
        if "content_hash" not in columns:
            try:
                conn.execute("ALTER TABLE skills ADD COLUMN content_hash TEXT DEFAULT ''")
                conn.commit()
            except Exception:
                logger.debug("ALTER TABLE skills ADD content_hash failed (column may already exist)", exc_info=True)
        if "source_path" not in columns:
            try:
                conn.execute("ALTER TABLE skills ADD COLUMN source_path TEXT DEFAULT ''")
                conn.commit()
            except Exception:
                logger.debug(
                    "ALTER TABLE skills ADD source_path failed (column may already exist)",
                    exc_info=True,
                )

        self._set_schema_version("skills", SCHEMA_VERSION)

    # ── Embedding ────────────────────────────────────────────────

    def _embed(self, text: str, *, source: str = "skill.search") -> list[float]:
        from xiaomei_brain.base.selection_query import embed_selection_query
        return embed_selection_query(self._shared, text, source=source)

    def _embed_batch(self, texts: list[str], *, source: str = "skill.index") -> list[list[float]]:
        return self._shared.embed_batch(texts, source=source)

    def _get_embedding_dim(self) -> int:
        dim = self._shared.dim
        if dim is not None:
            return dim
        return 512  # bge-small-zh-v1.5 default

    # ── LanceDB ──────────────────────────────────────────────────

    def _get_lance_table(self) -> Any:
        if self._lance_table is not None:
            return self._lance_table

        import lancedb
        import pyarrow as pa

        self._lance_dir.mkdir(parents=True, exist_ok=True)
        self._lance_db = lancedb.connect(str(self._lance_dir))
        expected_dim = self._get_embedding_dim()

        existing = self._lance_db.list_tables()
        if "skills" in existing:
            tbl = self._lance_db.open_table("skills")
            actual = tbl.to_arrow().schema.field("vector").type.list_size
            if actual != expected_dim:
                logger.warning(
                    "SkillStorage: LanceDB dim mismatch (%d vs %d), rebuilding",
                    actual, expected_dim,
                )
                self._lance_db.drop_table("skills")
            else:
                self._lance_table = tbl
                return self._lance_table

        schema = pa.schema([
            pa.field("id", pa.int64()),
            pa.field("vector", pa.list_(pa.float32(), expected_dim)),
        ])
        try:
            self._lance_table = self._lance_db.create_table("skills", schema=schema)
            # 新表 → 全量构建
            self._rebuild_lancedb()
        except ValueError:
            # list_tables() 有时不返回 "skills"，但实际已存在 → 直接打开
            # content_hash 在后续 import 中处理增量，不重建
            self._lance_table = self._lance_db.open_table("skills")
            logger.info("SkillStorage: LanceDB skills table opened (existing, skip rebuild)")
        return self._lance_table

    def _rebuild_lancedb(self) -> None:
        """从 SQLite 重建 LanceDB 向量索引。清空已有数据，全量重建。"""
        table = self._lance_table
        if table is None:
            return

        conn = self._get_conn()
        rows = conn.execute("SELECT id, name, description, tags FROM skills").fetchall()
        if not rows:
            return

        # 清空旧数据
        try:
            n_before = table.count_rows()
            if n_before > 0:
                table.delete("id >= 0")
                logger.info("SkillStorage: cleared %d old LanceDB vectors", n_before)
        except Exception:
            logger.warning("SkillStorage: failed to clear old LanceDB vectors", exc_info=True)
        texts = []
        ids = []
        for row in rows:
            tags = json.loads(row["tags"]) if row["tags"] else []
            tags_str = " ".join(tags) if isinstance(tags, list) else str(tags)
            texts.append(f"{row['name']}: {row['description']} {tags_str}")
            ids.append(row["id"])

        logger.warning("SkillStorage: embedding %d texts for LanceDB rebuild...", len(texts))
        try:
            vectors = self._embed_batch(texts, source="skill.index")
        except Exception:
            logger.exception("SkillStorage: embedding failed during LanceDB rebuild")
            return

        import pyarrow as pa
        batch_data = [{"id": i, "vector": v} for i, v in zip(ids, vectors)]
        table.add(batch_data)
        logger.info("SkillStorage: LanceDB index rebuilt (%d vectors)", len(ids))

    def _upsert_lance(self, skill_id: int) -> None:
        """插入或更新单条 LanceDB 向量。"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT name, description, tags FROM skills WHERE id = ?", (skill_id,)
        ).fetchone()
        if not row:
            return

        tags = json.loads(row["tags"]) if row["tags"] else []
        tags_str = " ".join(tags) if isinstance(tags, list) else str(tags)
        text = f"{row['name']}: {row['description']} {tags_str}"
        vector = self._embed(text, source="skill.index")

        table = self._get_lance_table()
        import pyarrow as pa
        # Delete old vector if exists
        try:
            table.delete(f"id = {skill_id}")
        except Exception:
            logger.debug("SkillStorage: delete old vector failed for skill %d", skill_id, exc_info=True)
        table.add([{"id": skill_id, "vector": vector}])

    # ── 导入 ─────────────────────────────────────────────────────

    def import_from_dir(self, skills_dir: str | Path) -> int:
        """扫描目录中的 SKILL.md 文件，导入到数据库。

        已存在的技能（同名）会被更新。

        Returns:
            导入的技能数量
        """
        import re
        import yaml

        skills_dir = Path(skills_dir)
        if not skills_dir.is_dir():
            logger.info("SkillStorage: skills dir not found: %s", skills_dir)
            skills_dir.mkdir(parents=True, exist_ok=True)
            return 0

        _FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
        imported = 0

        for skill_file in skills_dir.rglob("SKILL.md"):
            try:
                with open(skill_file, "r", encoding="utf-8") as f:
                    text = f.read()

                fm = {}
                body = text
                m = _FRONTMATTER_RE.match(text)
                if m:
                    try:
                        fm = yaml.safe_load(m.group(1)) or {}
                    except yaml.YAMLError:
                        pass
                    body = text[m.end():].strip()

                name = fm.get("name", skill_file.parent.name)
                description = fm.get("description", "")
                version = str(fm.get("version", "1.0.0"))
                tags = fm.get("tags", [])
                if isinstance(tags, str):
                    tags = [t.strip() for t in tags.split(",")]
                # ``requires_tools`` is Xiaomei's canonical field. Accept the
                # common ``tools`` alias so third-party Skills do not silently
                # lose their runtime dependencies.
                tool_bindings = fm.get("requires_tools", fm.get("tools", []))
                if isinstance(tool_bindings, str):
                    tool_bindings = [t.strip() for t in tool_bindings.split(",")]

                self._upsert_skill(
                    name=name,
                    description=description,
                    version=version,
                    tags=tags,
                    content=body,
                    source="local",
                    tool_bindings=tool_bindings,
                    source_path=str(skill_file.resolve()),
                )
                imported += 1
                logger.debug("SkillStorage: imported %s from %s", name, skill_file)
            except Exception:
                logger.warning("SkillStorage: failed to import %s", skill_file, exc_info=True)

        logger.info("SkillStorage: imported %d skills from %s", imported, skills_dir)
        return imported

    def _upsert_skill(
        self,
        name: str,
        description: str,
        version: str,
        tags: list[str],
        content: str,
        source: str,
        tool_bindings: list[str] | None = None,
        source_path: str = "",
    ) -> int:
        """插入或更新技能。返回 skill id。

        内容未变时跳过 LanceDB 更新，只更新元数据（usage_count 等不在此方法更新）。
        """
        import hashlib

        conn = self._get_conn()
        now = time.time()
        tags_json = json.dumps(tags, ensure_ascii=False)
        bindings_json = json.dumps(tool_bindings or [], ensure_ascii=False)

        # Include tool bindings so dependency-only changes are persisted and
        # cannot be mistaken for an unchanged Skill.
        content_fp = hashlib.sha256(
            f"{name}|{description}|{tags_json}|{bindings_json}|{content}".encode("utf-8")
        ).hexdigest()

        existing = conn.execute(
            "SELECT id, content_hash FROM skills WHERE name = ?", (name,)
        ).fetchone()

        if existing:
            skill_id = existing["id"]
            conn.execute("""
                UPDATE skills SET
                    description = ?, version = ?, tags = ?, content = ?,
                    source = ?, tool_bindings = ?, updated_at = ?, content_hash = ?,
                    source_path = ?
                WHERE id = ?
            """, (
                description, version, tags_json, content, source, bindings_json,
                now, content_fp, source_path, skill_id,
            ))
            conn.commit()

            # 内容未变 → 跳过 LanceDB 更新
            if existing["content_hash"] == content_fp:
                logger.debug("SkillStorage: %s content unchanged, skip embed", name)
                return skill_id
        else:
            cursor = conn.execute("""
                INSERT INTO skills (name, description, version, tags, content, source,
                                    tool_bindings, created_at, updated_at, content_hash,
                                    source_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                name, description, version, tags_json, content, source,
                bindings_json, now, now, content_fp, source_path,
            ))
            skill_id = cursor.lastrowid
            conn.commit()

        # 更新向量索引（新技能 或 内容已变）
        try:
            self._upsert_lance(skill_id)
        except Exception:
            logger.warning("SkillStorage: LanceDB upsert failed for %s", name, exc_info=True)

        return skill_id

    # ── 查询 ─────────────────────────────────────────────────────

    def list_skills(
        self, query: str = "", top_k: int = 10, sort_by_usage: bool = True,
    ) -> list[dict[str, Any]]:
        """列出技能元数据（Tier 0）。

        Args:
            query: 语义搜索查询，为空则返回所有
            top_k: 返回数量
            sort_by_usage: 按使用频率排序

        Returns:
            技能字典列表（不含 content）
        """
        conn = self._get_conn()

        if not query:
            order = "usage_count DESC, last_used_at DESC" if sort_by_usage else "name ASC"
            rows = conn.execute(
                f"SELECT * FROM skills ORDER BY {order} LIMIT ?", (top_k,)
            ).fetchall()
            return [self._row_to_dict(r, include_content=False) for r in rows]

        # 语义搜索
        try:
            query_vec = self._embed(query, source="skill.search")
            table = self._get_lance_table()
            results = table.search(query_vec).limit(top_k).to_list()
        except Exception:
            logger.debug("SkillStorage: semantic search failed, fallback to keyword")
            return self._keyword_search(query, top_k)

        if not results:
            return []

        skill_ids = [item["id"] for item in results]
        # LanceDB returns a distance, not a similarity score: smaller values
        # are more relevant. Keep that meaning explicit when ranking results.
        distances = {
            item["id"]: item.get("_distance", 0)
            for item in results
        }

        placeholders = ",".join("?" * len(skill_ids))
        rows = conn.execute(
            f"SELECT * FROM skills WHERE id IN ({placeholders})",
            skill_ids,
        ).fetchall()

        skills = []
        for row in rows:
            d = self._row_to_dict(row, include_content=False)
            d["_distance"] = round(distances.get(row["id"], 0), 4)
            skills.append(d)
        skills.sort(key=lambda x: x["_distance"])

        # An explicit name, tag or description match is stronger evidence than
        # an embedding neighbour.  Keep semantic Top-K as the fallback, but do
        # not let it hide an unmistakable request such as "Word document".
        semantic_by_name = {item["name"]: item for item in skills}
        ranked: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in self._lexical_search(query, top_k):
            candidate = semantic_by_name.get(item["name"], item)
            ranked.append(candidate)
            seen.add(candidate["name"])
        for item in skills:
            if item["name"] not in seen:
                ranked.append(item)
                seen.add(item["name"])
        selected = ranked[:top_k]
        from xiaomei_brain.base.vector_trace import record_vector_trace
        record_vector_trace(
            source="skill.search",
            phase="retrieval",
            query=query,
            candidates=[{
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "distance": item.get("_distance"),
                "selected": item in selected,
            } for item in ranked],
            selected=[str(item.get("name") or "") for item in selected],
            metadata={"top_k": top_k, "metric": "l2_distance"},
        )
        return selected

    @staticmethod
    def _search_terms(value: str) -> set[str]:
        """Build lightweight English tokens and Chinese bigrams for matching."""
        text = str(value or "").casefold().replace("_", " ").replace("-", " ")
        ascii_terms = {
            token for token in re.findall(r"[a-z0-9]+", text)
            if len(token) > 1 and token not in {
                "the", "and", "for", "with", "from", "into", "this", "that",
                "skill", "please", "use", "need", "want",
            }
        }
        chinese_runs = re.findall(r"[\u4e00-\u9fff]+", text)
        chinese_terms = {
            run[index:index + 2]
            for run in chinese_runs
            for index in range(max(0, len(run) - 1))
        }
        return ascii_terms | chinese_terms

    def _lexical_search(self, query: str, top_k: int) -> list[dict[str, Any]]:
        """Return explicit metadata matches, ordered before semantic results."""
        terms = self._search_terms(query)
        if not terms:
            return []
        rows = self._get_conn().execute(
            "SELECT * FROM skills ORDER BY usage_count DESC"
        ).fetchall()
        scored: list[tuple[Any, int]] = []
        for row in rows:
            name = str(row["name"] or "").casefold().replace("_", " ").replace("-", " ")
            description = str(row["description"] or "").casefold()
            tags = json.loads(row["tags"]) if row["tags"] else []
            tag_text = " ".join(str(tag).casefold() for tag in tags)
            score = sum(
                (100 if term in name else 0)
                + (60 if term in tag_text else 0)
                + (20 if term in description else 0)
                for term in terms
            )
            if score:
                scored.append((row, score))
        scored.sort(key=lambda item: (-item[1], -int(item[0]["usage_count"] or 0), item[0]["name"]))
        return [
            self._row_to_dict(row, include_content=False)
            for row, _score in scored[:top_k]
        ]

    def _keyword_search(self, query: str, top_k: int) -> list[dict[str, Any]]:
        return self._lexical_search(query, top_k)

    def view_skill(self, name: str) -> dict[str, Any] | None:
        """查看技能完整内容（Tier 1）。

        Args:
            name: 技能名称

        Returns:
            包含完整 content 的字典，不存在返回 None
        """
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM skills WHERE name = ?", (name,)).fetchone()
        if not row:
            return None
        return self._row_to_dict(row, include_content=True)

    def list_names(self) -> list[str]:
        """返回所有技能名称。"""
        conn = self._get_conn()
        rows = conn.execute("SELECT name FROM skills ORDER BY name").fetchall()
        return [r["name"] for r in rows]

    def list_resource_roots(self) -> list[str]:
        """Return canonical read-only roots for filesystem-backed Skills."""
        rows = self._get_conn().execute(
            "SELECT source_path FROM skills WHERE source_path != ''"
        ).fetchall()
        roots = {
            str(Path(str(row["source_path"])).parent)
            for row in rows
            if str(row["source_path"] or "").strip()
        }
        return sorted(roots)

    def count(self) -> int:
        conn = self._get_conn()
        return conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]

    # ── 系统提示词索引 ───────────────────────────────────────────

    def build_skill_index_prompt(self, query: str, top_k: int = 5) -> str:
        """生成注入 system prompt 的动态技能索引文本。

        embed(query) → LanceDB 语义搜索 → 拼成 <available_skills> 块。

        Args:
            query: 用户输入原文，用于语义召回相关技能
            top_k: 召回数量

        Returns:
            索引文本，无相关技能时返回空字符串
        """
        if not self.count():
            return ""

        skills = self.list_skills(query=query, top_k=top_k)
        if not skills:
            return ""

        lines = [
            "\n<技能>",
            "在回复前先浏览以下技能。如果某个技能与当前任务相关或部分相关，"
            "你必须用 skill_view(技能名) 加载该技能并严格按其指示执行。"
            "宁可多加载一个不需要的技能，也不要漏掉关键步骤、陷阱或既定工作流程。"
            "技能包含针对特定任务的深入知识——API 端点、工具专用命令和经过验证的"
            "高效工作流程，优于通用方法。即使你觉得用基础工具就能处理，也先加载技能——"
            "因为技能定义了该任务在此环境中的正确做法。"
            "技能可能包含你的项目记忆、用户偏好或之前确定的约定，"
            "忽略它们意味着丢失上下文。遇到困难或需要反复尝试的任务，"
            "完成后请主动提出将其保存为技能。"
            "如果确实没有相关技能，可以跳过。",
            "<available_skills>",
        ]
        for s in skills:
            tags_str = f" [{', '.join(s.get('tags', []))}]" if s.get("tags") else ""
            lines.append(f"  - {s['name']}: {s['description']}{tags_str}")
        lines.append("</available_skills>")
        lines.append("使用 skill_view(name) 加载技能完整内容。")
        lines.append("</技能>")

        return "\n".join(lines)

    # ── 写操作 ───────────────────────────────────────────────────

    def record_usage(self, name: str) -> None:
        """记录技能使用。"""
        conn = self._get_conn()
        now = time.time()
        conn.execute(
            "UPDATE skills SET usage_count = usage_count + 1, last_used_at = ? WHERE name = ?",
            (now, name),
        )
        conn.commit()

    def add_skill(
        self,
        name: str,
        description: str,
        content: str,
        tags: list[str] | None = None,
        tool_bindings: list[str] | None = None,
        source: str = "generated",
    ) -> int:
        """手动添加技能。"""
        return self._upsert_skill(
            name=name,
            description=description,
            version="1.0.0",
            tags=tags or [],
            content=content,
            source=source,
            tool_bindings=tool_bindings,
        )

    def remove_skill(self, name: str) -> bool:
        """删除技能。"""
        conn = self._get_conn()
        row = conn.execute("SELECT id FROM skills WHERE name = ?", (name,)).fetchone()
        if not row:
            return False
        skill_id = row["id"]
        conn.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
        conn.commit()

        # 删除向量
        try:
            table = self._get_lance_table()
            table.delete(f"id = {skill_id}")
        except Exception:
            logger.debug("SkillStorage: delete vector failed for skill %d", skill_id, exc_info=True)
        return True

    # ── 工具 ─────────────────────────────────────────────────────

    def _row_to_dict(self, row: sqlite3.Row, include_content: bool = False) -> dict[str, Any]:
        try:
            tags = json.loads(row["tags"]) if row["tags"] else []
        except (json.JSONDecodeError, TypeError):
            tags = []
        try:
            tool_bindings = json.loads(row["tool_bindings"]) if row["tool_bindings"] else []
        except (json.JSONDecodeError, TypeError):
            tool_bindings = []

        d = {
            "name": row["name"],
            "description": row["description"],
            "version": row["version"],
            "tags": tags if isinstance(tags, list) else [],
            "source": row["source"],
            "tool_bindings": tool_bindings if isinstance(tool_bindings, list) else [],
            "usage_count": row["usage_count"],
            "last_used_at": row["last_used_at"],
            "created_at": row["created_at"],
        }
        if include_content:
            d["content"] = row["content"]
            source_path = str(row["source_path"] or "").strip()
            d["source_path"] = source_path
            d["resource_root"] = (
                str(Path(source_path).parent) if source_path else ""
            )
        return d
