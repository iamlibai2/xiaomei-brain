"""RelationshipEngine — 关系引擎。

轻量引擎：事件驱动 + 衰减 + SQLite 持久化。
比 Drive 简单——无子系统，就是几个方法 + 一张 DB 表。

事件：
- on_user_message()   → depth + 0.002, interaction_count + 1
- on_social_signal()  → trust ± (根据信号类型)
- tick(idle_duration) → 空闲 > 24h 时 depth - 0.01

约束：
- trust ≤ 0 时 depth 不再增长
- depth ∈ [0, 1], trust ∈ [0, 1]
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..base.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

# ── 社交信号 → trust 映射 ──────────────────────────────

SIGNAL_TRUST_MAP: dict[str, float] = {
    "user_happy":        +0.05,
    "user_trusting":     +0.08,
    "user_enthusiastic": +0.05,
    "user_cold":         -0.08,
    "user_angry":        -0.10,
    "user_stressed":     -0.03,
    "user_low_mood":      0.00,   # 情绪低落不影响信任
}

# ── DDL ───────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS relationships (
    user_id TEXT PRIMARY KEY,
    depth REAL DEFAULT 0.0,
    trust REAL DEFAULT 0.1,
    closeness REAL DEFAULT 0.0,
    interaction_count INTEGER DEFAULT 0,
    last_interaction_time REAL DEFAULT 0,
    last_decay_time REAL DEFAULT 0
);
"""

# ── 衰减参数 ──────────────────────────────────────────

DECAY_IDLE_THRESHOLD = 24 * 3600   # 空闲 24 小时开始衰减
DECAY_AMOUNT = 0.01                # 每次衰减量
DECAY_INTERVAL = 3600              # 衰减间隔：1 小时检查一次（避免每分钟都减）


