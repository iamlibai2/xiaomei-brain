"""DreamStorage: 梦境报告存储。

存储路径：~/.xiaomei-brain/agents/{agent_id}/dream/
每天一个 JSON 文件。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class DreamStorage:
    """梦境报告存储"""

    def __init__(self, base_dir: str, agent_id: str = "xiaomei") -> None:
        self.base_dir = os.path.join(
            os.path.expanduser(base_dir),
            "agents",
            agent_id,
            "dream",
        )
        os.makedirs(self.base_dir, exist_ok=True)

    def save(self, report: Any) -> str:
        """保存梦境报告，返回文件路径。"""
        date_str = datetime.now().strftime("%Y-%m-%d")
        filepath = os.path.join(self.base_dir, f"{date_str}.json")

        data = asdict(report) if hasattr(report, "__dataclass_fields__") else report
        data["date"] = date_str
        data["saved_at"] = datetime.now().isoformat()

        try:
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                if not isinstance(existing, list):
                    existing = [existing]
            else:
                existing = []

            existing.append(data)

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)

            logger.info("[DreamStorage] 已保存: %s", filepath)
            return filepath
        except Exception as e:
            logger.error("[DreamStorage] 保存失败: %s", e)
            return ""

    def load_today(self) -> list[dict]:
        """加载今天的梦境报告"""
        date_str = datetime.now().strftime("%Y-%m-%d")
        filepath = os.path.join(self.base_dir, f"{date_str}.json")
        if not os.path.exists(filepath):
            return []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else [data]
        except Exception as e:
            logger.warning("[DreamStorage] 加载失败: %s", e)
            return []

    def get_last_summary(self) -> str:
        """获取最近一次梦境摘要"""
        today = self.load_today()
        if today:
            last = today[-1]
            return last.get("summary", "")
        return ""
