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