class RelationshipStorage(SQLiteStore):
    """relationships 表的 SQLite 持久化。"""

    def __init__(self, db_path: str) -> None:
        super().__init__(db_path)
        self._init_table()

    def _init_table(self) -> None:
        conn = self._get_conn()
        conn.executescript(DDL)
        # 迁移：为旧数据库添加 closeness 列
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(relationships)").fetchall()]
        if "closeness" not in cols:
            conn.execute("ALTER TABLE relationships ADD COLUMN closeness REAL DEFAULT 0.0")
        conn.commit()

    def load(self, user_id: str) -> dict | None:
        """加载指定用户的关系数据。无记录返回 None。"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM relationships WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None

    def save(self, user_id: str, depth: float, trust: float,
             closeness: float, interaction_count: int,
             last_interaction_time: float, last_decay_time: float) -> None:
        """保存关系数据（INSERT OR REPLACE）。"""
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO relationships
               (user_id, depth, trust, closeness, interaction_count, last_interaction_time, last_decay_time)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, depth, trust, closeness, interaction_count, last_interaction_time, last_decay_time),
        )
        conn.commit()


class RelationshipEngine:
    """关系引擎 — 事件驱动 + 衰减 + SQLite 持久化。"""

    def __init__(self, db_path: str, user_id: str = "default") -> None:
        self._storage = RelationshipStorage(db_path)
        self._user_id = user_id
        self.depth: float = 0.0
        self.trust: float = 0.1
        self.closeness: float = 0.0
        self.interaction_count: int = 0
        self.last_interaction_time: float = 0.0
        self._last_decay_time: float = time.time()
        self._loaded = False

    # ── 初始化 / 用户切换 ──────────────────────────────

    def load(self, user_id: str | None = None) -> None:
        """从 DB 加载关系数据。

        Args:
            user_id: 要加载的用户 ID，None = 使用当前 user_id
        """
        uid = user_id or self._user_id
        self._user_id = uid
        data = self._storage.load(uid)
        if data:
            self.depth = float(data.get("depth", 0.0))
            self.trust = float(data.get("trust", 0.1))
            self.closeness = float(data.get("closeness", 0.0))
            self.interaction_count = int(data.get("interaction_count", 0))
            self.last_interaction_time = float(data.get("last_interaction_time", 0))
            self._last_decay_time = float(data.get("last_decay_time", time.time()))
            logger.info(
                "[Relationship] 从 DB 加载 user=%s: depth=%.2f, trust=%.2f, closeness=%.2f, count=%d",
                uid, self.depth, self.trust, self.closeness, self.interaction_count,
            )
        else:
            self.depth = 0.0
            self.trust = 0.1
            self.closeness = 0.0
            self.interaction_count = 0
            self.last_interaction_time = 0.0
            logger.info("[Relationship] 无历史数据 user=%s，使用默认值", uid)
        self._loaded = True

    def switch_user(self, user_id: str) -> None:
        """切换到指定用户，加载对应关系数据。"""
        if user_id == self._user_id and self._loaded:
            return
        self.load(user_id)

    def save(self) -> None:
        """保存到 DB。"""
        self._storage.save(
            user_id=self._user_id,
            depth=self.depth,
            trust=self.trust,
            closeness=self.closeness,
            interaction_count=self.interaction_count,
            last_interaction_time=self.last_interaction_time,
            last_decay_time=self._last_decay_time,
        )

    # ── 事件驱动 ───────────────────────────────────────

    def on_user_message(self) -> None:
        """用户发消息：depth 增长，trust 越高涨得越快。

        增长 = 0.002 × trust 乘数
        - trust ≥ 0.8 → 乘数 1.2（信任高，关系快速加深）
        - trust ≈ 0.5 → 乘数 1.0（中性，正常增长）
        - trust ≤ 0.2 → 乘数 0.5（信任低，关系难以推进）
        - trust ≤ 0   → 乘数 0  （不信任，完全停滞）
        """
        multiplier = min(1.2, max(0.0, self.trust * 1.2))
        delta = 0.002 * multiplier
        if delta < 0.001:
            return

        self.depth = min(1.0, self.depth + delta)
        self.interaction_count += 1
        self.last_interaction_time = time.time()
        self.save()
        logger.debug("[Relationship] on_user_message: depth=%.2f (+%.3f), trust=%.2f, count=%d",
                     self.depth, delta, self.trust, self.interaction_count)

    def on_social_signal(self, signal_type: str, intensity: float) -> None:
        """社交信号影响 trust 和 closeness。

        signal_type: user_happy / user_cold / user_angry 等
        intensity: 0.0-1.0，作为缩放因子

        closeness：只在 user_trusting 且 depth > 0.3 时增长。
        对方信任我，是建立亲密的关键时刻。增长慢（+0.02 × intensity），不衰减。
        """
        delta = SIGNAL_TRUST_MAP.get(signal_type, 0.0)
        if delta != 0.0:
            self.trust = max(0.0, min(1.0, self.trust + delta * intensity))
            logger.info("[Relationship] on_social_signal: %s → trust=%.2f (delta=%.3f)",
                        signal_type, self.trust, delta * intensity)

        # closeness 只在 user_trusting 且有一定深度时增长
        if signal_type == "user_trusting" and self.depth > 0.3:
            self.closeness = min(1.0, self.closeness + 0.02 * intensity)
            logger.info("[Relationship] closeness += %.3f → %.2f",
                        0.02 * intensity, self.closeness)

        self.save()

    def tick(self, idle_duration: float) -> None:
        """L1 周期调用：检查空闲衰减。

        空闲 > 24h 且距上次衰减 > 1h → depth - 0.01。
        """
        if idle_duration < DECAY_IDLE_THRESHOLD:
            return

        now = time.time()
        if now - self._last_decay_time < DECAY_INTERVAL:
            return

        self.depth = max(0.0, self.depth - DECAY_AMOUNT)
        self._last_decay_time = now
        self.save()
        logger.info("[Relationship] 空闲衰减: depth=%.2f (idle=%.0fh)",
                    self.depth, idle_duration / 3600)

    # ── 关系状态 ────────────────────────────────────────

    def get_relationship_status(self) -> str:
        """从 depth 算关系状态。"""
        if self.depth >= 0.8:
            return "亲密"
        elif self.depth >= 0.6:
            return "知己"
        elif self.depth >= 0.4:
            return "熟悉"
        else:
            return "初识"

    def get_summary(self) -> str:
        """返回关系摘要。"""
        return (
            f"关系{self.get_relationship_status()}，"
            f"深度{self.depth:.0%}，信任{self.trust:.0%}，"
            f"亲密度{self.closeness:.0%}，"
            f"互动{self.interaction_count}次"
        )
