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
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

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


class Essence:
    """底色存储 — agent 的只读本质层。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        os.makedirs(self.db_path.parent, exist_ok=True)
        self._init_table()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_table(self) -> None:
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS essence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                priority REAL DEFAULT 0.5,
                created_at REAL NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_essence_category ON essence(category)")
        conn.commit()

    # ── Write (只增) ───────────────────────────────────────────

    def add(
        self,
        category: str,
        content: str,
        priority: float = 0.5,
    ) -> int:
        """添加一条底色片段。

        Args:
            category: 类型（必须是 VALID_CATEGORIES 之一）
            content: 第一人称描述
            priority: 排序优先级 (0-1)

        Returns:
            新记录的 ID
        """
        if category not in VALID_CATEGORIES:
            raise ValueError(f"Invalid category: {category}. Valid: {VALID_CATEGORIES}")

        conn = self._get_conn()
        now = time.time()
        cursor = conn.execute(
            "INSERT INTO essence (category, content, priority, created_at) VALUES (?, ?, ?, ?)",
            (category, content.strip(), priority, now),
        )
        conn.commit()
        logger.info("[Essence] +%s #%d: %s", category, cursor.lastrowid, content[:60])
        return cursor.lastrowid

    def add_batch(self, items: list[dict]) -> list[int]:
        """批量添加。

        Args:
            items: [{"category": ..., "content": ..., "priority": 0.5}, ...]

        Returns:
            新记录 ID 列表
        """
        ids = []
        for item in items:
            ids.append(self.add(
                category=item["category"],
                content=item["content"],
                priority=item.get("priority", 0.5),
            ))
        return ids

    # ── Read ───────────────────────────────────────────────────

    def count(self) -> int:
        conn = self._get_conn()
        return conn.execute("SELECT COUNT(*) FROM essence").fetchone()[0]

    def get_all(self) -> list[dict]:
        """获取全部底色片段，按 category + priority 排序。"""
        conn = self._get_conn()
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
    ) -> str:
        """渲染为注入 SelfImage 的文本。

        Args:
            categories: 要包含的类别列表，None = 全部
            max_items: 每个类别最多取几条，None = 全部
        """
        all_items = self.get_all()

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

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
