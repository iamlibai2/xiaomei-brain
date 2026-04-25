"""ConsciousnessStorage: 意识存储。

意识历史形成"意识流"，存储为 JSON 文件。
独立性：意识是最上层，不应依赖记忆系统（SQLite）。
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ConsciousnessStorage:
    """意识存储。

    存储结构：
        ~/.xiaomei-brain/agents/{agent_id}/consciousness/
            2026-04-22.json
            2026-04-21.json

    每个文件包含当天的所有意识记录。
    """

    def __init__(self, base_dir: str | Path, agent_id: str = "xiaomei") -> None:
        self.base_dir = Path(base_dir)
        self.agent_id = agent_id
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        """确保目录存在"""
        consciousness_dir = self.base_dir / "agents" / self.agent_id / "consciousness"
        consciousness_dir.mkdir(parents=True, exist_ok=True)
        self._consciousness_dir = consciousness_dir

    def _get_today_file(self) -> Path:
        """获取今天的文件路径"""
        today = datetime.now().strftime("%Y-%m-%d")
        return self._consciousness_dir / f"{today}.json"

    def _load_today_records(self) -> list[dict]:
        """加载今天的记录"""
        file_path = self._get_today_file()
        if not file_path.exists():
            return []

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("records", [])
        except Exception as e:
            logger.warning("[ConsciousnessStorage] 加载失败: %s", e)
            return []

    def _save_today_records(self, records: list[dict]) -> None:
        """保存今天的记录"""
        file_path = self._get_today_file()

        data = {
            "agent_id": self.agent_id,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "records": records,
            "updated_at": time.time(),
        }

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug("[ConsciousnessStorage] 保存 %d 条记录到 %s", len(records), file_path)
        except Exception as e:
            logger.error("[ConsciousnessStorage] 保存失败: %s", e)

    # ── 公共接口 ─────────────────────────────────────────────

    def save(self, report: Any) -> None:
        """保存一条意识记录"""
        records = self._load_today_records()
        records.append(report.to_dict() if hasattr(report, "to_dict") else report)
        self._save_today_records(records)

    def get_today_records(self) -> list[dict]:
        """获取今天的所有记录"""
        return self._load_today_records()

    def get_records_by_date(self, date_str: str) -> list[dict]:
        """获取指定日期的记录"""
        file_path = self._consciousness_dir / f"{date_str}.json"
        if not file_path.exists():
            return []

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("records", [])
        except Exception:
            return []

    def get_recent_records(self, limit: int = 10) -> list[dict]:
        """获取最近的记录"""
        records = self._load_today_records()
        return records[-limit:]

    def get_last_dream_summary(self) -> str | None:
        """获取最近梦境摘要（用于苏醒）"""
        records = self._load_today_records()

        # 找最近的 deep 类型记录
        for record in reversed(records):
            if record.get("depth") == "deep":
                return record.get("summary") or record.get("full_report")

        return None

    def get_last_self_image(self) -> dict | None:
        """获取最近的 SelfImage 快照（用于启动恢复）。

        从最近的记录中提取 self_image 字段，
        如果当天没有记录，尝试从最近的历史文件中获取。

        Returns:
            dict: SelfImage 快照，或 None（无历史记录）
        """
        # 先查今天的记录
        records = self._load_today_records()
        for record in reversed(records):
            if "self_image" in record and record["self_image"]:
                return record["self_image"]

        # 今天没有，查最近的历史文件
        dates = self.list_all_dates()
        for date_str in dates:
            if date_str == datetime.now().strftime("%Y-%m-%d"):
                continue  # 跳过今天（已查过）

            records = self.get_records_by_date(date_str)
            for record in reversed(records):
                if "self_image" in record and record["self_image"]:
                    logger.info("[ConsciousnessStorage] 从 %s 恢复 SelfImage", date_str)
                    return record["self_image"]

        return None

    def clear_today_records(self) -> None:
        """清空今天的记录"""
        self._save_today_records([])

    def list_all_dates(self) -> list[str]:
        """列出所有有记录的日期"""
        import re
        dates = []
        for file_path in self._consciousness_dir.glob("*.json"):
            date = file_path.stem
            if re.match(r"\d{4}-\d{2}-\d{2}", date):
                dates.append(date)
        return sorted(dates, reverse=True)

    def get_stats(self) -> dict:
        """获取统计信息"""
        records = self._load_today_records()
        return {
            "today_count": len(records),
            "dates": self.list_all_dates(),
            "last_record": records[-1] if records else None,
        }

    # ── 身份变化记录 ─────────────────────────────────────────────

    def _get_changes_file(self) -> Path:
        """获取变化记录文件路径"""
        return self._consciousness_dir / "changes.json"

    def _load_changes(self) -> list[dict]:
        """加载身份变化记录"""
        file_path = self._get_changes_file()
        if not file_path.exists():
            return []

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("changes", [])
        except Exception as e:
            logger.warning("[ConsciousnessStorage] 加载变化记录失败: %s", e)
            return []

    def _save_changes(self, changes: list[dict]) -> None:
        """保存身份变化记录"""
        file_path = self._get_changes_file()

        data = {
            "agent_id": self.agent_id,
            "changes": changes,
            "updated_at": time.time(),
        }

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug("[ConsciousnessStorage] 保存 %d 条变化记录", len(changes))
        except Exception as e:
            logger.error("[ConsciousnessStorage] 保存变化记录失败: %s", e)

    def record_identity_change(
        self,
        field: str,
        old_value: Any,
        new_value: Any,
        reason: str,
        source: str = "dream",
    ) -> None:
        """记录身份变化

        Args:
            field: 变化的字段名（如 "core_traits", "values", "role"）
            old_value: 旧值
            new_value: 新值
            reason: 变化原因（如 "梦境反省：用户反馈我变得更体贴了"）
            source: 来源（dream/user/system）
        """
        changes = self._load_changes()

        change_record = {
            "timestamp": time.time(),
            "datetime": datetime.now().isoformat(),
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
            "reason": reason,
            "source": source,
        }

        changes.append(change_record)
        self._save_changes(changes)

        logger.info(
            "[ConsciousnessStorage] 身份变化: %s 从 '%s' 变为 '%s'（原因：%s）",
            field, old_value, new_value, reason[:50],
        )

    def get_identity_changes(self, limit: int = 20) -> list[dict]:
        """获取身份变化历史"""
        changes = self._load_changes()
        return changes[-limit:]

    def get_changes_by_field(self, field: str) -> list[dict]:
        """获取指定字段的变化历史"""
        changes = self._load_changes()
        return [c for c in changes if c.get("field") == field]

    # ── 模块化存储（Self 系统）────────────────────────────────────────────

    def _get_module_file(self, module_name: str) -> Path:
        """获取模块存储文件路径"""
        return self._consciousness_dir / f"{module_name}.json"

    def _load_json(self, file_path: Path) -> dict:
        """加载 JSON 文件"""
        if not file_path.exists():
            return {}
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("[ConsciousnessStorage] 加载 %s 失败: %s", file_path, e)
            return {}

    def _save_json(self, file_path: Path, data: dict) -> None:
        """保存 JSON 文件"""
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug("[ConsciousnessStorage] 保存 %s", file_path)
        except Exception as e:
            logger.error("[ConsciousnessStorage] 保存 %s 失败: %s", file_path, e)

    # SelfState 存储
    def save_self_state(self, state_data: dict) -> None:
        """保存 SelfState"""
        data = {"agent_id": self.agent_id, "updated_at": time.time(), **state_data}
        self._save_json(self._get_module_file("state"), data)

    def load_self_state(self) -> dict:
        """加载 SelfState"""
        return self._load_json(self._get_module_file("state"))

    # SelfPerception 存储
    def save_self_perception(self, perception_data: dict) -> None:
        """保存 SelfPerception"""
        data = {"agent_id": self.agent_id, "updated_at": time.time(), **perception_data}
        self._save_json(self._get_module_file("perception"), data)

    def load_self_perception(self) -> dict:
        """加载 SelfPerception"""
        return self._load_json(self._get_module_file("perception"))

    # SelfRelation 存储
    def save_self_relation(self, relation_data: dict) -> None:
        """保存 SelfRelation"""
        data = {"agent_id": self.agent_id, "updated_at": time.time(), **relation_data}
        self._save_json(self._get_module_file("relation"), data)

    def load_self_relation(self) -> dict:
        """加载 SelfRelation"""
        return self._load_json(self._get_module_file("relation"))

    # SelfMemory 存储
    def save_self_memory(self, memory_data: dict) -> None:
        """保存 SelfMemory"""
        data = {"agent_id": self.agent_id, "updated_at": time.time(), **memory_data}
        self._save_json(self._get_module_file("memory"), data)

    def load_self_memory(self) -> dict:
        """加载 SelfMemory"""
        return self._load_json(self._get_module_file("memory"))

    # SelfGrowth 存储
    def save_self_growth(self, growth_data: dict) -> None:
        """保存 SelfGrowth"""
        data = {"agent_id": self.agent_id, "updated_at": time.time(), **growth_data}
        self._save_json(self._get_module_file("growth"), data)

    def load_self_growth(self) -> dict:
        """加载 SelfGrowth"""
        return self._load_json(self._get_module_file("growth"))