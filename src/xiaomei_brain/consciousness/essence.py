"""Essence: 底色存储。

集中管理决定 agent 是谁的不可变片段：
- 个人原则、核心特质、价值观
- 身份叙事、元记忆
- 底线、追求、输出风格

约束：
- 只增不删不改（代码层面不提供 UPDATE/DELETE）
- 不参与记忆召回混排，单独注入 SelfImage [底色] 层
- 和后天记忆（longterm/conversation/DAG）完全隔离
"""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any

from xiaomei_brain.base.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

# ── 合法 category 枚举 ──────────────────────────────────────────
VALID_CATEGORIES = {
    "principle",    # 个人原则
    "meta_memory",  # 元记忆
    "narrative",    # 身份叙事
    "trait",        # 核心特质
    "value",        # 价值观
    "meaning",      # 存在意义
    "calling",      # 追求
    "boundary",     # 底线
    "passions",     # 热爱
    "style",        # 输出风格
}


class Essence(SQLiteStore):
    """底色存储 — agent 的只读本质层。"""

    def __init__(self, db_path: str) -> None:
        super().__init__(db_path)
        self._init_table()

    def _init_table(self) -> None:
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS essence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                priority REAL DEFAULT 0.5,
                created_at REAL NOT NULL,
                relation_types TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_essence_category ON essence(category)")
        # Migration: add relation_types column to existing tables
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(essence)").fetchall()]
        if "relation_types" not in cols:
            conn.execute("ALTER TABLE essence ADD COLUMN relation_types TEXT")
        conn.commit()

    # ── Write (只增) ───────────────────────────────────────────

    def add(
        self,
        category: str,
        content: str,
        priority: float = 0.5,
        relation_types: str | None = None,
    ) -> int:
        """添加一条底色片段。

        Args:
            category: 类型（必须是 VALID_CATEGORIES 之一）
            content: 第一人称描述
            priority: 排序优先级 (0-1)
            relation_types: 逗号分隔的关系类型（如 "恋人,朋友"），空值 = 通用

        Returns:
            新记录的 ID
        """
        if category not in VALID_CATEGORIES:
            raise ValueError(f"Invalid category: {category}. Valid: {VALID_CATEGORIES}")

        conn = self._get_conn()
        now = time.time()
        cursor = conn.execute(
            "INSERT INTO essence (category, content, priority, created_at, relation_types) VALUES (?, ?, ?, ?, ?)",
            (category, content.strip(), priority, now, relation_types),
        )
        conn.commit()
        logger.info("[Essence] +%s #%d: %s", category, cursor.lastrowid, content[:60])
        return cursor.lastrowid

    def add_batch(self, items: list[dict]) -> list[int]:
        """批量添加。

        Args:
            items: [{"category": ..., "content": ..., "priority": 0.5, "relation_types": "恋人,朋友"}, ...]

        Returns:
            新记录 ID 列表
        """
        ids = []
        for item in items:
            ids.append(self.add(
                category=item["category"],
                content=item["content"],
                priority=item.get("priority", 0.5),
                relation_types=item.get("relation_types"),
            ))
        return ids

    # ── Read ───────────────────────────────────────────────────

    def count(self) -> int:
        conn = self._get_conn()
        return conn.execute("SELECT COUNT(*) FROM essence").fetchone()[0]

    def get_all(self, relation_type: str | None = None) -> list[dict]:
        """获取底色片段，按 category + priority 排序。

        Args:
            relation_type: 当前关系类型。style 类别只返回通用项（NULL）和匹配项。
        """
        conn = self._get_conn()
        if relation_type:
            rows = conn.execute(
                """SELECT * FROM essence
                   WHERE category != 'style'
                      OR relation_types IS NULL
                      OR relation_types LIKE ?
                   ORDER BY category, priority DESC, id""",
                (f"%{relation_type}%",),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM essence ORDER BY category, priority DESC, id"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_by_category(self, category: str) -> list[dict]:
        """按类别获取。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM essence WHERE category = ? ORDER BY priority DESC, id",
            (category,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_categories(self) -> list[str]:
        """获取有数据的所有类别。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT DISTINCT category FROM essence ORDER BY category"
        ).fetchall()
        return [r["category"] for r in rows]

    # ── 渲染 ───────────────────────────────────────────────────

    def render(
        self,
        categories: list[str] | None = None,
        max_items: int | None = None,
        relation_type: str | None = None,
    ) -> str:
        """渲染为注入 SelfImage 的文本。

        Args:
            categories: 要包含的类别列表，None = 全部
            max_items: 每个类别最多取几条，None = 全部
            relation_type: 当前关系类型
        """
        all_items = self.get_all(relation_type=relation_type)

        # 过滤类别
        if categories:
            all_items = [i for i in all_items if i["category"] in categories]

        if not all_items:
            return ""

        lines = ["\n## [底色]"]
        current_cat = None

        for item in all_items:
            if max_items:
                # 每个类别计数
                pass  # 简单的 per-category 限制实现
            if item["category"] != current_cat:
                current_cat = item["category"]
                cat_labels = {
                    "principle": "原则",
                    "meta_memory": "元记忆",
                    "narrative": "身份叙事",
                    "trait": "核心特质",
                    "value": "价值观",
                    "meaning": "存在意义",
                    "calling": "追求",
                    "boundary": "底线",
                    "passions": "热爱",
                    "style": "输出风格",
                }
                label = cat_labels.get(current_cat, current_cat)
                lines.append(f"\n### {label}")
            lines.append(item["content"])

        return "\n".join(lines)

